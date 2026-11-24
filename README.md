# CalcHelp

Сайт с калькуляторами на Flask и Telegram-ботом. Команда `/start` отправляет приветствие и кнопку на сайт.

## Настройка Render

Для существующего Web Service задайте переменные в **Environment**:

- `BOT_TOKEN` — токен от @BotFather.
- `BOT_LINK` — публичная ссылка на бота, например `https://t.me/имя_бота`.
- `SITE_URL` — адрес сайта, например `https://calchelp.onrender.com`.
- `SECRET_KEY` — секрет Flask-сессий. Render может сгенерировать его автоматически.

Команда запуска: `gunicorn --bind 0.0.0.0:$PORT app:app`.
При старте приложение устанавливает Telegram webhook на `/telegram/webhook`.

## Публикация изменений

Из папки проекта отправьте изменения в GitHub:

```powershell
git add .
git commit -m "Add Telegram start handler"
git push
```

Render выполнит новый деплой после push. Не добавляйте `.env` и токен бота в репозиторий.
