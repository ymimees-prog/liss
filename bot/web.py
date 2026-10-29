"""Webhook mode for free hosting (PythonAnywhere): a plain WSGI app, no extra dependencies.

  POST /tg/<secret>    — updates from Telegram
  GET  /tick/<secret>  — call every few minutes (e.g. from cron-job.org) to send reminders
"""
import asyncio
import json
import logging
import threading

from .app import build, webhook_secret
from .config import load_config
from .reminders import send_due_reminders

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_config = load_config()
_bot, _dp, _db = build(_config)
_secret = webhook_secret(_config)
# One long-lived loop so the bot's HTTP session survives between requests.
_loop = asyncio.new_event_loop()
_lock = threading.Lock()


def _run(coro):
    with _lock:
        return _loop.run_until_complete(coro)


def application(environ, start_response):
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET")
    status, body = "200 OK", b"ok"
    try:
        if path == f"/tg/{_secret}" and method == "POST":
            size = int(environ.get("CONTENT_LENGTH") or 0)
            update = json.loads(environ["wsgi.input"].read(size) or b"{}")
            _run(_dp.feed_webhook_update(_bot, update))
        elif path == f"/tick/{_secret}":
            _run(send_due_reminders(_bot, _db))
        else:
            status, body = "404 Not Found", "Akia bot работает 🙂".encode()
    except Exception:
        # Always answer 200 to Telegram: otherwise it re-sends the same update forever.
        log.exception("failed to handle %s", path)
    start_response(status, [("Content-Type", "text/plain; charset=utf-8")])
    return [body]
