#!/bin/sh
# Запуск на Mac/Linux/Android (Termux): sh start.sh
cd "$(dirname "$0")"
if [ ! -f .env ]; then
    printf "Вставь ключ бота от @BotFather и нажми Enter: "
    read -r TOKEN
    printf "BOT_TOKEN=%s\nALLOWED_USERS=9166868659\nTZ=Europe/Moscow\nDB_PATH=liss.db\n" "$TOKEN" > .env
fi
if [ ! -d .venv ]; then
    echo "Первый запуск: устанавливаю всё нужное..."
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || { rm -rf .venv; exit 1; }
fi
echo "Бот запущен! Открой @Akia7_bot в Telegram. Остановить: Ctrl+C"
exec .venv/bin/python -m bot
