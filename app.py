import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import time


# ===== 刷新秒數 =====
REFRESH_SEC = 30

# ===== 是否啟用跳空判斷 =====
ENABLE_GAP_SIGNAL = True

# ===== 股票分組 =====
stock_groups = {
    "權值股": [
        "2330.TW", "00981A.TW", "2449.TW", "2317.TW", "3711.TW",
        "6488.TWO", "2327.TW", "6176.TW", "2303.TW", "5347.TWO",
    ],
    "自選股1": [
        "3008.TW", "3035.TW", "4566.TW", "4956.TW", "6456.TW",
        "4749.TWO", "6271.TW", "6290.TWO", "4919.TW"
    ],
    "低軌衛星": [
        "6285.TW", "2313.TW",
    ],
    "ABF": [
        "4958.TW", "3037.TW", "8046.TW", "3189.TW",
        "8996.TW", "5439.TWO", "8358.TWO",
    ],
    "記憶體": [
        "6770.TW", "2408.TW", "2344.TW", "8271.TW",
        "4967.TW", "3260.TWO", "2451.TW",
    ],
    "CCL": [
        "2383.TW", "6274.TWO", "6213.TW", "8039.TW"
    ],
    "CPO": [
        "4979.TWO", "3163.TWO", "4977.TW",
        "3081.TWO", "3450.TW", "6442.TW"
    ],
}


# ===== 快取：降低重複請求 =====
@st.cache_data(ttl=REFRESH_SEC)
def download_stock_data(symbol):
    df = yf.download(
        symbol,
        period="3mo",
        auto_adjust=True,
        progress=False
    )
    return df


# ===== 將 yfinance 回傳欄位整理成標準 OHLC =====
def normalize_ohlc(df):
    """
    將 yfinance 可能回傳的 MultiIndex 或一般欄位，
    統一整理成單層欄位：Open / High / Low / Close / Volume
    """
    if df is None or df.empty:
        return pd.DataFrame()

    required_cols = ["Open", "High", "Low", "Close", "Volume"]

    # 如果本來就是單層欄位
    if not isinstance(df.columns, pd.MultiIndex):
        cols = [c for c in required_cols if c in df.columns]
        if "Close" in cols and "High" in cols and "Low" in cols:
            return df[cols].copy()
        return pd.DataFrame()

    # 如果是 MultiIndex，嘗試從多層欄位找出需要的欄位
    normalized = pd.DataFrame(index=df.index)

    for target_col in required_cols:
        matched_series = None

        for col in df.columns:
            # col 可能像 ('Close', '2330.TW') 或 ('2330.TW', 'Close')
            if isinstance(col, tuple) and target_col in col:
                matched_series = df[col]
                break

        if matched_series is not None:
            normalized[target_col] = matched_series

    if {"Close", "High", "Low"}.issubset(normalized.columns):
        return normalized

    return pd.DataFrame()


# ===== 取得價格：優先用 fast_info，抓不到就用最後收盤 =====
def get_last_price(symbol, df):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.get("last_price", None)
        if price is not None and pd.notna(price):
            return float(price)
    except Exception:
        pass

    # fallback
    if not df.empty and "Close" in df.columns:
        return float(df["Close"].iloc[-1])

    raise ValueError("無法取得即時價格")


# ===== 技術指標計算 =====
def compute_indicators(df, price):
    if df is None or df.empty:
        raise ValueError("下載資料為空")

    if len(df) < 20:
        raise ValueError("歷史資料不足（至少需要 20 筆）")

    close = df["Close"]
    low = df["Low"]
    high = df["High"]

    # 確保是數值型態
    close = pd.to_numeric(close, errors="coerce")
    low = pd.to_numeric(low, errors="coerce")
    high = pd.to_numeric(high, errors="coerce")

    if close.isna().all() or low.isna().all() or high.isna().all():
        raise ValueError("OHLC 資料格式異常")

    # ===== 漲跌 =====
    yesterday_close = close.iloc[-2]
    if pd.isna(yesterday_close) or yesterday_close == 0:
        raise ValueError("昨收資料異常")

    change_pct = (price / yesterday_close - 1) * 100

    # ===== MA =====
    ma5 = float(close.tail(5).mean())
    ma10 = float(close.tail(10).mean())
    ma20 = float(close.tail(20).mean())

    if price > ma5:
        ma_range = ">MA5"
    elif ma5 >= price > ma10:
        ma_range = "MA5~10"
    elif ma10 >= price > ma20:
        ma_range = "MA10~20"
    else:
        ma_range = "<MA20"

    if ma5 > ma10 > ma20:
        ma_trend = "多頭"
    elif ma5 < ma10 < ma20:
        ma_trend = "空頭"
    else:
        ma_trend = "糾結"

    # ===== KD =====
    low_9 = low.rolling(9).min()
    high_9 = high.rolling(9).max()
    denominator = (high_9 - low_9).replace(0, pd.NA)

    rsv = ((close - low_9) / denominator) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()

    if len(k.dropna()) < 2 or len(d.dropna()) < 2:
        raise ValueError("KD 計算資料不足")

    k_t = float(k.iloc[-1])
    d_t = float(d.iloc[-1])
    k_y = float(k.iloc[-2])
    d_y = float(d.iloc[-2])

    # ===== KD 訊號 =====
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

    # ===== 跳空判斷（新增，但不改原本邏輯）=====
    gap_signal = "-"
    today_low = low.iloc[-1]
    yesterday_high = high.iloc[-2]

    if (
        ENABLE_GAP_SIGNAL
        and pd.notna(today_low)
        and pd.notna(yesterday_high)
        and today_low > yesterday_high
    ):
        gap_signal = "跳空"

    return {
        "price": round(float(price), 2),
        "pct": round(float(change_pct), 2),
        "ma_range": ma_range,
        "ma_trend": ma_trend,
        "k": round(k_t, 1),
        "d": round(d_t, 1),
        "kd_signal": kd_signal,
        "gap_signal": gap_signal
    }


# ===== 顏色格式（不用 Styler） =====
def format_color(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return f"🔴 +{val:.2f}%"
        elif val < 0:
            return f"🟢 {val:.2f}%"
        else:
            return f"{val:.2f}%"
    return val


def format_k(val):
    if isinstance(val, (int, float)):
        if val >= 74:
            return f"🔴 {val:.1f}"
        elif val >= 50:
            return f"🟡 {val:.1f}"
        else:
            return f"🟢 {val:.1f}"
    return val


def format_gap(val):
    if val == "跳空":
        return "🔴 跳空"
    return "-"


# ===== Streamlit UI =====
st.set_page_config(layout="wide")
st.title("📊 股票監控面板 -告訴我你會買日月光")
tw_now = datetime.now(ZoneInfo("Asia/Taipei"))
st.caption(f"更新時間：{tw_now.strftime('%Y-%m-%d %H:%M:%S')}")


# ===== 顯示各群組 =====
for group_name, stocks in stock_groups.items():
    st.subheader(f"【{group_name}】({len(stocks)}檔)")

    rows = []

    for symbol in stocks:
        try:
            raw_df = download_stock_data(symbol)
            df = normalize_ohlc(raw_df)

            if df.empty:
                raise ValueError("無法解析 yfinance 欄位格式")

            price = get_last_price(symbol, df)
            data = compute_indicators(df, price)

            rows.append({
                "代碼": symbol,
                "價格": f"{data['price']:.2f}",
                "漲跌%": data["pct"],
                "MA位置": data["ma_range"],
                "MA排列": data["ma_trend"],
                "K值": data["k"],
                "D值": f"{data['d']:.1f}",
                "KD訊號": data["kd_signal"],
                "跳空訊號": data["gap_signal"]
            })

        except Exception as e:
            rows.append({
                "代碼": symbol,
                "價格": "錯誤",
                "漲跌%": "-",
                "MA位置": "-",
                "MA排列": "-",
                "K值": "-",
                "D值": "-",
                "KD訊號": "-",
                "跳空訊號": str(e)
            })

    df_table = pd.DataFrame(rows)

    # 顯示前格式化（只改顯示，不改計算邏輯）
    if not df_table.empty:
        df_table["漲跌%"] = df_table["漲跌%"].apply(format_color)
        df_table["K值"] = df_table["K值"].apply(format_k)
        df_table["跳空訊號"] = df_table["跳空訊號"].apply(format_gap)

    st.dataframe(df_table, use_container_width=True)

# ===== 自動刷新 =====
time.sleep(REFRESH_SEC)
st.rerun()
