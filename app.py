import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ===============================
# 股票分組（直接沿用你的）
# ===============================
stock_groups = {
    "權值股": [
        "2330","00981A","2449","2317","3711",
        "6488","2327","6176","2303","5347",
    ],
    "自選股1": [
        "3008","3035","4566","4956","6456",
        "4749","6271","6290","4919"
    ]
}

# ===============================
# 主邏輯（重寫為 Streamlit 用）
# ===============================
def get_stock(symbol):

    try:
        code = symbol

        # ===== 即時價格（TWSE）=====
        try:
            url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw&json=1"
            res = requests.get(url, timeout=3).json()

            if res.get("msgArray"):
                info = res["msgArray"][0]
                price = float(info.get("z", info.get("y", 0)))
                prev = float(info.get("y", price))
                name = info.get("n","")
            else:
                raise Exception()
        except:
            name = symbol

            hist = yf.download(f"{code}.TW", period="5d", progress=False)
            if hist.empty:
                hist = yf.download(f"{code}.TWO", period="5d", progress=False)

            if hist.empty:
                return None

            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])

        # ===== 歷史資料（KD / MA）=====
        hist = yf.download(f"{code}.TW", period="3mo", progress=False)
        if hist.empty:
            hist = yf.download(f"{code}.TWO", period="3mo", progress=False)

        if hist.empty or len(hist) < 20:
            return None

        df = hist.copy()
        df.columns = [c.lower() for c in df.columns]

        df.loc[df.index[-1], "close"] = price

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

        # ===== KD =====
        df["9h"] = df["high"].rolling(9).max()
        df["9l"] = df["low"].rolling(9).min()

        df["rsv"] = (df["close"] - df["9l"]) / (df["9h"] - df["9l"] + 1e-9) * 100
        df["rsv"] = df["rsv"].fillna(50)

        k, d = 50, 50
        k_list, d_list = [], []

        for r in df["rsv"]:
            k = k * 2/3 + r/3
            d = d * 2/3 + k/3
            k_list.append(k)
            d_list.append(d)

        k_t, d_t = k_list[-1], d_list[-1]
        k_y, d_y = k_list[-2], d_list[-2]

        # ===== KD訊號 =====
        if k_y <= d_y and k_t > d_t:
            signal = "黃金交叉"
        elif k_y >= d_y and k_t < d_t:
            signal = "死亡交叉"
        elif abs(k_t - d_t) < 3:
            signal = "交叉接近"
        elif k_t < 25:
            signal = "超賣"
        else:
            signal = ""

        # ===== 漲跌 =====
        pct = (price - prev) / prev * 100 if prev != 0 else 0

        return {
            "名稱": name,
            "代號": code,
            "價格": round(price,2),
            "漲跌%": round(pct,2),
            "K": round(k_t,1),
            "D": round(d_t,1),
            "MA位置": ma_range,
            "MA排列": ma_trend,
            "訊號": signal
        }

    except:
        return None


# ===============================
# UI
# ===============================
st.set_page_config(layout="wide")

st.title("📊 台股KD監控系統")
st.caption(f"更新時間：{datetime.now().strftime('%H:%M:%S')}")

# ✅ 自動刷新
st_autorefresh(interval=30000)

# ===============================
# 顯示
# ===============================
for group, stocks in stock_groups.items():

    st.subheader(f"📂 {group}")

    data = []

    for s in stocks:
        r = get_stock(s)
        if r:
            data.append(r)

    if data:
        df = pd.DataFrame(data)

        def color_pct(v):
            return "color:red" if v > 0 else "color:green"

        st.dataframe(
            df.style.applymap(color_pct, subset=["漲跌%"]),
            use_container_width=True
        )

    else:
        st.warning("抓不到資料")
