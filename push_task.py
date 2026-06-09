import os
import re
import json
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

# ===== 設定常數與環境變數 =====
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

GROUPS_FILE = "stock_groups.json"
STOCK_NAME_FILE = "TWstocklistname.txt"
ENABLE_GAP_SIGNAL = True

DEFAULT_STOCK_GROUPS = {
    "權值股": ["2330.TW", "2317.TW", "2454.TW"],
}

# ===== 核心邏輯區 =====
def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 尚未設定 Telegram Token 或 Chat ID，略過發送。")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"❌ Telegram 傳送失敗：{res.text}")
        else:
            print("✅ Telegram 訊息發送成功")
    except Exception as e:
        print(f"❌ Telegram 連線失敗: {e}")


def load_stock_groups():
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception as e:
            print(f"讀取 {GROUPS_FILE} 失敗: {e}")
    return DEFAULT_STOCK_GROUPS


# ===== 參考 app2026-0608.py 的穩健讀檔邏輯 =====
def load_stock_name_map(file_path: str = STOCK_NAME_FILE) -> dict:
    name_map = {}

    if not os.path.exists(file_path):
        print(f"⚠️ 找不到股票名稱檔案：{file_path}，將只顯示股票代碼。")
        return name_map

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue

                line = line.replace("\ufeff", "").replace("\u3000", "")

                # 優先處理 Tab 分隔
                if "\t" in line:
                    parts = line.split("\t")
                    parts = [p.strip() for p in parts if p.strip()]
                    if len(parts) >= 2:
                        symbol = parts[0].upper()
                        name = parts[1].strip()
                        name_map[symbol] = name
                        continue

                # 再處理一般空白分隔
                m = re.match(r"^([^\s]+)\s+(.+)$", line)
                if m:
                    symbol = m.group(1).strip().upper()
                    name = m.group(2).strip()
                    name_map[symbol] = name

        print(f"✅ 成功載入 {len(name_map)} 筆股票名稱對照。")

    except Exception as e:
        print(f"⚠️ 讀取股票名稱檔發生錯誤: {e}")

    return name_map


# ===== 批次版為求穩定：只查本地名稱表，查不到就回代碼，不再打 get_info() =====
def get_stock_name(symbol: str, name_map: dict) -> str:
    symbol = symbol.upper()
    if symbol in name_map:
        return name_map[symbol]
    return symbol.split(".")[0]


def download_stock_data(symbol):
    return yf.download(symbol, period="3mo", auto_adjust=True, progress=False)


def normalize_ohlc(df):
    if df is None or df.empty:
        return pd.DataFrame()

    required_cols = ["Open", "High", "Low", "Close", "Volume"]

    if not isinstance(df.columns, pd.MultiIndex):
        cols = [c for c in required_cols if c in df.columns]
        if "Close" in cols and "High" in cols and "Low" in cols:
            return df[cols].copy()
        return pd.DataFrame()

    normalized = pd.DataFrame(index=df.index)
    for target_col in required_cols:
        matched_series = None
        for col in df.columns:
            if isinstance(col, tuple) and target_col in col:
                matched_series = df[col]
                break
        if matched_series is not None:
            normalized[target_col] = matched_series

    if {"Close", "High", "Low"}.issubset(normalized.columns):
        return normalized

    return pd.DataFrame()


def get_last_price(symbol, df):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.get("last_price", None)
        if price is not None and pd.notna(price):
            return float(price)
    except Exception:
        pass

    if not df.empty and "Close" in df.columns:
        return float(df["Close"].iloc[-1])

    raise ValueError("無法取得價格")


def compute_indicators(df, price):
    if df is None or df.empty:
        raise ValueError("下載資料為空")
    if len(df) < 20:
        raise ValueError("歷史資料不足（至少需要 20 筆）")

    close = pd.to_numeric(df["Close"].squeeze(), errors="coerce")
    low = pd.to_numeric(df["Low"].squeeze(), errors="coerce")
    high = pd.to_numeric(df["High"].squeeze(), errors="coerce")

    if close.isna().all() or low.isna().all() or high.isna().all():
        raise ValueError("OHLC 資料格式異常")

    yesterday_close = float(close.iloc[-2])
    if pd.isna(yesterday_close) or yesterday_close == 0:
        raise ValueError("昨收資料異常")

    price_val = float(price)
    change_pct = float((price_val / yesterday_close - 1) * 100)

    low_9 = low.rolling(9).min()
    high_9 = high.rolling(9).max()
    denominator = (high_9 - low_9).replace(0, pd.NA)

    rsv = ((close - low_9) / denominator) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()

    if len(k.dropna()) < 2 or len(d.dropna()) < 2:
        raise ValueError("KD 計算資料不足")

    k_t, d_t = float(k.iloc[-1]), float(d.iloc[-1])
    k_y, d_y = float(k.iloc[-2]), float(d.iloc[-2])

    if k_y <= d_y and k_t > d_t:
        kd_signal = "黃金交叉"
    elif k_y >= d_y and k_t < d_t:
        kd_signal = "死亡交叉"
    elif k_t < d_t and (d_t - k_t) < 3:
        kd_signal = "即將黃金交叉"
    elif k_t > d_t and (k_t - d_t) < 3:
        kd_signal = "即將死亡交叉"
    elif k_t < 25:
        kd_signal = "超賣"
    else:
        kd_signal = "-"

    gap_signal = "-"
    today_low = float(low.iloc[-1])
    yesterday_high = float(high.iloc[-2])

    if ENABLE_GAP_SIGNAL and pd.notna(today_low) and pd.notna(yesterday_high) and today_low > yesterday_high:
        gap_signal = "跳空"

    return {
        "price": round(price_val, 2),
        "pct": round(change_pct, 2),
        "kd_signal": kd_signal,
        "gap_signal": gap_signal,
    }


# ===== 主程式執行區 =====
def main():
    tw_now = datetime.now(ZoneInfo("Asia/Taipei"))
    print(f"🕒 開始執行定時掃描... 台灣時間: {tw_now.strftime('%Y-%m-%d %H:%M:%S')}")

    stock_groups = load_stock_groups()
    name_map = load_stock_name_map()

    total_scanned = 0
    hit_messages = []

    for group_name, stocks in stock_groups.items():
        print(f"\n📂 掃描分類：{group_name}（{len(stocks)} 檔）")

        for symbol in stocks:
            total_scanned += 1

            try:
                raw_df = download_stock_data(symbol)
                df = normalize_ohlc(raw_df)

                if df.empty or len(df) < 20:
                    print(f"⚠️ {symbol} 歷史資料不足或格式異常，略過")
                    continue

                price = get_last_price(symbol, df)
                stock_name = get_stock_name(symbol, name_map)
                data = compute_indicators(df, price)

                is_high_gain = data["pct"] >= 1
                has_kd_signal = data["kd_signal"] in ["黃金交叉", "即將黃金交叉"]
                has_gap_signal = data["gap_signal"] == "跳空"

                if is_high_gain and (has_kd_signal or has_gap_signal):
                    yahoo_url = f"https://tw.stock.yahoo.com/quote/{symbol}"
                    symbol_link = f'<a href="{yahoo_url}">{symbol}</a>'

                    msg = (
                        f"🔔 <b>強勢股達標通知：{stock_name} ({symbol_link})</b>\n\n"
                        f"📈 價格：{data['price']}\n"
                        f"🔥 漲幅：+{data['pct']}%\n"
                        f"📊 KD訊號：{data['kd_signal']}\n"
                        f"🚀 跳空訊號：{data['gap_signal']}"
                    )

                    hit_messages.append(msg)
                    print(f"🎯 達標: {stock_name} ({symbol})")

            except Exception as e:
                print(f"⚠️ 處理 {symbol} 時發生錯誤: {e}")

    print(f"\n📊 本次共掃描 {total_scanned} 檔股票。")

    if hit_messages:
        print(f"📨 準備發送 {len(hit_messages)} 則達標通知...")
        for msg in hit_messages:
            send_telegram_message(msg)
            time.sleep(1)
    else:
        print("🤷‍♂️ 目前無股票達標。")

    print("🏁 掃描結束。")


if __name__ == "__main__":
    main()
