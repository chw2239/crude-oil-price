"""
Commodities Daily Image → Feishu App Bot
Flow:
  1. Fetch prices via yfinance
  2. Render PNG with Pillow
  3. Get tenant_access_token (app_id + app_secret)
  4. Upload PNG → image_key
  5. Send image message to chat_id
"""

import os
import io
import json
import logging
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config (all from GitHub Secrets / env vars) ────────────────────────────────
FEISHU_APP_ID            = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET        = os.environ["FEISHU_APP_SECRET"]
FEISHU_CHAT_ID           = os.environ["FEISHU_CHAT_ID"]            # oc_xxxxxxxx
FEISHU_THREAD_MESSAGE_ID = os.environ["FEISHU_THREAD_MESSAGE_ID"]  # om_xxxxxxxx
FEISHU_BASE              = "https://open.feishu.cn/open-apis"

TICKERS = [
    ("Crude Oil",   "CL=F"),
    ("Natural Gas", "NG=F"),
    ("Gasoline",    "RB=F"),
    ("Heating Oil", "HO=F"),
    ("Gold",        "GC=F"),
    ("Silver",      "SI=F"),
    ("Copper",      "HG=F"),
]

# ── 1. Fetch prices ────────────────────────────────────────────────────────────

def fetch_prices() -> list[dict]:
    rows = []
    for name, sym in TICKERS:
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
            if hist.empty or len(hist) < 2:
                raise ValueError("Insufficient history")
            last  = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            chg   = (last - prev) / prev * 100
            rows.append({"name": name, "price": last, "change_pct": chg})
            log.info(f"  {name}: {last:.2f}  {chg:+.2f}%")
        except Exception as e:
            log.warning(f"  {name} ({sym}) failed: {e}")
            rows.append({"name": name, "price": None, "change_pct": None})
    return rows

# ── 2. Render PNG ──────────────────────────────────────────────────────────────

W           = 484
H_TITLEBAR  = 56
ROW_H       = 52
H_FOOTER    = 40

C_TITLE_BG  = ( 74, 102, 126)   # 深藍灰標題（原圖）
C_ROW_DARK  = (255, 255, 255)   # 白
C_ROW_LIGHT = (240, 244, 248)   # 極淡藍灰
C_FOOTER_BG = (255, 255, 255)
C_TITLE_TXT = (255, 255, 255)
C_TEXT      = ( 30,  30,  30)
C_GREEN     = (  0, 160,  80)
C_RED       = (210,  50,  50)
C_GRAY      = (100, 100, 100)
C_SOURCE    = ( 60, 120, 190)   # 藍色連結
C_DIVIDER   = (210, 218, 226)


def _font(bold=False, size=12):
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    )
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def build_image(rows: list[dict]) -> bytes:
    H = H_TITLEBAR + len(rows) * ROW_H + H_FOOTER
    img  = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    ft_title  = _font(bold=True,  size=26)
    ft_row    = _font(bold=False, size=22)
    ft_footer = _font(bold=False, size=18)

    # Title bar
    draw.rectangle([0, 0, W, H_TITLEBAR], fill=C_TITLE_BG)
    draw.text((W // 2, H_TITLEBAR // 2), "Commodities",
              font=ft_title, fill=C_TITLE_TXT, anchor="mm")

    # Data rows
    y = H_TITLEBAR
    for i, row in enumerate(rows):
        bg = C_ROW_DARK if i % 2 == 0 else C_ROW_LIGHT
        draw.rectangle([0, y, W, y + ROW_H], fill=bg)
        draw.line([0, y, W, y], fill=C_DIVIDER, width=1)
        cy = y + ROW_H // 2

        draw.text((16, cy), row["name"], font=ft_row, fill=C_TEXT, anchor="lm")

        if row["price"] is not None:
            p   = row["price"]
            txt = f"{p:,.2f}"
            draw.text((300, cy), txt, font=ft_row, fill=C_TEXT, anchor="rm")
        else:
            draw.text((300, cy), "–", font=ft_row, fill=C_GRAY, anchor="rm")

        if row["change_pct"] is not None:
            c    = row["change_pct"]
            col  = C_GREEN if c >= 0 else C_RED
            sign = "+" if c >= 0 else ""
            draw.text((468, cy), f"{sign}{c:.2f}%", font=ft_row, fill=col, anchor="rm")
        else:
            draw.text((468, cy), "–", font=ft_row, fill=C_GRAY, anchor="rm")

        y += ROW_H

    # Footer
    draw.rectangle([0, y, W, H], fill=C_FOOTER_BG)
    draw.line([0, y, W, y], fill=C_DIVIDER, width=1)
    hkt      = datetime.now(timezone(timedelta(hours=8)))
    fy       = y + H_FOOTER // 2
    draw.text((16,     fy), hkt.strftime("%Y.%m.%d"), font=ft_footer, fill=C_GRAY,   anchor="lm")
    draw.text((W - 16, fy), "oil-price.net",          font=ft_footer, fill=C_SOURCE, anchor="rm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# ── 3. Feishu: get token ───────────────────────────────────────────────────────

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

# ── 4. Feishu: upload image ────────────────────────────────────────────────────

def upload_image(token: str, image_bytes: bytes) -> str:
    resp = requests.post(
        f"{FEISHU_BASE}/im/v1/images",
        headers={"Authorization": f"Bearer {token}"},
        data={"image_type": "message"},
        files={"image": ("commodities.png", image_bytes, "image/png")},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Upload error: {data}")
    image_key = data["data"]["image_key"]
    log.info(f"Uploaded image → {image_key}")
    return image_key

# ── 5. Feishu: send image message (reply into thread) ─────────────────────────

def send_text_message(token: str, text: str):
    payload = {
        "msg_type": "text",
        "content":  json.dumps({"text": text}),
        "reply_in_thread": True,
    }
    resp = requests.post(
        f"{FEISHU_BASE}/im/v1/messages/{FEISHU_THREAD_MESSAGE_ID}/reply",
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
        raise RuntimeError(f"Send text error: {data}")
    log.info(f"Text sent ✓  msg_id={data['data']['message_id']}")


def send_image_message(token: str, image_key: str):
    payload = {
        "receive_id": FEISHU_CHAT_ID,
        "msg_type":   "image",
        "content":    json.dumps({"image_key": image_key}),
        "reply_in_thread": True,
    }
    resp = requests.post(
        f"{FEISHU_BASE}/im/v1/messages/{FEISHU_THREAD_MESSAGE_ID}/reply",
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

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    log.info("── Fetch prices ──")
    rows = fetch_prices()

    log.info("── Render image ──")
    image_bytes = build_image(rows)
    with open("commodities.png", "wb") as f:
        f.write(image_bytes)

    log.info("── Feishu send ──")
    token     = get_tenant_token()
    hkt       = datetime.now(timezone(timedelta(hours=8)))
    title     = f"{hkt.strftime('%Y-%m-%d')}  Crude Oil Price Update"
    send_text_message(token, title)
    image_key = upload_image(token, image_bytes)
    send_image_message(token, image_key)

    log.info("Done ✓")


if __name__ == "__main__":
    main()
