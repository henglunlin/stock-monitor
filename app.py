import streamlit as st
import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===============================
# 股票分組
# ===============================
stock_groups = {
    "權值股": ["2330", "00981A", "2449", "2317", "3711",
           "6488", "2327", "6176", "2303", "5347"],
    "自選股1": ["3008", "3035", "4566", "4956", "6456",
            "4749", "6271", "6290", "4919", "3122", "8028",
            "6231", "6412", "6695", "6147", "4722"],
    "低軌衛星": ["6285", "2313"],
    "ABF": ["4958", "3037", "8046", "3189", "8996", "5439", "8358"],
    "記憶體": ["6770", "2408", "2344", "8271", "4967", "3260", "2451", "3006", "2337"],
    "CCL": ["2383", "6274", "6213", "8039"],
    "CP": ["4979", "3163", "4977", "3081", "3450", "6442"],
}

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


# ===============================
# 核心邏輯
# ===============================
def get_live_and_kd(stock_id):
    try:
        hist = yf.download(f"{stock_id}.TW", period="6mo", progress=False)
        if hist.empty:
            hist = yf.download(f"{stock_id}.TWO", period="6mo", progress=False)

        if hist.empty or len(hist) < 10:
            return None

        hist.columns = [c.lower() for c in hist.columns]

        # 即時價格 (TWSE)
        ts = int(time.time() * 1000)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw&json=1&delay=0&_={ts}"
        res = session.get(url, timeout=5, verify=False).json()

        if res.get("msgArray"):
            info = res["msgArray"][0]
            price = float(info.get("z", info.get("y", 0)))
            high = float(info.get("h", price))
            low = float(info.get("l", price))
            prev = float(info.get("y", price))
            name = info.get("n", stock_id)
        else:
            return None

        # ===== KD =====
        df = hist.copy()
        df.iloc[-1, df.columns.get_loc("close")] = price
        df.iloc[-1, df.columns.get_loc("high")] = high
        df.iloc[-1, df.columns.get_loc("low")] = low

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

        diff = price - prev
        pct = diff / prev * 100

        return {
            "id": stock_id,
            "name": name,
            "price": price,
            "pct": pct,
            "k": round(k, 1),
            "d": round(d, 1),
            "ma_range": ma_range,
            "ma_trend": ma_trend
        }

    except:
        return None


# ===============================
# Streamlit UI
# ===============================
st.set_page_config(layout="wide")
st.title("📊 台股即時監控")

st.caption(f"更新時間：{datetime.now().strftime('%H:%M:%S')}")

# 自動刷新
refresh = st.sidebar.slider("刷新秒數", 5, 60, 30)
time.sleep(refresh)
st.rerun()

# 顯示
for group, stocks in stock_groups.items():
    st.subheader(f"📂 {group}")

    data = []
    for sid in stocks:
        r = get_live_and_kd(sid)
        if r:
            data.append(r)

    if data:
        df = pd.DataFrame(data)

        def color_pct(v):
            return "color:red" if v > 0 else "color:green"

        st.dataframe(
            df.style.applymap(color_pct, subset=["pct"]),
            use_container_width=True
        )