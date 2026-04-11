# =============================================================================
# handlers/admin_flow.py — Luồng Admin: Nhập Thu, Nhập Chi, Tổng Kết, Backup
# =============================================================================

import asyncio
import json
import logging

from telegram import Update, InputFile
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import database as db
from config import ADMIN_ID, GROUP_CHAT_ID
from keyboards import (
    approve_keyboard,
    build_toggle_keyboard,
    default_toggle_states,
    main_menu,
    member_select_keyboard,
)
from utils.csv_exporter import export_csv
from utils.money_parser import format_amount, parse_amount

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers dùng chung
# ---------------------------------------------------------------------------

async def _delete_after(message, delay: int) -> None:
    """Xóa một tin nhắn sau `delay` giây (silent nếu không có quyền)."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def _reject_group_command(update: Update) -> bool:
    """
    Kiểm tra lệnh có bị gõ trong Group không.
    Nếu đúng: xóa lệnh + gửi cảnh báo tự xóa sau 5 giây → trả về True.
    Nếu không: trả về False (tiếp tục xử lý bình thường).
    """
    chat_type = update.effective_chat.type
    if chat_type in ("group", "supergroup"):
        # Cố xóa tin nhắn lệnh
        try:
            await update.message.delete()
        except Exception:
            pass
        warn = await update.effective_chat.send_message(
            "⚠️ Từ chối truy cập: Vui lòng vào *Inbox riêng* của Admin để thực hiện lệnh này.",
            parse_mode="Markdown",
        )
        asyncio.create_task(_delete_after(warn, 5))
        return True
    return False


# ---------------------------------------------------------------------------
# ConversationHandler states
# ---------------------------------------------------------------------------
(
    # Luồng CHI
    CHI_AMOUNT,
    CHI_NOTE,
    CHI_PAYER,
    CHI_TOGGLE,
    # Luồng THU
    THU_AMOUNT,
    THU_TOGGLE,
) = range(6)


# ===========================================================================
# LUỒNG NHẬP CHI
# ===========================================================================

async def chi_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1: Hỏi số tiền."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    if await _reject_group_command(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "💸 *Nhập Chi Tiêu Mới*\n\nBước 1/4 — Nhập số tiền:\n"
        "_Ví dụ: 50k, 1.2tr, 200000_",
        parse_mode="Markdown",
    )
    return CHI_AMOUNT


async def chi_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1 nhận → Bước 2: Hỏi nội dung."""
    amount = parse_amount(update.message.text)
    if amount is None or amount <= 0:
        await update.message.reply_text("❌ Số tiền không hợp lệ. Thử lại:")
        return CHI_AMOUNT

    ctx.user_data["chi_amount"] = amount
    await update.message.reply_text(
        f"✅ Số tiền: *{format_amount(amount)}*\n\n"
        "Bước 2/4 — Nhập nội dung chi tiêu:",
        parse_mode="Markdown",
    )
    return CHI_NOTE


async def chi_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 2 nhận → Bước 3: Chọn người trả."""
    note = update.message.text.strip()
    if not note:
        await update.message.reply_text("❌ Nội dung không được để trống. Thử lại:")
        return CHI_NOTE

    ctx.user_data["chi_note"] = note
    await update.message.reply_text(
        "Bước 3/4 — Ai đã *trả tiền* (ứng tiền) cho bill này?",
        parse_mode="Markdown",
        reply_markup=member_select_keyboard("payer"),
    )
    return CHI_PAYER


async def chi_payer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 3 nhận → Bước 4: Bảng Toggle chia tiền."""
    query = update.callback_query
    await query.answer()

    _, payer_name = query.data.split(":", 1)
    ctx.user_data["chi_payer"] = payer_name

    states = default_toggle_states()
    ctx.user_data["chi_toggle"] = states

    await query.edit_message_text(
        f"✅ Người trả: *{payer_name}*\n\n"
        "Bước 4/4 — Chọn những người *tham gia chia tiền* (mặc định: tất cả):",
        parse_mode="Markdown",
        reply_markup=build_toggle_keyboard(states),
    )
    return CHI_TOGGLE


async def chi_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý bấm toggle từng người."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    name = data["name"]
    states: dict[str, bool] = ctx.user_data["chi_toggle"]
    states[name] = not states[name]
    ctx.user_data["chi_toggle"] = states

    # Đảm bảo ít nhất 1 người được chọn
    if not any(states.values()):
        states[name] = True
        await query.answer("Phải có ít nhất 1 người tham gia!", show_alert=True)

    await query.edit_message_reply_markup(
        reply_markup=build_toggle_keyboard(states)
    )
    return CHI_TOGGLE


async def chi_confirm_draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin bấm XÁC NHẬN → gửi bản nháp vào inbox Admin để duyệt."""
    query = update.callback_query
    await query.answer()

    states: dict[str, bool] = ctx.user_data["chi_toggle"]
    participants = [n for n, v in states.items() if v]
    amount: int = ctx.user_data["chi_amount"]
    note: str = ctx.user_data["chi_note"]
    payer: str = ctx.user_data["chi_payer"]
    per_person = amount / len(participants)

    # Lưu tạm vào user_data (chưa ghi DB)
    ctx.user_data["chi_draft"] = {
        "amount": amount,
        "note": note,
        "payer_name": payer,
        "shared_by": participants,
    }

    participant_list = "\n".join(f"  • {n}" for n in participants)
    draft_text = (
        "📋 *Bản Nháp Chi Tiêu*\n\n"
        f"💰 Số tiền: *{format_amount(amount)}*\n"
        f"📝 Nội dung: {note}\n"
        f"👤 Người trả: *{payer}*\n"
        f"👥 Chia cho *{len(participants)}* người ({format_amount(per_person)}/người):\n"
        f"{participant_list}\n\n"
        "Xác nhận ghi vào quỹ?"
    )

    await query.edit_message_text(draft_text, parse_mode="Markdown")

    # Gửi tin duyệt (dùng id=-1 placeholder, ghi DB sau khi duyệt)
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=draft_text,
        parse_mode="Markdown",
        reply_markup=approve_keyboard(-1),  # -1 = đang chờ ghi DB
    )
    # [Fix #1] Khôi phục menu chính sau khi kết thúc conversation
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text="⏳ Bấm *✅ Duyệt* phía trên để xác nhận ghi sổ.",
        parse_mode="Markdown",
        reply_markup=main_menu(ADMIN_ID),
    )
    return ConversationHandler.END


async def chi_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin bấm HỦY trong bảng toggle."""
    query = update.callback_query
    await query.answer("Đã hủy.")
    await query.edit_message_text("❌ Đã hủy nhập chi.")
    ctx.user_data.clear()
    # [Fix #1] Khôi phục menu chính
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text="Chọn chức năng tiếp theo:",
        reply_markup=main_menu(ADMIN_ID),
    )
    return ConversationHandler.END


# ===========================================================================
# LUỒNG NHẬP THU
# ===========================================================================

async def thu_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1: Hỏi số tiền nộp quỹ."""
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    if await _reject_group_command(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "💰 *Nhập Thu Quỹ Mới*\n\nBước 1/2 — Nhập số tiền nộp:\n"
        "_Ví dụ: 500k, 1tr, 300000_",
        parse_mode="Markdown",
    )
    return THU_AMOUNT


async def thu_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1 nhận → Bước 2: Bảng toggle chọn người nộp (multi)."""
    amount = parse_amount(update.message.text)
    if amount is None or amount <= 0:
        await update.message.reply_text("❌ Số tiền không hợp lệ. Thử lại:")
        return THU_AMOUNT

    ctx.user_data["thu_amount"] = amount
    # Mặc định: chưa ai được chọn (❌ hết)
    states = {name: False for name in __import__("config").MEMBERS}
    ctx.user_data["thu_toggle"] = states

    await update.message.reply_text(
        f"✅ Số tiền: *{format_amount(amount)}*\n\n"
        "Bước 2/2 — Chọn *những người đã nộp* (bấm để bật/tắt):",
        parse_mode="Markdown",
        reply_markup=build_toggle_keyboard(
            states,
            confirm_callback="thu_confirm",
            cancel_callback="thu_cancel",
        ),
    )
    return THU_TOGGLE


async def thu_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý bấm toggle từng người trong luồng THU."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    name = data["name"]
    states: dict[str, bool] = ctx.user_data["thu_toggle"]
    states[name] = not states[name]
    ctx.user_data["thu_toggle"] = states

    await query.edit_message_reply_markup(
        reply_markup=build_toggle_keyboard(
            states,
            confirm_callback="thu_confirm",
            cancel_callback="thu_cancel",
        )
    )
    return THU_TOGGLE


async def thu_confirm_draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin bấm XÁC NHẬN → gửi bản nháp thu để duyệt."""
    query = update.callback_query
    await query.answer()

    states: dict[str, bool] = ctx.user_data["thu_toggle"]
    payers = [n for n, v in states.items() if v]

    if not payers:
        await query.answer("Chưa chọn ai! Hãy chọn ít nhất 1 người.", show_alert=True)
        return THU_TOGGLE

    amount: int = ctx.user_data["thu_amount"]
    per_person = amount / len(payers)

    ctx.user_data["thu_draft"] = {
        "amount": amount,
        "payers": payers,
    }

    payer_list = "\n".join(f"  • {n}: +{format_amount(per_person)}" for n in payers)
    draft_text = (
        "📋 *Bản Nháp Thu Quỹ*\n\n"
        f"💰 Tổng nộp: *{format_amount(amount)}*\n"
        f"👥 Chia đều cho *{len(payers)}* người ({format_amount(per_person)}/người):\n"
        f"{payer_list}\n\n"
        "Xác nhận ghi vào quỹ?"
    )

    await query.edit_message_text(draft_text, parse_mode="Markdown")

    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=draft_text,
        parse_mode="Markdown",
        reply_markup=approve_keyboard(-2),
    )
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text="⏳ Bấm *✅ Duyệt* phía trên để xác nhận ghi sổ.",
        parse_mode="Markdown",
        reply_markup=main_menu(ADMIN_ID),
    )
    return ConversationHandler.END


async def thu_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin bấm HỦY trong bảng toggle THU."""
    query = update.callback_query
    await query.answer("Đã hủy.")
    await query.edit_message_text("❌ Đã hủy nhập thu.")
    ctx.user_data.clear()
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text="Chọn chức năng tiếp theo:",
        reply_markup=main_menu(ADMIN_ID),
    )
    return ConversationHandler.END


# ===========================================================================
# XỬ LÝ DUYỆT / HỦY (approve_keyboard callback)
# ===========================================================================

async def handle_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin bấm ✅ Duyệt."""
    query = update.callback_query
    await query.answer()

    _, tx_id_str = query.data.split(":", 1)
    tx_id = int(tx_id_str)

    if tx_id == -1:
        # Duyệt CHI draft
        draft = ctx.user_data.get("chi_draft")
        if not draft:
            await query.edit_message_text("❌ Không tìm thấy bản nháp. Vui lòng nhập lại.")
            return

        new_id = db.add_chi(
            amount=draft["amount"],
            note=draft["note"],
            payer_name=draft["payer_name"],
            shared_by=draft["shared_by"],
        )
        await broadcast_to_group(ctx, tx_type="chi", draft=draft, tx_id=new_id)

    elif tx_id == -2:
        # Duyệt THU draft — có thể nhiều người nộp chung
        draft = ctx.user_data.get("thu_draft")
        if not draft:
            await query.edit_message_text("❌ Không tìm thấy bản nháp. Vui lòng nhập lại.")
            return

        payers: list[str] = draft["payers"]
        per_person = draft["amount"] / len(payers)
        for payer_name in payers:
            new_id = db.add_thu(
                amount=round(per_person),
                payer_name=payer_name,
            )
        await broadcast_to_group(ctx, tx_type="thu", draft=draft, tx_id=new_id)

    else:
        # Duyệt giao dịch đã có trong DB (reserved)
        pass

    # Auto-backup sau khi duyệt
    await _auto_backup(ctx, query)

    ctx.user_data.clear()
    await query.edit_message_text("✅ Đã ghi vào quỹ!")

    # [Fix #2] Gửi số dư hiện tại sau khi duyệt
    balance_text = _format_balance_summary()
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=balance_text,
        parse_mode="Markdown",
        reply_markup=main_menu(ADMIN_ID),  # [Fix #1] Luôn hiển thị menu
    )


async def handle_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin bấm ❌ Hủy trong inbox."""
    query = update.callback_query
    await query.answer("Đã hủy giao dịch.")
    ctx.user_data.clear()
    await query.edit_message_text("❌ Giao dịch đã bị hủy.")
    # [Fix #1] Khôi phục menu chính
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text="Chọn chức năng tiếp theo:",
        reply_markup=main_menu(ADMIN_ID),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def cmd_setgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setgroup — Admin gõ lệnh này ngay trong Group.
    Bot tự bắt chat_id của Group và lưu vào DB làm kênh broadcast.
    """
    if update.effective_user.id != ADMIN_ID:
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "❌ Lệnh này phải được gõ *trong Group*, không phải chat riêng.",
            parse_mode="Markdown",
        )
        return

    db.set_setting("group_chat_id", str(chat.id))
    logger.info("Group broadcast đã được set: %s (%d)", chat.title, chat.id)

    await update.message.reply_text(
        "✅ Đã ghi nhận Group này là kênh thông báo nội bộ.\n"
        "Mọi biên lai sẽ được gửi về đây!",
        parse_mode="Markdown",
    )


def _get_group_chat_id() -> int:
    """Đọc GROUP_CHAT_ID từ DB (ưu tiên) hoặc fallback về config."""
    saved = db.get_setting("group_chat_id")
    if saved:
        return int(saved)
    return GROUP_CHAT_ID  # fallback từ .env


async def broadcast_to_group(
    ctx: ContextTypes.DEFAULT_TYPE,
    tx_type: str,
    draft: dict,
    tx_id: int,
) -> None:
    """Gửi thông báo giao dịch ra Group Chat chung sau khi Admin duyệt."""
    group_id = _get_group_chat_id()
    if not group_id:
        logger.warning("GROUP_CHAT_ID chưa cấu hình — bỏ qua broadcast.")
        return

    total_thu = sum(r["amount"] for r in db.get_transactions_by_type("thu"))
    total_chi = sum(r["amount"] for r in db.get_transactions_by_type("chi"))
    remaining = total_thu - total_chi

    if tx_type == "thu":
        payers: list[str] = draft.get("payers", [draft.get("payer_name", "?")])
        per_person = draft["amount"] / len(payers)
        payer_lines = "\n".join(
            f"  • {p}: +{format_amount(per_person)}" for p in payers
        )
        text = (
            "📥 *THU QUỸ*\n"
            f"👥 Người nộp:\n{payer_lines}\n"
            f"💰 Tổng: *{format_amount(draft['amount'])}*"
        )

    else:  # chi
        shared: list[str] = draft.get("shared_by", [])
        per_person = draft["amount"] / len(shared) if shared else draft["amount"]
        text = (
            "📤 *CHI QUỸ*\n"
            f"📝 Nội dung: {draft['note']}\n"
            f"👤 Người trả: *{draft['payer_name']}*\n"
            f"💰 Tổng: *{format_amount(draft['amount'])}*"
            f" ({len(shared)} người · {format_amount(per_person)}/người)"
        )

    text += f"\n\n💰 *Quỹ còn lại: {format_amount(remaining)}*"
    text += f"\n{'─' * 20}\n🆔 Giao dịch #{tx_id}"

    try:
        await ctx.bot.send_message(
            chat_id=group_id,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        # Lỗi broadcast không được block giao dịch đã ghi DB
        logger.error("Không thể gửi thông báo ra group: %s", e)


def _format_balance_summary() -> str:
    """Tóm tắt tổng quỹ còn lại sau giao dịch."""
    total_thu = sum(r["amount"] for r in db.get_transactions_by_type("thu"))
    total_chi = sum(r["amount"] for r in db.get_transactions_by_type("chi"))
    remaining = total_thu - total_chi
    return f"💰 Quỹ còn: *{format_amount(remaining)}*"



async def _auto_backup(ctx: ContextTypes.DEFAULT_TYPE, query) -> None:
    """Gửi file CSV backup vào inbox Admin sau mỗi lần duyệt."""
    from utils.csv_exporter import export_csv

    rows = db.get_all_transactions()
    csv_path = export_csv(rows)
    with open(csv_path, "rb") as f:
        await ctx.bot.send_document(
            chat_id=ADMIN_ID,
            document=InputFile(f, filename="backup.csv"),
            caption="💾 Auto-backup sau khi duyệt giao dịch.",
        )


# ===========================================================================
# TỔNG KẾT (Admin only)
# ===========================================================================

async def tong_ket(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Hiện danh sách ai dư / ai thiếu và cần trả cho ai."""
    if update.effective_user.id != ADMIN_ID:
        return

    from utils.money_parser import format_amount

    balance = db.calc_balance()
    du = {n: v for n, v in balance.items() if v > 0}
    thieu = {n: v for n, v in balance.items() if v < 0}
    hoa_von = {n: v for n, v in balance.items() if v == 0}

    lines = ["📋 *TỔNG KẾT QUỸ*\n"]

    if du:
        lines.append("✅ *Dư:*")
        for name, val in sorted(du.items(), key=lambda x: -x[1]):
            lines.append(f"  • {name}: +{format_amount(val)}")

    if thieu:
        lines.append("\n❌ *Thiếu (cần nộp thêm):*")
        for name, val in sorted(thieu.items(), key=lambda x: x[1]):
            lines.append(f"  • {name}: {format_amount(val)}")

    if hoa_von:
        lines.append("\n⚖️ *Hòa vốn:*")
        for name in hoa_von:
            lines.append(f"  • {name}: 0đ")

    # Tính chuỗi thanh toán đơn giản (debt settlement)
    settlement = _settle(balance)
    if settlement:
        lines.append("\n💳 *Cần chuyển khoản:*")
        for payer, receiver, amt in settlement:
            lines.append(f"  • {payer} → {receiver}: {format_amount(amt)}")

    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")

    # Broadcast tổng kết ra Group
    group_id = _get_group_chat_id()
    if group_id:
        try:
            await ctx.bot.send_message(
                chat_id=group_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Không thể gửi tổng kết ra group: %s", e)
    else:
        logger.warning("GROUP_CHAT_ID chưa cấu hình — bỏ qua broadcast tổng kết.")


TREASURER = "Quốc Huy"  # Người thu/trả tiền trung gian


def _settle(balance: dict[str, float]) -> list[tuple[str, str, float]]:
    """
    Thanh toán qua trung gian Quốc Huy:
    - Người THIẾU → chuyển tiền cho Quốc Huy
    - Quốc Huy → chuyển tiền cho người DƯ
    Số dư của Quốc Huy tự động được bù trừ trong vòng này.
    """
    result: list[tuple[str, str, float]] = []

    for name, val in balance.items():
        if name == TREASURER:
            continue
        if val < -1:  # thiếu → trả cho Quốc Huy
            result.append((name, TREASURER, round(-val)))
        elif val > 1:  # dư → Quốc Huy trả lại
            result.append((TREASURER, name, round(val)))

    return result


# ===========================================================================
# RESET (Admin only)
# ===========================================================================

async def reset_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Bước 1: Admin gõ /reset → hỏi xác nhận."""
    if update.effective_user.id != ADMIN_ID:
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚠️ XÁC NHẬN XÓA TẤT CẢ", callback_data="reset_confirm"),
        InlineKeyboardButton("❌ Hủy", callback_data="reset_cancel"),
    ]])
    await update.message.reply_text(
        "⚠️ *CẢNH BÁO*\n\nThao tác này sẽ xóa *toàn bộ* dữ liệu thu/chi.\nKhông thể hoàn tác!\n\nBạn có chắc chắn?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def reset_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin bấm xác nhận → xóa toàn bộ dữ liệu."""
    query = update.callback_query
    await query.answer()

    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='transactions'")

    await query.edit_message_text("✅ Đã xóa toàn bộ dữ liệu. Quỹ về 0đ.")
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text="💰 Quỹ còn: *0đ*",
        parse_mode="Markdown",
        reply_markup=main_menu(ADMIN_ID),
    )


async def reset_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Đã hủy.")
    await query.edit_message_text("❌ Hủy reset. Dữ liệu vẫn còn nguyên.")


# ===========================================================================
# BACKUP thủ công
# ===========================================================================

async def backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return

    rows = db.get_all_transactions()
    if not rows:
        await update.message.reply_text("ℹ️ Chưa có giao dịch nào để xuất.")
        return

    csv_path = export_csv(rows)
    with open(csv_path, "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename="backup.csv"),
            caption=f"💾 Backup {len(rows)} giao dịch.",
        )


# ===========================================================================
# IMPORT từ CSV backup
# ===========================================================================

async def import_csv(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin gửi file backup.csv vào Inbox bot → tự động import vào DB.
    Bỏ qua các dòng đã tồn tại (dựa theo id).
    """
    if update.effective_user.id != ADMIN_ID:
        return

    doc = update.message.document
    if not doc or not doc.file_name.endswith(".csv"):
        return

    await update.message.reply_text("⏳ Đang import dữ liệu...")

    # Tải file về
    file = await ctx.bot.get_file(doc.file_id)
    import io, csv
    buf = io.BytesIO()
    await file.download_to_memory(buf)
    buf.seek(0)
    content = buf.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(content))
    imported = skipped = 0

    with db.get_conn() as conn:
        existing_ids = {
            row[0] for row in conn.execute("SELECT id FROM transactions").fetchall()
        }

        for row in reader:
            try:
                tx_id = int(row["id"])
                if tx_id in existing_ids:
                    skipped += 1
                    continue

                shared_by = json.dumps(
                    [s.strip() for s in row["shared_by"].split(",") if s.strip()],
                    ensure_ascii=False,
                )
                conn.execute(
                    """
                    INSERT INTO transactions (id, type, amount, note, payer_name, shared_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tx_id,
                        row["type"],
                        int(row["amount"]),
                        row.get("note", ""),
                        row["payer_name"],
                        shared_by,
                        row["created_at"],
                    ),
                )
                imported += 1
            except Exception as e:
                logger.warning("Bỏ qua dòng lỗi: %s — %s", row, e)

    await update.message.reply_text(
        f"✅ Import hoàn tất!\n"
        f"📥 Đã nhập: *{imported}* giao dịch\n"
        f"⏭️ Bỏ qua (trùng): *{skipped}* giao dịch",
        parse_mode="Markdown",
        reply_markup=main_menu(ADMIN_ID),
    )
