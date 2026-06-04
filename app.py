import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import time

# ===== 刷新秒數 =====
REFRESH_SEC = 30

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


# ===== 技術指標計算 =====
def compute_indicators(df, price):
    close = df["Close"]
    low = df["Low"]
    high = df["High"]

    # ===== 漲跌 =====
    yesterday_close = close.iloc[-2]
    change_pct = (price / yesterday_close - 1) * 100

    # ===== MA =====
    ma5 = close.tail(5).mean()
    ma10 = close.tail(10).mean()
    ma20 = close.tail(20).mean()

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
    rsv = (
        (close - low.rolling(9).min()) /
        (high.rolling(9).max() - low.rolling(9).min())
    ) * 100

    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()

    k_t, d_t = k.iloc[-1], d.iloc[-1]
    k_y, d_y = k.iloc[-2], d.iloc[-2]

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

    return {
        "price": round(price, 2),
        "pct": round(change_pct, 2),
        "ma_range": ma_range,
        "ma_trend": ma_trend,
        "k": round(k_t, 1),
        "d": round(d_t, 1),
        "kd_signal": kd_signal
    }


# ===== Streamlit UI =====
st.set_page_config(layout="wide")
st.title("📊 股票監控面板 (yfinance)")

st.caption(f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ===== 顯示各群組 =====
for group_name, stocks in stock_groups.items():
    st.subheader(f"【{group_name}】({len(stocks)}檔)")

    rows = []

    for symbol in stocks:
        try:
            ticker = yf.Ticker(symbol)
            price = ticker.fast_info["last_price"]

            df = yf.download(
                symbol,
                period="3mo",
                auto_adjust=True,
                progress=False
            )

            data = compute_indicators(df, price)

            rows.append({
                "代碼": symbol,
                "價格": data["price"],
                "漲跌%": data["pct"],
                "MA位置": data["ma_range"],
                "MA排列": data["ma_trend"],
                "K值": data["k"],
                "D值": data["d"],
                "KD訊號": data["kd_signal"]
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
                "KD訊號": str(e)
            })

    df_table = pd.DataFrame(rows)

    # ✅ ===== 新版顏色處理（不使用 style） =====
    def format_color(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return f"🔴 {val}"
            elif val < 0:
                return f"🟢 {val}"
        return val

    def format_k(val):
        if isinstance(val, (int, float)):
            if val >= 74:
                return f"🔴 {val}"
            elif val >= 50:
                return f"🟡 {val}"
            else:
                return f"🟢 {val}"
        return val

    df_table["漲跌%"] = df_table["漲跌%"].apply(format_color)
    df_table["K值"] = df_table["K值"].apply(format_k)

    st.dataframe(df_table, use_container_width=True)

# ===== 自動刷新 =====
time.sleep(REFRESH_SEC)
st.rerun()
