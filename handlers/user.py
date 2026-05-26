"""Команди для покупця: /start (deep-link → превью), купівля, «Мої покупки»."""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import monobank
import texts
from config import PAYMENT_CODE_TTL_HOURS
from database import (
    create_payment,
    get_product,
    list_user_purchases,
    user_has_paid_product,
)

logger = logging.getLogger(__name__)

router = Router()


# ══════════════════════════════════════════════════════════════════════════════
#   Утиліти
# ══════════════════════════════════════════════════════════════════════════════

def _format_price(price_kop: int) -> str:
    return f"{price_kop / 100:.2f}".rstrip("0").rstrip(".") + "₴"


def _is_media(message: Message) -> bool:
    return bool(
        message.photo or message.video or message.animation
        or message.video_note or message.audio or message.document
    )


async def _replace_or_edit(message: Message, text: str, kb) -> None:
    """Якщо поточне media — видаляємо й шлемо нове. Інакше edit_text."""
    if _is_media(message):
        try:
            await message.delete()
        except Exception:
            pass
        await message.bot.send_message(
            message.chat.id, text, reply_markup=kb, disable_web_page_preview=True,
        )
    else:
        try:
            await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception as exc:
            logger.warning("edit_text fallback: %s", exc)
            await message.bot.send_message(
                message.chat.id, text, reply_markup=kb, disable_web_page_preview=True,
            )


async def _send_media_with_caption(bot, chat_id: int, product: dict, caption: str, reply_markup) -> None:
    file_id = product["preview_file_id"]
    kind = product["preview_type"]
    cap = caption or None  # None опускає поле, порожній рядок — теж OK, але None чистіше
    if kind == "photo":
        await bot.send_photo(chat_id, file_id, caption=cap, reply_markup=reply_markup)
    elif kind == "video":
        await bot.send_video(chat_id, file_id, caption=cap, reply_markup=reply_markup)
    elif kind == "animation":
        await bot.send_animation(chat_id, file_id, caption=cap, reply_markup=reply_markup)
    else:
        await bot.send_message(
            chat_id, caption or " ", reply_markup=reply_markup, disable_web_page_preview=True,
        )


def _parse_buy_payload(args: str | None) -> int | None:
    if not args or not args.startswith("buy_"):
        return None
    try:
        return int(args[4:])
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#   Welcome
# ══════════════════════════════════════════════════════════════════════════════

def _welcome_view() -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_MY_PURCHASES, callback_data="my_purchases")],
    ])
    return texts.START_WELCOME, kb


async def _send_welcome(message: Message) -> None:
    text, kb = _welcome_view()
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == "welcome")
async def cb_welcome(callback: CallbackQuery):
    text, kb = _welcome_view()
    await _replace_or_edit(callback.message, text, kb)
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#   /start — deep-link на превью товару
# ══════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    product_id = _parse_buy_payload(command.args)

    if product_id is None:
        await _send_welcome(message)
        return

    product = await get_product(product_id)
    if not product or not product["is_active"] or product["price_kop"] <= 0:
        await message.answer(texts.ERR_PRODUCT_UNAVAILABLE)
        await _send_welcome(message)
        return

    await _send_preview_new(message, product)


# ══════════════════════════════════════════════════════════════════════════════
#   Превью товару
# ══════════════════════════════════════════════════════════════════════════════

def _build_preview_caption(product: dict) -> str:
    """Caption = опис каналу як є. Порожньо, якщо опис не задано."""
    return (product.get("description") or "").strip()


def _build_preview_kb(product: dict) -> InlineKeyboardMarkup:
    price = _format_price(product["price_kop"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.BTN_BUY.format(price=price),
            callback_data=f"buy:{product['id']}",
        )],
        [InlineKeyboardButton(text=texts.BTN_MY_PURCHASES, callback_data="my_purchases")],
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data="welcome")],
    ])


async def _send_preview_new(message: Message, product: dict) -> None:
    """Нове повідомлення з превью (виклик з /start)."""
    caption = _build_preview_caption(product)
    kb = _build_preview_kb(product)
    if product.get("preview_file_id"):
        # media: caption може бути порожнім — Telegram покаже лише медіа
        await _send_media_with_caption(message.bot, message.chat.id, product, caption, kb)
    else:
        # без медіа потрібен хоч якийсь текст — fallback на назву
        text = caption or texts.PRODUCT_PREVIEW_FALLBACK.format(title=product["chat_title"])
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def _replace_with_preview(message: Message, product: dict) -> None:
    """Замінити поточне повідомлення на превью (callback 'prev:')."""
    caption = _build_preview_caption(product)
    kb = _build_preview_kb(product)
    if product.get("preview_file_id"):
        try:
            await message.delete()
        except Exception:
            pass
        await _send_media_with_caption(message.bot, message.chat.id, product, caption, kb)
    else:
        text = caption or texts.PRODUCT_PREVIEW_FALLBACK.format(title=product["chat_title"])
        await _replace_or_edit(message, text, kb)


@router.callback_query(F.data.startswith("prev:"))
async def cb_prev(callback: CallbackQuery):
    try:
        product_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(texts.ERR_BAD_PRODUCT, show_alert=True)
        return

    product = await get_product(product_id)
    if not product or not product["is_active"] or product["price_kop"] <= 0:
        await callback.answer(texts.ERR_PRODUCT_UNAVAILABLE, show_alert=True)
        return

    await _replace_with_preview(callback.message, product)
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#   Купівля
# ══════════════════════════════════════════════════════════════════════════════

def _already_paid_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.BTN_BUY_AGAIN,
            callback_data=f"buy_confirm:{product_id}",
        )],
        [InlineKeyboardButton(text=texts.BTN_MY_PURCHASES, callback_data="my_purchases")],
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"prev:{product_id}")],
    ])


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery):
    """«Купити» з превью товару."""
    try:
        product_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(texts.ERR_BAD_PRODUCT, show_alert=True)
        return

    product = await get_product(product_id)
    if not product or not product["is_active"] or product["price_kop"] <= 0:
        await callback.answer(texts.ERR_PRODUCT_UNAVAILABLE, show_alert=True)
        return

    user = callback.from_user

    if await user_has_paid_product(user.id, product_id):
        text = texts.ALREADY_PAID.format(title=product["chat_title"])
        kb = _already_paid_kb(product_id)
        await _replace_or_edit(callback.message, text, kb)
        await callback.answer()
        return

    await _proceed_to_buy(callback, product)


@router.callback_query(F.data.startswith("buy_confirm:"))
async def cb_buy_confirm(callback: CallbackQuery):
    """Повторна покупка (з екрану ALREADY_PAID)."""
    try:
        product_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(texts.ERR_BAD_PRODUCT, show_alert=True)
        return

    product = await get_product(product_id)
    if not product or not product["is_active"] or product["price_kop"] <= 0:
        await callback.answer(texts.ERR_PRODUCT_UNAVAILABLE, show_alert=True)
        return

    await _proceed_to_buy(callback, product)


async def _proceed_to_buy(callback: CallbackQuery, product: dict) -> None:
    payment = await _create_payment_safely(product, callback.from_user)
    if payment is None:
        await callback.answer(texts.ERR_TECHNICAL, show_alert=True)
        return

    text, kb = _build_buy_view(product, payment)
    await _replace_or_edit(callback.message, text, kb)
    await callback.answer(texts.CODE_GENERATED_TOAST)


async def _create_payment_safely(product: dict, user) -> dict | None:
    try:
        payment = await create_payment(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            product_id=product["id"],
            chat_id=product["chat_id"],
            amount_kop=product["price_kop"],
            ttl_hours=PAYMENT_CODE_TTL_HOURS,
        )
    except Exception as exc:
        logger.exception("create_payment впав: %s", exc)
        return None

    logger.info(
        "🧾 Видано код %s: user=%d (@%s), product=%d, %d коп.",
        payment["payment_code"], user.id, user.username or "",
        product["id"], product["price_kop"],
    )
    return payment


def _build_buy_view(product: dict, payment: dict) -> tuple[str, InlineKeyboardMarkup]:
    code = payment["payment_code"]
    price = _format_price(product["price_kop"])
    jar_url = monobank.get_jar_send_url(
        amount_kop=product["price_kop"],
        comment=code,
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_GO_TO_JAR, url=jar_url)],
        [InlineKeyboardButton(text=texts.BTN_MY_PURCHASES, callback_data="my_purchases")],
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"prev:{product['id']}")],
    ])

    text = texts.BUY_INSTRUCTION.format(
        title=product["chat_title"],
        price=price,
        code=code,
        ttl_hours=PAYMENT_CODE_TTL_HOURS,
    )
    return text, kb


# ══════════════════════════════════════════════════════════════════════════════
#   Мої покупки
# ══════════════════════════════════════════════════════════════════════════════

@router.message(Command("my"))
async def cmd_my(message: Message):
    await _send_my_purchases(message, user_id=message.from_user.id, edit=False)


@router.callback_query(F.data == "my_purchases")
async def cb_my_purchases(callback: CallbackQuery):
    await _send_my_purchases(callback.message, user_id=callback.from_user.id, edit=True)
    await callback.answer()


async def _send_my_purchases(target: Message, user_id: int, *, edit: bool) -> None:
    purchases = await list_user_purchases(user_id)

    if not purchases:
        text = texts.MY_PURCHASES_EMPTY
    else:
        lines = [texts.MY_PURCHASES_HEADER]
        for p in purchases:
            title = p.get("chat_title") or f"chat {p['chat_id']}"
            link = p.get("invite_link") or ""
            lines.append(texts.MY_PURCHASES_ITEM_TITLE.format(title=title))
            if link:
                lines.append(texts.MY_PURCHASES_ITEM_LINK.format(link=link))
            else:
                lines.append(texts.MY_PURCHASES_ITEM_PENDING)
        lines.append(texts.MY_PURCHASES_FOOTER)
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data="welcome")],
    ])

    if edit:
        await _replace_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb, disable_web_page_preview=True)
