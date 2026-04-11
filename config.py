# =============================================================================
# config.py — Cấu hình toàn bộ hệ thống
# =============================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# --- Bot Token ---
BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# --- Telegram ID của Admin ---
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "7291021545"))

# --- Danh sách thành viên (theo thứ tự hiển thị) ---
MEMBERS: list[str] = [
    "Hiền Nguyễn",
    "Hậu Nguyễn",
    "Thảo Lê",
    "Minh 96",
    "Hiền Vũ",
    "Lại Lộc",
    "Phan Anh",
    "Văn Linh",
    "Sơn Cris",
    "Quốc Huy",
    "Hiếu Nghĩa",
]

# --- Telegram Group Chat ID ---
GROUP_CHAT_ID: int = int(os.getenv("GROUP_CHAT_ID", "0"))

# --- Đường dẫn file Database ---
DB_PATH: str = os.path.join(os.path.dirname(__file__), "fund.db")

# --- Đường dẫn file Backup CSV ---
BACKUP_PATH: str = os.path.join(os.path.dirname(__file__), "backup.csv")
