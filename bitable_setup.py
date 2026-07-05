"""
One-time setup script:
  1. Create a Feishu Base (多維表格)
  2. Create a table with fields: 日期 / 商品 / 價格 / 漲跌%
  3. Backfill 5 years of daily historical prices via yfinance
  4. Share the Base with the target group chat (so humans can open & build a Dashboard)

Run this ONCE (via GitHub Actions workflow_dispatch, or locally).
After running, note down the printed `app_token` and `table_id` —
you'll need them as GitHub Secrets for the daily script, and to open
the Base in Feishu to manually build the Dashboard (charts).
"""

import os
import json
import time
import logging
from datetime import datetime, timezone

import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FEISHU_APP_ID     = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
FEISHU_CHAT_ID    = os.environ["FEISHU_CHAT_ID"]     # 分享權限用，讓群組能打開這個 Base
FEISHU_BASE       = "https://open.feishu.cn/open-apis"

TICKERS = [
    ("Crude Oil (原油)",     "CL=F"),
    ("Natural Gas (天然氣)", "NG=F"),
    ("Gasoline (汽油)",      "RB=F"),
    ("Heating Oil (取暖油)", "HO=F"),
    ("Gold (黃金)",          "GC=F"),
    ("Silver (白銀)",        "SI=F"),
    ("Copper (銅)",          "HG=F"),
]

BASE_NAME  = "Commodities Price History"
TABLE_NAME = "Price History"


def get_tenant_token() -> str:
    resp = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Token error: {data}")
    log.info("Got tenant_access_token ✓")
    return data["tenant_access_token"]


def create_base(token: str) -> tuple[str, str]:
    """建立多維表格，回傳 (app_token, base_url)"""
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": BASE_NAME},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Create base error: {data}")
    app_token = data["data"]["app"]["app_token"]
    base_url  = data["data"]["app"]["url"]
    log.info(f"Base created ✓  app_token={app_token}")
    log.info(f"Base URL: {base_url}")
    return app_token, base_url


def create_table(token: str, app_token: str) -> str:
    """建立資料表 + 欄位，回傳 table_id"""
    payload = {
        "table": {
            "name": TABLE_NAME,
            "default_view_name": "Grid View",
            "fields": [
                {"field_name": "日期",   "type": 5},   # DateTime
                {"field_name": "商品",   "type": 3,    # Single Select
                 "property": {"options": [{"name": name} for name, _ in TICKERS]}},
                {"field_name": "價格",   "type": 2},   # Number
                {"field_name": "漲跌%",  "type": 2},   # Number
            ]
        }
    }
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Create table error: {data}")
    table_id = data["data"]["table_id"]
    log.info(f"Table created ✓  table_id={table_id}")
    return table_id


def share_with_group(token: str, app_token: str):
    """把 Base 分享給目標群組，讓群組成員能打開編輯"""
    resp = requests.post(
        f"{FEISHU_BASE}/drive/v1/permissions/{app_token}/members"
        f"?type=bitable&need_notification=false",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "member_type": "openchat",
            "member_id":   FEISHU_CHAT_ID,
            "perm":        "full_access",
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("code") == 0:
        log.info("Shared with group chat ✓")
    else:
        log.warning(f"Share warning (non-fatal): {data}")


def fetch_history(name: str, sym: str) -> list[dict]:
    log.info(f"Fetching 5y history for {name} ({sym})…")
    hist = yf.Ticker(sym).history(period="5y", interval="1d", auto_adjust=False)
    if hist.empty:
        log.warning(f"  No data for {name}")
        return []

    closes = hist["Close"]
    records = []
    prev = None
    for date, price in closes.items():
        price = float(price)
        if prev is not None and prev != 0:
            chg = (price - prev) / prev * 100
        else:
            chg = 0.0
        ts_ms = int(date.replace(tzinfo=timezone.utc).timestamp() * 1000)
        records.append({
            "fields": {
                "日期":  ts_ms,
                "商品":  name,
                "價格":  round(price, 4),
                "漲跌%": round(chg, 4),
            }
        })
        prev = price
    log.info(f"  {len(records)} records")
    return records


def batch_write(token: str, app_token: str, table_id: str, records: list[dict]):
    """500 筆一批寫入"""
    CHUNK = 500
    total = len(records)
    for i in range(0, total, CHUNK):
        chunk = records[i:i + CHUNK]
        resp = requests.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"records": chunk},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Batch write error at offset {i}: {data}")
        log.info(f"  Wrote {i + len(chunk)}/{total}")
        time.sleep(0.3)  # 避免觸發限流


def main():
    token = get_tenant_token()

    log.info("── Create Base ──")
    app_token, base_url = create_base(token)

    log.info("── Create Table ──")
    table_id = create_table(token, app_token)

    log.info("── Share with group ──")
    share_with_group(token, app_token)

    log.info("── Backfill 5y history ──")
    for name, sym in TICKERS:
        records = fetch_history(name, sym)
        if records:
            batch_write(token, app_token, table_id, records)

    log.info("=" * 60)
    log.info("SETUP COMPLETE")
    log.info(f"  app_token : {app_token}")
    log.info(f"  table_id  : {table_id}")
    log.info(f"  base_url  : {base_url}")
    log.info("=" * 60)
    log.info("下一步：")
    log.info("1. 把 app_token / table_id 存成 GitHub Secrets")
    log.info("   FEISHU_BITABLE_APP_TOKEN / FEISHU_BITABLE_TABLE_ID")
    log.info("2. 打開 Base URL，手動建立一個儀表盤（Dashboard），")
    log.info("   加入 7 張折線圖（一個商品一張，X 軸=日期，Y 軸=價格，篩選=該商品）")
    log.info("3. 把儀表盤網址存成 GitHub Secret FEISHU_DASHBOARD_URL")


if __name__ == "__main__":
    main()
