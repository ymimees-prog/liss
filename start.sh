#!/bin/sh
# Запуск на Mac/Linux/Android (Termux): sh start.sh
cd "$(dirname "$0")"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Впиши BOT_TOKEN и ALLOWED_USERS в файл .env (например: nano .env) и запусти sh start.sh ещё раз."
    exit 0
fi
if [ ! -d .venv ]; then
    echo "Первый запуск: устанавливаю всё нужное..."
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi
echo "Бот запущен. Остановить: Ctrl+C"
exec .venv/bin/python -m bot
