import streamlit as st
import requests
import yfinance as yf
import pandas as pd
import urllib3
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===============================
# 股票分組
# ===============================
stock_groups = {
    "權值股": ["2330", "2317", "2303"],
    "自選股": ["3008", "3035", "4956"]
}

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

# ===============================
# 核心邏輯
# ===============================
def get_stock(stock_id):
    try:
        hist = yf.download(f"{stock_id}.TW", period="3mo", progress=False)
        if hist.empty:
            hist = yf.download(f"{stock_id}.TWO", period="3mo", progress=False)

        if hist.empty or len(hist) < 5:
            return None

        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])

        diff = price - prev
        pct = diff / prev * 100

        return {
            "id": stock_id,
            "price": round(price, 2),
            "pct": round(pct, 2)
        }

    except:
        return None


# ===============================
# UI
# ===============================
st.set_page_config(layout="wide")
st.title("📊 台股即時監控")

st.caption(f"更新時間：{datetime.now().strftime('%H:%M:%S')}")

# ✅ 正確自動刷新（雲端用）
st_autorefresh(interval=30000)

for group, stocks in stock_groups.items():
    st.subheader(f"📂 {group}")

    cols = st.columns(3)

    for i, sid in enumerate(stocks):
        r = get_stock(sid)

        if r:
            cols[i % 3].metric(
                label=sid,
                value=f"{r['price']}",
                delta=f"{r['pct']}%"
            )
