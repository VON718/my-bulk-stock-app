import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# 導入局部極值計算 (用於 Auto-Pivot)
try:
    from scipy.signal import argrelextrema
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False

# 頁面配置
st.set_page_config(page_title="專業級美股終極戰鬥儀表板", layout="wide")

if "alerted_stocks" not in st.session_state:
    st.session_state.alerted_stocks = set()

# --- 側邊欄風控與排程 ---
with st.sidebar:
    st.header("⚙️ 戰鬥室設定 (Controls)")
    account_capital = st.number_input("帳戶總本金 (USD)", min_value=1000, value=50000, step=5000)
    risk_pct = st.slider("單筆最大承擔風險 (%)", min_value=0.25, max_value=3.0, value=1.0, step=0.25)
    max_risk_amount = account_capital * (risk_pct / 100.0)
    st.caption(f"🛡️ 單筆風險上限：**${max_risk_amount:,.2f}**")
    
    st.divider()
    st.subheader("🔄 盤中自動輪詢")
    enable_autorefresh = st.checkbox("啟用定時自動掃描", value=False)
    refresh_interval = st.selectbox("輪詢間隔", [60, 180, 300, 600], index=2, format_func=lambda x: f"{x} 秒")
    if enable_autorefresh and AUTOREFRESH_AVAILABLE:
        st_autorefresh(interval=refresh_interval * 1000, key="auto_scanner_refresh")
        
    st.divider()
    st.subheader("📢 即時推播 (Discord)")
    discord_webhook_url = st.text_input("Discord Webhook URL", type="password", placeholder="https://discord.com/api/webhooks/...")

# --- 1. 大盤環境過濾器 (獲取 SPY 與 QQQ) ---
@st.cache_data(ttl=300)
def get_market_regime_and_spy():
    """快取大盤數據，供全域大盤燈號與個股 RS 線共用"""
    try:
        spy = yf.Ticker("SPY").history(period="2y", interval="1d", auto_adjust=True)
        qqq = yf.Ticker("QQQ").history(period="2y", interval="1d", auto_adjust=True)
        if spy.empty or qqq.empty:
            return None, None
        
        spy_c, qqq_c = spy['Close'].iloc[-1], qqq['Close'].iloc[-1]
        spy_ma50, spy_ma200 = ta.sma(spy['Close'], 50).iloc[-1], ta.sma(spy['Close'], 200).iloc[-1]
        qqq_ma50, qqq_ma200 = ta.sma(qqq['Close'], 50).iloc[-1], ta.sma(qqq['Close'], 200).iloc[-1]

        bullish = (spy_c > spy_ma50 > spy_ma200) and (qqq_c > qqq_ma50 > qqq_ma200)
        bearish = (spy_c < spy_ma200) or (qqq_c < qqq_ma200)

        regime_data = {"bullish": bullish, "bearish": bearish}
        return regime_data, spy
    except Exception:
        return None, None

regime, spy_df = get_market_regime_and_spy()

if regime:
    if regime["bullish"]:
        st.success("🟢 **大盤信號：強勢多頭 (Risk-On)** ｜ SPY 與 QQQ 均站上 50MA 與 200MA，多頭突破勝率最高。")
    elif regime["bearish"]:
        st.error("🔴 **大盤信號：空頭修正警戒 (Risk-Off)** ｜ 指數跌破 200MA 年線，建議嚴控部位或空倉觀望！")
    else:
        st.warning("🟡 **大盤信號：震盪整理期 (Caution)** ｜ 大盤跌破短期均線或兩指步調不一，操作以防守為主。")

st.title("🚀 專業級美股清單掃描儀 (Institutional Pro)")

# 用戶輸入名單
raw_input = st.text_area(
    "輸入股票代碼 (逗號或空格隔開):", 
    value="NVDA, TSLA, AAPL, PLTR, AMD, MSFT, META, GOOGL, CRWD, SMCI", 
    height=70
)
tickers = [t.strip().upper() for t in raw_input.replace(',', ' ').split() if t.strip()]

# --- 輔助：即時價格與成交量 ---
def get_latest_market_data(ticker, fallback_price, fallback_vol):
    latest_price, prev_close, today_volume = None, None, None
    try:
        fast = ticker.fast_info
        p = getattr(fast, 'last_price', None) or getattr(fast, 'lastPrice', None)
        if p and not pd.isna(p) and p > 0: latest_price = float(p)
        pc = getattr(fast, 'previous_close', None) or getattr(fast, 'previousClose', None)
        if pc and not pd.isna(pc) and pc > 0: prev_close = float(pc)
        vol = getattr(fast, 'last_volume', None) or getattr(fast, 'lastVolume', None)
        if vol and not pd.isna(vol) and vol > 0: today_volume = float(vol)
    except Exception:
        pass
    if latest_price is None: latest_price = float(fallback_price)
    if today_volume is None: today_volume = float(fallback_vol)
    return latest_price, prev_close, today_volume

# --- 功能 4 輔助：自動計算樞紐高點 (Pivot Point) ---
def find_auto_pivot(df):
    """抓出最近 25 日內的局部高點作為 Cheating Pivot"""
    if len(df) < 30:
        return float(df['High'].iloc[-20:-1].max())
    
    recent_highs = df['High'].iloc[-25:-1]
    if SCIPY_AVAILABLE:
        extrema = argrelextrema(recent_highs.values, np.greater, order=2)[0]
        if len(extrema) > 0:
            return float(recent_highs.iloc[extrema[-1]])
    return float(recent_highs.max())

# --- 核心分析函式 (整合 功能 1, 2, 4, 5) ---
def analyze_stock(symbol, capital, risk_budget, spy_history):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 200:
            return None

        # 計算指標
        df['MA50'] = ta.sma(df['Close'], length=50)
        df['MA150'] = ta.sma(df['Close'], length=150)
        df['MA200'] = ta.sma(df['Close'], length=200)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df = df.dropna()
        if len(df) < 25: return None

        curr = df.iloc[-1]
        prev_day = df.iloc[-2]
        prev_22 = df.iloc[-22]

        current_price, prev_close, current_vol = get_latest_market_data(ticker, curr['Close'], curr['Volume'])
        if prev_close is None: prev_close = float(prev_day['Close'])

        change_pct = ((current_price - prev_close) / prev_close) * 100
        avg_vol_20 = float(df['Volume'].iloc[-21:-1].mean()) if len(df) >= 21 else float(df['Volume'].mean())
        vol_multiple = (current_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

        # 52 週位置
        past_year = df.tail(252)
        high_52w = float(past_year['High'].max())
        low_52w = float(past_year['Low'].min())
        pct_above_low = ((current_price - low_52w) / low_52w) * 100
        pct_below_high = ((high_52w - current_price) / high_52w) * 100

        # --- [功能 1] RS 相對強度與「線先於價創新高」偵測 ---
        rs_status = "普通"
        if spy_history is not None and not spy_history.empty:
            aligned_stock = df['Close'].tail(252)
            aligned_spy = spy_history['Close'].reindex(aligned_stock.index).ffill()
            rs_series = aligned_stock / aligned_spy
            rs_52w_high = float(rs_series.max())
            curr_rs = float(rs_series.iloc[-1])
            
            # RS 達到 52 週新高 (容許 0.5% 誤差) 且 股價尚未創 52 週新高
            if curr_rs >= rs_52w_high * 0.995:
                if pct_below_high > 3.0:
                    rs_status = "⭐ RS 領先突圍"
                else:
                    rs_status = "🔥 RS 雙創新高"

        # --- [功能 2] 財報倒數避雷針 ---
        earnings_warning = "安全"
        days_to_earnings = 999
        try:
            cal = ticker.calendar
            e_date = None
            if isinstance(cal, pd.DataFrame) and not cal.empty:
                if 'Earnings Date' in cal.index:
                    e_date = pd.to_datetime(cal.loc['Earnings Date'].iloc[0])
                elif 'Earnings Date' in cal.columns:
                    e_date = pd.to_datetime(cal['Earnings Date'].iloc[0])
            elif isinstance(cal, dict) and 'Earnings Date' in cal:
                val = cal['Earnings Date']
                e_date = pd.to_datetime(val[0] if isinstance(val, (list, tuple)) else val)
            
            if e_date is not None:
                e_date = pd.to_datetime(e_date).tz_localize(None).normalize()
                today = pd.Timestamp.now().normalize()
                days_to_earnings = (e_date - today).days
                if 0 <= days_to_earnings <= 10:
                    earnings_warning = f"⚠️ 倒數 {days_to_earnings} 天"
                elif days_to_earnings < 0:
                    earnings_warning = "近期已公佈"
        except Exception:
            earnings_warning = "無資料"

        # --- [功能 5] 板塊資訊 ---
        sector = "其他/未分類"
        try:
            sec = ticker.info.get('sector')
            if sec: sector = sec
        except Exception:
            pass

        # 趨勢評分 (滿分 6 分)
        score = 0
        if current_price > float(curr['MA150']) and current_price > float(curr['MA200']): score += 1
        if float(curr['MA150']) > float(curr['MA200']): score += 1
        if float(curr['MA200']) > float(prev_22['MA200']): score += 1
        if float(curr['MA50']) > float(curr['MA150']): score += 1
        if pct_above_low >= 25.0: score += 1
        if pct_below_high <= 25.0: score += 1

        # VCP 收斂判斷
        w1 = df.tail(60); d1 = (w1['High'].max() - w1['Low'].min()) / w1['High'].max()
        w2 = df.tail(30); d2 = (w2['High'].max() - w2['Low'].min()) / w2['High'].max()
        w3 = df.tail(10); d3 = (w3['High'].max() - w3['Low'].min()) / w3['High'].max()
        vcp_tight = (d1 > d2 and d2 > d3)

        # 停損與部位
        atr_value = float(curr['ATR'])
        stop_loss = max(0.01, current_price - (atr_value * 1.5))
        risk_per_share = current_price - stop_loss
        suggested_shares = int(risk_budget // risk_per_share) if risk_per_share > 0 else 0

        # [功能 4] 樞紐高點
        pivot_price = find_auto_pivot(df)

        # 建議行動判斷 (含財報避雷強制降級)
        action = "觀察中"
        if score >= 5 and vcp_tight:
            if d3 < 0.15:
                # 突破昨高或突破樞紐
                if current_price > float(prev_day['High']):
                    action = "🔥 立即買入 (Buy)"
                else:
                    action = "🚀 準備突破 (Ready)"
            else:
                action = "⌛ 等待進一步收斂"
        elif score >= 4:
            action = "📈 趨勢尚可"
        else:
            action = "🚫 趨勢偏弱"

        # 財報地雷懲罰機制
        if 0 <= days_to_earnings <= 10 and "買入" in action:
            action = f"⚠️ 避開財報 (倒數{days_to_earnings}天)"

        return {
            "代碼": symbol,
            "板塊": sector,
            "最新價": round(current_price, 2),
            "漲跌幅 (%)": round(change_pct, 2),
            "量能倍數": round(vol_multiple, 2),
            "RS狀態": rs_status,
            "財報預警": earnings_warning,
            "趨勢分數": f"{score}/6",
            "距52W高點": round(pct_below_high, 1),
            "VCP狀態": "✅ 正在收斂" if vcp_tight else "❌ 波動較大",
            "建議行動": action,
            "樞紐高點": round(pivot_price, 2),
            "建議停損": round(stop_loss, 2),
            "建議股數": suggested_shares,
            "預估總值": round(suggested_shares * current_price, 2)
        }
    except Exception:
        return None

# --- [功能 3] 個股歷史訊號「微回測引擎」 (Micro-Backtester) ---
def run_micro_backtest(df):
    """
    對指定個股進行近 2 年 VCP 突破回測：
    進場：Close > 50MA > 150MA 且 當日 High 突破昨日 High
    停損：進場價 - 1.5 * ATR
    停利：風險報酬比 2.5:1 或持倉滿 15 天出場
    """
    if len(df) < 100:
        return None
    
    df = df.copy()
    df['MA50'] = ta.sma(df['Close'], 50)
    df['MA150'] = ta.sma(df['Close'], 150)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], 14)
    df = df.dropna()

    trades = []
    in_pos = False
    entry_p, stop_p, target_p = 0, 0, 0
    days_held = 0

    for i in range(1, len(df)):
        curr_bar = df.iloc[i]
        prev_bar = df.iloc[i-1]

        if not in_pos:
            # 觸發條件
            if (curr_bar['Close'] > curr_bar['MA50'] > curr_bar['MA150']) and (curr_bar['High'] > prev_bar['High']):
                in_pos = True
                entry_p = float(prev_bar['High'])
                risk = float(curr_bar['ATR']) * 1.5
                stop_p = max(0.01, entry_p - risk)
                target_p = entry_p + (risk * 2.5)
                days_held = 0
        else:
            days_held += 1
            # 停損觸發
            if curr_bar['Low'] <= stop_p:
                pnl = (stop_p - entry_p) / entry_p
                trades.append(pnl)
                in_pos = False
            # 停利觸發
            elif curr_bar['High'] >= target_p:
                pnl = (target_p - entry_p) / entry_p
                trades.append(pnl)
                in_pos = False
            # 時間停損
            elif days_held >= 15:
                pnl = (curr_bar['Close'] - entry_p) / entry_p
                trades.append(pnl)
                in_pos = False

    if not trades:
        return None

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = (len(wins) / len(trades)) * 100
    gross_profits = sum(wins)
    gross_losses = abs(sum(losses)) if abs(sum(losses)) > 0 else 0.001
    profit_factor = gross_profits / gross_losses

    return {
        "總交易次數": len(trades),
        "歷史勝率 (%)": round(win_rate, 1),
        "盈虧比 (Profit Factor)": round(profit_factor, 2),
        "平均報酬 (%)": round(np.mean(trades) * 100, 2),
        "最大單筆獲利 (%)": round(max(trades) * 100, 2),
        "最大單筆虧損 (%)": round(min(trades) * 100, 2)
    }

# --- 繪製 K 線圖 + [功能 4] 自動樞紐突破線 ---
def plot_stock_chart(symbol, stop_price, pivot_price):
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="8mo", interval="1d", auto_adjust=True)
    if df.empty:
        st.error("無法加載該標的 K 線圖。")
        return df

    df['MA20'] = ta.sma(df['Close'], 20)
    df['MA50'] = ta.sma(df['Close'], 50)
    df['MA200'] = ta.sma(df['Close'], 200)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.75, 0.25]
    )

    # 主圖 K 線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K線", increasing_line_color="#00e676", decreasing_line_color="#ff5252"
    ), row=1, col=1)

    # 均線系統
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#ffea00', width=1.2), name="20 MA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='#2979ff', width=1.5), name="50 MA"), row=1, col=1)
    if df['MA200'].dropna().shape[0] > 0:
        fig.add_trace(go.Scatter(x=df.index, y=df['MA200'], line=dict(color='#d500f9', width=1.8), name="200 MA"), row=1, col=1)

    # [功能 4] 自動樞紐突破線 (橘色點虛線)
    if pivot_price:
        fig.add_hline(
            y=pivot_price, line_dash="dashdot", line_color="#ff9100", line_width=2,
            annotation_text=f"🔑 Pivot 樞紐位: ${pivot_price:.2f}",
            annotation_position="top right", row=1, col=1
        )

    # 停損線 (紅色虛線)
    if stop_price:
        fig.add_hline(
            y=stop_price, line_dash="dash", line_color="#ff1744", line_width=1.5,
            annotation_text=f"🛑 建議停損: ${stop_price:.2f}",
            annotation_position="bottom right", row=1, col=1
        )

    # 副圖：量能
    bar_colors = ['#00e676' if c >= o else '#ff5252' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=bar_colors, name="成交量"), row=2, col=1)

    fig.update_layout(
        title=f"📈 {symbol} 技術結構 (含 Minervini Cheating Pivot 與 ATR 停損)",
        xaxis_rangeslider_visible=False,
        height=540,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_dark"
    )
    st.plotly_chart(fig, use_container_width=True)
    return df

# --- 主程式掃描觸發 ---
if st.button("🚀 開始全維度深度掃描") or enable_autorefresh:
    with st.spinner("同步全球即時行情、計算 RS 強度與掃描財報中..."):
        results = [res for s in tickers if (res := analyze_stock(s, account_capital, max_risk_amount, spy_df))]

    if results:
        final_df = pd.DataFrame(results)
        
        # --- [功能 5] 板塊集團效應 (Sector Breadth) 展示 ---
        st.subheader("🏢 板塊集團動能 (Sector Breadth)")
        sector_group = final_df.groupby('板塊').agg(
            總數=('代碼', 'count'),
            強勢數=('趨勢分數', lambda x: sum(int(str(s).split('/')[0]) >= 5 for s in x)),
            突圍數=('RS狀態', lambda x: sum("RS" in str(s) for s in x))
        ).reset_index()
        sector_group['多頭佔比'] = (sector_group['強勢數'] / sector_group['總數']) * 100

        sec_cols = st.columns(min(len(sector_group), 4))
        for idx, row in sector_group.iterrows():
            with sec_cols[idx % 4]:
                st.metric(
                    label=f"板塊: {row['板塊']}",
                    value=f"{row['多頭佔比']:.0f}% 多頭",
                    delta=f"{row['強勢數']}/{row['總數']} 檔符合強勢"
                )

        st.divider()

        # --- 綜合報表展示 ---
        st.subheader("📊 專業篩選矩陣 (自動排序)")
        final_df = final_df.sort_values(by=['建議行動', '距52W高點'], ascending=[False, True])

        def highlight_row(row):
            if "立即買入" in str(row['建議行動']): return ['background-color: #4a1515; color: white'] * len(row)
            elif "準備突破" in str(row['建議行動']): return ['background-color: #1b3d22; color: white'] * len(row)
            elif "避開財報" in str(row['建議行動']): return ['background-color: #4a3c15; color: white'] * len(row)
            return [''] * len(row)

        def style_rs(val):
            if "RS 領先突圍" in str(val): return 'color: #00e5ff; font-weight: bold;'
            elif "RS 雙創新高" in str(val): return 'color: #76ff03; font-weight: bold;'
            return ''

        styled_df = (
            final_df.style
            .apply(highlight_row, axis=1)
            .map(style_rs, subset=['RS狀態'])
            .format({
                "最新價": "${:.2f}", "漲跌幅 (%)": "{:+.2f}%", "量能倍數": "{:.2f}x",
                "距52W高點": "-{:.1f}%", "樞紐高點": "${:.2f}", "建議停損": "${:.2f}",
                "建議股數": "{:,} 股", "預估總值": "${:,.2f}"
            })
        )
        st.dataframe(styled_df, use_container_width=True)

        # --- [功能 3 & 4] K 線視覺確認與微回測引擎 ---
        st.divider()
        st.subheader("🔬 標的型態二次確認與量化微回測")

        buy_stocks = final_df[final_df['建議行動'].str.contains("立即買入")]['代碼'].tolist()
        default_pick = buy_stocks[0] if buy_stocks else final_df['代碼'].iloc[0]

        selected_symbol = st.selectbox(
            "選擇要深入驗證的個股：", final_df['代碼'].tolist(),
            index=final_df['代碼'].tolist().index(default_pick)
        )

        matched_row = final_df[final_df['代碼'] == selected_symbol].iloc[0]
        
        # 繪製圖表 (疊加 Pivot 線)
        stock_history_df = plot_stock_chart(selected_symbol, matched_row['建議停損'], matched_row['樞紐高點'])

        # 執行微回測
        st.markdown(f"#### 🧪 {selected_symbol} 過去 2 年動能突破策略微回測 (Micro-Backtest)")
        if stock_history_df is not None and not stock_history_df.empty:
            bt_results = run_micro_backtest(stock_history_df)
            if bt_results:
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("總樣本交易次數", f"{bt_results['總交易次數']} 次")
                c2.metric("歷史勝率 (Win Rate)", f"{bt_results['歷史勝率 (%)']}%")
                c3.metric("盈虧比 (Profit Factor)", f"{bt_results['盈虧比 (Profit Factor)']}")
                c4.metric("平均每筆報酬", f"{bt_results['平均報酬 (%)']}%")
                c5.metric("最大獲利 / 最大虧損", f"{bt_results['最大單筆獲利 (%)']}% / {bt_results['最大單筆虧損 (%)']}%")
            else:
                st.info("該標的在過去 2 年內樣本訊號不足（可能因處於長期盤整或上市時間較短）。")
    else:
        st.error("未能獲取有效分析數據，請檢查代碼或網路連線。")
