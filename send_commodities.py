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
FEISHU_APP_ID     = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
FEISHU_CHAT_ID    = os.environ["FEISHU_CHAT_ID"]   # oc_xxxxxxxxxxxxxxxx
FEISHU_BASE       = "https://open.feishu.cn/open-apis"

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

W           = 340
H_TITLEBAR  = 34
H_COLHDR    = 22
ROW_H       = 28
H_FOOTER    = 28

C_TITLE_BG  = (34,  98, 130)
C_DARK      = (28,  28,  34)
C_LIGHT     = (36,  36,  44)
C_COLHDR    = (44,  44,  56)
C_FOOTER    = (22,  22,  28)
C_WHITE     = (240, 240, 240)
C_GRAY      = (140, 140, 150)
C_GREEN     = ( 72, 199, 116)
C_RED       = (220,  72,  72)

COL = {"name": 10, "price": 192, "chg": 268}


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
    H = H_TITLEBAR + H_COLHDR + len(rows) * ROW_H + H_FOOTER
    img  = Image.new("RGB", (W, H), C_DARK)
    draw = ImageDraw.Draw(img)

    ft_title  = _font(bold=True,  size=15)
    ft_colhdr = _font(bold=False, size=9)
    ft_row    = _font(bold=False, size=11)
    ft_footer = _font(bold=False, size=9)

    # Title bar
    draw.rectangle([0, 0, W, H_TITLEBAR], fill=C_TITLE_BG)
    draw.text((W // 2, H_TITLEBAR // 2), "Commodities",
              font=ft_title, fill=C_WHITE, anchor="mm")

    # Column header
    y = H_TITLEBAR
    draw.rectangle([0, y, W, y + H_COLHDR], fill=C_COLHDR)
    draw.text((COL["name"],  y + H_COLHDR // 2), "Commodity", font=ft_colhdr, fill=C_GRAY, anchor="lm")
    draw.text((COL["price"], y + H_COLHDR // 2), "Price",     font=ft_colhdr, fill=C_GRAY, anchor="lm")
    draw.text((COL["chg"],   y + H_COLHDR // 2), "Change",    font=ft_colhdr, fill=C_GRAY, anchor="lm")
    y += H_COLHDR

    # Data rows
    for i, row in enumerate(rows):
        draw.rectangle([0, y, W, y + ROW_H], fill=C_DARK if i % 2 == 0 else C_LIGHT)
        cy = y + ROW_H // 2

        draw.text((COL["name"], cy), row["name"], font=ft_row, fill=C_WHITE, anchor="lm")

        if row["price"] is not None:
            p   = row["price"]
            txt = f"{p:,.0f}" if p >= 1000 else f"{p:.2f}"
            draw.text((COL["price"], cy), txt, font=ft_row, fill=C_WHITE, anchor="lm")
        else:
            draw.text((COL["price"], cy), "-", font=ft_row, fill=C_GRAY, anchor="lm")

        if row["change_pct"] is not None:
            c    = row["change_pct"]
            col  = C_GREEN if c >= 0 else C_RED
            sign = "+" if c >= 0 else ""
            draw.text((COL["chg"], cy), f"{sign}{c:.2f}%", font=ft_row, fill=col, anchor="lm")
        else:
            draw.text((COL["chg"], cy), "-", font=ft_row, fill=C_GRAY, anchor="lm")

        y += ROW_H

    # Footer
    draw.rectangle([0, y, W, H], fill=C_FOOTER)
    hkt      = datetime.now(timezone(timedelta(hours=8)))
    date_str = hkt.strftime("%Y.%m.%d  HKT")
    fy = y + H_FOOTER // 2
    draw.text((10,     fy), date_str,        font=ft_footer, fill=C_GRAY, anchor="lm")
    draw.text((W - 10, fy), "oil-price.net", font=ft_footer, fill=C_GRAY, anchor="rm")

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

# ── 5. Feishu: send image message ─────────────────────────────────────────────

def send_image_message(token: str, image_key: str):
    payload = {
        "receive_id": FEISHU_CHAT_ID,
        "msg_type":   "image",
        "content":    json.dumps({"image_key": image_key}),
    }
    resp = requests.post(
        f"{FEISHU_BASE}/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization":  f"Bearer {token}",
            "Content-Type":   "application/json",
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
    # Also save locally as Actions artifact
    with open("commodities.png", "wb") as f:
        f.write(image_bytes)

    log.info("── Feishu send ──")
    token     = get_tenant_token()
    image_key = upload_image(token, image_bytes)
    send_image_message(token, image_key)

    log.info("Done ✓")


if __name__ == "__main__":
    main()
