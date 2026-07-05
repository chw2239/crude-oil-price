"""
Commodities Daily Text List → Feishu App Bot
Flow:
  1. Fetch prices via yfinance
  2. Get tenant_access_token (app_id + app_secret)
  3. Send post (rich text) message with aligned commodity list
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config (all from GitHub Secrets / env vars) ────────────────────────────────
FEISHU_APP_ID           = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET       = os.environ["FEISHU_APP_SECRET"]
FEISHU_CHAT_ID          = os.environ["FEISHU_CHAT_ID"]            # oc_xxxxxxxx
FEISHU_BITABLE_APP_TOKEN = os.environ["FEISHU_BITABLE_APP_TOKEN"]  # 多維表格 app_token
FEISHU_BITABLE_TABLE_ID  = os.environ["FEISHU_BITABLE_TABLE_ID"]   # 資料表 table_id
FEISHU_DASHBOARD_URL     = os.environ["FEISHU_DASHBOARD_URL"]      # 儀表盤網址（趨勢圖）
FEISHU_BASE             = "https://open.feishu.cn/open-apis"

TICKERS = [
    ("Crude Oil",   "原油",   "CL=F"),
    ("Natural Gas", "天然氣", "NG=F"),
    ("Gasoline",    "汽油",   "RB=F"),
    ("Heating Oil", "取暖油", "HO=F"),
    ("Gold",        "黃金",   "GC=F"),
    ("Silver",      "白銀",   "SI=F"),
    ("Copper",      "銅",     "HG=F"),
]

# ── 1. Fetch prices ────────────────────────────────────────────────────────────

def fetch_prices() -> list[dict]:
    rows = []
    for name_en, name_zh, sym in TICKERS:
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
            if hist.empty or len(hist) < 2:
                raise ValueError("Insufficient history")
            last  = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            chg   = (last - prev) / prev * 100
            rows.append({"name": f"{name_en} ({name_zh})", "price": last, "change_pct": chg})
            log.info(f"  {name_en}: {last:.2f}  {chg:+.2f}%")
        except Exception as e:
            log.warning(f"  {name_en} ({sym}) failed: {e}")
            rows.append({"name": f"{name_en} ({name_zh})", "price": None, "change_pct": None})
    return rows

# ── 2. Feishu: get token ───────────────────────────────────────────────────────

def get_tenant_token() -> str:
    resp = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        headers={"Content-Type": "application/json"},
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Token error: {data}")
    log.info("Got tenant_access_token ✓")
    return data["tenant_access_token"]

# ── 3. Build aligned text rows ─────────────────────────────────────────────────

# ── 3. Build Feishu Interactive Card (column_set table) ────────────────────────

def _row_elements(row: dict) -> list[dict]:
    """單一商品的三欄內容：名稱（超連結至儀表盤）/ 價格 / 漲跌（顏色化文字）"""
    name_link = f"[{row['name']}]({FEISHU_DASHBOARD_URL})"

    if row["price"] is not None:
        price_text = f"{row['price']:,.2f}"
    else:
        price_text = "–"

    if row["change_pct"] is not None:
        c = row["change_pct"]
        color = "green" if c >= 0 else "red"
        sign  = "+" if c >= 0 else ""
        chg_text = f"<font color='{color}'>{sign}{c:.2f}%</font>"
    else:
        chg_text = "–"

    return [
        {"tag": "column", "width": "weighted", "weight": 3,
         "elements": [{"tag": "markdown", "content": name_link}]},
        {"tag": "column", "width": "weighted", "weight": 2,
         "elements": [{"tag": "markdown", "content": price_text, "text_align": "right"}]},
        {"tag": "column", "width": "weighted", "weight": 2,
         "elements": [{"tag": "markdown", "content": chg_text, "text_align": "right"}]},
    ]


def build_card(title: str, rows: list[dict]) -> dict:
    elements = []

    # 數據列（每行後加分隔線）
    for row in rows:
        elements.append({
            "tag": "column_set",
            "flex_mode": "none",
            "columns": _row_elements(row),
        })
        elements.append({"tag": "hr"})

    elements.append({
        "tag": "markdown",
        "content": "[oil-price.net](https://oil-price.net/dashboard.php)"
    })

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "yellow"
        },
        "body": {"elements": elements}
    }

# ── 4. Feishu: send interactive card message ───────────────────────────────────

def send_card_message(token: str, title: str, rows: list[dict]):
    """
    互動卡片訊息，用 column_set 真正分欄達到精準對齊。
    每次發送都是全新獨立訊息（不接續任何話題）。
    """
    card = build_card(title, rows)
    payload = {
        "receive_id": FEISHU_CHAT_ID,
        "msg_type":   "interactive",
        "content":    json.dumps(card),
    }
    resp = requests.post(
        f"{FEISHU_BASE}/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Send error: {data}")
    log.info(f"Message sent ✓  msg_id={data['data']['message_id']}")

# ── 5. Feishu: write today's record to Bitable ─────────────────────────────────

def write_to_bitable(token: str, rows: list[dict]):
    hkt   = datetime.now(timezone(timedelta(hours=8)))
    ts_ms = int(hkt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    records = []
    for row in rows:
        if row["price"] is None:
            continue
        records.append({
            "fields": {
                "日期":  ts_ms,
                "商品":  row["name"],
                "價格":  round(row["price"], 4),
                "漲跌%": round(row["change_pct"], 4) if row["change_pct"] is not None else 0,
            }
        })

    if not records:
        log.warning("No valid records to write to Bitable")
        return

    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_BITABLE_APP_TOKEN}"
        f"/tables/{FEISHU_BITABLE_TABLE_ID}/records/batch_create",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        json={"records": records},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        # 不中斷主流程，僅記錄警告（避免因表格寫入失敗而漏發群組訊息）
        log.warning(f"Bitable write failed (non-fatal): {data}")
    else:
        log.info(f"Bitable write ✓  {len(records)} records")

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    log.info("── Fetch prices ──")
    rows = fetch_prices()

    log.info("── Feishu send ──")
    token = get_tenant_token()
    hkt   = datetime.now(timezone(timedelta(hours=8)))
    title = f"Commodities Daily | {hkt.strftime('%Y %b %d')}"
    send_card_message(token, title, rows)

    log.info("── Bitable write ──")
    write_to_bitable(token, rows)

    log.info("Done ✓")


if __name__ == "__main__":
    main()
