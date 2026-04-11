# =============================================================================
# database.py — Toàn bộ logic SQLite
# =============================================================================

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

from config import DB_PATH, MEMBERS


# ---------------------------------------------------------------------------
# Context manager cho connection
# ---------------------------------------------------------------------------

@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Truy cập cột bằng tên
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Khởi tạo schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Tạo bảng nếu chưa tồn tại."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT    NOT NULL CHECK(type IN ('thu', 'chi')),
                amount      INTEGER NOT NULL,
                note        TEXT    NOT NULL DEFAULT '',
                payer_name  TEXT    NOT NULL,
                shared_by   TEXT    NOT NULL DEFAULT '[]',
                created_at  TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            )
        """)


def get_setting(key: str) -> str | None:
    """Đọc một giá trị cấu hình từ DB."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    """Ghi hoặc cập nhật một giá trị cấu hình vào DB."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Ghi dữ liệu
# ---------------------------------------------------------------------------

def add_thu(amount: int, payer_name: str, note: str = "") -> int:
    """
    Ghi một giao dịch THU (thành viên nộp quỹ).
    shared_by = [payer_name] — chỉ người nộp được ghi nhận.
    Trả về id của bản ghi vừa tạo.
    """
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions (type, amount, note, payer_name, shared_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("thu", amount, note, payer_name, json.dumps([payer_name]), now),
        )
        return cur.lastrowid


def add_chi(
    amount: int,
    note: str,
    payer_name: str,
    shared_by: list[str],
) -> int:
    """
    Ghi một giao dịch CHI.
    payer_name  — người đã trả tiền thực tế (ứng tiền).
    shared_by   — danh sách những người tham gia chia tiền bill này.
    Trả về id của bản ghi vừa tạo.
    """
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions (type, amount, note, payer_name, shared_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("chi", amount, note, payer_name, json.dumps(shared_by), now),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Đọc dữ liệu
# ---------------------------------------------------------------------------

def get_all_transactions() -> list[sqlite3.Row]:
    """Trả về toàn bộ giao dịch, mới nhất trước."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions ORDER BY created_at DESC"
        ).fetchall()


def get_transactions_by_type(tx_type: str) -> list[sqlite3.Row]:
    """Lọc giao dịch theo loại ('thu' hoặc 'chi')."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE type = ? ORDER BY created_at DESC",
            (tx_type,),
        ).fetchall()


def get_transaction_by_id(tx_id: int) -> sqlite3.Row | None:
    """Lấy một giao dịch theo id."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()


def delete_transaction(tx_id: int) -> None:
    """Xóa giao dịch theo id (dùng khi Admin hủy)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))


# ---------------------------------------------------------------------------
# Tính toán số dư
# ---------------------------------------------------------------------------

def calc_balance() -> dict[str, float]:
    """
    Tính số dư từng thành viên:
        S = Tổng tiền đã nộp quỹ
          + Tổng tiền đã ứng trả bill (payer_name trong CHI)
          − Σ(amount_bill / số_người_chia)

    Người ứng tiền trả bill được coi như đã nộp vào quỹ phần đó.
    Trả về dict { tên: số_dư }.
    """
    balance: dict[str, float] = {name: 0.0 for name in MEMBERS}

    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM transactions").fetchall()

    for row in rows:
        shared_by: list[str] = json.loads(row["shared_by"])

        if row["type"] == "thu":
            # Người nộp quỹ trực tiếp
            payer = row["payer_name"]
            if payer in balance:
                balance[payer] += row["amount"]

        elif row["type"] == "chi":
            # Người ứng tiền trả bill → được cộng toàn bộ số tiền
            payer = row["payer_name"]
            if payer in balance:
                balance[payer] += row["amount"]

            # Mỗi người tham gia bị trừ phần chia đều (kể cả payer)
            if shared_by:
                per_person = row["amount"] / len(shared_by)
                for name in shared_by:
                    if name in balance:
                        balance[name] -= per_person

    return balance


def calc_member_detail(member_name: str) -> dict:
    """
    Trả về sao kê chi tiết của một thành viên:
    {
        "total_paid_in": float,        # Tổng đã nộp quỹ + ứng tiền trả bill
        "total_spent":   float,        # Tổng đã tiêu (phần chia)
        "balance":       float,        # Số dư = paid_in − spent
        "thu_records":   list[dict],   # Các lần nộp quỹ trực tiếp
        "chi_records":   list[dict],   # Các bill có tham gia
        "paid_bills":    list[dict],   # Các bill đã ứng tiền trả
    }
    """
    total_paid_in: float = 0.0
    total_spent: float = 0.0
    thu_records: list[dict] = []
    chi_records: list[dict] = []
    paid_bills:  list[dict] = []

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY created_at ASC"
        ).fetchall()

    for row in rows:
        shared_by: list[str] = json.loads(row["shared_by"])

        if row["type"] == "thu" and row["payer_name"] == member_name:
            total_paid_in += row["amount"]
            thu_records.append({
                "id": row["id"],
                "amount": row["amount"],
                "note": row["note"],
                "created_at": row["created_at"],
            })

        elif row["type"] == "chi":
            per_person = row["amount"] / len(shared_by) if shared_by else 0

            # Nếu là người ứng tiền → được cộng toàn bộ bill
            if row["payer_name"] == member_name:
                total_paid_in += row["amount"]
                paid_bills.append({
                    "id": row["id"],
                    "amount": row["amount"],
                    "note": row["note"],
                    "participant_count": len(shared_by),
                    "created_at": row["created_at"],
                })

            # Nếu có tham gia → bị trừ phần chia
            if member_name in shared_by:
                total_spent += per_person
                chi_records.append({
                    "id": row["id"],
                    "amount": row["amount"],
                    "per_person": per_person,
                    "note": row["note"],
                    "payer_name": row["payer_name"],
                    "participant_count": len(shared_by),
                    "created_at": row["created_at"],
                })

    return {
        "total_paid_in": total_paid_in,
        "total_spent": total_spent,
        "balance": total_paid_in - total_spent,
        "thu_records": thu_records,
        "chi_records": chi_records,
        "paid_bills": paid_bills,
    }
