"""Клієнт Monobank Personal API.

Документація: https://api.monobank.ua/docs/

Робота через персональний токен (X-Token) з акаунту monobank, а не Acquiring.
Платежі ідентифікуються через поле "comment" вхідної транзакції на банку (jar).
"""

import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

API_BASE = "https://api.monobank.ua"
CCY_UAH = 980

_session: aiohttp.ClientSession | None = None
_jar_account_id: str | None = None
_jar_send_id: str | None = None
_jar_title: str = ""


async def init(token: str, jar_send_id: str) -> None:
    """Відкриває HTTP-сесію та шукає банку за sendId в client-info."""
    global _session, _jar_account_id, _jar_send_id, _jar_title

    _session = aiohttp.ClientSession(
        headers={"X-Token": token},
        timeout=aiohttp.ClientTimeout(total=15),
    )
    _jar_send_id = jar_send_id

    info = await _client_info()
    jars = info.get("jars", []) or []
    if not jars:
        raise RuntimeError(
            "У цьому акаунті немає жодної банки. "
            "Створіть банку в додатку Monobank і вкажіть її sendId у MONO_JAR_SEND_ID."
        )

    matched = next((j for j in jars if j.get("sendId") == jar_send_id), None)
    if not matched:
        available = ", ".join(j.get("sendId", "?") for j in jars)
        raise RuntimeError(
            f"Банку з sendId={jar_send_id!r} не знайдено. "
            f"Доступні sendId: {available}"
        )

    _jar_account_id = matched["id"]
    _jar_title = matched.get("title", "")
    logger.info(
        "Monobank: знайдена банка %r (sendId=%s, account=%s)",
        _jar_title, _jar_send_id, _jar_account_id,
    )


async def close() -> None:
    global _session
    if _session is not None:
        await _session.close()
        _session = None


def _require_session() -> aiohttp.ClientSession:
    if _session is None:
        raise RuntimeError("monobank.init() не викликано")
    return _session


# ══════════════════════════════════════════════════════════════════════════════
#   API calls
# ══════════════════════════════════════════════════════════════════════════════

async def _client_info() -> dict[str, Any]:
    """GET /personal/client-info — список акаунтів та банок.

    Має жорсткий rate limit (1 запит / 60 сек). Викликаємо лише на старті.
    """
    session = _require_session()
    async with session.get(f"{API_BASE}/personal/client-info") as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(
                f"monobank client-info failed: HTTP {resp.status}: {body}"
            )
        return await resp.json()


async def set_webhook(webhook_url: str) -> None:
    """POST /personal/webhook — реєструє URL для отримання StatementItem.

    Monobank робить GET на цей URL для перевірки доступності (має відповісти 200).
    Rate limit: 1 запит / 60 сек.
    """
    session = _require_session()
    async with session.post(
        f"{API_BASE}/personal/webhook",
        json={"webHookUrl": webhook_url},
    ) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise RuntimeError(
                f"monobank set webhook failed: HTTP {resp.status}: {body}"
            )
    logger.info("Webhook зареєстровано в Monobank: %s", webhook_url)


def get_jar_account_id() -> str:
    if _jar_account_id is None:
        raise RuntimeError("monobank.init() не викликано")
    return _jar_account_id


def get_jar_send_url(amount_kop: int | None = None, comment: str | None = None) -> str:
    """URL банки. Якщо передати amount_kop та/або comment, вони підставляться
    у поля суми й коментаря на сторінці оплати Monobank.
    """
    if _jar_send_id is None:
        raise RuntimeError("monobank.init() не викликано")

    base = f"https://send.monobank.ua/{_jar_send_id}"
    params: dict[str, str] = {}
    if amount_kop:
        # формат "49" або "49.50" — без зайвих нулів
        params["a"] = f"{amount_kop / 100:.2f}".rstrip("0").rstrip(".")
    if comment:
        params["t"] = comment
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def get_jar_title() -> str:
    return _jar_title


__all__ = [
    "init",
    "close",
    "set_webhook",
    "get_jar_account_id",
    "get_jar_send_url",
    "get_jar_title",
    "CCY_UAH",
]
