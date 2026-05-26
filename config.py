import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"Помилка: {name} не задано в .env файлі!")
    return value


BOT_TOKEN = _require("BOT_TOKEN")
MONO_TOKEN = _require("MONO_TOKEN")
MONO_JAR_SEND_ID = _require("MONO_JAR_SEND_ID")
MONO_WEBHOOK_SECRET = _require("MONO_WEBHOOK_SECRET")
WEBHOOK_BASE_URL = _require("WEBHOOK_BASE_URL").rstrip("/")

ADMIN_IDS: list[int] = [
    int(uid.strip())
    for uid in _require("ADMIN_IDS").split(",")
    if uid.strip()
]

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))

# Секрет в шляху — захист від випадкових POST'ів (Personal API не підписує webhook).
WEBHOOK_PATH = f"/monobank/webhook/{MONO_WEBHOOK_SECRET}"
WEBHOOK_URL = WEBHOOK_BASE_URL + WEBHOOK_PATH

PAYMENT_CODE_TTL_HOURS = int(os.getenv("PAYMENT_CODE_TTL_HOURS", "24"))
