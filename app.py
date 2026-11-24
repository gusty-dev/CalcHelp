from flask import Flask, render_template, request, session
from datetime import datetime, timedelta
import csv
import ast
import math
import re
import os
import hashlib
import hmac
import json
from urllib.request import Request as URLRequest, urlopen

from dotenv import load_dotenv


app = Flask(__name__)

load_dotenv()
app.secret_key = os.getenv("SECRET_KEY", "local-dev-only-change-me")
app.config["BOT_TOKEN"] = os.getenv("BOT_TOKEN", "")
app.config["BOT_LINK"] = os.getenv("BOT_LINK", "")
app.config["SITE_URL"] = os.getenv("SITE_URL", "").rstrip("/")


def telegram_secret():
    token = app.config["BOT_TOKEN"]
    if not token:
        return ""
    return hashlib.sha256((token + ":calchelp-webhook").encode()).hexdigest()


def telegram_api(method, payload):
    token = app.config["BOT_TOKEN"]
    data = json.dumps(payload).encode("utf-8")
    req = URLRequest(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=8) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API returned an unsuccessful response")
    return result


@app.post("/telegram/webhook")
def telegram_webhook():
    expected = telegram_secret()
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        return {"ok": False}, 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message") or {}
    text = message.get("text", "")
    chat = message.get("chat") or {}

    if text.startswith("/start") and chat.get("id") is not None:
        site_url = app.config["SITE_URL"]
        if not site_url:
            app.logger.error("SITE_URL is missing; cannot reply to /start")
            return {"ok": False}, 503
        try:
            telegram_api("sendMessage", {
                "chat_id": chat["id"],
                "text": (
                    "Привет! Я CalcHelp 👋\n"
                    "На сайте собраны калькуляторы и инструменты для учёбы."
                ),
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "Открыть CalcHelp", "url": site_url}
                    ]]
                },
            })
        except Exception as exc:
            app.logger.warning("Telegram reply failed: %s", type(exc).__name__)
            return {"ok": False}, 502

    return {"ok": True}


def configure_telegram_webhook():
    token = app.config["BOT_TOKEN"]
    site_url = app.config["SITE_URL"]
    if not token or not site_url:
        return
    try:
        telegram_api("setWebhook", {
            "url": f"{site_url}/telegram/webhook",
            "secret_token": telegram_secret(),
        })
        app.logger.info("Telegram webhook configured")
    except Exception as exc:
        app.logger.warning("Telegram webhook setup failed: %s", type(exc).__name__)


@app.context_processor
def inject_bot_link():
    return {"bot_link": app.config["BOT_LINK"]}


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def format_result(result):

    if isinstance(result, float):

        if result.is_integer():
            return str(int(result))

        return str(round(result, 10))

    return str(result)


def add_multiplication(expression):

    result = ""
    i = 0

    while i < len(expression):

        # sqrt
        if expression.startswith("sqrt", i):

            if result and (
                result[-1].isdigit()
                or result[-1] == ")"
            ):
                result += "*"

            result += "sqrt"
            i += 4
            continue

        current = expression[i]

        # 2(
        if result and current == "(" and (
            result[-1].isdigit()
            or result[-1] == ")"
        ):
            result += "*"

        # )2
        elif result and current.isdigit() and result[-1] == ")":
            result += "*"

        # )sqrt(...)
        elif result and current == "s" and result.endswith(")"):
            result += "*"

        result += current
        i += 1

    return result


# =========================================================
# ВЫЧИСЛЕНИЕ ВЫРАЖЕНИЯ
# =========================================================

def calculate_expression(expression):

    try:

        allowed = "0123456789.+-*/()^√! "

        if any(char not in allowed for char in expression):
            return "Ошибка"

        # -------------------------------------------------
        # СТЕПЕНЬ
        # -------------------------------------------------

        expression = expression.replace("^", "**")

        # -------------------------------------------------
        # ФАКТОРИАЛ
        #
        # Сначала обрабатываем факториал.
        #
        # 5!       -> factorial(5)
        # (3+2)!   -> factorial((3+2))
        # 120√3!   -> 120√factorial(3)
        # -------------------------------------------------

        factorial_pattern = re.compile(
            r"(\([^()]*\)|\d+(?:\.\d+)?)!"
        )

        while "!" in expression:

            new_expression = factorial_pattern.sub(
                r"factorial(\1)",
                expression
            )

            if new_expression == expression:
                return "Ошибка"

            expression = new_expression

        # -------------------------------------------------
        # КОРЕНЬ
        # -------------------------------------------------

        # √(5)
        expression = expression.replace(
            "√(",
            "sqrt("
        )

        # √factorial(3)
        expression = re.sub(
            r"√(factorial\([^()]*\))",
            r"sqrt(\1)",
            expression
        )

        # √25
        expression = re.sub(
            r"√(\d+(?:\.\d+)?)",
            r"sqrt(\1)",
            expression
        )

        # -------------------------------------------------
        # НЕЯВНОЕ УМНОЖЕНИЕ
        # -------------------------------------------------

        expression = add_multiplication(
            expression
        )

        # -------------------------------------------------
        # AST
        # -------------------------------------------------

        tree = ast.parse(
            expression,
            mode="eval"
        )

        # -------------------------------------------------
        # РЕКУРСИВНОЕ ВЫЧИСЛЕНИЕ
        # -------------------------------------------------

        def calculate_node(node):

            # =============================================
            # ЧИСЛА
            # =============================================

            if isinstance(node, ast.Constant):

                if isinstance(
                    node.value,
                    (int, float)
                ):
                    return node.value

                raise ValueError

            # =============================================
            # АРИФМЕТИЧЕСКИЕ ОПЕРАЦИИ
            # =============================================

            if isinstance(node, ast.BinOp):

                left = calculate_node(
                    node.left
                )

                right = calculate_node(
                    node.right
                )

                # +
                if isinstance(
                    node.op,
                    ast.Add
                ):
                    return left + right

                # -
                elif isinstance(
                    node.op,
                    ast.Sub
                ):
                    return left - right

                # *
                elif isinstance(
                    node.op,
                    ast.Mult
                ):
                    return left * right

                # /
                elif isinstance(
                    node.op,
                    ast.Div
                ):

                    if right == 0:
                        raise ZeroDivisionError

                    return left / right

                # **
                elif isinstance(
                    node.op,
                    ast.Pow
                ):
                    return left ** right

                raise ValueError

            # =============================================
            # ФУНКЦИИ
            # =============================================

            if isinstance(
                node,
                ast.Call
            ):

                # -----------------------------------------
                # КОРЕНЬ
                # -----------------------------------------

                if (
                    isinstance(
                        node.func,
                        ast.Name
                    )
                    and node.func.id == "sqrt"
                    and len(node.args) == 1
                ):

                    value = calculate_node(
                        node.args[0]
                    )

                    if value < 0:
                        raise ValueError

                    return math.sqrt(value)

                # -----------------------------------------
                # ФАКТОРИАЛ
                # -----------------------------------------

                if (
                    isinstance(
                        node.func,
                        ast.Name
                    )
                    and node.func.id == "factorial"
                    and len(node.args) == 1
                ):

                    value = calculate_node(
                        node.args[0]
                    )

                    # Факториал только для целых
                    if not isinstance(
                        value,
                        int
                    ):
                        raise ValueError

                    # Защита от огромных чисел
                    if value < 0 or value > 100:
                        raise ValueError

                    return math.factorial(
                        value
                    )

                raise ValueError

            # =============================================
            # +5 / -5
            # =============================================

            if isinstance(
                node,
                ast.UnaryOp
            ):

                value = calculate_node(
                    node.operand
                )

                if isinstance(
                    node.op,
                    ast.UAdd
                ):
                    return +value

                elif isinstance(
                    node.op,
                    ast.USub
                ):
                    return -value

                raise ValueError

            raise ValueError

        # -------------------------------------------------
        # РЕЗУЛЬТАТ
        # -------------------------------------------------

        result = calculate_node(
            tree.body
        )

        return format_result(
            result
        )

    except ZeroDivisionError:

        return "Нельзя делить на ноль"

    except:

        return "Ошибка"


# =========================================================
# ГЛАВНАЯ
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# ОБЫЧНЫЙ КАЛЬКУЛЯТОР
# =========================================================

@app.route(
    "/calculator",
    methods=["GET", "POST"]
)
def calculator():

    if request.method == "POST":

        # =================================================
        # BACKSPACE
        # =================================================

        if "backspace" in request.form:

            display = session.get(
                "display",
                "0"
            )

            display = display[:-1]

            if display == "":
                display = "0"

            session["display"] = display

        # =================================================
        # CLEAR
        # =================================================

        elif "clear" in request.form:

            session.clear()

            session["display"] = "0"

        # =================================================
        # ОТКРЫВАЮЩАЯ СКОБКА
        # =================================================

        elif "open_bracket" in request.form:

            bracket = request.form[
                "open_bracket"
            ]

            display = session.get(
                "display",
                "0"
            )

            if display == "0":
                display = bracket

            else:
                display += bracket

            session["display"] = display

        # =================================================
        # ЗАКРЫВАЮЩАЯ СКОБКА
        # =================================================

        elif "close_bracket" in request.form:

            bracket = request.form[
                "close_bracket"
            ]

            display = session.get(
                "display",
                "0"
            )

            if display == "0":
                display = bracket

            else:
                display += bracket

            session["display"] = display

        # =================================================
        # ЦИФРЫ
        # =================================================

        elif "number" in request.form:

            number = request.form[
                "number"
            ]

            display = session.get(
                "display",
                "0"
            )

            if display in [
                "Ошибка",
                "Нельзя делить на ноль"
            ]:
                display = "0"

            # После "=" вводим новое число
            if session.get(
                "new_number",
                False
            ):

                if number == ".":
                    display = "0."

                else:
                    display = number

                session["new_number"] = False

            elif display == "0":

                if number == ".":
                    display = "0."

                else:
                    display = number

            else:

                # Защита от двух точек
                if number == ".":

                    parts = re.split(
                        r"[+\-*/^]",
                        display
                    )

                    current_number = parts[-1]

                    if "." in current_number:

                        return render_template(
                            "calculator.html",
                            number=display,
                            history=session.get(
                                "history",
                                []
                            )
                        )

                display += number

            session["display"] = display

        # =================================================
        # ОПЕРАЦИИ
        # =================================================

        elif "operation" in request.form:

            operation = request.form[
                "operation"
            ]

            display = session.get(
                "display",
                "0"
            )

            if operation == "add":
                symbol = "+"

            elif operation == "subtract":
                symbol = "-"

            elif operation == "multiply":
                symbol = "*"

            elif operation == "divide":
                symbol = "/"

            elif operation == "power":
                symbol = "^"

            else:
                symbol = ""

            if symbol == "":

                session["display"] = "Ошибка"

            else:

                if display == "0":
                    display = ""

                if display and display[-1] in "+-*/^":
                    display = display[:-1]

                display += symbol

                session["display"] = display
                session["new_number"] = False

        # =================================================
        # ПРОЦЕНТ
        # =================================================

        elif "percent" in request.form:

            display = session.get(
                "display",
                "0"
            )

            try:

                number = float(
                    display
                )

                result = number / 100

                session["display"] = format_result(
                    result
                )

            except:

                session["display"] = "Ошибка"

        # =================================================
        # ФАКТОРИАЛ
        # =================================================

        elif "factorial" in request.form:

            display = session.get(
                "display",
                "0"
            )

            if display in [
                "Ошибка",
                "Нельзя делить на ноль"
            ]:

                display = "0"

            if display == "0":

                display = "0!"

            else:

                display += "!"

            session["display"] = display

        # =================================================
        # КОРЕНЬ
        # =================================================

        elif "sqrt" in request.form:

            display = session.get(
                "display",
                "0"
            )

            if display == "0":

                display = "√"

            else:

                display += "√"

            session["display"] = display
            session["new_number"] = False

        # =================================================
        # РАВНО
        # =================================================

        elif "calculate" in request.form:

            expression = session.get(
                "display",
                "0"
            )

            result = calculate_expression(
                expression
            )

            history = session.get(
                "history",
                []
            )

            history.append(
                f"{expression} = {result}"
            )

            history = history[-7:]

            session["history"] = history
            session["display"] = result
            session["new_number"] = True

    display = session.get(
        "display",
        "0"
    )

    history = session.get(
        "history",
        []
    )

    return render_template(
        "calculator.html",
        number=display,
        history=history
    )


# =========================================================
# СИСТЕМЫ СЧИСЛЕНИЯ
# =========================================================
@app.route("/number-system", methods=["GET", "POST"])
def number_system():
    result = None
    number = ""
    from_base = 10
    to_base = 2

    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def to_decimal(value, base):
        """Перевод числа из любой системы в точную дробь."""
        value = value.strip().upper().replace(",", ".")

        sign = -1 if value.startswith("-") else 1
        if value.startswith(("-", "+")):
            value = value[1:]

        if not value or value.count(".") > 1:
            raise ValueError("Неверная запись числа")

        if "." in value:
            integer_part, fractional_part = value.split(".")
        else:
            integer_part, fractional_part = value, ""

        if not integer_part and not fractional_part:
            raise ValueError("Введите число")

        integer_value = 0

        for char in integer_part:
            if char not in digits or digits.index(char) >= base:
                raise ValueError("Недопустимая цифра")
            integer_value = integer_value * base + digits.index(char)

        fractional_value = Fraction(0, 1)

        for position, char in enumerate(fractional_part, start=1):
            if char not in digits or digits.index(char) >= base:
                raise ValueError("Недопустимая цифра")
            fractional_value += Fraction(
                digits.index(char), base ** position
            )

        return sign * (Fraction(integer_value, 1) + fractional_value)

    def from_decimal(value, base, precision=12):
        """Перевод точной дроби в нужную систему."""
        if value < 0:
            sign = "-"
            value = -value
        else:
            sign = ""

        integer_part = value.numerator // value.denominator
        fractional_part = value - integer_part

        if integer_part == 0:
            integer_result = "0"
        else:
            integer_result = ""
            while integer_part > 0:
                integer_result = digits[integer_part % base] + integer_result
                integer_part //= base

        if fractional_part == 0:
            return sign + integer_result

        fractional_result = ""

        for _ in range(precision):
            fractional_part *= base
            digit = fractional_part.numerator // fractional_part.denominator
            fractional_result += digits[digit]
            fractional_part -= digit

            if fractional_part == 0:
                break

        fractional_result = fractional_result.rstrip("0")

        if fractional_result:
            return sign + integer_result + "." + fractional_result

        return sign + integer_result

    if request.method == "POST":
        number = request.form.get("number", "").strip().upper()

        try:
            from_base = int(request.form.get("from_base", 10))
            to_base = int(request.form.get("to_base", 2))

            if not 2 <= from_base <= 36 or not 2 <= to_base <= 36:
                raise ValueError("Основание системы должно быть от 2 до 36")

            decimal_number = to_decimal(number, from_base)
            result = from_decimal(decimal_number, to_base)

        except (ValueError, ZeroDivisionError):
            result = "Ошибка: проверь число и выбранную систему счисления"

    return render_template(
        "number_system.html",
        result=result,
        number=number,
        from_base=from_base,
        to_base=to_base
    )
# =========================================================
# ВРЕМЯ
# =========================================================

@app.route(
    "/time",
    methods=["GET", "POST"]
)
def time():

    difference_result = None
    countdown_result = None
    add_result = None

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        # =================================================
        # РАЗНИЦА МЕЖДУ ДАТАМИ
        # =================================================

        if action == "difference":

            try:

                start_date = request.form[
                    "start_date"
                ]

                start_time = request.form[
                    "start_time"
                ]

                end_date = request.form[
                    "end_date"
                ]

                end_time = request.form[
                    "end_time"
                ]

                start = datetime.strptime(
                    start_date + " " + start_time,
                    "%Y-%m-%d %H:%M"
                )

                end = datetime.strptime(
                    end_date + " " + end_time,
                    "%Y-%m-%d %H:%M"
                )

                difference = (
                    end - start
                )

                total_seconds = int(
                    difference.total_seconds()
                )

                if total_seconds < 0:

                    difference_result = (
                        "Дата окончания раньше "
                        "даты начала"
                    )

                else:

                    days = (
                        total_seconds // 86400
                    )

                    total_seconds %= 86400

                    hours = (
                        total_seconds // 3600
                    )

                    total_seconds %= 3600

                    minutes = (
                        total_seconds // 60
                    )

                    seconds = (
                        total_seconds % 60
                    )

                    difference_result = (
                        f"{days} дней "
                        f"{hours} ч "
                        f"{minutes} мин "
                        f"{seconds} сек"
                    )

            except:

                difference_result = "Ошибка"

        # =================================================
        # ОБРАТНЫЙ ОТСЧЁТ
        # =================================================

        elif action == "countdown":

            try:

                target_date = request.form[
                    "target_date"
                ]

                target_time = request.form[
                    "target_time"
                ]

                target = datetime.strptime(
                    target_date + " " + target_time,
                    "%Y-%m-%d %H:%M"
                )

                now = datetime.now()

                remaining = (
                    target - now
                )

                total_seconds = int(
                    remaining.total_seconds()
                )

                if total_seconds <= 0:

                    countdown_result = (
                        "Дата уже наступила"
                    )

                else:

                    days = (
                        total_seconds // 86400
                    )

                    total_seconds %= 86400

                    hours = (
                        total_seconds // 3600
                    )

                    total_seconds %= 3600

                    minutes = (
                        total_seconds // 60
                    )

                    countdown_result = (
                        f"{days} дней "
                        f"{hours} ч "
                        f"{minutes} мин"
                    )

            except:

                countdown_result = "Ошибка"

        # =================================================
        # ПРИБАВИТЬ / ВЫЧЕСТЬ
        # =================================================

        elif action == "add_time":

            try:

                start_date = request.form[
                    "add_start_date"
                ]

                start_time = request.form[
                    "add_start_time"
                ]

                days = int(
                    request.form.get(
                        "days",
                        0
                    ) or 0
                )

                hours = int(
                    request.form.get(
                        "hours",
                        0
                    ) or 0
                )

                minutes = int(
                    request.form.get(
                        "minutes",
                        0
                    ) or 0
                )

                seconds = int(
                    request.form.get(
                        "seconds",
                        0
                    ) or 0
                )

                operation = request.form.get(
                    "time_operation",
                    "add"
                )

                start = datetime.strptime(
                    start_date + " " + start_time,
                    "%Y-%m-%d %H:%M"
                )

                delta = timedelta(
                    days=days,
                    hours=hours,
                    minutes=minutes,
                    seconds=seconds
                )

                if operation == "subtract":

                    result_date = (
                        start - delta
                    )

                else:

                    result_date = (
                        start + delta
                    )

                add_result = (
                    result_date.strftime(
                        "%d.%m.%Y %H:%M:%S"
                    )
                )

            except:

                add_result = "Ошибка"

    return render_template(
        "time.html",
        difference_result=difference_result,
        countdown_result=countdown_result,
        add_result=add_result
    )


# =========================================================
# ЕДИНИЦЫ
# =========================================================

@app.route(
    "/units",
    methods=["GET", "POST"]
)
def units():

    categories = {

        "Длина": {
            "Миллиметры": 0.001,
            "Сантиметры": 0.01,
            "Метры": 1,
            "Километры": 1000,
            "Дюймы": 0.0254,
            "Футы": 0.3048,
            "Мили": 1609.344
        },

        "Масса": {
            "Миллиграммы": 0.000001,
            "Граммы": 0.001,
            "Килограммы": 1,
            "Тонны": 1000,
            "Фунты": 0.45359237
        },

        "Объём": {
            "Миллилитры": 0.000001,
            "Литры": 0.001,
            "Кубические метры": 1,
            "Галлоны": 0.00378541
        },

        "Время": {
            "Миллисекунды": 0.001,
            "Секунды": 1,
            "Минуты": 60,
            "Часы": 3600,
            "Дни": 86400
        },

        "Скорость": {
            "м/с": 1,
            "км/ч": 0.2777777778,
            "миль/ч": 0.44704
        },

        "Площадь": {
            "мм²": 0.000001,
            "см²": 0.0001,
            "м²": 1,
            "км²": 1000000,
            "Гектары": 10000,
            "Акры": 4046.8564224
        },

        "Температура": {
            "°C": 1,
            "°F": 1,
            "K": 1
        }
    }

    selected_category = "Длина"

    value = ""

    result = None

    current_units = list(
        categories[
            selected_category
        ].keys()
    )

    from_unit = current_units[0]
    to_unit = current_units[1]

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        # =================================================
        # СМЕНА КАТЕГОРИИ
        # =================================================

        if action == "change_category":

            selected_category = request.form.get(
                "category",
                "Длина"
            )

            if selected_category not in categories:

                selected_category = "Длина"

            current_units = list(
                categories[
                    selected_category
                ].keys()
            )

            from_unit = current_units[0]

            if len(current_units) > 1:

                to_unit = current_units[1]

            else:

                to_unit = current_units[0]

        # =================================================
        # КОНВЕРТАЦИЯ
        # =================================================

        elif action == "convert":

            selected_category = request.form.get(
                "category",
                "Длина"
            )

            if selected_category not in categories:

                selected_category = "Длина"

            current_units = list(
                categories[
                    selected_category
                ].keys()
            )

            value = request.form.get(
                "value",
                ""
            )

            from_unit = request.form.get(
                "from_unit",
                current_units[0]
            )

            to_unit = request.form.get(
                "to_unit",
                current_units[1]
                if len(current_units) > 1
                else current_units[0]
            )

            try:

                if from_unit not in current_units:
                    raise ValueError

                if to_unit not in current_units:
                    raise ValueError

                number = float(value)

                # Температура
                if selected_category == "Температура":

                    if from_unit == "°C":

                        celsius = number

                    elif from_unit == "°F":

                        celsius = (
                            number - 32
                        ) * 5 / 9

                    else:

                        celsius = (
                            number - 273.15
                        )

                    if to_unit == "°C":

                        converted = celsius

                    elif to_unit == "°F":

                        converted = (
                            celsius * 9 / 5
                        ) + 32

                    else:

                        converted = (
                            celsius + 273.15
                        )

                # Остальные единицы
                else:

                    base_value = (
                        number
                        * categories[
                            selected_category
                        ][from_unit]
                    )

                    converted = (
                        base_value
                        / categories[
                            selected_category
                        ][to_unit]
                    )

                result = format_result(
                    converted
                )

            except:

                result = "Ошибка"

    return render_template(
        "units.html",
        categories=categories,
        current_units=current_units,
        selected_category=selected_category,
        value=value,
        from_unit=from_unit,
        to_unit=to_unit,
        result=result
    )


# =========================================================
# ПРОЦЕНТЫ
# =========================================================

@app.route(
    "/percent",
    methods=["GET", "POST"]
)
def percent():

    result = None
    error = None

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        try:

            # =================================================
            # СКОЛЬКО ПРОЦЕНТОВ
            # =================================================

            if action == "what_percent":

                number = float(
                    request.form["number"]
                )

                total = float(
                    request.form["total"]
                )

                if total == 0:
                    raise ZeroDivisionError

                result = (
                    number / total
                ) * 100

                result = (
                    f"{format_result(result)}%"
                )

            # =================================================
            # ИЗМЕНЕНИЕ В ПРОЦЕНТАХ
            # =================================================

            elif action == "change_percent":

                old_value = float(
                    request.form["old_value"]
                )

                new_value = float(
                    request.form["new_value"]
                )

                if old_value == 0:
                    raise ZeroDivisionError

                change = (
                    (
                        new_value
                        - old_value
                    )
                    / old_value
                ) * 100

                formatted = format_result(
                    abs(change)
                )

                if change > 0:

                    result = (
                        f"+{formatted}%"
                    )

                elif change < 0:

                    result = (
                        f"-{formatted}%"
                    )

                else:

                    result = "0%"

        except ZeroDivisionError:

            error = "Нельзя делить на ноль"

        except:

            error = "Ошибка"

    return render_template(
        "percent.html",
        result=result,
        error=error
    )


# =========================================================
# ГЕОМЕТРИЯ
# =========================================================

@app.route(
    "/geometry",
    methods=["GET", "POST"]
)
def geometry():

    result = None
    error = None
    shape = None

    if request.method == "POST":

        shape = request.form.get(
            "shape"
        )

        try:

            # =================================================
            # КВАДРАТ
            # =================================================

            if shape == "square":

                side = float(
                    request.form["side"]
                )

                if side <= 0:
                    raise ValueError

                area = side ** 2
                perimeter = side * 4

                result = {
                    "title": "Квадрат",
                    "items": [
                        f"Площадь: {format_result(area)}",
                        f"Периметр: {format_result(perimeter)}"
                    ]
                }

            # =================================================
            # ПРЯМОУГОЛЬНИК
            # =================================================

            elif shape == "rectangle":

                length = float(
                    request.form["length"]
                )

                width = float(
                    request.form["width"]
                )

                if length <= 0 or width <= 0:
                    raise ValueError

                area = length * width
                perimeter = 2 * (
                    length + width
                )

                result = {
                    "title": "Прямоугольник",
                    "items": [
                        f"Площадь: {format_result(area)}",
                        f"Периметр: {format_result(perimeter)}"
                    ]
                }

            # =================================================
            # ТРЕУГОЛЬНИК
            # =================================================

            elif shape == "triangle":

                base = float(
                    request.form["base"]
                )

                height = float(
                    request.form["height"]
                )

                if base <= 0 or height <= 0:
                    raise ValueError

                area = (
                    base * height / 2
                )

                result = {
                    "title": "Треугольник",
                    "items": [
                        f"Площадь: {format_result(area)}"
                    ]
                }

            # =================================================
            # КРУГ
            # =================================================

            elif shape == "circle":

                radius = float(
                    request.form["radius"]
                )

                if radius <= 0:
                    raise ValueError

                area = (
                    math.pi * radius ** 2
                )

                circumference = (
                    2 * math.pi * radius
                )

                result = {
                    "title": "Круг",
                    "items": [
                        f"Площадь: {format_result(area)}",
                        f"Длина окружности: {format_result(circumference)}"
                    ]
                }

            # =================================================
            # РОМБ
            # =================================================

            elif shape == "rhombus":

                diagonal1 = float(
                    request.form["diagonal1"]
                )

                diagonal2 = float(
                    request.form["diagonal2"]
                )

                if diagonal1 <= 0 or diagonal2 <= 0:
                    raise ValueError

                area = (
                    diagonal1
                    * diagonal2
                    / 2
                )

                result = {
                    "title": "Ромб",
                    "items": [
                        f"Площадь: {format_result(area)}"
                    ]
                }

            # =================================================
            # ТРАПЕЦИЯ
            # =================================================

            elif shape == "trapezoid":

                base1 = float(
                    request.form["base1"]
                )

                base2 = float(
                    request.form["base2"]
                )

                height = float(
                    request.form["height"]
                )

                if (
                    base1 <= 0
                    or base2 <= 0
                    or height <= 0
                ):
                    raise ValueError

                area = (
                    (base1 + base2)
                    * height
                    / 2
                )

                result = {
                    "title": "Трапеция",
                    "items": [
                        f"Площадь: {format_result(area)}"
                    ]
                }

            # =================================================
            # КУБ
            # =================================================

            elif shape == "cube":

                side = float(
                    request.form["side"]
                )

                if side <= 0:
                    raise ValueError

                volume = side ** 3
                surface = 6 * side ** 2

                result = {
                    "title": "Куб",
                    "items": [
                        f"Объём: {format_result(volume)}",
                        f"Площадь поверхности: {format_result(surface)}"
                    ]
                }

            # =================================================
            # ПРЯМОУГОЛЬНЫЙ ПАРАЛЛЕЛЕПИПЕД
            # =================================================

            elif shape == "cuboid":

                length = float(
                    request.form["length"]
                )

                width = float(
                    request.form["width"]
                )

                height = float(
                    request.form["height"]
                )

                if (
                    length <= 0
                    or width <= 0
                    or height <= 0
                ):
                    raise ValueError

                volume = (
                    length
                    * width
                    * height
                )

                surface = 2 * (
                    length * width
                    + length * height
                    + width * height
                )

                result = {
                    "title": "Прямоугольный параллелепипед",
                    "items": [
                        f"Объём: {format_result(volume)}",
                        f"Площадь поверхности: {format_result(surface)}"
                    ]
                }

            # =================================================
            # ЦИЛИНДР
            # =================================================

            elif shape == "cylinder":

                radius = float(
                    request.form["radius"]
                )

                height = float(
                    request.form["height"]
                )

                if radius <= 0 or height <= 0:
                    raise ValueError

                volume = (
                    math.pi
                    * radius ** 2
                    * height
                )

                surface = (
                    2 * math.pi * radius ** 2
                    + 2 * math.pi * radius * height
                )

                result = {
                    "title": "Цилиндр",
                    "items": [
                        f"Объём: {format_result(volume)}",
                        f"Площадь поверхности: {format_result(surface)}"
                    ]
                }

            # =================================================
            # СФЕРА
            # =================================================

            elif shape == "sphere":

                radius = float(
                    request.form["radius"]
                )

                if radius <= 0:
                    raise ValueError

                volume = (
                    4 / 3
                    * math.pi
                    * radius ** 3
                )

                surface = (
                    4
                    * math.pi
                    * radius ** 2
                )

                result = {
                    "title": "Сфера",
                    "items": [
                        f"Объём: {format_result(volume)}",
                        f"Площадь поверхности: {format_result(surface)}"
                    ]
                }

            # =================================================
            # КОНУС
            # =================================================

            elif shape == "cone":

                radius = float(
                    request.form["radius"]
                )

                height = float(
                    request.form["height"]
                )

                if radius <= 0 or height <= 0:
                    raise ValueError

                slant_height = math.sqrt(
                    radius ** 2
                    + height ** 2
                )

                volume = (
                    math.pi
                    * radius ** 2
                    * height
                    / 3
                )

                surface = (
                    math.pi
                    * radius ** 2
                    + math.pi
                    * radius
                    * slant_height
                )

                result = {
                    "title": "Конус",
                    "items": [
                        f"Объём: {format_result(volume)}",
                        f"Площадь поверхности: {format_result(surface)}",
                        f"Образующая: {format_result(slant_height)}"
                    ]
                }

            # =================================================
            # ПИРАМИДА
            # =================================================

            elif shape == "pyramid":

                base = float(
                    request.form["base"]
                )

                height = float(
                    request.form["height"]
                )

                if base <= 0 or height <= 0:
                    raise ValueError

                volume = (
                    base ** 2
                    * height
                    / 3
                )

                slant_height = math.sqrt(
                    height ** 2
                    + (base / 2) ** 2
                )

                surface = (
                    base ** 2
                    + 2
                    * base
                    * slant_height
                )

                result = {
                    "title": "Правильная четырёхугольная пирамида",
                    "items": [
                        f"Объём: {format_result(volume)}",
                        f"Площадь поверхности: {format_result(surface)}",
                        f"Апофема: {format_result(slant_height)}"
                    ]
                }

            else:

                error = "Неизвестная фигура"

        except:

            error = (
                "Введите корректные "
                "положительные числа"
            )

    return render_template(
        "geometry.html",
        result=result,
        error=error,
        selected_shape=shape
    )


# =========================================================
# НОД И НОК
# =========================================================

@app.route(
    "/NOK_NOD",
    methods=["GET", "POST"]
)
def nok_nod():

    result = None
    error = None

    if request.method == "POST":

        try:

            number1 = int(
                request.form["number1"]
            )

            number2 = int(
                request.form["number2"]
            )

            if number1 == 0 and number2 == 0:
                raise ValueError

            gcd = math.gcd(
                number1,
                number2
            )

            lcm = (
                abs(number1 * number2)
                // gcd
            )

            result = {
                "number1": number1,
                "number2": number2,
                "gcd": gcd,
                "lcm": lcm
            }

        except:

            error = (
                "Введите два корректных "
                "целых числа"
            )

    return render_template(
        "NOK_NOD.html",
        result=result,
        error=error
    )

# =========================================================
# ДРОБИ
# =========================================================

from fractions import Fraction


@app.route(
    "/fractions",
    methods=["GET", "POST"]
)
def fractions_calculator():

    result = None
    error = None

    numerator1 = ""
    denominator1 = ""
    numerator2 = ""
    denominator2 = ""
    operation = "add"

    if request.method == "POST":

        try:

            numerator1 = request.form[
                "numerator1"
            ]

            denominator1 = request.form[
                "denominator1"
            ]

            numerator2 = request.form[
                "numerator2"
            ]

            denominator2 = request.form[
                "denominator2"
            ]

            operation = request.form.get(
                "operation",
                "add"
            )

            n1 = int(numerator1)
            d1 = int(denominator1)

            n2 = int(numerator2)
            d2 = int(denominator2)

            if d1 == 0 or d2 == 0:
                raise ZeroDivisionError

            fraction1 = Fraction(
                n1,
                d1
            )

            fraction2 = Fraction(
                n2,
                d2
            )

            # -----------------------------------------
            # ОПЕРАЦИЯ
            # -----------------------------------------

            if operation == "add":

                answer = (
                    fraction1
                    + fraction2
                )

            elif operation == "subtract":

                answer = (
                    fraction1
                    - fraction2
                )

            elif operation == "multiply":

                answer = (
                    fraction1
                    * fraction2
                )

            elif operation == "divide":

                if fraction2 == 0:
                    raise ZeroDivisionError

                answer = (
                    fraction1
                    / fraction2
                )

            else:

                raise ValueError

            # -----------------------------------------
            # РЕЗУЛЬТАТ
            # -----------------------------------------

            numerator = answer.numerator
            denominator = answer.denominator

            if denominator == 1:

                result = str(
                    numerator
                )

            else:

                # Смешанная дробь
                if abs(numerator) >= denominator:

                    whole = (
                        numerator
                        // denominator
                    )

                    remainder = abs(
                        numerator
                        % denominator
                    )

                    if remainder == 0:

                        result = str(
                            whole
                        )

                    else:

                        result = (
                            f"{whole} "
                            f"{remainder}/{denominator}"
                        )

                else:

                    result = (
                        f"{numerator}/"
                        f"{denominator}"
                    )

        except ZeroDivisionError:

            error = "Нельзя делить на ноль"

        except:

            error = (
                "Введите корректные "
                "целые числа"
            )

    return render_template(
        "drobi.html",
        result=result,
        error=error,
        numerator1=numerator1,
        denominator1=denominator1,
        numerator2=numerator2,
        denominator2=denominator2,
        operation=operation
    )

# =========================================
# ТЕОРЕМА ПИФАГОРА
# =========================================

@app.route("/pifagor", methods=["GET", "POST"])
def pifagor():

    result = None
    error = None

    side_a = ""
    side_b = ""
    side_c = ""

    calculate = "hypotenuse"

    if request.method == "POST":

        calculate = request.form.get("calculate", "hypotenuse")

        side_a = request.form.get("side_a", "")
        side_b = request.form.get("side_b", "")
        side_c = request.form.get("side_c", "")

        try:

            if calculate == "hypotenuse":

                a = float(side_a)
                b = float(side_b)

                if a <= 0 or b <= 0:
                    raise ValueError

                result = format_result(
                    math.sqrt(a ** 2 + b ** 2)
                )


            elif calculate == "cathetus":

                a = float(side_a)
                c = float(side_c)

                if a <= 0 or c <= 0:
                    raise ValueError

                if c <= a:
                    error = "Гипотенуза должна быть больше катета"

                else:

                    result = format_result(
                        math.sqrt(c ** 2 - a ** 2)
                    )


        except (ValueError, TypeError):

            if not error:
                error = "Введите положительные числа"


        except Exception:

            error = "Не удалось выполнить расчёт"


    return render_template(
        "pifagor.html",
        result=result,
        error=error,
        calculate=calculate,
        side_a=side_a,
        side_b=side_b,
        side_c=side_c
    )

# =========================================
# КВАДРАТНЫЕ УРАВНЕНИЯ
# =========================================

@app.route("/kvadrat", methods=["GET", "POST"])
def quadratic():

    result = None
    error = None
    discriminant = None

    a = ""
    b = ""
    c = ""

    if request.method == "POST":

        a = request.form.get("a", "")
        b = request.form.get("b", "")
        c = request.form.get("c", "")

        try:

            a_value = float(a)
            b_value = float(b)
            c_value = float(c)

            if a_value == 0:
                error = "Коэффициент a не может быть равен нулю"

            else:

                discriminant = (
                    b_value ** 2
                    - 4 * a_value * c_value
                )

                if discriminant > 0:

                    x1 = (
                        -b_value
                        + math.sqrt(discriminant)
                    ) / (2 * a_value)

                    x2 = (
                        -b_value
                        - math.sqrt(discriminant)
                    ) / (2 * a_value)

                    x1 = format_result(x1)
                    x2 = format_result(x2)

                    result = (
                        f"x₁ = {x1}; x₂ = {x2}"
                    )


                elif discriminant == 0:

                    x = (
                        -b_value
                        / (2 * a_value)
                    )

                    x = format_result(x)

                    result = f"x = {x}"


                else:

                    result = (
                        "Действительных корней нет"
                    )


                discriminant = format_result(
                    discriminant
                )


        except (ValueError, TypeError):

            error = (
                "Введите корректные числовые значения"
            )


    return render_template(
        "kvadrat.html",
        result=result,
        error=error,
        discriminant=discriminant,
        a=a,
        b=b,
        c=c
    )

@app.route("/combinatorics", methods=["GET", "POST"])
def combinatorics():
    result = None
    error = None
    formula = None

    operation = request.form.get("operation", "permutations")
    n_value = request.form.get("n", "")
    k_value = request.form.get("k", "")

    if request.method == "POST":
        operation = request.form.get("operation")

        try:
            n = int(request.form.get("n", 0))

            if n < 0:
                raise ValueError

            if operation == "permutations":
                result = math.factorial(n)

                formula = (
                    f"P({n}) = {n}! = {result}"
                )

            elif operation == "arrangements":
                k = int(request.form.get("k", 0))

                if k < 0 or k > n:
                    raise ValueError

                result = math.factorial(n) // math.factorial(n - k)

                formula = (
                    f"A({n}, {k}) = {n}! / ({n} - {k})! "
                    f"= {math.factorial(n)} / {math.factorial(n - k)} "
                    f"= {result}"
                )

            elif operation == "combinations":
                k = int(request.form.get("k", 0))

                if k < 0 or k > n:
                    raise ValueError

                result = math.comb(n, k)

                formula = (
                    f"C({n}, {k}) → "
                    f"{n}! / ({k}! × ({n} - {k})!) → "
                    f"{math.factorial(n)} / "
                    f"({math.factorial(k)} × {math.factorial(n - k)}) → "
                    f"{math.factorial(n)} / "
                    f"{math.factorial(k) * math.factorial(n - k)} → "
                    f"{result}"
                )

            else:
                error = "Неизвестная операция."

        except (ValueError, OverflowError):
            error = "Проверь введённые значения."

    return render_template(
        "combinatorics.html",
        result=result,
        formula=formula,
        error=error
    )

# =========================================================
# СЛОЖНЫЙ ПРОЦЕНТ
# =========================================================

@app.route(
    "/hard-percent",
    methods=["GET", "POST"]
)
def hard_percent():

    result = None
    error = None

    if request.method == "POST":

        try:

            principal = float(
                request.form["principal"]
            )

            rate = float(
                request.form["rate"]
            )

            years = int(
                request.form["years"]
            )

            if principal <= 0:
                raise ValueError

            if years < 0:
                raise ValueError

            result = principal * (
                1 + rate / 100
            ) ** years

            result = format_result(
                result
            )

        except:

            error = (
                "Введите корректные значения"
            )

    return render_template(
        "hard_percent.html",
        result=result,
        error=error
    )

# =========================================================
# ТРИГОНОМЕТРИЯ
# =========================================================

@app.route("/trigonometry", methods=["GET", "POST"])
def trigonometry():

    result = None
    error = None
    formula = None

    operation = request.form.get(
        "operation",
        "sin"
    )

    angle_value = request.form.get(
        "angle",
        ""
    )

    angle_unit = request.form.get(
        "angle_unit",
        "degrees"
    )

    if request.method == "POST":

        try:

            angle = float(
                request.form.get("angle")
            )

            # =========================================
            # ПЕРЕВОД ГРАДУСОВ → РАДИАНЫ
            # =========================================

            if operation == "degrees_to_radians":

                result = math.radians(angle)

                formula = (
                    f"{angle}° × π / 180 = "
                    f"{result} рад"
                )

            # =========================================
            # ПЕРЕВОД РАДИАНОВ → ГРАДУСЫ
            # =========================================

            elif operation == "radians_to_degrees":

                result = math.degrees(angle)

                formula = (
                    f"{angle} рад × 180 / π = "
                    f"{result}°"
                )

            else:

                # =====================================
                # ОБЫЧНАЯ ТРИГОНОМЕТРИЯ
                # =====================================

                if angle_unit == "degrees":
                    radians = math.radians(angle)
                    unit_symbol = "°"
                else:
                    radians = angle
                    unit_symbol = " рад"

                if operation == "sin":

                    result = math.sin(radians)

                    formula = (
                        f"sin({angle}{unit_symbol}) = "
                        f"{result}"
                    )

                elif operation == "cos":

                    result = math.cos(radians)

                    formula = (
                        f"cos({angle}{unit_symbol}) = "
                        f"{result}"
                    )

                elif operation == "tan":

                    # Тангенс не существует,
                    # если cos(x) = 0
                    if abs(math.cos(radians)) < 1e-12:
                        raise ValueError

                    result = math.tan(radians)

                    formula = (
                        f"tan({angle}{unit_symbol}) = "
                        f"{result}"
                    )

                elif operation == "arcsin":

                    if angle < -1 or angle > 1:
                        raise ValueError

                    result = math.asin(angle)

                    if angle_unit == "degrees":
                        result = math.degrees(result)

                    formula = (
                        f"arcsin({angle}) = "
                        f"{result}{unit_symbol}"
                    )

                elif operation == "arccos":

                    if angle < -1 or angle > 1:
                        raise ValueError

                    result = math.acos(angle)

                    if angle_unit == "degrees":
                        result = math.degrees(result)

                    formula = (
                        f"arccos({angle}) = "
                        f"{result}{unit_symbol}"
                    )

                elif operation == "arctan":

                    result = math.atan(angle)

                    if angle_unit == "degrees":
                        result = math.degrees(result)

                    formula = (
                        f"arctan({angle}) = "
                        f"{result}{unit_symbol}"
                    )

                else:

                    error = "Неизвестная операция."

            if result is not None:
                result = format_result(result)

        except (ValueError, TypeError, OverflowError):

            result = None

            error = "Проверь введённое значение."

    return render_template(
        "trigonometry.html",
        result=result,
        error=error,
        formula=formula,
        operation=operation,
        angle_value=angle_value,
        angle_unit=angle_unit
    )

@app.route("/statistics", methods=["GET", "POST"])
def statistics():

    numbers_value = ""

    average = None
    median = None
    mode = None
    minimum = None
    maximum = None
    data_range = None
    variance = None
    standard_deviation = None

    error = None

    if request.method == "POST":

        numbers_value = request.form.get(
            "numbers",
            ""
        ).strip()

        try:
            # Поддерживаем:
            # 10 20 30
            # 10;20;30
            # 10
            # 20
            # 30
            raw = numbers_value.replace("\n", ";")

            if ";" in raw:
                parts = raw.split(";")
            else:
                parts = raw.split()

            numbers = []

            for part in parts:
                part = part.strip()

                if not part:
                    continue

                number = float(
                    part.replace(",", ".")
                )

                numbers.append(number)

            if not numbers:
                raise ValueError

            # Среднее
            average = sum(numbers) / len(numbers)

            # Сортировка
            sorted_numbers = sorted(numbers)

            # Медиана
            median = statistics_median = (
                sorted_numbers[len(sorted_numbers) // 2]
                if len(sorted_numbers) % 2 == 1
                else (
                    sorted_numbers[len(sorted_numbers) // 2 - 1]
                    + sorted_numbers[len(sorted_numbers) // 2]
                ) / 2
            )

            # Мода
            counts = {}

            for number in numbers:
                counts[number] = counts.get(number, 0) + 1

            max_count = max(counts.values())

            if max_count == 1:
                mode = "Нет"
            else:
                modes = [
                    number
                    for number, count in counts.items()
                    if count == max_count
                ]

                mode = ", ".join(
                    str(format_result(number))
                    for number in sorted(modes)
                )

            # Минимум / максимум
            minimum = min(numbers)
            maximum = max(numbers)

            # Размах
            data_range = maximum - minimum

            # Дисперсия
            variance = sum(
                (x - average) ** 2
                for x in numbers
            ) / len(numbers)

            # Стандартное отклонение
            standard_deviation = math.sqrt(
                variance
            )

            average = format_result(average)
            median = format_result(median)
            minimum = format_result(minimum)
            maximum = format_result(maximum)
            data_range = format_result(data_range)
            variance = format_result(variance)
            standard_deviation = format_result(
                standard_deviation
            )

        except (ValueError, TypeError, OverflowError):

            error = (
                "Введите корректный набор чисел."
            )

    return render_template(
        "statistics.html",
        numbers_value=numbers_value,
        average=average,
        median=median,
        mode=mode,
        minimum=minimum,
        maximum=maximum,
        data_range=data_range,
        variance=variance,
        standard_deviation=standard_deviation,
        error=error
    )

@app.route("/coordinate-geometry", methods=["GET", "POST"])
def coordinate_geometry():

    result = None
    formula = None
    error = None

    operation = request.form.get(
        "operation",
        "distance"
    )

    x1_value = request.form.get("x1", "")
    y1_value = request.form.get("y1", "")
    x2_value = request.form.get("x2", "")
    y2_value = request.form.get("y2", "")

    if request.method == "POST":

        try:
            x1 = float(request.form.get("x1"))
            y1 = float(request.form.get("y1"))
            x2 = float(request.form.get("x2"))
            y2 = float(request.form.get("y2"))

            if operation == "distance":

                distance = math.sqrt(
                    (x2 - x1) ** 2 +
                    (y2 - y1) ** 2
                )

                result = format_result(distance)

                formula = (
                    f"√(({x2} − {x1})² + "
                    f"({y2} − {y1})²) = "
                    f"{result}"
                )

            elif operation == "midpoint":

                x = (x1 + x2) / 2
                y = (y1 + y2) / 2

                x = format_result(x)
                y = format_result(y)

                result = f"({x}; {y})"

                formula = (
                    f"(({x1} + {x2}) / 2; "
                    f"({y1} + {y2}) / 2)"
                )

            elif operation == "slope":

                if x2 == x1:
                    raise ValueError(
                        "vertical_line"
                    )

                slope = (
                    (y2 - y1) /
                    (x2 - x1)
                )

                result = format_result(slope)

                formula = (
                    f"({y2} − {y1}) / "
                    f"({x2} − {x1}) = "
                    f"{result}"
                )

            elif operation == "line":

                if x2 == x1:
                    result = f"x = {format_result(x1)}"

                    formula = (
                        "Вертикальная прямая"
                    )

                else:

                    k = (
                        (y2 - y1) /
                        (x2 - x1)
                    )

                    b = y1 - k * x1

                    k = format_result(k)
                    b = format_result(b)

                    if b == 0:
                        result = f"y = {k}x"
                    elif isinstance(b, (int, float)) and b < 0:
                        result = f"y = {k}x − {abs(b)}"
                    else:
                        result = f"y = {k}x + {b}"

                    formula = (
                        "y = kx + b"
                    )

            else:
                error = "Неизвестная операция."

        except ValueError as exc:

            if str(exc) == "vertical_line":
                error = (
                    "Для углового коэффициента "
                    "вертикальной прямой не существует."
                )
            else:
                error = (
                    "Введите корректные координаты."
                )

        except (TypeError, OverflowError):

            error = (
                "Введите корректные координаты."
            )

    return render_template(
        "coordinate_geometry.html",
        result=result,
        formula=formula,
        error=error,
        operation=operation,
        x1_value=x1_value,
        y1_value=y1_value,
        x2_value=x2_value,
        y2_value=y2_value
    )

@app.route("/graph", methods=["GET", "POST"])
def graph():
    function = ""
    function2 = ""
    x_min = -10
    x_max = 10
    error = None

    if request.method == "POST":
        function = request.form.get("function", "").strip()
        function2 = request.form.get("function2", "").strip()

        try:
            x_min = float(request.form.get("x_min", -10))
            x_max = float(request.form.get("x_max", 10))

            if x_min >= x_max:
                error = "Левая граница должна быть меньше правой."

        except ValueError:
            error = "Границы должны быть числами."

    return render_template(
        "graph.html",
        function=function,
        function2=function2,
        x_min=x_min,
        x_max=x_max,
        error=error
    )
# =========================================================
# BMI
# =========================================================

def normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def calculate_bmi_percentile(bmi, age_months, sex):

    try:

        with open(
            "bmi_data.csv",
            "r",
            encoding="utf-8-sig"
        ) as file:

            reader = csv.DictReader(file)

            closest = None
            smallest_difference = float("inf")

            for row in reader:

                if int(row["sex"]) != sex:
                    continue

                age = float(row["age_months"])

                difference = abs(
                    age - age_months
                )

                if difference < smallest_difference:

                    smallest_difference = difference
                    closest = row

            if closest is None:
                return None

            L = float(closest["L"])
            M = float(closest["M"])
            S = float(closest["S"])

            if L == 0:

                z = math.log(bmi / M) / S

            else:

                z = (
                    ((bmi / M) ** L - 1)
                    / (L * S)
                )

            percentile = normal_cdf(z) * 100

            return round(percentile, 1)

    except Exception:

        return None


@app.route(
    "/bmi",
    methods=["GET", "POST"]
)
def bmi():

    height = ""
    weight = ""
    birth_date = ""
    sex = ""

    result = None
    percentile = None
    category = None
    error = None

    if request.method == "POST":

        height = request.form.get(
            "height",
            ""
        ).strip()

        weight = request.form.get(
            "weight",
            ""
        ).strip()

        birth_date = request.form.get(
            "birth_date",
            ""
        ).strip()

        sex = request.form.get(
            "sex",
            ""
        ).strip()

        try:

            height_value = float(
                height.replace(",", ".")
            )

            weight_value = float(
                weight.replace(",", ".")
            )

            if (
                height_value <= 0
                or weight_value <= 0
            ):
                raise ValueError

            birth = datetime.strptime(
                birth_date,
                "%Y-%m-%d"
            ).date()

            today = datetime.now().date()

            if birth >= today:

                error = (
                    "Дата рождения указана неправильно."
                )

            else:

                age_days = (
                    today - birth
                ).days

                age_months = (
                    age_days / 30.4375
                )

                # 2–20 лет
                if (
                    age_months < 24
                    or age_months >= 240
                ):

                    error = (
                        "Калькулятор рассчитан "
                        "на возраст от 2 до 20 лет."
                    )

                elif sex not in ["1", "2"]:

                    error = "Выберите пол."

                else:

                    bmi_value = (
                        weight_value
                        / ((height_value / 100) ** 2)
                    )

                    result = round(
                        bmi_value,
                        2
                    )

                    percentile = (
                        calculate_bmi_percentile(
                            bmi_value,
                            age_months,
                            int(sex)
                        )
                    )

                    if percentile is not None:

                        if percentile < 5:

                            category = (
                                "Ниже 5-го перцентиля"
                            )

                        elif percentile < 85:

                            category = (
                                "5-й–84-й перцентиль"
                            )

                        elif percentile < 95:

                            category = (
                                "85-й–94-й перцентиль"
                            )

                        else:

                            category = (
                                "95-й перцентиль и выше"
                            )

        except (
            ValueError,
            TypeError
        ):

            error = (
                "Проверьте дату рождения, "
                "рост, вес и пол."
            )

    return render_template(
        "bmi.html",
        height=height,
        weight=weight,
        birth_date=birth_date,
        sex=sex,
        result=result,
        percentile=percentile,
        category=category,
        error=error
    )


@app.route("/logarithms", methods=["GET", "POST"])
def logarithms():
    result = None
    argument = ""
    base = "2"
    operation = "log"

    if request.method == "POST":
        argument = request.form.get("argument", "").strip()
        base = request.form.get("base", "2").strip()
        operation = request.form.get("operation", "log")

        try:
            # Разрешаем ввод десятичных дробей через запятую
            x = float(argument.replace(",", "."))

            if not math.isfinite(x) or x <= 0:
                raise ValueError(
                    "Аргумент логарифма должен быть больше нуля."
                )

            if operation == "log":
                a = float(base.replace(",", "."))

                if not math.isfinite(a) or a <= 0 or a == 1:
                    raise ValueError(
                        "Основание должно быть больше нуля и не равно 1."
                    )

                value = math.log(x, a)
                expression = f"log₍{a:g}₎({x:g})"

            elif operation == "ln":
                value = math.log(x)
                expression = f"ln({x:g})"

            elif operation == "lg":
                value = math.log10(x)
                expression = f"lg({x:g})"

            else:
                raise ValueError("Выбери доступный вид логарифма.")

            result = {
                "expression": expression,
                "value": format_result(value)
            }

        except (ValueError, OverflowError):
            result = {
                "error": (
                    "Проверь введённые значения. Аргумент должен быть "
                    "положительным, а основание — положительным "
                    "и отличным от 1."
                )
            }

    return render_template(
        "logarithms.html",
        result=result,
        argument=argument,
        base=base,
        operation=operation
    )



@app.route("/kbzhu", methods=["GET", "POST"])
def kbzhu():
    result = None
    error = None
    under18 = False

    if request.method == "POST":
        try:
            age = int(request.form.get("age", ""))
            sex = request.form.get("sex", "")
            height = float(request.form.get("height", ""))
            weight = float(request.form.get("weight", ""))
            target_weight = float(request.form.get("target_weight", ""))
            activity = float(request.form.get("activity", ""))

            if not 1 <= age <= 120:
                raise ValueError()

            if sex not in ("male", "female"):
                raise ValueError()

            if not 80 <= height <= 250:
                raise ValueError()

            if not 20 <= weight <= 350:
                raise ValueError()

            if not 20 <= target_weight <= 350:
                raise ValueError()

            if activity not in (1.2, 1.375, 1.55, 1.725, 1.9):
                raise ValueError()

            # Формула Миффлина — Сан Жеора
            if sex == "male":
                bmr = 10 * weight + 6.25 * height - 5 * age + 5
            else:
                bmr = 10 * weight + 6.25 * height - 5 * age - 161

            maintenance = bmr * activity

            # Ориентир для взрослых целей; для подростков
            # результат следует рассматривать только как справочный.
            if target_weight > weight + 0.5:
                calories = maintenance * 1.10
                goal = "ориентир для набора веса"
            elif target_weight < weight - 0.5:
                calories = maintenance * 0.90
                goal = "ориентир для снижения веса"
            else:
                calories = maintenance
                goal = "ориентир для поддержания веса"

            protein = weight * 1.6
            fat = weight * 0.8
            carbs = max(
                0,
                (calories - protein * 4 - fat * 9) / 4
            )

            result = {
                "calories": round(calories),
                "protein": round(protein),
                "fat": round(fat),
                "carbs": round(carbs),
                "goal": goal,
            }

            under18 = age < 18

        except (ValueError, TypeError):
            error = (
                "Проверь введённые данные. "
                "Заполни все поля корректно."
            )

    return render_template(
        "kbzhu.html",
        result=result,
        error=error,
        under18=under18
    )


@app.route("/fuel", methods=["GET", "POST"])
def fuel():
    result = None
    error = None

    if request.method == "POST":
        try:
            distance = float(request.form.get("distance", ""))
            consumption = float(request.form.get("consumption", ""))
            price = float(request.form.get("price", ""))
            trip_type = request.form.get("trip_type", "")

            if not all(map(math.isfinite, [
                distance, consumption, price
            ])):
                raise ValueError()

            if trip_type not in ("one_way", "round_trip"):
                raise ValueError()

            if not 0 < distance <= 1000000:
                error = "Расстояние должно быть больше 0."
            elif not 0 < consumption <= 200:
                error = "Проверь расход топлива."
            elif not 0 < price <= 1000000:
                error = "Проверь цену за литр."
            else:
                # Учитываем поездку в одну сторону или туда и обратно.
                total_distance = distance

                if trip_type == "round_trip":
                    total_distance *= 2

                liters = total_distance * consumption / 100
                total_cost = liters * price
                cost_per_100 = consumption * price

                result = {
                    "distance": round(total_distance, 2),
                    "liters": round(liters, 2),
                    "total_cost": round(total_cost, 2),
                    "cost_per_100": round(cost_per_100, 2),
                }

        except (ValueError, TypeError):
            error = "Заполни все поля корректными числами и выбери тип поездки."

    return render_template(
        "fuel.html",
        result=result,
        error=error
    )
# =========================================================
# ЗАПУСК
# =========================================================

configure_telegram_webhook()

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )
