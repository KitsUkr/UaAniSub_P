"""HTTP-сервер для прийому StatementItem-webhook'ів від Monobank Personal API.

Маршрут: WEBHOOK_PATH = /monobank/webhook/<MONO_WEBHOOK_SECRET>
- GET  → 200 OK (Monobank пінгує URL при реєстрації)
- POST → JSON {"type":"StatementItem","data":{"account":"...","statementItem":{...}}}
"""

import json
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

import monobank
import texts
from config import ADMIN_IDS, WEBHOOK_PATH
from database import (
    get_payment_by_code,
    get_payment_by_id,
    get_payment_by_statement_id,
    mark_payment_paid,
    mark_payment_underpaid,
    set_payment_invite_link,
)

logger = logging.getLogger(__name__)


def build_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WEBHOOK_PATH, _handle_post)
    app.router.add_get(WEBHOOK_PATH, _handle_ping)  # для верифікації при set_webhook
    app.router.add_get("/health", _handle_health)
    return app


async def _handle_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _handle_ping(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _handle_post(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        logger.warning("Webhook: тіло не JSON")
        return web.Response(status=400, text="bad json")

    if data.get("type") != "StatementItem":
        logger.debug("Webhook: невідомий type=%r, ігноруємо", data.get("type"))
        return web.Response(text="ignored")

    payload = data.get("data") or {}
    account = payload.get("account", "")
    item = payload.get("statementItem") or {}

    statement_id = item.get("id", "")
    amount = item.get("amount", 0)  # копійки, додатнє для зарахування
    comment = (item.get("comment") or "").strip()

    if not statement_id:
        logger.warning("Webhook: відсутній statementItem.id")
        return web.Response(status=400, text="missing id")

    # Фільтр: тільки наша банка, тільки зарахування
    if account != monobank.get_jar_account_id():
        logger.debug("Webhook: чужий account=%s, пропуск", account)
        return web.Response(text="ok")
    if amount <= 0:
        logger.debug("Webhook: відплив (amount=%d), пропуск", amount)
        return web.Response(text="ok")

    # Ідемпотентність — той самий statement_id вже оброблено
    existing = await get_payment_by_statement_id(statement_id)
    if existing:
        logger.info("Webhook: statement %s вже оброблено", statement_id)
        return web.Response(text="duplicate")

    bot: Bot = request.app["bot"]

    if not comment:
        await _alert_unmatched(
            bot, statement_id, amount, comment,
            texts.UNMATCHED_REASON_NO_COMMENT,
        )
        logger.warning("Webhook: вхідний платіж %s без коментаря, amount=%d",
                       statement_id, amount)
        return web.Response(text="no comment")

    payment = await _extract_payment_by_comment(comment)
    if not payment:
        await _alert_unmatched(
            bot, statement_id, amount, comment,
            texts.UNMATCHED_REASON_NOT_FOUND,
        )
        logger.warning(
            "Webhook: не вдалося зіставити платіж. statement=%s, comment=%r, amount=%d",
            statement_id, comment, amount,
        )
        return web.Response(text="unmatched")

    # TTL-перевірка: pending з простроченим expires_at
    if _is_expired(payment):
        logger.warning("Webhook: код %s прострочений, statement=%s",
                       payment["payment_code"], statement_id)
        await _alert_unmatched(
            bot, statement_id, amount, comment,
            texts.UNMATCHED_REASON_EXPIRED.format(user_id=payment["user_id"]),
        )
        return web.Response(text="expired code")

    if amount < payment["amount_kop"]:
        await _handle_underpaid(bot, payment, statement_id, amount)
        return web.Response(text="underpaid")

    await _handle_success(bot, payment, statement_id, amount)
    return web.Response(text="ok")


async def _extract_payment_by_comment(comment: str) -> dict | None:
    """Спершу пробуємо весь коментар, потім токени, починаючи з UAS-."""
    payment = await get_payment_by_code(comment)
    if payment:
        return payment

    for token in comment.split():
        if token.upper().startswith("UAS-"):
            payment = await get_payment_by_code(token)
            if payment:
                return payment

    for token in comment.split():
        payment = await get_payment_by_code(token)
        if payment:
            return payment

    return None


def _is_expired(payment: dict) -> bool:
    dt = payment.get("expires_at")
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > dt and payment["status"] != "paid"


# ══════════════════════════════════════════════════════════════════════════════
#   Обробка успіху / недоплати
# ══════════════════════════════════════════════════════════════════════════════

async def _handle_success(bot: Bot, payment: dict, statement_id: str, amount: int) -> None:
    payment_id = payment["id"]
    if not await mark_payment_paid(payment_id, statement_id, amount):
        logger.info("Платіж %d вже оброблено паралельно, skip", payment_id)
        return

    payment = await get_payment_by_id(payment_id) or payment
    user_id = payment["user_id"]
    chat_id = payment["chat_id"]

    try:
        link = await bot.create_chat_invite_link(
            chat_id=chat_id,
            member_limit=1,
            name=f"buy_{payment_id}",
        )
    except TelegramAPIError as exc:
        logger.exception("Не вдалося створити invite-link для chat %d: %s", chat_id, exc)
        await _alert_admins(bot, texts.ADMIN_INVITE_FAILED.format(
            payment_id=payment_id,
            code=payment["payment_code"],
            chat_id=chat_id,
            error=str(exc),
            user_id=user_id,
        ))
        await _delete_instruction(bot, user_id, payment.get("instruction_message_id"))
        await _safe_send(bot, user_id, texts.PAID_INVITE_LINK_FAILED)
        return

    await set_payment_invite_link(payment_id, link.invite_link)

    chat_title = await _resolve_chat_title(bot, chat_id)
    title_line = texts.PAID_TITLE_LINE.format(title=chat_title) if chat_title else ""

    if amount > payment["amount_kop"]:
        diff = (amount - payment["amount_kop"]) / 100
        overpaid_note = texts.PAID_OVERPAID_NOTE.format(diff=diff)
    else:
        overpaid_note = ""

    await _delete_instruction(bot, user_id, payment.get("instruction_message_id"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_MY_PURCHASES, callback_data="my_purchases")],
    ])
    await _safe_send(
        bot, user_id,
        texts.PAID_SUCCESS.format(
            title_line=title_line,
            link=link.invite_link,
            overpaid_note=overpaid_note,
        ),
        reply_markup=kb,
    )
    logger.info(
        "✅ Видано доступ: payment=%d, user=%d, chat=%d, paid=%d коп.",
        payment_id, user_id, chat_id, amount,
    )


async def _handle_underpaid(bot: Bot, payment: dict, statement_id: str, amount: int) -> None:
    payment_id = payment["id"]
    if not await mark_payment_underpaid(payment_id, statement_id, amount):
        return

    expected = payment["amount_kop"]
    diff = (expected - amount) / 100
    await _delete_instruction(bot, payment["user_id"], payment.get("instruction_message_id"))
    await _safe_send(
        bot, payment["user_id"],
        texts.UNDERPAID_USER.format(
            expected=expected / 100,
            got=amount / 100,
            diff=diff,
        ),
    )
    await _alert_admins(bot, texts.ADMIN_UNDERPAID.format(
        payment_id=payment_id,
        code=payment["payment_code"],
        expected=expected / 100,
        got=amount / 100,
        statement_id=statement_id,
        user_id=payment["user_id"],
        username=payment.get("username") or "",
    ))
    logger.warning("Недоплата: payment=%d, expected=%d, got=%d", payment_id, expected, amount)


# ══════════════════════════════════════════════════════════════════════════════
#   Утиліти
# ══════════════════════════════════════════════════════════════════════════════

async def _alert_unmatched(
    bot: Bot, statement_id: str, amount: int, comment: str, reason: str,
) -> None:
    await _alert_admins(bot, texts.ADMIN_UNMATCHED.format(
        reason=reason,
        amount=amount / 100,
        comment=comment or "—",
        statement_id=statement_id,
    ))


async def _resolve_chat_title(bot: Bot, chat_id: int) -> str:
    try:
        chat = await bot.get_chat(chat_id)
        return chat.title or ""
    except TelegramAPIError:
        return ""


async def _safe_send(
    bot: Bot,
    user_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await bot.send_message(
            user_id, text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramAPIError as exc:
        logger.warning("Не вдалося надіслати %d: %s", user_id, exc)


async def _delete_instruction(bot: Bot, user_id: int, message_id: int | None) -> None:
    """Видаляє повідомлення з BUY_INSTRUCTION. Помилки ігноруємо — юзер міг
    видалити сам, або message_id застарів (юзер натиснув «Назад»)."""
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=user_id, message_id=message_id)
    except TelegramAPIError as exc:
        logger.info("delete_message (msg=%s) пропущено: %s", message_id, exc)


async def _alert_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, disable_web_page_preview=True)
        except TelegramAPIError:
            pass
