import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(
    os.getenv("DB_DIR", os.path.dirname(os.path.abspath(__file__))),
    "bot.db",
)

# Алфавіт без неоднозначних символів (0/O, 1/I/l).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6  # 32^6 ≈ 1 млрд — достатньо для унікальності

_db: aiosqlite.Connection | None = None


@asynccontextmanager
async def get_db():
    if _db is None:
        raise RuntimeError("Database is not initialized. Call init_db() first.")
    yield _db


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON")

    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id         INTEGER NOT NULL UNIQUE,
            chat_title      TEXT    NOT NULL DEFAULT '',
            price_kop       INTEGER NOT NULL DEFAULT 0,
            description     TEXT    NOT NULL DEFAULT '',
            is_active       INTEGER NOT NULL DEFAULT 1,
            preview_file_id TEXT    DEFAULT NULL,
            preview_type    TEXT    DEFAULT NULL,
            added_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_code    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            user_id         INTEGER NOT NULL,
            username        TEXT    DEFAULT '',
            full_name       TEXT    DEFAULT '',
            product_id      INTEGER NOT NULL REFERENCES products(id),
            chat_id         INTEGER NOT NULL,
            amount_kop      INTEGER NOT NULL,
            received_kop    INTEGER DEFAULT NULL,
            status          TEXT    NOT NULL DEFAULT 'pending',
            statement_id    TEXT    DEFAULT NULL UNIQUE,
            invite_link     TEXT    DEFAULT '',
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at      TIMESTAMP NOT NULL,
            paid_at         TIMESTAMP DEFAULT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_payments_user_id    ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_product_id ON payments(product_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status     ON payments(status);
        """
    )

    # Міграції для існуючих БД
    cursor = await _db.execute("PRAGMA table_info(products)")
    existing_cols = {row[1] for row in await cursor.fetchall()}
    for col_name, col_def in [
        ("preview_file_id", "TEXT DEFAULT NULL"),
        ("preview_type", "TEXT DEFAULT NULL"),
    ]:
        if col_name not in existing_cols:
            await _db.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_def}")
            logger.info("Added column %s to products", col_name)

    await _db.commit()


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


# ══════════════════════════════════════════════════════════════════════════════
#   Products
# ══════════════════════════════════════════════════════════════════════════════

async def add_or_update_product(chat_id: int, chat_title: str) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO products (chat_id, chat_title)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE
                SET chat_title = excluded.chat_title
            """,
            (chat_id, chat_title),
        )
        await db.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        row = await (await db.execute(
            "SELECT id FROM products WHERE chat_id = ?", (chat_id,)
        )).fetchone()
        return row["id"]


async def get_product_by_chat_id(chat_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM products WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_product(product_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_active_products() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM products
            WHERE is_active = 1 AND price_kop > 0
            ORDER BY added_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def list_all_products() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM products ORDER BY added_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def set_product_price(chat_id: int, price_kop: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE products SET price_kop = ? WHERE chat_id = ?",
            (price_kop, chat_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_product_description(chat_id: int, description: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE products SET description = ? WHERE chat_id = ?",
            (description, chat_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def toggle_product_active(chat_id: int) -> bool | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT is_active FROM products WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        new_state = 0 if row["is_active"] else 1
        await db.execute(
            "UPDATE products SET is_active = ? WHERE chat_id = ?",
            (new_state, chat_id),
        )
        await db.commit()
        return bool(new_state)


async def set_product_active(chat_id: int, is_active: bool) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE products SET is_active = ? WHERE chat_id = ?",
            (1 if is_active else 0, chat_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_product_by_chat_id(chat_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM products WHERE chat_id = ?", (chat_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_product_preview(chat_id: int, file_id: str, preview_type: str) -> bool:
    """preview_type: 'photo' | 'video' | 'animation'."""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE products SET preview_file_id = ?, preview_type = ? WHERE chat_id = ?",
            (file_id, preview_type, chat_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def clear_product_preview(chat_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE products SET preview_file_id = NULL, preview_type = NULL WHERE chat_id = ?",
            (chat_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


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
    expires_iso = expires_at.isoformat()

    async with get_db() as db:
        # У теорії можливі колізії — повторюємо до успіху (макс 5 спроб).
        for _ in range(5):
            code = _generate_code()
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO payments
                        (payment_code, user_id, username, full_name,
                         product_id, chat_id, amount_kop, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (code, user_id, username, full_name,
                     product_id, chat_id, amount_kop, expires_iso),
                )
                await db.commit()
                row = await (await db.execute(
                    "SELECT * FROM payments WHERE id = ?", (cursor.lastrowid,)
                )).fetchone()
                return dict(row)
            except aiosqlite.IntegrityError:
                continue  # колізія коду, генеруємо ще раз
        raise RuntimeError("Не вдалося згенерувати унікальний код оплати")


async def get_payment_by_code(payment_code: str) -> dict | None:
    """Пошук pending-платежа за кодом (без врахування регістру)."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM payments WHERE payment_code = ? COLLATE NOCASE",
            (payment_code,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_payment_by_statement_id(statement_id: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM payments WHERE statement_id = ?", (statement_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_payment_by_id(payment_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        )
        row = await cursor.fetchone()
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
    paid_at = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE payments
            SET status = 'paid',
                statement_id = ?,
                received_kop = ?,
                paid_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (statement_id, received_kop, paid_at, payment_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_payment_underpaid(
    payment_id: int,
    statement_id: str,
    received_kop: int,
) -> bool:
    paid_at = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE payments
            SET status = 'underpaid',
                statement_id = ?,
                received_kop = ?,
                paid_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (statement_id, received_kop, paid_at, payment_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_payment_invite_link(payment_id: int, invite_link: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE payments SET invite_link = ? WHERE id = ?",
            (invite_link, payment_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def expire_old_pending_payments() -> int:
    """Позначає всі прострочені pending-платежі як expired. Викликається періодично."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE payments
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at < ?
            """,
            (now_iso,),
        )
        await db.commit()
        return cursor.rowcount


async def user_has_paid_product(user_id: int, product_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT 1 FROM payments
            WHERE user_id = ? AND product_id = ? AND status = 'paid'
            LIMIT 1
            """,
            (user_id, product_id),
        )
        return await cursor.fetchone() is not None


async def list_user_purchases(user_id: int) -> list[dict]:
    """Успішні покупки юзера з назвою каналу та invite-посиланням."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT p.*, pr.chat_title
            FROM payments p
            LEFT JOIN products pr ON pr.id = p.product_id
            WHERE p.user_id = ? AND p.status = 'paid'
            ORDER BY p.paid_at DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def stats_per_product() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
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
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
