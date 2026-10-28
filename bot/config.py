import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the bot runs without extra dependencies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_users: frozenset[int]
    tz: str
    db_path: str


def load_config() -> Config:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируй .env.example в .env и вставь токен от @BotFather.")
    allowed = frozenset(
        int(x) for x in os.environ.get("ALLOWED_USERS", "").replace(" ", "").split(",") if x
    )
    return Config(
        bot_token=token,
        allowed_users=allowed,
        tz=os.environ.get("TZ", "Europe/Moscow"),
        db_path=os.environ.get("DB_PATH", "liss.db"),
    )
