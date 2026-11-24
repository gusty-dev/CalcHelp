# CalcHelp

Веб-сайт с калькуляторами на Flask.

## Локальный запуск

Требуется Python 3.10 или новее.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Откройте <http://localhost:5000>. В `.env` задайте `SECRET_KEY`, `BOT_TOKEN` и `BOT_LINK`.

## Публикация на GitHub

Создайте пустой репозиторий на GitHub, затем из папки проекта выполните:

```bash
git init
git add .
git commit -m "Prepare CalcHelp for deployment"
git branch -M main
git remote add origin https://github.com/ВАШ_АККАУНТ/ИМЯ_РЕПОЗИТОРИЯ.git
git push -u origin main
```

Файл `.env` и виртуальное окружение исключены из Git. Не добавляйте токен бота в файлы проекта и не публикуйте его в репозитории.

## Публикация на Render

1. В Render выберите **New → Blueprint** и подключите GitHub-репозиторий. Файл `render.yaml` задаёт запуск веб-сервиса.
2. Render автоматически создаст `SECRET_KEY`. В разделе **Environment** задайте значения `BOT_TOKEN` и `BOT_LINK`.
3. Сохраните переменные и дождитесь завершения деплоя. При последующих push в ветку `main` Render сможет обновлять сайт автоматически.

`BOT_LINK` задавайте в виде `https://t.me/имя_бота`. Если ссылка заполнена, сайт покажет кнопку перехода к боту. `BOT_TOKEN` хранится в конфигурации сервиса и зарезервирован для интеграции с Telegram API. Текущий проект сам по себе не обрабатывает сообщения Telegram и не использует токен.
