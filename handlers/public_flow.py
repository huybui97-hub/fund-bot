# =============================================================================
# handlers/public_flow.py — Luồng Thành Viên: Số Dư, Lịch Sử, Tra Cứu, Thống Kê
# =============================================================================

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from keyboards import member_select_keyboard
from utils.money_parser import format_amount

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 💰 Số Dư
# ---------------------------------------------------------------------------

async def so_du(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    balance = db.calc_balance()

    lines = ["💰 *SỐ DƯ QUỸ*\n"]
    for name, val in balance.items():
        icon = "✅" if val > 0 else ("❌" if val < 0 else "⚖️")
        sign = "+" if val > 0 else ""
        lines.append(f"{icon} {name}: *{sign}{format_amount(val)}*")

    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# 📜 Lịch Sử — phân trang
# ---------------------------------------------------------------------------

PAGE_SIZE = 10  # Số giao dịch mỗi trang


def _build_history_page(rows: list, page: int) -> tuple[str, object]:
    """
    Trả về (text, InlineKeyboardMarkup) cho trang `page` (0-indexed).
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    total = len(rows)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    chunk = rows[start: start + PAGE_SIZE]

    lines = [f"📜 *LỊCH SỬ GIAO DỊCH* — Trang {page + 1}/{total_pages}\n"]
    for row in chunk:
        shared   = json.loads(row["shared_by"])
        is_thu   = row["type"] == "thu"
        tx_label = "🟢 THU" if is_thu else "🔴 CHI"
        date_str = row["created_at"][:10]
        note     = row["note"] or "—"
        people   = f" · {len(shared)}ng" if not is_thu else ""
        lines.append(
            f"{tx_label} · {row['payer_name']} | {date_str} | *{format_amount(row['amount'])}*"
            + (f"\n   └ {note}{people}" if (note != "—" or people) else "")
        )

    # Nút điều hướng
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Trước", callback_data=f"hist:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Tiếp ▶️", callback_data=f"hist:{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav]) if nav else None
    return "\n".join(lines), keyboard


async def lich_su(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.get_all_transactions()
    if not rows:
        await update.effective_message.reply_text("ℹ️ Chưa có giao dịch nào.")
        return

    # Cả Group lẫn Inbox đều dùng phân trang, trang đầu là 10 giao dịch gần nhất
    text, keyboard = _build_history_page(rows, page=0)
    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=keyboard
    )


async def lich_su_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback khi bấm ◀️ / ▶️ để lật trang lịch sử."""
    query = update.callback_query
    await query.answer()

    page = int(query.data.split(":")[1])
    rows = db.get_all_transactions()
    text, keyboard = _build_history_page(rows, page)

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=keyboard
    )


# ---------------------------------------------------------------------------
# 🔍 Tra Cứu
# ---------------------------------------------------------------------------

async def tra_cuu_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Hiện bảng 11 nút tên để chọn."""
    await update.effective_message.reply_text(
        "🔍 *Tra Cứu Cá Nhân*\n\nChọn thành viên cần xem:",
        parse_mode="Markdown",
        reply_markup=member_select_keyboard("lookup"),
    )


async def tra_cuu_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback khi chọn tên → hiển thị sao kê."""
    query = update.callback_query
    await query.answer()

    _, member_name = query.data.split(":", 1)
    detail = db.calc_member_detail(member_name)

    lines = [f"🔍 *SAO KÊ: {member_name}*\n"]
    lines.append(f"💵 Đã nộp quỹ: *{format_amount(detail['total_paid_in'])}*")
    lines.append(f"💸 Đã tiêu (phần chia): *{format_amount(detail['total_spent'])}*")

    bal = detail["balance"]
    sign = "+" if bal >= 0 else ""
    icon = "✅ Dư" if bal > 0 else ("❌ Thiếu" if bal < 0 else "⚖️ Hòa")
    lines.append(f"📊 Số dư: *{sign}{format_amount(bal)}* ({icon})\n")

    if detail["thu_records"]:
        lines.append("📥 *Các lần nộp quỹ:*")
        for r in detail["thu_records"]:
            lines.append(f"  • {r['created_at'][:10]}: +{format_amount(r['amount'])}")

    if detail["paid_bills"]:
        lines.append("\n💳 *Các bill đã ứng tiền trả:*")
        for r in detail["paid_bills"]:
            lines.append(
                f"  • {r['created_at'][:10]}: +{format_amount(r['amount'])}"
                f" ({r['note']} · {r['participant_count']} người)"
            )

    if detail["chi_records"]:
        lines.append("\n📤 *Các bill đã tham gia:*")
        for r in detail["chi_records"][:15]:
            lines.append(
                f"  • {r['created_at'][:10]}: -{format_amount(r['per_person'])}"
                f" ({r['note']} · {r['participant_count']} người)"
            )
        if len(detail["chi_records"]) > 15:
            lines.append(f"  _... và {len(detail['chi_records']) - 15} bill khác_")

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# 📊 Thống Kê
# ---------------------------------------------------------------------------

async def thong_ke(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    balance = db.calc_balance()

    du     = sorted([(n, v) for n, v in balance.items() if v > 0], key=lambda x: -x[1])
    thieu  = sorted([(n, v) for n, v in balance.items() if v < 0], key=lambda x: x[1])
    hoa    = [n for n, v in balance.items() if v == 0]

    total_thu = sum(r["amount"] for r in db.get_transactions_by_type("thu"))
    total_chi = sum(r["amount"] for r in db.get_transactions_by_type("chi"))

    lines = ["📊 *THỐNG KÊ QUỸ*\n"]
    lines.append(f"📥 Tổng thu: *{format_amount(total_thu)}*")
    lines.append(f"📤 Tổng chi: *{format_amount(total_chi)}*")
    lines.append(f"💰 Tồn quỹ: *{format_amount(total_thu - total_chi)}*\n")

    if du:
        lines.append("✅ *Dư tiền:*")
        for name, val in du:
            lines.append(f"  • {name}: +{format_amount(val)}")

    if thieu:
        lines.append("\n❌ *Thiếu tiền:*")
        for name, val in thieu:
            lines.append(f"  • {name}: {format_amount(val)}")

    if hoa:
        lines.append("\n⚖️ *Hòa vốn:*")
        for name in hoa:
            lines.append(f"  • {name}")

    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")
