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
STOCK_NAME_FILE = "TWstocklistname2.txt"
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


# ===== 強化查表邏輯，剔除後綴干擾與自動處理編碼/路徑 =====
def load_stock_name_map(file_path: str = STOCK_NAME_FILE) -> dict:
    name_map = {}

    # 確保使用絕對路徑，避免終端機執行目錄不同導致找不到檔案
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, file_path)

    if not os.path.exists(full_path):
        print(f"⚠️ 找不到股票名稱檔案：{full_path}，將只顯示股票代碼。")
        return name_map

    # 加入多種台灣常見編碼，先嘗試 UTF-8，失敗則退回 Windows 預設的 cp950/Big5
    encodings = ["utf-8-sig", "utf-8", "cp950", "big5"]
    
    for enc in encodings:
        try:
            with open(full_path, "r", encoding=enc) as f:
                for raw_line in f:
                    # 清理不可見字元與全形空白
                    line = raw_line.strip().replace("\ufeff", "").replace("\u3000", " ")
                    if not line:
                        continue

                    # 統一使用 split() 自動切割所有空白與 Tab
                    parts = line.split()
                    if len(parts) >= 2:
                        # 強制把 .TW 或 .TWO 切掉，只留下純代碼作為字典的 Key (例如 2330)
                        base_symbol = parts[0].upper().split('.')[0]
                        name = parts[1].strip()
                        name_map[base_symbol] = name
            
            print(f"✅ 成功以 {enc} 編碼載入 {len(name_map)} 筆股票名稱對照。")
            return name_map  # 只要有一種編碼成功讀取，就提早結束函式

        except UnicodeDecodeError:
            # 如果發生編碼錯誤，什麼都不做，讓迴圈嘗試下一個編碼
            continue
        except Exception as e:
            print(f"⚠️ 讀取股票名稱檔發生其他錯誤: {e}")
            return name_map

    print("❌ 所有編碼格式皆無法讀取該檔案，請打開 TXT 檔案確認內容是否正常。")
    return name_map


def get_stock_name(symbol: str, name_map: dict) -> str:
    # 查詢時也把傳進來的 .TW 拿掉，確保一定能跟字典 Key 對上
    base_symbol = symbol.split('.')[0].upper()
    if base_symbol in name_map:
        return name_map[base_symbol]
    return base_symbol


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
                    # Yahoo 台灣股市的網址通常不帶後綴，使用純數字（如 /quote/2330）能確保網頁正常解析
                    base_symbol = symbol.split('.')[0]
                    yahoo_url = f"https://tw.stock.yahoo.com/quote/{base_symbol}"
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
