import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Алфавіт без неоднозначних символів (0/O, 1/I/l).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6  # 32^6 ≈ 1 млрд — достатньо для унікальності

_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def get_db():
    if _pool is None:
        raise RuntimeError("Database is not initialized. Call init_db() first.")
    async with _pool.acquire() as conn:
        yield conn


def _rowcount(status: str) -> int:
    """Парсить статус asyncpg ('UPDATE 1', 'DELETE 3', ...) у кількість рядків."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


async def init_db() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id              BIGSERIAL PRIMARY KEY,
                chat_id         BIGINT      NOT NULL UNIQUE,
                chat_title      TEXT        NOT NULL DEFAULT '',
                price_kop       BIGINT      NOT NULL DEFAULT 0,
                description     TEXT        NOT NULL DEFAULT '',
                is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
                preview_file_id TEXT        DEFAULT NULL,
                preview_type    TEXT        DEFAULT NULL,
                added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS payments (
                id                     BIGSERIAL   PRIMARY KEY,
                payment_code           TEXT        NOT NULL UNIQUE,
                user_id                BIGINT      NOT NULL,
                username               TEXT        DEFAULT '',
                full_name              TEXT        DEFAULT '',
                product_id             BIGINT      NOT NULL REFERENCES products(id),
                chat_id                BIGINT      NOT NULL,
                amount_kop             BIGINT      NOT NULL,
                received_kop           BIGINT      DEFAULT NULL,
                status                 TEXT        NOT NULL DEFAULT 'pending',
                statement_id           TEXT        DEFAULT NULL UNIQUE,
                invite_link            TEXT        NOT NULL DEFAULT '',
                instruction_message_id BIGINT      DEFAULT NULL,
                created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at             TIMESTAMPTZ NOT NULL,
                paid_at                TIMESTAMPTZ DEFAULT NULL
            );

            ALTER TABLE payments ADD COLUMN IF NOT EXISTS instruction_message_id BIGINT;

            CREATE INDEX IF NOT EXISTS idx_payments_user_id    ON payments(user_id);
            CREATE INDEX IF NOT EXISTS idx_payments_product_id ON payments(product_id);
            CREATE INDEX IF NOT EXISTS idx_payments_status     ON payments(status);
            """
        )


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ══════════════════════════════════════════════════════════════════════════════
#   Products
# ══════════════════════════════════════════════════════════════════════════════

async def add_or_update_product(chat_id: int, chat_title: str) -> int:
    async with get_db() as db:
        row = await db.fetchrow(
            """
            INSERT INTO products (chat_id, chat_title)
            VALUES ($1, $2)
            ON CONFLICT (chat_id) DO UPDATE
                SET chat_title = EXCLUDED.chat_title
            RETURNING id
            """,
            chat_id, chat_title,
        )
        return row["id"]


async def get_product_by_chat_id(chat_id: int) -> dict | None:
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT * FROM products WHERE chat_id = $1", chat_id
        )
        return dict(row) if row else None


async def get_product(product_id: int) -> dict | None:
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT * FROM products WHERE id = $1", product_id
        )
        return dict(row) if row else None


async def list_active_products() -> list[dict]:
    async with get_db() as db:
        rows = await db.fetch(
            """
            SELECT * FROM products
            WHERE is_active = TRUE AND price_kop > 0
            ORDER BY added_at DESC
            """
        )
        return [dict(row) for row in rows]


async def list_all_products() -> list[dict]:
    async with get_db() as db:
        rows = await db.fetch("SELECT * FROM products ORDER BY added_at DESC")
        return [dict(row) for row in rows]


async def set_product_price(chat_id: int, price_kop: int) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "UPDATE products SET price_kop = $1 WHERE chat_id = $2",
            price_kop, chat_id,
        )
        return _rowcount(status) > 0


async def set_product_description(chat_id: int, description: str) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "UPDATE products SET description = $1 WHERE chat_id = $2",
            description, chat_id,
        )
        return _rowcount(status) > 0


async def toggle_product_active(chat_id: int) -> bool | None:
    async with get_db() as db:
        row = await db.fetchrow(
            """
            UPDATE products SET is_active = NOT is_active
            WHERE chat_id = $1
            RETURNING is_active
            """,
            chat_id,
        )
        return row["is_active"] if row else None


async def set_product_active(chat_id: int, is_active: bool) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "UPDATE products SET is_active = $1 WHERE chat_id = $2",
            is_active, chat_id,
        )
        return _rowcount(status) > 0


async def delete_product_by_chat_id(chat_id: int) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "DELETE FROM products WHERE chat_id = $1", chat_id
        )
        return _rowcount(status) > 0


async def set_product_preview(chat_id: int, file_id: str, preview_type: str) -> bool:
    """preview_type: 'photo' | 'video' | 'animation'."""
    async with get_db() as db:
        status = await db.execute(
            "UPDATE products SET preview_file_id = $1, preview_type = $2 WHERE chat_id = $3",
            file_id, preview_type, chat_id,
        )
        return _rowcount(status) > 0


async def clear_product_preview(chat_id: int) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "UPDATE products SET preview_file_id = NULL, preview_type = NULL WHERE chat_id = $1",
            chat_id,
        )
        return _rowcount(status) > 0


# ══════════════════════════════════════════════════════════════════════════════
#   Payments
# ══════════════════════════════════════════════════════════════════════════════

def _generate_code() -> str:
    return "UAS-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


async def create_payment(
    user_id: int,
    username: str,
    full_name: str,
    product_id: int,
    chat_id: int,
    amount_kop: int,
    ttl_hours: int,
) -> dict:
    """Створює pending-платіж з унікальним кодом. Повертає рядок payment."""
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    async with get_db() as db:
        # У теорії можливі колізії — повторюємо до успіху (макс 5 спроб).
        for _ in range(5):
            code = _generate_code()
            try:
                row = await db.fetchrow(
                    """
                    INSERT INTO payments
                        (payment_code, user_id, username, full_name,
                         product_id, chat_id, amount_kop, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                    """,
                    code, user_id, username, full_name,
                    product_id, chat_id, amount_kop, expires_at,
                )
                return dict(row)
            except asyncpg.UniqueViolationError:
                continue  # колізія коду, генеруємо ще раз
        raise RuntimeError("Не вдалося згенерувати унікальний код оплати")


async def get_payment_by_code(payment_code: str) -> dict | None:
    """Пошук pending-платежа за кодом (без врахування регістру)."""
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT * FROM payments WHERE UPPER(payment_code) = UPPER($1)",
            payment_code,
        )
        return dict(row) if row else None


async def get_payment_by_statement_id(statement_id: str) -> dict | None:
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT * FROM payments WHERE statement_id = $1", statement_id
        )
        return dict(row) if row else None


async def get_payment_by_id(payment_id: int) -> dict | None:
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT * FROM payments WHERE id = $1", payment_id
        )
        return dict(row) if row else None


async def mark_payment_paid(
    payment_id: int,
    statement_id: str,
    received_kop: int,
) -> bool:
    """Атомарне «закриття» pending-платежа.

    Повертає True, якщо саме цей виклик переключив статус. Захист від
    подвійного webhook'у: рядок змінюється лише якщо все ще pending.
    """
    paid_at = datetime.now(timezone.utc)
    async with get_db() as db:
        status = await db.execute(
            """
            UPDATE payments
            SET status = 'paid',
                statement_id = $1,
                received_kop = $2,
                paid_at = $3
            WHERE id = $4 AND status = 'pending'
            """,
            statement_id, received_kop, paid_at, payment_id,
        )
        return _rowcount(status) > 0


async def mark_payment_underpaid(
    payment_id: int,
    statement_id: str,
    received_kop: int,
) -> bool:
    paid_at = datetime.now(timezone.utc)
    async with get_db() as db:
        status = await db.execute(
            """
            UPDATE payments
            SET status = 'underpaid',
                statement_id = $1,
                received_kop = $2,
                paid_at = $3
            WHERE id = $4 AND status = 'pending'
            """,
            statement_id, received_kop, paid_at, payment_id,
        )
        return _rowcount(status) > 0


async def set_payment_invite_link(payment_id: int, invite_link: str) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "UPDATE payments SET invite_link = $1 WHERE id = $2",
            invite_link, payment_id,
        )
        return _rowcount(status) > 0


async def set_payment_instruction_message_id(payment_id: int, message_id: int) -> bool:
    async with get_db() as db:
        status = await db.execute(
            "UPDATE payments SET instruction_message_id = $1 WHERE id = $2",
            message_id, payment_id,
        )
        return _rowcount(status) > 0


async def expire_old_pending_payments() -> int:
    """Позначає всі прострочені pending-платежі як expired. Викликається періодично."""
    now = datetime.now(timezone.utc)
    async with get_db() as db:
        status = await db.execute(
            """
            UPDATE payments
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at < $1
            """,
            now,
        )
        return _rowcount(status)


async def user_has_paid_product(user_id: int, product_id: int) -> bool:
    async with get_db() as db:
        row = await db.fetchrow(
            """
            SELECT 1 FROM payments
            WHERE user_id = $1 AND product_id = $2 AND status = 'paid'
            LIMIT 1
            """,
            user_id, product_id,
        )
        return row is not None


async def list_user_purchases(user_id: int) -> list[dict]:
    """Успішні покупки юзера з назвою каналу та invite-посиланням."""
    async with get_db() as db:
        rows = await db.fetch(
            """
            SELECT p.*, pr.chat_title
            FROM payments p
            LEFT JOIN products pr ON pr.id = p.product_id
            WHERE p.user_id = $1 AND p.status = 'paid'
            ORDER BY p.paid_at DESC
            """,
            user_id,
        )
        return [dict(row) for row in rows]


async def stats_per_product() -> list[dict]:
    async with get_db() as db:
        rows = await db.fetch(
            """
            SELECT
                pr.id            AS product_id,
                pr.chat_id       AS chat_id,
                pr.chat_title    AS chat_title,
                pr.price_kop     AS price_kop,
                pr.is_active     AS is_active,
                COUNT(p.id)      AS sold_count,
                COALESCE(SUM(p.received_kop), 0) AS revenue_kop
            FROM products pr
            LEFT JOIN payments p
                ON p.product_id = pr.id AND p.status = 'paid'
            GROUP BY pr.id
            ORDER BY revenue_kop DESC, pr.added_at DESC
            """
        )
        return [dict(row) for row in rows]
