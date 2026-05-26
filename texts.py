"""Усі тексти, що бачить користувач (UK).

Шаблони використовують `.format(...)` з іменованими плейсхолдерами.
"""

# ══════════════════════════════════════════════════════════════════════════════
#   Welcome (/start без payload)
# ══════════════════════════════════════════════════════════════════════════════

START_WELCOME = (
    "<b>UaAniSub</b>\n"
    "Доступ до приватних аніме-каналів з українською озвучкою.\n\n"
    "Для покупки скористайтесь посиланням від адміністратора."
)

# ══════════════════════════════════════════════════════════════════════════════
#   Превью товару (відкривається через deep-link)
# ══════════════════════════════════════════════════════════════════════════════

# Текст превью = опис каналу як є (без авто-форматування).
# Якщо опис не задано і немає медіа — використовується назва як fallback.
PRODUCT_PREVIEW_FALLBACK = "<b>{title}</b>"

# ══════════════════════════════════════════════════════════════════════════════
#   Купівля
# ══════════════════════════════════════════════════════════════════════════════

ERR_BAD_PRODUCT = "Некоректний товар"
ERR_PRODUCT_UNAVAILABLE = "Товар недоступний"
ERR_TECHNICAL = "Технічна помилка, спробуйте пізніше."

ALREADY_PAID = (
    "Ви вже маєте доступ до <b>{title}</b>.\n"
    "Якщо втратили посилання — погляньте в «Мої покупки».\n\n"
    "Купити ще одне?"
)

BUY_INSTRUCTION = (
    "<b>{title}</b>\n"
    "Сума: <b>{price}</b>\n"
    "Код: <code>{code}</code>\n\n"
    "Натисніть «Перейти до банки» — сума й код у коментарі підставляться автоматично.\n\n"
    "<i>Якщо поля не підставились — впишіть код вручну в поле «Коментар». "
    "Код дійсний {ttl_hours} год.</i>"
)

CODE_GENERATED_TOAST = "Код згенеровано"

# ══════════════════════════════════════════════════════════════════════════════
#   Платіж: успіх / недоплата / технічна помилка
# ══════════════════════════════════════════════════════════════════════════════

PAID_SUCCESS = (
    "<b>Дякуємо за покупку!</b>{title_line}\n\n"
    "<a href=\"{link}\">{link}</a>\n\n"
    "<i>Одноразове — діє для одного переходу.</i>"
    "{overpaid_note}"
)
PAID_TITLE_LINE = "\nКанал: <b>{title}</b>"
PAID_OVERPAID_NOTE = "\n<i>Дякуємо за донат +{diff:.2f}₴.</i>"

PAID_INVITE_LINK_FAILED = (
    "Оплату отримано, але виникла технічна помилка з видачею посилання.\n"
    "Зверніться до підтримки."
)

UNDERPAID_USER = (
    "<b>Недоплата.</b>\n"
    "Очікувалось: {expected:.2f}₴, отримано: {got:.2f}₴.\n"
    "Зверніться до підтримки."
)

# ══════════════════════════════════════════════════════════════════════════════
#   Мої покупки
# ══════════════════════════════════════════════════════════════════════════════

MY_PURCHASES_EMPTY = (
    "<b>Мої покупки</b>\n\n"
    "Порожньо."
)
MY_PURCHASES_HEADER = "<b>Мої покупки</b>\n"
MY_PURCHASES_FOOTER = "\n<i>Посилання одноразові.</i>"
MY_PURCHASES_ITEM_TITLE = "• <b>{title}</b>"
MY_PURCHASES_ITEM_LINK = "  <a href=\"{link}\">{link}</a>"
MY_PURCHASES_ITEM_PENDING = "  <i>посилання готується…</i>"

# ══════════════════════════════════════════════════════════════════════════════
#   Кнопки
# ══════════════════════════════════════════════════════════════════════════════

BTN_MY_PURCHASES = "Мої покупки"
BTN_BUY = "Купити за {price}"
BTN_BUY_AGAIN = "Так, купити ще раз"
BTN_GO_TO_JAR = "Перейти до оплати"
BTN_BACK = "« Назад"

# Адмін-кнопки
BTN_PRICE = "Ціна"
BTN_DESC = "Опис"
BTN_PREVIEW = "Превью"
BTN_ADD_PREVIEW = "Додати"
BTN_REPLACE_PREVIEW = "Замінити"
BTN_DELETE_PREVIEW = "Видалити"
BTN_LINK_BUY = "Посилання на покупку"
BTN_TOGGLE_HIDE = "Приховати"
BTN_TOGGLE_SHOW = "Показати"
BTN_DELETE = "Видалити"
BTN_CONFIRM_DELETE = "Так, видалити"
BTN_CANCEL = "Скасувати"
BTN_CLOSE = "« Закрити"

# ══════════════════════════════════════════════════════════════════════════════
#   Адмін: реєстрація каналу (my_chat_member)
# ══════════════════════════════════════════════════════════════════════════════

CHANNEL_REGISTERED = (
    "<b>Канал підключено</b>\n"
    "{title}\n"
    "<code>{chat_id}</code>"
    "{price_line}\n\n"
    "{note}\n\n"
    "Управління — у меню /channels"
)
CHANNEL_REG_PRICE_SET = "\nЦіна: <b>{price}</b>"
CHANNEL_REG_PRICE_NONE = "\nЦіна ще не встановлена."
CHANNEL_REG_NOTE_OK = "Право <b>Invite Users via Link</b> увімкнено."
CHANNEL_REG_NOTE_NO_INVITE = (
    "<b>Увага:</b> бот не має права <b>Invite Users via Link</b>. "
    "Без нього він не зможе видавати посилання покупцям."
)

CHANNEL_DEACTIVATED = (
    "<b>Канал відключено</b>\n"
    "{title} (<code>{chat_id}</code>) — бот більше не адмін.\n"
    "Прихований з каталогу."
)

# ══════════════════════════════════════════════════════════════════════════════
#   Адмін: команди
# ══════════════════════════════════════════════════════════════════════════════

CHANNELS_EMPTY = (
    "Каналів немає.\n"
    "Додайте бота адміністратором у канал — він зареєструється автоматично."
)
CHANNELS_HEADER = "<b>Канали</b> — оберіть для управління:"

# Деталі каналу (адмін-меню)
ADMIN_CHANNEL_BTN = "{flag} {title}"
ADMIN_CHANNEL_DETAIL = (
    "<b>{title}</b>\n"
    "<code>{chat_id}</code>\n\n"
    "Ціна: <b>{price}</b>\n"
    "Статус: {status}\n"
    "Превью: {preview}\n"
    "Продано: {sold} шт · Виручка: {revenue}\n\n"
    "Опис: {description}"
)
ADMIN_STATUS_ACTIVE = "активний"
ADMIN_STATUS_HIDDEN = "прихований"
ADMIN_DESC_NONE = "<i>не задано</i>"
ADMIN_PRICE_NONE = "не встановлено"
ADMIN_PREVIEW_YES = "є"
ADMIN_PREVIEW_NO = "—"

ADMIN_PREVIEW_TITLE = "Превью каналу <b>{title}</b>"
ADMIN_PREVIEW_NONE = "Превью каналу <b>{title}</b> не задано."
ADMIN_PROMPT_PREVIEW = (
    "Надішліть <b>фото</b>, <b>відео</b> або <b>GIF</b> для превью каналу.\n"
    "<i>Воно показуватиметься покупцям на сторінці оплати.</i>"
)
ERR_NOT_MEDIA = "Підтримуються лише фото, відео та GIF."
ADMIN_PREVIEW_SAVED_TOAST = "Превью збережено"
ADMIN_PREVIEW_DELETED_TOAST = "Превью видалено"

ADMIN_PROMPT_PRICE = (
    "Введіть нову ціну в гривнях (напр. <code>49.50</code>):"
)
ADMIN_PROMPT_DESC = "Введіть опис каналу (можна з форматуванням):"
ADMIN_PROMPT_DESC_REPLACE = (
    "Поточний опис:\n"
    "<blockquote>{current}</blockquote>\n\n"
    "Надішліть новий опис (попередній буде замінено). "
    "Форматування (жирний, курсив, посилання) зберігається."
)
ERR_EMPTY_DESC = "Опис не може бути порожнім."

ADMIN_CONFIRM_DELETE = (
    "Видалити канал <b>{title}</b> з каталогу?\n"
    "<i>Історія платежів зберігається.</i>"
)
ADMIN_CHANNEL_DELETED_TOAST = "Канал видалено"
ADMIN_TOGGLED_SHOWN_TOAST = "Показано"
ADMIN_TOGGLED_HIDDEN_TOAST = "Приховано"

USAGE_SETPRICE = (
    "<code>/setprice &lt;chat_id&gt; &lt;UAH&gt;</code>\n"
    "напр.: <code>/setprice -1001234567890 49.50</code>"
)
USAGE_SETDESC = "<code>/setdesc &lt;chat_id&gt; &lt;текст&gt;</code>"
USAGE_TOGGLE = "<code>/toggle &lt;chat_id&gt;</code>"
USAGE_REMOVE = (
    "<code>/remove &lt;chat_id&gt;</code>\n"
    "Видаляє з каталогу. Історія платежів зберігається."
)
USAGE_LINK = (
    "<code>/link &lt;chat_id&gt;</code>\n"
    "Генерує deep-link на сторінку оплати каналу."
)

ADMIN_LINK_RESULT = (
    "Посилання на покупку <b>{title}</b>:\n"
    "<code>{link}</code>"
)

ERR_BAD_AMOUNT = "Некоректна сума."
ERR_BAD_CHAT_ID = "Некоректний chat_id."
ERR_CHANNEL_NOT_FOUND = "Канал <code>{chat_id}</code> не знайдено."

PRICE_UPDATED = "Ціна для <code>{chat_id}</code>: <b>{price}</b>."
DESC_UPDATED = "Опис для <code>{chat_id}</code> оновлено."
TOGGLED_SHOWN = "Показано: <code>{chat_id}</code>"
TOGGLED_HIDDEN = "Приховано: <code>{chat_id}</code>"
REMOVED = "Канал <code>{chat_id}</code> видалено."

# ══════════════════════════════════════════════════════════════════════════════
#   Адмін: статистика
# ══════════════════════════════════════════════════════════════════════════════

STATS_EMPTY = "Немає каналів і продажів."
STATS_HEADER = "<b>Статистика продажів</b>\n"
STATS_LINE = (
    "{flag} <b>{title}</b>\n"
    "    {price} · {sold} шт · {revenue}"
)
STATS_TOTAL = "\n<b>Разом:</b> {total_sold} шт · {total_revenue}"

# ══════════════════════════════════════════════════════════════════════════════
#   Адмін: алерти від webhook
# ══════════════════════════════════════════════════════════════════════════════

ADMIN_INVITE_FAILED = (
    "<b>Помилка видачі invite-link</b>\n"
    "Платіж #{payment_id}, код <code>{code}</code>, chat <code>{chat_id}</code>.\n"
    "Помилка: <code>{error}</code>\n"
    "Юзер: <code>{user_id}</code>. Видайте доступ вручну."
)

ADMIN_UNDERPAID = (
    "<b>Недоплата #{payment_id}</b>\n"
    "Код: <code>{code}</code>\n"
    "Очікувалось: {expected:.2f}₴, отримано: {got:.2f}₴\n"
    "Statement: <code>{statement_id}</code>\n"
    "Юзер: <code>{user_id}</code> @{username}"
)

ADMIN_UNMATCHED = (
    "<b>Незіставлений платіж</b>\n"
    "Причина: {reason}\n"
    "Сума: {amount:.2f}₴\n"
    "Коментар: <code>{comment}</code>\n"
    "Statement: <code>{statement_id}</code>"
)

UNMATCHED_REASON_NO_COMMENT = "порожній коментар"
UNMATCHED_REASON_NOT_FOUND = "код не знайдено або прострочений"
UNMATCHED_REASON_EXPIRED = "код прострочений (юзер {user_id})"
