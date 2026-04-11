# =============================================================================
# utils/money_parser.py — Smart Money Parser
# =============================================================================
#
# Bảng chuyển đổi:
#   50k / 50K           → 50_000
#   1.5k / 1,5k         → 1_500
#   1tr / 1TR           → 1_000_000
#   1.2tr / 1,2tr       → 1_200_000
#   1tr2                → 1_200_000   (1 triệu 2 trăm nghìn)
#   2m / 2M             → 2_000_000
#   1.5m / 1,5m         → 1_500_000
#   200000              → 200_000
#   200.000 / 200,000   → 200_000     (dấu phân cách nghìn)
#   500đ / 500vnd       → 500
#   Nhập linh tinh      → None
# =============================================================================

import re


def parse_money(text: str) -> int | None:
    """
    Chuyển chuỗi tiền tự nhiên sang số nguyên VND.
    Trả về None nếu không nhận dạng được.
    """
    if not text:
        return None

    s = text.strip().lower().replace(" ", "")

    # Bỏ hậu tố tiền tệ thuần túy (không kèm số nhân)
    s = re.sub(r"(đ|dong|vnd)$", "", s)

    # ------------------------------------------------------------------
    # 1. Dạng 1tr2  →  1_000_000 + 2 * 100_000 = 1_200_000
    # ------------------------------------------------------------------
    m = re.fullmatch(r"(\d+)tr(\d+)", s)
    if m:
        return int(m.group(1)) * 1_000_000 + int(m.group(2)) * 100_000

    # ------------------------------------------------------------------
    # 2. Dạng X.Ytr hoặc X,Ytr  →  float * 1_000_000
    # ------------------------------------------------------------------
    m = re.fullmatch(r"(\d+)[.,](\d+)tr", s)
    if m:
        return int(float(f"{m.group(1)}.{m.group(2)}") * 1_000_000)

    # ------------------------------------------------------------------
    # 3. Dạng Xtr  →  X * 1_000_000
    # ------------------------------------------------------------------
    m = re.fullmatch(r"(\d+)tr", s)
    if m:
        return int(m.group(1)) * 1_000_000

    # ------------------------------------------------------------------
    # 4. Dạng X.Ym / X,Ym / Xm  →  float * 1_000_000
    # ------------------------------------------------------------------
    m = re.fullmatch(r"(\d+)(?:[.,](\d+))?m", s)
    if m:
        base = f"{m.group(1)}.{m.group(2)}" if m.group(2) else m.group(1)
        return int(float(base) * 1_000_000)

    # ------------------------------------------------------------------
    # 5. Dạng X.Yk / X,Yk / Xk  →  float * 1_000
    # ------------------------------------------------------------------
    m = re.fullmatch(r"(\d+)(?:[.,](\d+))?k", s)
    if m:
        base = f"{m.group(1)}.{m.group(2)}" if m.group(2) else m.group(1)
        return int(float(base) * 1_000)

    # ------------------------------------------------------------------
    # 6. Thuần số — xử lý dấu phân cách nghìn (200.000 / 200,000)
    #    Quy tắc: nếu sau dấu . hoặc , là đúng 3 chữ số → phân cách nghìn
    # ------------------------------------------------------------------
    clean = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", s)
    m = re.fullmatch(r"\d+", clean)
    if m:
        return int(clean)

    return None


# Alias để tương thích với code cũ đang dùng parse_amount
parse_amount = parse_money


def format_amount(amount: int | float) -> str:
    """Định dạng số tiền ra chuỗi dễ đọc: 1.200.000đ"""
    return f"{int(amount):,}đ".replace(",", ".")


# ------------------------------------------------------------------
# Tự test khi chạy file trực tiếp: python utils/money_parser.py
# ------------------------------------------------------------------
if __name__ == "__main__":
    cases = [
        ("50k",      50_000),
        ("50K",      50_000),
        ("1.5k",     1_500),
        ("1,5k",     1_500),
        ("1tr",      1_000_000),
        ("1.2tr",    1_200_000),
        ("1,2tr",    1_200_000),
        ("1tr2",     1_200_000),
        ("2m",       2_000_000),
        ("1.5m",     1_500_000),
        ("1,5m",     1_500_000),
        ("200000",   200_000),
        ("200.000",  200_000),
        ("200,000",  200_000),
        ("500đ",     500),
        ("500vnd",   500),
        ("abc",      None),
        ("8h",       None),
    ]

    passed = failed = 0
    for text, expected in cases:
        result = parse_money(text)
        ok = result == expected
        status = "OK" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"{status}  parse_money({text.encode('ascii','replace').decode():12}) = {str(result):>12}  (expected {expected})")

    print(f"\n{passed}/{passed + failed} passed")
