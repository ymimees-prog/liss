"""Switch the bot to hosting mode: `python -m bot.set_webhook https://USERNAME.pythonanywhere.com`."""
import asyncio
import sys

from .app import COMMANDS, build, webhook_secret
from .config import load_config


async def main(base_url: str) -> None:
    config = load_config()
    bot, _, _ = build(config)
    secret = webhook_secret(config)
    base_url = base_url.rstrip("/")
    try:
        await bot.set_webhook(f"{base_url}/tg/{secret}")
        await bot.set_my_commands(COMMANDS)
        info = await bot.get_webhook_info()
    finally:
        await bot.session.close()
    print("✅ Вебхук установлен:", info.url.replace(secret, "<секрет>"))
    print("\nСсылка для напоминаний (вставь в cron-job.org, запуск каждые 5 минут):")
    print(f"{base_url}/tick/{secret}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("Использование: python -m bot.set_webhook https://ТВОЙ_ЛОГИН.pythonanywhere.com")
    asyncio.run(main(sys.argv[1]))
