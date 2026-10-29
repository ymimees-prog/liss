from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..common import h
from ..db import Database
from ..keyboards import BTN_DIGEST, main_menu
from ..logic import parse_time

router = Router()

HELP = """<b>Что я умею</b>

☀️ <b>Сводка</b> — курсы, открытые сделки, портфель и что повторить. Каждое утро присылаю сама
📈 <b>Рынок</b> — курсы доллара, USDT и крипты, графики с разбором, уведомления о цене
💼 <b>Портфель</b> — твои монеты, их стоимость сейчас и прибыль/убыток
📓 <b>Сделки</b> — дневник сделок (демо и реальных) со статистикой
🧮 <b>Калькулятор</b> — сколько купить, чтобы рисковать не больше 1–2% депозита
🎓 <b>Обучение</b> — уроки по крипте и трейдингу, тема дня, повторения

<b>Команды</b>
/digest 09:00 — время утренней сводки (/digest off — выключить)
/tz Europe/Moscow — часовой пояс
/cancel — отменить ввод"""


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, user):
    await state.clear()
    await message.answer(
        f"Привет, {h(user['name']) or 'бро'}! 👋\n\n"
        "Я твой помощник в крипте и трейдинге: слежу за курсами, считаю риск, веду дневник сделок "
        "и портфель, учу без воды. Главное правило — сначала защищаем депозит, потом зарабатываем 🛡\n\n"
        "С чего начать:\n"
        "1. 📈 Рынок — посмотри курсы и графики\n"
        "2. 🎓 Обучение → 🎯 Тема дня\n"
        "3. 📓 Сделки — запиши первую демо-сделку\n\n" + HELP,
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Окей, отменила.", reply_markup=main_menu())


@router.message(Command("digest"))
async def set_digest(message: Message, command: CommandObject, db: Database, user):
    arg = (command.args or "").strip().lower()
    if arg in ("off", "выкл"):
        db.update_user(user["user_id"], digest_time="off")
        await message.answer("🔕 Утренняя сводка выключена. Включить: <code>/digest 09:00</code>")
        return
    hhmm = parse_time(arg)
    if not hhmm:
        await message.answer("Напиши время: <code>/digest 09:00</code> или <code>/digest off</code>")
        return
    db.update_user(user["user_id"], digest_time=hhmm)
    await message.answer(f"⏰ Готово, сводка каждый день в {hhmm}.")


@router.message(Command("tz"))
async def set_tz(message: Message, command: CommandObject, db: Database, user):
    try:
        ZoneInfo((command.args or "").strip())
    except (ZoneInfoNotFoundError, ValueError):
        await message.answer("Напиши часовой пояс, например: <code>/tz Europe/Moscow</code> или <code>/tz Asia/Almaty</code>")
        return
    db.update_user(user["user_id"], tz=command.args.strip())
    await message.answer(f"🌍 Часовой пояс: {h(command.args.strip())}")


@router.message(F.text == BTN_DIGEST)
async def digest(message: Message, state: FSMContext, db: Database, user):
    from ..digest import build_digest

    await state.clear()
    await message.answer(await build_digest(db, user))
