# =============================================================================
# main.py — Entry point
# =============================================================================

import asyncio
import logging
import re

from telegram import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
from config import ADMIN_ID, BOT_TOKEN
from handlers.admin_flow import (
    CHI_AMOUNT,
    CHI_NOTE,
    CHI_PAYER,
    CHI_TOGGLE,
    THU_AMOUNT,
    THU_TOGGLE,
    backup,
    import_csv,
    cmd_setgroup,
    reset_start,
    reset_confirm,
    reset_cancel,
    chi_amount,
    chi_cancel,
    chi_confirm_draft,
    chi_note,
    chi_payer,
    chi_start,
    chi_toggle,
    handle_approve,
    handle_reject,
    thu_amount,
    thu_cancel,
    thu_confirm_draft,
    thu_start,
    thu_toggle,
    tong_ket,
)
from handlers.public_flow import (
    lich_su,
    lich_su_page,
    so_du,
    thong_ke,
    tra_cuu_member,
    tra_cuu_start,
)
from keyboards import main_menu

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setup menu lệnh "/" khi khởi động
# ---------------------------------------------------------------------------

# Lệnh hiển thị cho tất cả thành viên
COMMANDS_PUBLIC = [
    BotCommand("start",    "🚀 Khởi động Bot & Hiển thị bàn phím"),
    BotCommand("help",     "❓ Hướng dẫn sử dụng Bot"),
    BotCommand("balance",  "💰 Xem tổng số dư"),
    BotCommand("history",  "📜 Xem lịch sử giao dịch"),
    BotCommand("thongke",  "📊 Báo cáo công nợ toàn đoàn"),
    BotCommand("tracuu",   "🔍 Tra cứu sao kê cá nhân"),
]

# Lệnh bổ sung chỉ Admin thấy (ghi đè scope cho Admin)
COMMANDS_ADMIN = COMMANDS_PUBLIC + [
    BotCommand("thu",      "📥 Nhập quỹ"),
    BotCommand("chi",      "📤 Ghi nhận chi tiêu"),
    BotCommand("summary",  "📋 Chốt sổ quyết toán"),
    BotCommand("setgroup", "⚙️ Đặt nhóm này làm kênh thông báo"),
    BotCommand("reset",    "🗑️ Xóa toàn bộ dữ liệu"),
]


async def setup_commands(app: Application) -> None:
    """Chạy 1 lần lúc bot khởi động — thiết lập menu '/' trên Telegram."""
    # Tất cả người dùng (chat riêng)
    await app.bot.set_my_commands(
        commands=COMMANDS_PUBLIC,
        scope=BotCommandScopeAllPrivateChats(),
    )
    # Admin thấy thêm lệnh quản trị
    await app.bot.set_my_commands(
        commands=COMMANDS_ADMIN,
        scope=BotCommandScopeChat(chat_id=ADMIN_ID),
    )
    logger.info("Menu lệnh '/' đã được thiết lập trên Telegram.")


# ---------------------------------------------------------------------------
# Forward tin nhắn / ảnh từ Group lên Inbox Admin
# ---------------------------------------------------------------------------

# Regex nhận diện số tiền Việt Nam trong text (không phân biệt hoa/thường)
# Khớp: 50k | 1.2tr | 200đ | 500vnd | 3 cành | 2líp | ...
_MONEY_RE = re.compile(
    r"\d[\d.,]*\s*(?:k|tr|đ|dong|vnd|cành|líp)",
    re.IGNORECASE,
)


def _has_money(text: str) -> bool:
    return bool(_MONEY_RE.search(text))


async def handle_group_message(update: Update, ctx) -> None:
    """
    Lắng nghe Group:
    - Ảnh  → luôn forward Admin.
    - Text → chỉ forward nếu chứa số tiền VN (regex).
    - Text thường (8h, phòng 102...) → bỏ qua hoàn toàn.
    """
    msg = update.message
    is_photo = bool(msg.photo)
    is_money_text = (not is_photo) and bool(msg.text) and _has_money(msg.text)

    if not (is_photo or is_money_text):
        return  # Không phải ảnh, không phải tin tiền → im lặng

    user = update.effective_user
    sender_name = user.full_name or user.username or str(user.id)
    label = "một bill/ảnh" if is_photo else "một khoản tiền"

    # 1. Thông báo Admin
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 Admin lưu ý: *{sender_name}* vừa gửi một thông tin/biên lai trong Group. Vui lòng kiểm tra!",
        parse_mode="Markdown",
    )
    # 2. Forward nguyên bản
    await msg.forward(chat_id=ADMIN_ID)

    # 3. Xác nhận trong Group, tự xóa sau 5 giây
    notice = await msg.reply_text("✅ Đã gửi thông tin này đến Admin!")
    async def _cleanup():
        await asyncio.sleep(5)
        try:
            await notice.delete()
        except Exception:
            pass
    asyncio.create_task(_cleanup())


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_help(update: Update, ctx) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    is_group = update.effective_chat.type in ("group", "supergroup")

    if is_group:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💰 Số Dư",    callback_data="cmd_balance"),
                InlineKeyboardButton("📜 Lịch Sử",  callback_data="cmd_history"),
            ],
            [
                InlineKeyboardButton("📊 Thống Kê", callback_data="cmd_thongke"),
                InlineKeyboardButton("🔍 Tra Cứu",  callback_data="cmd_tracuu"),
            ],
        ])
        sent = await update.effective_message.reply_text(
            "🤖 *Chọn chức năng:*",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        async def _auto_delete():
            await asyncio.sleep(30)
            try:
                await sent.delete()
            except Exception:
                pass
        asyncio.create_task(_auto_delete())
    else:
        text = (
            "🤖 *Hướng dẫn sử dụng Bot Quỹ Du Lịch*\n\n"
            "/balance — 💰 Xem tổng quỹ còn lại\n"
            "/history — 📜 Xem 5 giao dịch gần nhất\n"
            "/thongke — 📊 Báo cáo công nợ toàn đoàn\n"
            "/tracuu  — 🔍 Tra cứu sao kê cá nhân\n\n"
            "_Mọi thắc mắc vui lòng liên hệ Admin của nhóm._ 😊"
        )
        await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_start(update: Update, ctx) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Xin chào *{user.first_name}*!\n\nChọn chức năng bên dưới:",
        parse_mode="Markdown",
        reply_markup=main_menu(user.id),
    )


# ---------------------------------------------------------------------------
# Callback query router
# ---------------------------------------------------------------------------

async def callback_router(update: Update, ctx) -> None:
    query = update.callback_query
    data = query.data

    if data == "cmd_balance":
        await query.answer()
        await so_du(update, ctx)
    elif data == "cmd_history":
        await query.answer()
        await lich_su(update, ctx)
    elif data == "cmd_thongke":
        await query.answer()
        await thong_ke(update, ctx)
    elif data == "cmd_tracuu":
        await query.answer()
        await tra_cuu_start(update, ctx)
    elif data.startswith("hist:"):
        await lich_su_page(update, ctx)
    elif data.startswith("lookup:"):
        await tra_cuu_member(update, ctx)
    elif data.startswith("approve:"):
        await handle_approve(update, ctx)
    elif data.startswith("reject:"):
        await handle_reject(update, ctx)
    elif data == "reset_confirm":
        await reset_confirm(update, ctx)
    elif data == "reset_cancel":
        await reset_cancel(update, ctx)
    else:
        await query.answer()


# ---------------------------------------------------------------------------
# Conversation: Nhập Chi
# ---------------------------------------------------------------------------

def chi_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📤 Nhập Chi$"), chi_start),
            CommandHandler("chi", chi_start),
        ],
        states={
            CHI_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, chi_amount)],
            CHI_NOTE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, chi_note)],
            CHI_PAYER:  [CallbackQueryHandler(chi_payer, pattern=r"^payer:")],
            CHI_TOGGLE: [
                CallbackQueryHandler(chi_toggle, pattern=r"^\{.*\"action\".*\"toggle\""),
                CallbackQueryHandler(chi_confirm_draft, pattern=r"^chi_confirm$"),
                CallbackQueryHandler(chi_cancel, pattern=r"^chi_cancel$"),
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌"), chi_cancel)],
        allow_reentry=True,
        per_message=False,
    )


# ---------------------------------------------------------------------------
# Conversation: Nhập Thu
# ---------------------------------------------------------------------------

def thu_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📥 Nhập Thu$"), thu_start),
            CommandHandler("thu", thu_start),
        ],
        states={
            THU_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, thu_amount)],
            THU_TOGGLE: [
                CallbackQueryHandler(thu_toggle, pattern=r"^\{.*\"action\".*\"toggle\""),
                CallbackQueryHandler(thu_confirm_draft, pattern=r"^thu_confirm$"),
                CallbackQueryHandler(thu_cancel, pattern=r"^thu_cancel$"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        per_message=False,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN chưa được cấu hình trong file .env!")

    db.init_db()
    logger.info("Database khởi tạo xong.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(setup_commands)   # Thiết lập menu "/" khi khởi động
        .build()
    )

    # --- Slash commands ---
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("reset",   reset_start))
    app.add_handler(CommandHandler("setgroup",cmd_setgroup))
    app.add_handler(CommandHandler("balance", so_du))
    app.add_handler(CommandHandler("history", lich_su))
    app.add_handler(CommandHandler("thongke", thong_ke))
    app.add_handler(CommandHandler("tracuu",  tra_cuu_start))
    app.add_handler(CommandHandler("summary", tong_ket))

    # --- Conversations (đăng ký TRƯỚC MessageHandler thông thường) ---
    app.add_handler(chi_conversation())
    app.add_handler(thu_conversation())

    # --- Reply keyboard — public ---
    app.add_handler(MessageHandler(filters.Regex("^💰 Số Dư$"),   so_du))
    app.add_handler(MessageHandler(filters.Regex("^📜 Lịch Sử$"), lich_su))
    app.add_handler(MessageHandler(filters.Regex("^🔍 Tra Cứu$"), tra_cuu_start))
    app.add_handler(MessageHandler(filters.Regex("^📊 Thống Kê$"),thong_ke))

    # --- Reply keyboard — admin ---
    app.add_handler(MessageHandler(filters.Regex("^📋 Tổng Kết$"),tong_ket))
    app.add_handler(MessageHandler(filters.Regex("^💾 Backup$"),  backup))

    # --- Khẩu lệnh gọi Bot trong Group ---
    _bot_call = filters.ChatType.GROUPS & filters.Regex(
        r"(?i)(^bot$|bot\s*ơi|ơi\s*bot|bot\s*help|bot\s*hướng\s*dẫn|dùng\s*bot\s*sao|bot\s*dùng\s*sao)"
    )
    app.add_handler(MessageHandler(_bot_call, cmd_help))

    # --- Lắng nghe Group: ảnh + text có tiền → forward Admin ---
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & (filters.PHOTO | filters.TEXT),
        handle_group_message,
    ))

    # --- Import CSV (Admin gửi file vào Inbox bot) ---
    app.add_handler(MessageHandler(
        filters.Document.FileExtension("csv") & filters.ChatType.PRIVATE,
        import_csv,
    ))

    # --- Inline callbacks ---
    app.add_handler(CallbackQueryHandler(callback_router))

    logger.info("Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
