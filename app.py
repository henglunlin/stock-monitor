import streamlit as st
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ===============================
# 股票分組（保留你原本結構）
# ===============================
stock_groups = {
    "權值股": ["2330", "00981A", "2449", "2317", "3711"],
    "自選股": ["3008", "3035", "4566", "4956"],
}

# ===============================
# 抓資料 + KD + MA
# ===============================
def get_stock_data(stock_id):
    try:
        # ===== 歷史資料 (用來算KD) =====
        hist = yf.download(f"{stock_id}.TW", period="3mo", progress=False)
        if hist.empty:
            hist = yf.download(f"{stock_id}.TWO", period="3mo", progress=False)

        if hist.empty or len(hist) < 10:
            return None

        hist.columns = [c.lower() for c in hist.columns]

        # ===== 即時價格 (TWSE) =====
        try:
            url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw&json=1"
            res = requests.get(url, timeout=3).json()

            if res.get("msgArray"):
                info = res["msgArray"][0]
                price = float(info.get("z", info.get("y", 0)))
                prev = float(info.get("y", price))
                name = info.get("n", stock_id)
            else:
                raise Exception()

        except:
            # fallback = yfinance
            price = float(hist["close"].iloc[-1])
            prev = float(hist["close"].iloc[-2])
            name = stock_id

        # ===== KD =====
        df = hist.copy()
        df.loc[df.index[-1], "close"] = price

        df["9h"] = df["high"].rolling(9).max()
        df["9l"] = df["low"].rolling(9).min()
        df["rsv"] = (df["close"] - df["9l"]) / (df["9h"] - df["9l"] + 1e-9) * 100
        df["rsv"] = df["rsv"].fillna(50)

        k, d = 50, 50
        for r in df["rsv"]:
            k = k * 2/3 + r / 3
            d = d * 2/3 + k / 3

        # ===== MA =====
        close = df["close"]
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
            ma_trend = "盤整"

        # ===== 漲跌 =====
        diff = price - prev
        pct = diff / prev * 100 if prev != 0 else 0

        return {
            "名稱": name,
            "價格": round(price, 2),
            "漲跌%": round(pct, 2),
            "K": round(k, 1),
            "D": round(d, 1),
            "MA位置": ma_range,
            "MA排列": ma_trend
        }

    except:
        return None


# ===============================
# UI
# ===============================
st.set_page_config(layout="wide")

st.title("📊 台股KD監控系統")
st.caption(f"更新時間：{datetime.now().strftime('%H:%M:%S')}")

# ✅ 自動刷新（重要）
st_autorefresh(interval=30000)

# ===============================
# 顯示
# ===============================
for group, stocks in stock_groups.items():
    st.subheader(f"📂 {group}")

    data = []

    for sid in stocks:
        r = get_stock_data(sid)
        if r:
            r["代號"] = sid
            data.append(r)

    if data:
        df = pd.DataFrame(data)

        def color_pct(val):
            if val > 0:
                return "color:red"
            elif val < 0:
                return "color:green"
            return ""

        st.dataframe(
            df.style.applymap(color_pct, subset=["漲跌%"]),
            use_container_width=True
        )
    else:
        st.warning("⚠️ 抓不到資料")
