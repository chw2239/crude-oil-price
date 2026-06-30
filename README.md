# Commodities Daily → Feishu

每個工作日自動抓取大宗商品期貨價格，透過飛書機器人推送互動卡片訊息。

## 追蹤商品

| 商品 | 代號 |
|------|------|
| 原油 Crude Oil | CL=F |
| 天然氣 Natural Gas | NG=F |
| 汽油 Gasoline | RB=F |
| 取暖油 Heating Oil | HO=F |
| 黃金 Gold | GC=F |
| 白銀 Silver | SI=F |
| 銅 Copper | HG=F |

## 運作流程

1. 透過 [yfinance](https://github.com/ranaroussi/yfinance) 抓取各商品最新收盤價與前一日漲跌幅
2. 向飛書開放平台取得 `tenant_access_token`
3. 發送互動卡片訊息至指定群組，每欄顯示商品名稱、價格、漲跌幅（漲綠跌紅）

## 自動排程

GitHub Actions 於每天 UTC 23:00（HKT 07:00）觸發，可在 Actions 頁面手動執行測試。

## 設定

### GitHub Secrets

在 **Settings → Secrets and variables → Actions** 中新增以下三個 Secret：

| Secret | 說明 |
|--------|------|
| `FEISHU_APP_ID` | 飛書自建應用的 App ID |
| `FEISHU_APP_SECRET` | 飛書自建應用的 App Secret |
| `FEISHU_CHAT_ID` | 目標群組的 Chat ID（格式：`oc_xxxxxxxx`） |

### 飛書應用所需權限

- `im:message:send_as_bot` — 發送訊息

## 本地執行

```bash
pip install -r requirements.txt

export FEISHU_APP_ID=cli_xxxxxxxx
export FEISHU_APP_SECRET=xxxxxxxx
export FEISHU_CHAT_ID=oc_xxxxxxxx

python send_commodities.py
```

## 依賴套件

- `yfinance >= 0.2.54`
- `requests >= 2.31.0`
