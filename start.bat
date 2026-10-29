@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .env (
    copy .env.example .env >nul
    echo Открой файл .env в Блокноте, впиши BOT_TOKEN и ALLOWED_USERS, сохрани и запусти start.bat ещё раз.
    notepad .env
    pause
    exit /b
)
if not exist .venv (
    echo Первый запуск: устанавливаю всё нужное...
    python -m venv .venv || (echo Установи Python с python.org и поставь галочку "Add Python to PATH" & pause & exit /b)
    .venv\Scripts\pip install -r requirements.txt
)
echo Бот запущен. Не закрывай это окно. Остановить: Ctrl+C
.venv\Scripts\python -m bot
pause
