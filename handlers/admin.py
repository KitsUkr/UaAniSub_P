"""Адмін-функціонал: реєстрація каналів через my_chat_member + кнопкове меню."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import texts
from config import ADMIN_IDS
from database import (
    add_or_update_product,
    clear_product_preview,
    delete_product_by_chat_id,
    get_product_by_chat_id,
    list_all_products,
    set_product_active,
    set_product_description,
    set_product_preview,
    set_product_price,
    stats_per_product,
    toggle_product_active,
)

logger = logging.getLogger(__name__)

router = Router()


class ChannelFSM(StatesGroup):
    waiting_price = State()
    waiting_desc = State()
    waiting_preview = State()


def _is_media(message: Message) -> bool:
    return bool(
        message.photo or message.video or message.animation
        or message.video_note or message.audio or message.document
    )


async def _send_preview_media(bot, chat_id: int, product: dict, caption: str, reply_markup) -> None:
    file_id = product["preview_file_id"]
    kind = product["preview_type"]
    if kind == "photo":
        await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    elif kind == "video":
        await bot.send_video(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    elif kind == "animation":
        await bot.send_animation(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id, caption, reply_markup=reply_markup)


async def _replace_or_edit(message: Message, text: str, kb) -> None:
    """Якщо поточне повідомлення — media, видаляємо й шлемо нове.
    Якщо текст — редагуємо in-place."""
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


def _format_price(price_kop: int) -> str:
    if price_kop <= 0:
        return texts.ADMIN_PRICE_NONE
    return f"{price_kop / 100:.2f}".rstrip("0").rstrip(".") + "₴"


def _parse_chat_id(callback_data: str) -> int | None:
    try:
        return int(callback_data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
#   Авто-реєстрація канала (бота додали/видалили адміном)
# ══════════════════════════════════════════════════════════════════════════════

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    old_status = update.old_chat_member.status if update.old_chat_member else "left"
    new_status = update.new_chat_member.status
    chat = update.chat

    if chat.type not in ("channel", "supergroup", "group"):
        return

    chat_title = chat.title or f"Chat {chat.id}"

    if new_status == "administrator" and old_status in ("left", "kicked", "member", "restricted"):
        can_invite = bool(getattr(update.new_chat_member, "can_invite_users", False))

        await add_or_update_product(chat.id, chat_title)
        await set_product_active(chat.id, True)

        logger.info("📡 Канал зареєстровано: %s (%d)", chat_title, chat.id)

        note = texts.CHANNEL_REG_NOTE_OK if can_invite else texts.CHANNEL_REG_NOTE_NO_INVITE

        existing = await get_product_by_chat_id(chat.id)
        if existing and existing["price_kop"] > 0:
            price_line = texts.CHANNEL_REG_PRICE_SET.format(
                price=_format_price(existing["price_kop"])
            )
        else:
            price_line = texts.CHANNEL_REG_PRICE_NONE

        text = texts.CHANNEL_REGISTERED.format(
            title=chat_title,
            chat_id=chat.id,
            price_line=price_line,
            note=note,
        )
        await _notify_admins(update, text)

    elif new_status in ("left", "kicked") and old_status in ("administrator", "member"):
        await set_product_active(chat.id, False)
        logger.info("📡 Канал деактивовано: %s (%d) — бота видалено", chat_title, chat.id)
        await _notify_admins(
            update,
            texts.CHANNEL_DEACTIVATED.format(title=chat_title, chat_id=chat.id),
        )


async def _notify_admins(update: ChatMemberUpdated, text: str) -> None:
    targets = set(ADMIN_IDS)
    if update.from_user:
        targets.add(update.from_user.id)
    for uid in targets:
        try:
            await update.bot.send_message(uid, text, disable_web_page_preview=True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#   /channels — кнопкове меню каналів
# ══════════════════════════════════════════════════════════════════════════════

@router.message(Command("channels"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_channels(message: Message, state: FSMContext):
    await state.clear()
    text, kb = await _build_channels_list_view()
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ch_list", F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _build_channels_list_view()
    await _replace_or_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data == "ch_close", F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_close(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


async def _build_channels_list_view() -> tuple[str, InlineKeyboardMarkup]:
    products = await list_all_products()

    if not products:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_CLOSE, callback_data="ch_close")],
        ])
        return texts.CHANNELS_EMPTY, kb

    rows = []
    for p in products:
        flag = "✅" if p["is_active"] else "🚫"
        rows.append([InlineKeyboardButton(
            text=texts.ADMIN_CHANNEL_BTN.format(flag=flag, title=p["chat_title"]),
            callback_data=f"ch_view:{p['chat_id']}",
        )])
    rows.append([InlineKeyboardButton(text=texts.BTN_CLOSE, callback_data="ch_close")])

    return texts.CHANNELS_HEADER, InlineKeyboardMarkup(inline_keyboard=rows)


# ══════════════════════════════════════════════════════════════════════════════
#   Деталі каналу
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ch_view:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_view(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    text, kb = await _build_channel_detail_view(chat_id)
    if text is None:
        await callback.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id), show_alert=True)
        text, kb = await _build_channels_list_view()
        await _replace_or_edit(callback.message, text, kb)
        return

    await _replace_or_edit(callback.message, text, kb)
    await callback.answer()


async def _build_channel_detail_view(
    chat_id: int,
) -> tuple[str | None, InlineKeyboardMarkup | None]:
    product = await get_product_by_chat_id(chat_id)
    if not product:
        return None, None

    # Збираємо статистику продажів по цьому каналу
    sold = 0
    revenue_kop = 0
    for r in await stats_per_product():
        if r["chat_id"] == chat_id:
            sold = r["sold_count"]
            revenue_kop = r["revenue_kop"]
            break

    status = texts.ADMIN_STATUS_ACTIVE if product["is_active"] else texts.ADMIN_STATUS_HIDDEN
    description = product["description"] or texts.ADMIN_DESC_NONE
    preview = texts.ADMIN_PREVIEW_YES if product["preview_file_id"] else texts.ADMIN_PREVIEW_NO

    text = texts.ADMIN_CHANNEL_DETAIL.format(
        title=product["chat_title"],
        chat_id=chat_id,
        price=_format_price(product["price_kop"]),
        status=status,
        preview=preview,
        description=description,
        sold=sold,
        revenue=_format_price(revenue_kop) if revenue_kop > 0 else "—",
    )

    toggle_btn = texts.BTN_TOGGLE_HIDE if product["is_active"] else texts.BTN_TOGGLE_SHOW

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=texts.BTN_PRICE, callback_data=f"ch_price:{chat_id}"),
            InlineKeyboardButton(text=texts.BTN_DESC, callback_data=f"ch_desc:{chat_id}"),
        ],
        [InlineKeyboardButton(text=texts.BTN_PREVIEW, callback_data=f"ch_prev:{chat_id}")],
        [InlineKeyboardButton(text=texts.BTN_LINK_BUY, callback_data=f"ch_link:{chat_id}")],
        [InlineKeyboardButton(text=toggle_btn, callback_data=f"ch_toggle:{chat_id}")],
        [InlineKeyboardButton(text=texts.BTN_DELETE, callback_data=f"ch_del:{chat_id}")],
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data="ch_list")],
    ])

    return text, kb


# ══════════════════════════════════════════════════════════════════════════════
#   Дії: ціна (FSM)
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ch_price:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_price(callback: CallbackQuery, state: FSMContext):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    await state.set_state(ChannelFSM.waiting_price)
    await state.update_data(chat_id=chat_id, bot_msg_id=callback.message.message_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
    ])
    await callback.message.edit_text(texts.ADMIN_PROMPT_PRICE, reply_markup=kb)
    await callback.answer()


@router.message(
    ChannelFSM.waiting_price,
    F.from_user.id.in_(ADMIN_IDS),
)
async def fsm_price_input(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return

    data = await state.get_data()
    chat_id = data["chat_id"]
    bot_msg_id = data["bot_msg_id"]
    user_chat = message.chat.id

    try:
        await message.delete()
    except Exception:
        pass

    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
        ])
        await message.bot.edit_message_text(
            f"{texts.ERR_BAD_AMOUNT}\n\n{texts.ADMIN_PROMPT_PRICE}",
            chat_id=user_chat, message_id=bot_msg_id,
            reply_markup=kb,
        )
        return

    price_kop = int(round(amount * 100))
    await set_product_price(chat_id, price_kop)
    await state.clear()

    text, kb = await _build_channel_detail_view(chat_id)
    if text is None:
        text, kb = await _build_channels_list_view()
    await message.bot.edit_message_text(
        text, chat_id=user_chat, message_id=bot_msg_id,
        reply_markup=kb, disable_web_page_preview=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#   Дії: опис (FSM)
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ch_desc:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_desc(callback: CallbackQuery, state: FSMContext):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    product = await get_product_by_chat_id(chat_id)
    if not product:
        await callback.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id), show_alert=True)
        return

    await state.set_state(ChannelFSM.waiting_desc)
    await state.update_data(chat_id=chat_id, bot_msg_id=callback.message.message_id)

    current = (product.get("description") or "").strip()
    if current:
        prompt = texts.ADMIN_PROMPT_DESC_REPLACE.format(current=current)
    else:
        prompt = texts.ADMIN_PROMPT_DESC

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
    ])
    await callback.message.edit_text(prompt, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()


@router.message(
    ChannelFSM.waiting_desc,
    F.from_user.id.in_(ADMIN_IDS),
)
async def fsm_desc_input(message: Message, state: FSMContext):
    # Якщо це команда (наприклад /channels) — нехай команд-хендлер відпрацює;
    # але оскільки команд-хендлери реєструються раніше, цей хендлер взагалі
    # не побачить /channels. Залишилось лише ігнорувати невідомі команди.
    if message.text and message.text.startswith("/"):
        return

    data = await state.get_data()
    chat_id = data["chat_id"]
    bot_msg_id = data["bot_msg_id"]
    user_chat = message.chat.id

    try:
        await message.delete()
    except Exception:
        pass

    # html_text перетворює entities (жирний, курсив, посилання, спойлери, mentions
    # тощо) у HTML, який потім коректно рендериться в caption превью.
    description = (message.html_text or "").strip()
    if not description:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
        ])
        await message.bot.edit_message_text(
            f"{texts.ERR_EMPTY_DESC}\n\n{texts.ADMIN_PROMPT_DESC}",
            chat_id=user_chat, message_id=bot_msg_id,
            reply_markup=kb,
        )
        return

    saved = await set_product_description(chat_id, description)
    logger.info(
        "Опис каналу %s оновлено: saved=%s, len=%d",
        chat_id, saved, len(description),
    )
    await state.clear()

    text, kb = await _build_channel_detail_view(chat_id)
    if text is None:
        text, kb = await _build_channels_list_view()
    try:
        await message.bot.edit_message_text(
            text, chat_id=user_chat, message_id=bot_msg_id,
            reply_markup=kb, disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.warning(
            "Не вдалося edit_message_text після збереження опису (chat_id=%s): %s. "
            "Шлю нове повідомлення.",
            chat_id, exc,
        )
        await message.bot.send_message(
            user_chat, text, reply_markup=kb, disable_web_page_preview=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
#   Дії: посилання на покупку
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ch_link:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_link(callback: CallbackQuery):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    product = await get_product_by_chat_id(chat_id)
    if not product:
        await callback.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id), show_alert=True)
        return

    me = await callback.bot.me()
    deep_link = f"https://t.me/{me.username}?start=buy_{product['id']}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"ch_view:{chat_id}")],
    ])
    await callback.message.edit_text(
        texts.ADMIN_LINK_RESULT.format(title=product["chat_title"], link=deep_link),
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#   Дії: toggle (показати/приховати)
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ch_toggle:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_toggle(callback: CallbackQuery):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    new_state = await toggle_product_active(chat_id)
    if new_state is None:
        await callback.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id), show_alert=True)
        return

    text, kb = await _build_channel_detail_view(chat_id)
    if text:
        await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)

    toast = texts.ADMIN_TOGGLED_SHOWN_TOAST if new_state else texts.ADMIN_TOGGLED_HIDDEN_TOAST
    await callback.answer(toast)


# ══════════════════════════════════════════════════════════════════════════════
#   Дії: видалення (з підтвердженням)
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ch_del:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_del_confirm(callback: CallbackQuery):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    product = await get_product_by_chat_id(chat_id)
    if not product:
        await callback.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id), show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_CONFIRM_DELETE, callback_data=f"ch_del_yes:{chat_id}")],
        [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
    ])
    await callback.message.edit_text(
        texts.ADMIN_CONFIRM_DELETE.format(title=product["chat_title"]),
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ch_del_yes:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_del_yes(callback: CallbackQuery):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    deleted = await delete_product_by_chat_id(chat_id)

    text, kb = await _build_channels_list_view()
    await _replace_or_edit(callback.message, text, kb)

    toast = texts.ADMIN_CHANNEL_DELETED_TOAST if deleted else texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id)
    await callback.answer(toast)


# ══════════════════════════════════════════════════════════════════════════════
#   Дії: превью (FSM з прийомом фото/відео/GIF)
# ══════════════════════════════════════════════════════════════════════════════

async def _show_preview_screen(target_message: Message, chat_id: int) -> None:
    """Показати екран керування превью. Поточне повідомлення видаляється,
    бо ми переходимо між text↔media."""
    product = await get_product_by_chat_id(chat_id)
    if not product:
        text, kb = await _build_channels_list_view()
        await _replace_or_edit(target_message, text, kb)
        return

    try:
        await target_message.delete()
    except Exception:
        pass

    user_chat = target_message.chat.id
    if product["preview_file_id"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=texts.BTN_REPLACE_PREVIEW, callback_data=f"ch_prev_set:{chat_id}"),
                InlineKeyboardButton(text=texts.BTN_DELETE_PREVIEW, callback_data=f"ch_prev_del:{chat_id}"),
            ],
            [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"ch_view:{chat_id}")],
        ])
        caption = texts.ADMIN_PREVIEW_TITLE.format(title=product["chat_title"])
        await _send_preview_media(target_message.bot, user_chat, product, caption, kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_ADD_PREVIEW, callback_data=f"ch_prev_set:{chat_id}")],
            [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"ch_view:{chat_id}")],
        ])
        await target_message.bot.send_message(
            user_chat,
            texts.ADMIN_PREVIEW_NONE.format(title=product["chat_title"]),
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("ch_prev:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_prev(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    await _show_preview_screen(callback.message, chat_id)
    await callback.answer()


@router.callback_query(F.data.startswith("ch_prev_set:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_prev_set(callback: CallbackQuery, state: FSMContext):
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    # Видаляємо поточне (може бути media), шлемо текстове запрошення
    try:
        await callback.message.delete()
    except Exception:
        pass

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
    ])
    sent = await callback.bot.send_message(
        callback.message.chat.id,
        texts.ADMIN_PROMPT_PREVIEW,
        reply_markup=cancel_kb,
    )

    await state.set_state(ChannelFSM.waiting_preview)
    await state.update_data(chat_id=chat_id, bot_msg_id=sent.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("ch_prev_del:"), F.from_user.id.in_(ADMIN_IDS))
async def cb_ch_prev_del(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id = _parse_chat_id(callback.data)
    if chat_id is None:
        await callback.answer(texts.ERR_BAD_CHAT_ID, show_alert=True)
        return

    await clear_product_preview(chat_id)
    await _show_preview_screen(callback.message, chat_id)
    await callback.answer(texts.ADMIN_PREVIEW_DELETED_TOAST)


@router.message(ChannelFSM.waiting_preview, F.from_user.id.in_(ADMIN_IDS))
async def fsm_preview_input(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    bot_msg_id = data["bot_msg_id"]
    user_chat = message.chat.id

    file_id: str | None = None
    kind: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
        kind = "photo"
    elif message.video:
        file_id = message.video.file_id
        kind = "video"
    elif message.animation:
        file_id = message.animation.file_id
        kind = "animation"

    try:
        await message.delete()
    except Exception:
        pass

    if not file_id:
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=f"ch_view:{chat_id}")],
        ])
        try:
            await message.bot.edit_message_text(
                f"{texts.ERR_NOT_MEDIA}\n\n{texts.ADMIN_PROMPT_PREVIEW}",
                chat_id=user_chat, message_id=bot_msg_id,
                reply_markup=cancel_kb,
            )
        except Exception:
            pass
        return

    await set_product_preview(chat_id, file_id, kind)
    await state.clear()

    # Видаляємо запрошення (текст), показуємо екран превью (media)
    try:
        await message.bot.delete_message(user_chat, bot_msg_id)
    except Exception:
        pass

    product = await get_product_by_chat_id(chat_id)
    if not product:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=texts.BTN_REPLACE_PREVIEW, callback_data=f"ch_prev_set:{chat_id}"),
            InlineKeyboardButton(text=texts.BTN_DELETE_PREVIEW, callback_data=f"ch_prev_del:{chat_id}"),
        ],
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"ch_view:{chat_id}")],
    ])
    caption = texts.ADMIN_PREVIEW_TITLE.format(title=product["chat_title"])
    await _send_preview_media(message.bot, user_chat, product, caption, kb)


# ══════════════════════════════════════════════════════════════════════════════
#   Текстові команди (для досвідчених адмінів — альтернатива кнопкам)
# ══════════════════════════════════════════════════════════════════════════════

@router.message(Command("setprice"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_setprice(message: Message, state: FSMContext):
    await state.clear()
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(texts.USAGE_SETPRICE)
        return

    try:
        chat_id = int(parts[1])
        amount_uah = float(parts[2].replace(",", "."))
        if amount_uah <= 0:
            raise ValueError
    except ValueError:
        await message.answer(texts.ERR_BAD_AMOUNT)
        return

    price_kop = int(round(amount_uah * 100))
    if not await set_product_price(chat_id, price_kop):
        await message.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id))
        return

    await message.answer(texts.PRICE_UPDATED.format(
        price=_format_price(price_kop),
        chat_id=chat_id,
    ))


@router.message(Command("setdesc"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_setdesc(message: Message, state: FSMContext):
    await state.clear()
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(texts.USAGE_SETDESC)
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer(texts.ERR_BAD_CHAT_ID)
        return

    description = parts[2].strip()
    if not await set_product_description(chat_id, description):
        await message.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id))
        return

    await message.answer(texts.DESC_UPDATED.format(chat_id=chat_id))


@router.message(Command("toggle"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_toggle(message: Message, state: FSMContext):
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(texts.USAGE_TOGGLE)
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer(texts.ERR_BAD_CHAT_ID)
        return

    new_state = await toggle_product_active(chat_id)
    if new_state is None:
        await message.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id))
        return

    tpl = texts.TOGGLED_SHOWN if new_state else texts.TOGGLED_HIDDEN
    await message.answer(tpl.format(chat_id=chat_id))


@router.message(Command("link"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_link(message: Message, state: FSMContext):
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(texts.USAGE_LINK)
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer(texts.ERR_BAD_CHAT_ID)
        return

    product = await get_product_by_chat_id(chat_id)
    if not product:
        await message.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id))
        return

    me = await message.bot.me()
    deep_link = f"https://t.me/{me.username}?start=buy_{product['id']}"
    await message.answer(
        texts.ADMIN_LINK_RESULT.format(
            title=product["chat_title"],
            link=deep_link,
        ),
        disable_web_page_preview=True,
    )


@router.message(Command("remove"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_remove(message: Message, state: FSMContext):
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(texts.USAGE_REMOVE)
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer(texts.ERR_BAD_CHAT_ID)
        return

    if not await delete_product_by_chat_id(chat_id):
        await message.answer(texts.ERR_CHANNEL_NOT_FOUND.format(chat_id=chat_id))
        return

    await message.answer(texts.REMOVED.format(chat_id=chat_id))


@router.message(Command("stats"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stats(message: Message, state: FSMContext):
    await state.clear()
    rows = await stats_per_product()
    if not rows:
        await message.answer(texts.STATS_EMPTY)
        return

    total_sold = 0
    total_revenue_kop = 0

    lines = [texts.STATS_HEADER]
    for r in rows:
        sold = r["sold_count"]
        rev = r["revenue_kop"]
        total_sold += sold
        total_revenue_kop += rev
        flag = "✅" if r["is_active"] else "🚫"
        lines.append(texts.STATS_LINE.format(
            flag=flag,
            title=r["chat_title"],
            price=_format_price(r["price_kop"]),
            sold=sold,
            revenue=_format_price(rev),
        ))

    lines.append(texts.STATS_TOTAL.format(
        total_sold=total_sold,
        total_revenue=_format_price(total_revenue_kop),
    ))
    await message.answer("\n".join(lines))
