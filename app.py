import re
import os
import json
import copy
import time
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
/* 儀表板外層：手機可左右滑動 */
.dashboard-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    width: 100%;
    padding-bottom: 8px;
}

/* 固定 4 欄 */
.dashboard-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(220px, 1fr));
    gap: 12px;
    min-width: 940px;   /* 確保至少能容納 4 張 */
}

/* 卡片 */
.dashboard-card {
    border-radius: 12px;
    padding: 14px 16px;
    min-height: 175px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    box-sizing: border-box;
}

/* 卡片標題 */
.dashboard-title {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 10px;
}

/* 卡片主數字 */
.dashboard-main {
    font-size: 28px;
    font-weight: 800;
    margin-bottom: 6px;
}

/* 卡片副說明 */
.dashboard-sub {
    font-size: 14px;
    color: #666;
    margin-bottom: 10px;
}

/* 卡片明細 */
.dashboard-detail {
    font-size: 14px;
    line-height: 1.7;
}
</style>
""", unsafe_allow_html=True)

# ===== 刷新秒數 =====
REFRESH_SEC = 30

# ===== 是否啟用跳空判斷 =====
ENABLE_GAP_SIGNAL = True

# ===== 股票分組設定檔 =====
GROUPS_FILE = "stock_groups.json"

# ===== 預設股票分組 =====
DEFAULT_STOCK_GROUPS = {
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


# ===== 分組讀寫 =====
def load_stock_groups():
    """
    優先讀取本地 JSON，若失敗則載入預設值
    """
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass

    return copy.deepcopy(DEFAULT_STOCK_GROUPS)


def save_stock_groups(groups):
    """
    將分組儲存到本地 JSON
    """
    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)


# ===== 初始化可編輯股票分組 =====
if "stock_groups" not in st.session_state:
    st.session_state.stock_groups = load_stock_groups()


# ===== 工具函式 =====
def make_anchor_id(group_name: str) -> str:
    """
    將分類名稱轉成可當 HTML anchor 的 id
    """
    anchor = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", group_name).strip("-")
    return f"group-{anchor}"


def yahoo_quote_url(symbol: str) -> str:
    """
    產生台股 Yahoo 個股頁連結
    例如 2330.TW -> https://tw.stock.yahoo.com/quote/2330.TW
    """
    return f"https://tw.stock.yahoo.com/quote/{symbol}"


def normalize_symbols_from_text(text: str):
    """
    將文字區輸入轉成股票代碼清單
    支援：
    - 一行一檔
    - 半形逗號
    - 全形逗號
    """
    if not text:
        return []

    text = text.replace("，", ",")
    lines = []

    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        parts = [p.strip().upper() for p in raw_line.split(",") if p.strip()]
        lines.extend(parts)

    # 去重但保留順序
    seen = set()
    result = []
    for s in lines:
        if s not in seen:
            seen.add(s)
            result.append(s)

    return result


def render_stock_group_editor():
    """
    Sidebar 的股票分組編輯介面
    """
    st.sidebar.markdown("## 🛠️ 股票分組編輯")

    groups = st.session_state.stock_groups
    group_names = list(groups.keys())

    if not group_names:
        st.session_state.stock_groups = copy.deepcopy(DEFAULT_STOCK_GROUPS)
        groups = st.session_state.stock_groups
        group_names = list(groups.keys())

    # ===== 新增分類 =====
    with st.sidebar.expander("➕ 新增分類", expanded=False):
        new_group_name = st.text_input("分類名稱", key="new_group_name_input")
        if st.button("新增分類", key="add_group_btn", use_container_width=True):
            name = new_group_name.strip()
            if not name:
                st.sidebar.warning("請輸入分類名稱")
            elif name in groups:
                st.sidebar.warning("分類名稱已存在")
            else:
                groups[name] = []
                st.session_state.stock_groups = groups
                save_stock_groups(groups)
                st.rerun()

    # ===== 編輯既有分類 =====
    with st.sidebar.expander("📝 編輯分類", expanded=True):
        selected_group = st.selectbox("選擇分類", group_names, key="selected_group_editor")

        current_symbols = groups[selected_group]
        current_text = "\n".join(current_symbols)

        new_group_name = st.text_input(
            "分類名稱（可修改）",
            value=selected_group,
            key="rename_group_input"
        )

        symbols_text = st.text_area(
            "股票清單（每行一檔，或逗號分隔）",
            value=current_text,
            height=220,
            key="symbols_text_area"
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 儲存分類", key="save_group_btn", use_container_width=True):
                new_name = new_group_name.strip()
                if not new_name:
                    st.sidebar.warning("分類名稱不可為空")
                else:
                    new_symbols = normalize_symbols_from_text(symbols_text)

                    updated = {}
                    for k, v in groups.items():
                        if k == selected_group:
                            updated[new_name] = new_symbols
                        else:
                            updated[k] = v

                    st.session_state.stock_groups = updated
                    save_stock_groups(updated)
                    st.rerun()

        with col2:
            if st.button("🗑️ 刪除分類", key="delete_group_btn", use_container_width=True):
                if len(groups) <= 1:
                    st.sidebar.warning("至少保留一個分類")
                else:
                    groups.pop(selected_group, None)
                    st.session_state.stock_groups = groups
                    save_stock_groups(groups)
                    st.rerun()

    # ===== 還原預設 =====
    with st.sidebar.expander("♻️ 重設", expanded=False):
        if st.button("還原預設分組", key="reset_groups_btn", use_container_width=True):
            st.session_state.stock_groups = copy.deepcopy(DEFAULT_STOCK_GROUPS)
            save_stock_groups(st.session_state.stock_groups)
            st.rerun()

    # ===== 分組預覽 =====
    with st.sidebar.expander("👀 分組預覽", expanded=False):
        for g, symbols in st.session_state.stock_groups.items():
            st.markdown(f"**{g}**（{len(symbols)}檔）")
            st.caption(", ".join(symbols) if symbols else "（空）")


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

    # 單層欄位
    if not isinstance(df.columns, pd.MultiIndex):
        cols = [c for c in required_cols if c in df.columns]
        if "Close" in cols and "High" in cols and "Low" in cols:
            return df[cols].copy()
        return pd.DataFrame()

    # MultiIndex 欄位
    normalized = pd.DataFrame(index=df.index)

    for target_col in required_cols:
        matched_series = None
        for col in df.columns:
            # 可能是 ('Close', '2330.TW') 或 ('2330.TW', 'Close')
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

    # ===== 跳空判斷 =====
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


# ===== 顯示格式（不用 Styler） =====
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


# ===== 儀表板卡片（可點擊跳到分類表格）=====
def render_summary_dashboard(group_up_summary, rise_threshold):
    st.markdown("### 📌 各分類漲幅達標儀表板")
    st.caption(f"目前儀表板統計門檻：漲幅 ≥ {rise_threshold}%")

    html_parts = []
    html_parts.append('<div class="dashboard-scroll"><div class="dashboard-grid">')

    for item in group_up_summary:
        group_name = escape(str(item["分類"]))
        anchor_id = make_anchor_id(group_name)

        hit_count = item["達標數"]
        total_count = item["總數"]
        up_count = item["上漲數"]
        down_count = item["下跌數"]
        flat_count = item["平盤數"]
        error_count = item["錯誤數"]

        hit_ratio = (hit_count / total_count * 100) if total_count > 0 else 0

        # 顏色邏輯保留
        if hit_ratio >= 60:
            bg_color = "#fff1f0"
            border_color = "#ff7875"
            accent_color = "#cf1322"
        elif hit_ratio > 0:
            bg_color = "#fff7e6"
            border_color = "#ffa940"
            accent_color = "#d46b08"
        else:
            bg_color = "#f6ffed"
            border_color = "#95de64"
            accent_color = "#389e0d"

        card_html = (
            f'<a href="#{anchor_id}" style="text-decoration:none; color:inherit;">'
            f'<div class="dashboard-card" '
            f'style="background-color:{bg_color}; border:1px solid {border_color}; cursor:pointer;">'
            f'<div class="dashboard-title">{group_name}</div>'
            f'<div class="dashboard-main" style="color:{accent_color};">{hit_count} / {total_count}</div>'
            f'<div class="dashboard-sub">漲幅達標比例（≥{rise_threshold}%）：{hit_ratio:.0f}%</div>'
            f'<div class="dashboard-detail">'
            f'🎯 達標：<b>{hit_count}</b><br>'
            f'🔴 一般上漲：<b>{up_count}</b><br>'
            f'🟢 下跌：<b>{down_count}</b><br>'
            f'⚪ 平盤：<b>{flat_count}</b><br>'
            f'⚠️ 錯誤：<b>{error_count}</b>'
            f'</div>'
            f'</div>'
            f'</a>'
        )

        html_parts.append(card_html)

    html_parts.append("</div></div>")

    cards_html = "".join(html_parts)
    st.markdown(cards_html, unsafe_allow_html=True)


# ===== 主畫面 =====
st.title("📊 股票監控面板 - 告訴我你會買日月光")
render_stock_group_editor()

# 台灣時間
tw_now = datetime.now(ZoneInfo("Asia/Taipei"))
st.caption(f"更新時間：{tw_now.strftime('%Y-%m-%d %H:%M:%S')}")

# ===== 儀表板門檻設定（5%~9%）=====
rise_threshold = st.slider(
    "儀表板漲幅達標門檻 (%)",
    min_value=5,
    max_value=9,
    value=5,
    step=1
)

# ===== 先整理所有群組資料，方便做上方摘要 =====
group_tables = {}
group_up_summary = []

for group_name, stocks in st.session_state.stock_groups.items():
    rows = []
    hit_count = 0      # 漲幅 >= 門檻
    up_count = 0       # 一般上漲（>0）
    down_count = 0
    flat_count = 0
    error_count = 0

    for symbol in stocks:
        try:
            raw_df = download_stock_data(symbol)
            df = normalize_ohlc(raw_df)

            if df.empty:
                raise ValueError("無法解析 yfinance 欄位格式")

            price = get_last_price(symbol, df)
            data = compute_indicators(df, price)

            # ===== 儀表板統計：漲幅達標比例 =====
            if data["pct"] >= rise_threshold:
                hit_count += 1

            # ===== 原本漲跌統計 =====
            if data["pct"] > 0:
                up_count += 1
            elif data["pct"] < 0:
                down_count += 1
            else:
                flat_count += 1

            rows.append({
                "代碼": symbol,
                "代碼網址": yahoo_quote_url(symbol),
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
            error_count += 1
            rows.append({
                "代碼": symbol,
                "代碼網址": "",
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
    display_df = df_table.copy()

    # 顯示前格式化（只改顯示，不改計算邏輯）
    if not display_df.empty:
        display_df["漲跌%"] = display_df["漲跌%"].apply(format_color)
        display_df["K值"] = display_df["K值"].apply(format_k)
        display_df["跳空訊號"] = display_df["跳空訊號"].apply(format_gap)

    group_tables[group_name] = {
        "count": len(stocks),
        "table": display_df
    }

    group_up_summary.append({
        "分類": group_name,
        "達標數": hit_count,
        "上漲數": up_count,
        "下跌數": down_count,
        "平盤數": flat_count,
        "錯誤數": error_count,
        "總數": len(stocks)
    })

# ===== 上方儀表板 =====
render_summary_dashboard(group_up_summary, rise_threshold)

st.divider()

# ===== 顯示各群組表格 =====
for group_name, info in group_tables.items():
    anchor_id = make_anchor_id(group_name)

    # 這個 anchor 讓儀表板可以跳過來
    st.markdown(
        f'<div id="{anchor_id}" style="scroll-margin-top: 80px;"></div>',
        unsafe_allow_html=True
    )

    st.subheader(f"【{group_name}】({info['count']}檔)")

    table_df = info["table"].copy()

    # 用 URL 欄來取代顯示的代碼欄
    table_df["代碼"] = table_df["代碼網址"]

    st.dataframe(
        table_df.drop(columns=["代碼網址"]),
        use_container_width=True,
        column_config={
            "代碼": st.column_config.LinkColumn(
                "代碼",
                help="點擊前往台股 Yahoo",
                display_text=r"https://tw\.stock\.yahoo\.com/quote/(.*)"
            )
        }
    )

    st.markdown('<div style="margin-bottom: 10px;"></div>', unsafe_allow_html=True)

# ===== 自動刷新 =====
time.sleep(REFRESH_SEC)
st.rerun()
``
