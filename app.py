import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ===============================
# 股票分組
# ===============================
stock_groups = {
    "權值股": ["2330", "2317", "2303"],
    "自選股": ["3008", "3035", "4956"]
}

# ===============================
# 抓資料
# ===============================
def get_stock(stock_id):
    try:
        hist = yf.download(f"{stock_id}.TW", period="1mo", progress=False)

        if hist.empty:
            hist = yf.download(f"{stock_id}.TWO", period="1mo", progress=False)

        if hist.empty or len(hist) < 2:
            return None

        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])

        diff = price - prev
        pct = diff / prev * 100

        return {
            "代號": stock_id,
            "價格": round(price, 2),
            "漲跌%": round(pct, 2)
        }

    except:
        return None

# ===============================
# UI
# ===============================
st.set_page_config(layout="wide")
st.title("📊 台股即時監控")
st.caption(f"更新時間：{datetime.now().strftime('%H:%M:%S')}")

# ✅ 自動刷新
st_autorefresh(interval=30000)

# ===============================
# 顯示
# ===============================
for group, stocks in stock_groups.items():
    st.subheader(f"📂 {group}")

    data = []

    for sid in stocks:
        r = get_stock(sid)

        if r:
            data.append(r)   # ✅ 這行很重要！！！

    if data:
        df = pd.DataFrame(data)

        st.dataframe(df, use_container_width=True)
    else:
        st.warning("抓不到資料")
