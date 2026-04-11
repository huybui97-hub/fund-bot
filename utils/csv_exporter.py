# =============================================================================
# utils/csv_exporter.py — Xuất file CSV backup
# =============================================================================

import csv
import json
import os
from datetime import datetime

from config import BACKUP_PATH


def export_csv(rows: list) -> str:
    """
    Nhận danh sách sqlite3.Row từ get_all_transactions() và ghi ra file CSV.
    Trả về đường dẫn tuyệt đối của file vừa tạo.
    """
    fieldnames = ["id", "type", "amount", "note", "payer_name", "shared_by", "created_at"]

    with open(BACKUP_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            shared = json.loads(row["shared_by"])
            writer.writerow({
                "id": row["id"],
                "type": row["type"],
                "amount": row["amount"],
                "note": row["note"],
                "payer_name": row["payer_name"],
                "shared_by": ", ".join(shared),
                "created_at": row["created_at"],
            })

    return os.path.abspath(BACKUP_PATH)
