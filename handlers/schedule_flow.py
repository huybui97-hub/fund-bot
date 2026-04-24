import logging
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

import database as db
from config import ADMIN_ID
from schedule_data import SCHEDULE

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))


def _build_schedule_text(date_str: str) -> str | None:
    day = SCHEDULE.get(date_str)
    if not day:
        return None
    lines = [f"📅 *{day['title']}*\n"]
    for time_str, desc in day["activities"]:
        lines.append(f"  `{time_str}` — {desc}")
    return "\n".join(lines)


async def cmd_schedule(update: Update, ctx) -> None:
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    text = _build_schedule_text(today)
    if not text:
        text = "Hôm nay không có lịch trình chuyến đi."
    await update.effective_message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Job: nhắn Admin xin phê duyệt (thay vì tự động gửi nhóm)
# ---------------------------------------------------------------------------

async def send_reminder(context) -> None:
    """Job chạy 15 phút trước mỗi hoạt động → hỏi Admin có gửi vote nhóm không."""
    data = context.job.data
    date_str  = data["date"]
    time_str  = data["time"]
    desc      = data["desc"]

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Gửi vote nhóm", callback_data=f"remind_ok:{date_str}:{time_str}"),
        InlineKeyboardButton("❌ Bỏ qua",        callback_data="remind_skip"),
    ]])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"⏰ *Sắp đến 15 phút nữa:*\n"
            f"`{time_str}` — {desc}\n\n"
            f"Gửi vote nhắc nhở lên nhóm không?"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# Callback: Admin phê duyệt → tạo poll trên nhóm
# ---------------------------------------------------------------------------

async def handle_remind_approve(update: Update, ctx) -> None:
    query = update.callback_query
    await query.answer()

    # callback_data = "remind_ok:2026-04-25:05:00"
    _, date_str, time_str = query.data.split(":", 2)

    day = SCHEDULE.get(date_str, {})
    desc = next(
        (d for t, d in day.get("activities", []) if t == time_str),
        "Hoạt động sắp diễn ra",
    )

    group_id = db.get_setting("group_chat_id")
    if not group_id:
        await query.edit_message_text("⚠️ Chưa cài đặt nhóm. Dùng /setgroup trong nhóm trước.")
        return

    await ctx.bot.send_poll(
        chat_id=int(group_id),
        question=f"⏰ {time_str} — {desc}\nMọi người sẵn sàng chưa?",
        options=["✅ Sẵn sàng rồi!", "⏳ Cần thêm thời gian"],
        is_anonymous=False,
    )

    await query.edit_message_text(
        f"✅ Đã gửi vote lên nhóm cho hoạt động `{time_str}` — {desc}",
        parse_mode="Markdown",
    )


async def handle_remind_skip(update: Update, ctx) -> None:
    query = update.callback_query
    await query.answer("Đã bỏ qua.")
    await query.edit_message_text("❌ Bỏ qua nhắc nhở này.")


# ---------------------------------------------------------------------------
# Lệnh test thủ công (chỉ Admin)
# ---------------------------------------------------------------------------

async def cmd_testremind(update: Update, ctx) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Gửi vote nhóm", callback_data="remind_ok:2026-04-25:05:00"),
        InlineKeyboardButton("❌ Bỏ qua",        callback_data="remind_skip"),
    ]])
    await update.message.reply_text(
        "⏰ *[TEST] Sắp đến 15 phút nữa:*\n`05:00` — Tập trung nhà Hiền\n\nGửi vote nhắc nhở lên nhóm không?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# Lên lịch tất cả reminders khi bot khởi động
# ---------------------------------------------------------------------------

def schedule_reminders(app) -> None:
    now = datetime.now(VN_TZ)
    count = 0
    for date_str, day in SCHEDULE.items():
        y, m, d = map(int, date_str.split("-"))
        for time_str, desc in day["activities"]:
            h, mi = map(int, time_str.split(":"))
            dt_vn = datetime(y, m, d, h, mi, 0, tzinfo=VN_TZ)
            remind_dt = dt_vn - timedelta(minutes=15)
            if remind_dt > now:
                app.job_queue.run_once(
                    send_reminder,
                    when=remind_dt,
                    data={"date": date_str, "time": time_str, "desc": desc},
                )
                count += 1
    logger.info(f"Đã lên lịch {count} nhắc nhở tự động.")
