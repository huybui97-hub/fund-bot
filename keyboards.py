# =============================================================================
# keyboards.py — Toàn bộ bàn phím / inline keyboard
# =============================================================================

import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from config import ADMIN_ID, MEMBERS


# ---------------------------------------------------------------------------
# Menu chính (Reply Keyboard)
# ---------------------------------------------------------------------------

def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Trả về menu chính. Admin thấy thêm 4 nút quản trị."""
    base_buttons = [
        ["💰 Số Dư", "📜 Lịch Sử"],
        ["🔍 Tra Cứu", "📊 Thống Kê"],
        ["📅 Lịch Trình"],
    ]
    admin_buttons = [
        ["📥 Nhập Thu", "📤 Nhập Chi"],
        ["📋 Tổng Kết", "💾 Backup"],
    ]
    rows = admin_buttons + base_buttons if user_id == ADMIN_ID else base_buttons
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ---------------------------------------------------------------------------
# Chọn thành viên (11 nút tên — 1 cột)
# ---------------------------------------------------------------------------

def member_select_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    """
    Sinh bảng 11 nút tên thành viên.
    callback_data = f"{callback_prefix}:{tên}"
    Ví dụ prefix: "payer", "lookup"
    """
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"{callback_prefix}:{name}")]
        for name in MEMBERS
    ]
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Bảng Toggle Chia Tiền
# ---------------------------------------------------------------------------

def build_toggle_keyboard(
    states: dict[str, bool],
    confirm_callback: str = "chi_confirm",
    cancel_callback: str = "chi_cancel",
) -> InlineKeyboardMarkup:
    """
    Sinh bảng toggle chia tiền.

    states: { tên: True/False }  — True = tham gia (✅), False = không (❌)
    Mỗi nút có callback_data = JSON {"action":"toggle","name":"<tên>"}
    Nút cuối: XÁC NHẬN và HỦY.
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Hiển thị 2 cột để gọn hơn
    names = list(states.keys())
    for i in range(0, len(names), 2):
        row: list[InlineKeyboardButton] = []
        for name in names[i : i + 2]:
            icon = "✅" if states[name] else "❌"
            cb = json.dumps({"action": "toggle", "name": name}, ensure_ascii=False)
            row.append(InlineKeyboardButton(f"{icon} {name}", callback_data=cb))
        rows.append(row)

    # Nút hành động
    rows.append([
        InlineKeyboardButton("✅ XÁC NHẬN", callback_data=confirm_callback),
        InlineKeyboardButton("❌ HỦY", callback_data=cancel_callback),
    ])
    return InlineKeyboardMarkup(rows)


def default_toggle_states() -> dict[str, bool]:
    """Trả về trạng thái mặc định: tất cả đều ✅."""
    return {name: True for name in MEMBERS}


# ---------------------------------------------------------------------------
# Bảng Duyệt bill (Admin inbox)
# ---------------------------------------------------------------------------

def approve_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    """Nút Duyệt / Hủy trong inbox Admin."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"approve:{tx_id}"),
        InlineKeyboardButton("❌ Hủy", callback_data=f"reject:{tx_id}"),
    ]])
