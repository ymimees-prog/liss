"""Optional Claude tutor. Enabled only when ANTHROPIC_API_KEY is set; the bot works fully without it."""
import logging
import os

log = logging.getLogger(__name__)

SYSTEM = (
    "Ты — доброжелательный репетитор для студентки колледжа, которая учится на программиста и проходит "
    "челлендж «90 тяжёлых дней». Объясняй по-русски, просто и по делу, с примерами из жизни "
    "(деньги, учёба, её Telegram-бот). Код давай короткими кусками с пояснениями. "
    "Если тема про трейдинг — напоминай про риски и демо-счёт, не давай инвестиционных рекомендаций. "
    "Если про OSINT — только законные и этичные методы. "
    "Форматирование — только простой текст и Telegram HTML-теги <b>, <i>, <code>, <pre>; никакого Markdown. "
    "Ответ не длиннее 2500 символов."
)

_client = None


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.AsyncAnthropic()
    return _client


async def ask(question: str, topic: str | None = None) -> str:
    """Returns the tutor's answer, or a friendly error message (never raises)."""
    import anthropic

    content = f"Тема: {topic}\n\n{question}" if topic else question
    try:
        response = await _get_client().beta.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
            max_tokens=4000,
            system=SYSTEM,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        return "🔑 Ключ ANTHROPIC_API_KEY не подходит. Проверь его в .env."
    except anthropic.RateLimitError:
        return "⏳ Слишком много запросов, попробуй через минуту."
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s: %s", e.status_code, e.message)
        return "😔 Нейросеть сейчас недоступна. Встроенный урок всё равно с тобой!"
    except anthropic.APIConnectionError:
        return "🌐 Не получилось связаться с нейросетью (нет доступа к api.anthropic.com)."
    if response.stop_reason == "refusal":
        return "🙅 На этот вопрос нейросеть отвечать не стала. Попробуй переформулировать."
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text[:3900] or "🤔 Пустой ответ, попробуй спросить иначе."
