import re
import os
import json
import copy
import time
import gc
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import yfinance as yf

# ===== Streamlit UI 基本設定（一定要放最前面）=====
st.set_page_config(layout="wide")

# ===== 手機固定 4 張卡片 + 可左右滑動 CSS =====
st.markdown("""
<style>
.dashboard-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    width: 100%;
    padding-bottom: 8px;
}
.dashboard-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(220px, 1fr));
    gap: 12px;
    min-width: 940px;
}
.dashboard-card {
    border-radius: 12px;
    padding: 14px 16px;
    min-height: 175px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    box-sizing: border-box;
}
.dashboard-title {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 10px;
}
.dashboard-main {
    font-size: 28px;
    font-weight: 800;
    margin-bottom: 6px;
}
.dashboard-sub {
    font-size: 14px;
    color: #666;
    margin-bottom: 10px;
}
.dashboard-detail {
    font-size: 14px;
    line-height: 1.7;
}
</style>
""", unsafe_allow_html=True)

# ===== 全局參數 =====
REFRESH_SEC = 30
ENABLE_GAP_SIGNAL = True
GROUP_EDIT_PIN = "1219"
GROUPS_FILE = "stock_groups.json"
BACKUP_DIR = "backups"

DEFAULT_STOCK_GROUPS = {
    "權值股": ["2330.TW", "00981A.TW", "2449.TW", "2317.TW", "3711.TW", "6488.TWO", "2327.TW", "6176.TW", "2303.TW", "5347.TWO"],
    "自選股1": ["3008.TW", "3035.TW", "4566.TW", "4956.TW", "6456.TW", "4749.TWO", "6271.TW", "6290.TWO", "4919.TW"],
    "低軌衛星": ["6285.TW", "2313.TW"],
    "ABF": ["4958.TW", "3037.TW", "8046.TW", "3189.TW", "8996.TW", "5439.TWO", "8358.TWO"],
    "記憶體": ["6770.TW", "2408.TW", "2344.TW", "8271.TW", "4967.TW", "3260.TWO", "2451.TW"],
    "CCL": ["2383.TW", "6274.TWO", "6213.TW", "8039.TW"],
    "CPO": ["4979.TWO", "3163.TWO", "4977.TW", "3081.TWO", "3450.TW", "6442.TW"],
}

# ===== 狀態初始化 =====
if "stock_groups" not in st.session_state:
    st.session_state.stock_groups = copy.deepcopy(DEFAULT_STOCK_GROUPS)
if "group_editor_unlocked" not in st.session_state:
    st.session_state.group_editor_unlocked = False
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = False

# ===== 工具函式 =====
def load_stock_groups():
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    return copy.deepcopy(DEFAULT_STOCK_GROUPS)

st.session_state.stock_groups = load_stock_groups()

def save_stock_groups(groups):
    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

def make_anchor_id(group_name: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", group_name).strip("-")

def yahoo_quote_url(symbol: str) -> str:
    return f"https://tw.stock.yahoo.com/quote/{symbol}"

# ===== 快取與資料下載 (加入防當機猛藥) =====
@st.cache_data(ttl=REFRESH_SEC)
def download_stock_data(symbol):
    # 👉 猛藥 1：強制加上 threads=False，防止 yfinance 撐爆免費主機的執行緒上限
    df = yf.download(symbol, period="3mo", auto_adjust=True, progress=False, threads=False)
    return df

def get_last_price(symbol, df):
    # 👉 猛藥 2：徹底捨棄 yf.Ticker，直接從下載好的 DataFrame 拿最後一筆收盤價
    if not df.empty and "Close" in df.columns:
        return float(df["Close"].iloc[-1])
    raise ValueError("無法取得即時價格")

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

def compute_indicators(df, price):
    if df is None or df.empty or len(df) < 20:
        raise ValueError("歷史資料不足或異常")

    close = pd.to_numeric(df["Close"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")

    if close.isna().all() or low.isna().all() or high.isna().all():
        raise ValueError("OHLC 資料格式異常")

    yesterday_close = close.iloc[-2]
    if pd.isna(yesterday_close) or yesterday_close == 0:
        raise ValueError("昨收資料異常")

    change_pct = (price / yesterday_close - 1) * 100

    ma5 = float(close.tail(5).mean())
    ma10 = float(close.tail(10).mean())
    ma20 = float(close.tail(20).mean())

    if price > ma5: ma_range = ">MA5"
    elif ma5 >= price > ma10: ma_range = "MA5~10"
    elif ma10 >= price > ma20: ma_range = "MA10~20"
    else: ma_range = "<MA20"

    if ma5 > ma10 > ma20: ma_trend = "多頭"
    elif ma5 < ma10 < ma20: ma_trend = "空頭"
    else: ma_trend = "糾結"

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

    if k_y <= d_y and k_t > d_t: kd_signal = "黃金交叉"
    elif k_y >= d_y and k_t < d_t: kd_signal = "死亡交叉"
    elif k_t < d_t and (d_t - k_t) < 3: kd_signal = "即將黃金交叉"
    elif k_t > d_t and (k_t - d_t) < 3: kd_signal = "即將死亡交叉"
    elif k_t < 25: kd_signal = "超賣"
    else: kd_signal = "-"

    gap_signal = "跳空" if ENABLE_GAP_SIGNAL and pd.notna(low.iloc[-1]) and pd.notna(high.iloc[-2]) and low.iloc[-1] > high.iloc[-2] else "-"

    return {
        "price": round(float(price), 2), "pct": round(float(change_pct), 2),
        "ma_range": ma_range, "ma_trend": ma_trend, "k": round(k_t, 1),
        "d": round(d_t, 1), "kd_signal": kd_signal, "gap_signal": gap_signal
    }

def format_color(val):
    if isinstance(val, (int, float)):
        return f"🔴 +{val:.2f}%" if val > 0 else f"🟢 {val:.2f}%" if val < 0 else f"{val:.2f}%"
    return val

def format_k(val):
    if isinstance(val, (int, float)):
        return f"🔴 {val:.1f}" if val >= 74 else f"🟡 {val:.1f}" if val >= 50 else f"🟢 {val:.1f}"
    return val

def format_gap(val):
    return "🔴 跳空" if val == "跳空" else "-"

def render_summary_dashboard(group_up_summary, rise_threshold):
    st.markdown("### 📌 各分類漲幅達標儀表板")
    st.caption(f"目前儀表板統計門檻：漲幅 ≥ {rise_threshold}%")

    html_parts = ['<div class="dashboard-scroll"><div class="dashboard-grid">']
    for item in group_up_summary:
        group_name = escape(str(item["分類"]))
        hit_ratio = (item["達標數"] / item["總數"] * 100) if item["總數"] > 0 else 0

        bg_color, border_color, accent_color = ("#fff1f0", "#ff7875", "#cf1322") if hit_ratio >= 60 else \
                                               ("#fff7e6", "#ffa940", "#d46b08") if hit_ratio > 0 else \
                                               ("#f6ffed", "#95de64", "#389e0d")

        html_parts.append(
            f'<a href="#{make_anchor_id(group_name)}" style="text-decoration:none; color:inherit;">'
            f'<div class="dashboard-card" style="background-color:{bg_color}; border:1px solid {border_color};">'
            f'<div class="dashboard-title">{group_name}</div>'
            f'<div class="dashboard-main" style="color:{accent_color};">{item["達標數"]} / {item["總數"]}</div>'
            f'<div class="dashboard-sub">達標比例：{hit_ratio:.0f}%</div>'
            f'<div class="dashboard-detail">'
            f'🎯 達標：<b>{item["達標數"]}</b> | 🔴 上漲：<b>{item["上漲數"]}</b><br>'
            f'🟢 下跌：<b>{item["下跌數"]}</b> | ⚪ 平盤：<b>{item["平盤數"]}</b><br>'
            f'⚠️ 錯誤：<b>{item["錯誤數"]}</b></div></div></a>'
        )
    html_parts.append("</div></div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


# ===== 主畫面 =====
st.title("📊 股票監控面板 - 告訴我你會買日月光")

tw_now = datetime.now(ZoneInfo("Asia/Taipei"))
st.caption(f"更新時間：{tw_now.strftime('%Y-%m-%d %H:%M:%S')}")

rise_threshold = st.slider("儀表板漲幅達標門檻 (%)", 5, 9, 5, 1)

group_tables = {}
group_up_summary = []

for group_name, stocks in st.session_state.stock_groups.items():
    rows = []
    hit_count = up_count = down_count = flat_count = error_count = 0

    for symbol in stocks:
        try:
            raw_df = download_stock_data(symbol)
            df = normalize_ohlc(raw_df)
            price = get_last_price(symbol, df)
            data = compute_indicators(df, price)

            if data["pct"] >= rise_threshold: hit_count += 1
            if data["pct"] > 0: up_count += 1
            elif data["pct"] < 0: down_count += 1
            else: flat_count += 1

            rows.append({
                "代碼": symbol, "代碼網址": yahoo_quote_url(symbol), "價格": f"{data['price']:.2f}",
                "漲跌%": data["pct"], "MA位置": data["ma_range"], "MA排列": data["ma_trend"],
                "K值": data["k"], "D值": f"{data['d']:.1f}", "KD訊號": data["kd_signal"], "跳空訊號": data["gap_signal"]
            })
        except Exception as e:
            error_count += 1
            rows.append({
                "代碼": symbol, "代碼網址": "", "價格": "錯誤", "漲跌%": "-", "MA位置": "-", 
                "MA排列": "-", "K值": "-", "D值": "-", "KD訊號": "-", "跳空訊號": str(e)
            })

    display_df = pd.DataFrame(rows)
    if not display_df.empty:
        display_df["漲跌%"] = display_df["漲跌%"].apply(format_color)
        display_df["K值"] = display_df["K值"].apply(format_k)
        display_df["跳空訊號"] = display_df["跳空訊號"].apply(format_gap)

    group_tables[group_name] = {"count": len(stocks), "table": display_df}
    group_up_summary.append({
        "分類": group_name, "達標數": hit_count, "上漲數": up_count,
        "下跌數": down_count, "平盤數": flat_count, "錯誤數": error_count, "總數": len(stocks)
    })
    
    del rows
    del display_df
    gc.collect()

render_summary_dashboard(group_up_summary, rise_threshold)
st.divider()

for group_name, info in group_tables.items():
    st.markdown(f'<div id="{make_anchor_id(group_name)}" style="scroll-margin-top: 80px;"></div>', unsafe_allow_html=True)
    st.subheader(f"【{group_name}】({info['count']}檔)")
    
    table_df = info["table"].copy()
    table_df["代碼"] = table_df["代碼網址"]
    st.dataframe(
        table_df.drop(columns=["代碼網址"]),
        use_container_width=True,
        column_config={"代碼": st.column_config.LinkColumn("代碼", display_text=r"https://tw\.stock\.yahoo\.com/quote/(.*)")}
    )

st.divider()

# ==========================================
# ===== 👉 新增的控制區塊：手動更新與自動刷新開關 =====
# ==========================================
col1, col2 = st.columns(2)

with col1:
    # 手動按鈕：強制清除快取並重整
    if st.button("🔄 手動更新即時資料 (清除快取)", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with col2:
    # 開關 (Toggle)：控制是否啟動自動刷新
    auto_refresh = st.toggle("⏱️ 啟用自動更新 (每 30 秒)", value=st.session_state.auto_refresh_enabled)
    
    # 如果使用者切換了開關，把狀態存進 Session 並立即重整畫面
    if auto_refresh != st.session_state.auto_refresh_enabled:
        st.session_state.auto_refresh_enabled = auto_refresh
        st.rerun()

# 確保底層沒有殘留無用記憶體
gc.collect()

# 如果自動更新是「開啟」狀態，就執行倒數計時並重新載入
if st.session_state.auto_refresh_enabled:
    time.sleep(REFRESH_SEC)
    st.rerun()
