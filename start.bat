@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Akia bot

rem ---------- 1. Python ----------
python -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Python не найден. Пробую установить автоматически...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo Если установка прошла успешно — ЗАКРОЙ это окно и снова запусти start.bat.
    echo Если нет — скачай Python с python.org и при установке поставь галочку "Add python.exe to PATH".
    pause
    exit /b
)

rem ---------- 2. Settings (.env) ----------
if not exist .env (
    echo.
    echo Вставь ключ бота от @BotFather и нажми Enter.
    echo Чтобы вставить: нажми ПРАВУЮ кнопку мыши в этом окне.
    set /p TOKEN=Ключ: 
    call :write_env
)

rem ---------- 3. Libraries ----------
if not exist .venv (
    echo Первый запуск: устанавливаю всё нужное, это пара минут...
    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip >nul
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo Не получилось установить библиотеки. Сделай скриншот этого окна и пришли его.
        rmdir /s /q .venv
        pause
        exit /b
    )
)

rem ---------- 4. Run ----------
echo.
echo Бот запущен! Открой @Akia7_bot в Telegram и нажми Start.
echo НЕ закрывай это окно (его можно свернуть). Остановить: Ctrl+C
echo.
.venv\Scripts\python -m bot
echo.
echo Бот остановился. Если выше ошибка — пришли скриншот.
echo Неправильный ключ? Удали файл .env и запусти start.bat заново.
pause
exit /b

:write_env
(
    echo BOT_TOKEN=%TOKEN%
    echo ALLOWED_USERS=9166868659
    echo TZ=Europe/Moscow
    echo DB_PATH=liss.db
) > .env
exit /b
