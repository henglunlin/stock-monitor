import streamlit as st
import requests
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
# 抓資料（雙備援）
# ===============================
def get_stock(stock_id):
    # ===== 方法1：TWSE =====
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw&json=1&delay=0"
        res = requests.get(url, timeout=3)

        data = res.json()
        if data.get("msgArray"):
            info = data["msgArray"][0]

            z = info.get("z", "-")
            y = float(info.get("y", 0))

            price = float(z) if z not in ["-", ""] else y

            diff = price - y
            pct = diff / y * 100 if y != 0 else 0

            return {
                "代號": stock_id,
                "名稱": info.get("n", ""),
                "價格": round(price, 2),
                "漲跌%": round(pct, 2)
            }
    except:
        pass

    # ===== 方法2：yfinance 備援 =====
    try:
        hist = yf.download(f"{stock_id}.TW", period="5d", progress=False)

        if hist.empty:
            hist = yf.download(f"{stock_id}.TWO", period="5d", progress=False)

        if hist.empty or len(hist) < 2:
            return None

        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])

        diff = price - prev
        pct = diff / prev * 100

        return {
            "代號": stock_id,
            "名稱": stock_id,
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

# ✅ 自動刷新（30秒）
st_autorefresh(interval=30000)

# ===============================
# 顯示
# ===============================
for group, stocks in stock_groups.items():
    st.subheader(f"📂 {group}")

    cols = st.columns(3)

    for i, sid in enumerate(stocks):
        r = get_stock(sid)

        if r:
            cols[i % 3].metric(
                label=f"{r['名稱']} ({r['代號']})",
                value=f"{r['價格']}",
                delta=f"{r['漲跌%']}%"
            )
        else:
            cols[i % 3].write(f"{sid} ❌ 無資料")
