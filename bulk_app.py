import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# 嘗試載入自動刷新套件
try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False

# 頁面配置
st.set_page_config(page_title="專業級美股清單掃描儀", layout="wide")

# 初始化已推播標的紀錄（避免每分鐘重複通知）
if "alerted_stocks" not in st.session_state:
    st.session_state.alerted_stocks = set()

# --- 側邊欄配置 ---
with st.sidebar:
    st.header("⚙️ 系統與風控設定")
    
    # 1. 資金管理
    account_capital = st.number_input("帳戶總本金 (USD)", min_value=1000, value=50000, step=5000)
    risk_pct = st.slider("單筆最大承受風險 (%)", min_value=0.25, max_value=3.0, value=1.0, step=0.25)
    max_risk_amount = account_capital * (risk_pct / 100.0)
    st.caption(f"🛡️ 單筆最大可承擔虧損：**${max_risk_amount:,.2f}**")
    
    st.divider()
    
    # 2. 盤中自動輪詢
    st.subheader("🔄 盤中定時輪詢")
    enable_autorefresh = st.checkbox("啟用自動定時掃描", value=False)
    refresh_interval = st.selectbox("輪詢間隔時間", [60, 180, 300, 600], index=1, format_func=lambda x: f"{x} 秒")
    if enable_autorefresh and AUTOREFRESH_AVAILABLE:
        st_autorefresh(interval=refresh_interval * 1000, key="datarefresh")
    elif enable_autorefresh and not AUTOREFRESH_AVAILABLE:
        st.warning("尚未安裝 streamlit-autorefresh，請執行 `pip install streamlit-autorefresh`。")
        
    st.divider()

    # 3. Webhook 即時通知 (以 Discord 為例)
    st.subheader("📢 即時推播 (Discord)")
    discord_webhook_url = st.text_input("Discord Webhook URL", type="password", placeholder="https://discord.com/api/webhooks/...")
    st.caption("觸發條件：突破昨日高點 且 成交量放大倍數 ≥ 1.5x")

# --- 核心功能 1: 大盤環境過濾器 ---
def check_market_regime():
    try:
        spy = yf.Ticker("SPY").history(period="1y", interval="1d", auto_adjust=True)
        qqq = yf.Ticker("QQQ").history(period="1y", interval="1d", auto_adjust=True)
        
        if spy.empty or qqq.empty:
            return None
            
        spy_c, qqq_c = spy['Close'].iloc[-1], qqq['Close'].iloc[-1]
        spy_ma50, spy_ma200 = ta.sma(spy['Close'], 50).iloc[-1], ta.sma(spy['Close'], 200).iloc[-1]
        qqq_ma50, qqq_ma200 = ta.sma(qqq['Close'], 50).iloc[-1], ta.sma(qqq['Close'], 200).iloc[-1]
        
        # 評估狀態
        bullish = (spy_c > spy_ma50 > spy_ma200) and (qqq_c > qqq_ma50 > qqq_ma200)
        bearish = (spy_c < spy_ma200) or (qqq_c < qqq_ma200)
        
        return {
            "bullish": bullish,
            "bearish": bearish,
            "spy_price": spy_c, "spy_ma50": spy_ma50, "spy_ma200": spy_ma200,
            "qqq_price": qqq_c, "qqq_ma50": qqq_ma50, "qqq_ma200": qqq_ma200
        }
    except Exception:
        return None

# 頂部大盤信號展示
regime = check_market_regime()
if regime:
    if regime["bullish"]:
        st.success("🟢 **大盤信號：強勢多頭 (Risk-On)** ｜ SPY 與 QQQ 均站上 50MA 與 200MA，多頭突破勝率最高，可積極做多。")
    elif regime["bearish"]:
        st.error("🔴 **大盤信號：空頭修正警戒 (Risk-Off)** ｜ 指數跌破關鍵 200MA 年線，系統性風險上升，建議嚴控部位或空倉觀望！")
    else:
        st.warning("🟡 **大盤信號：震盪整理期 (Caution)** ｜ 指數跌破 50MA 或兩大指數步調不一，操作以縮減持倉、防守停損為主。")

st.title("🚀 專業級美股清單掃描儀")

# 輸入清單
raw_input = st.text_area("請輸入股票代碼 (逗號或空格隔開)", value="NVDA, TSLA, AAPL, PLTR, AMD, MSFT, META, GOOGL", height=70)
tickers = [t.strip().upper() for t in raw_input.replace(',', ' ').split() if t.strip()]

# --- 核心功能 2: Webhook 發送函式 ---
def send_webhook_alert(url, symbol, price, vol_mult, stop_price):
    if not url:
        return
    msg = {
        "embeds": [{
            "title": f"🔥 美股突破訊號觸發: {symbol}",
            "color": 3066993,
            "fields": [
                {"name": "即時現價", "value": f"${price:.2f}", "inline": True},
                {"name": "成交量倍數", "value": f"{vol_mult:.2f}x (放量)", "inline": True},
                {"name": "建議停損價", "value": f"${stop_price:.2f}", "inline": True},
                {"name": "形態狀態", "value": "VCP 深度收斂後突破昨高", "inline": False}
            ]
        }]
    }
    try:
        requests.post(url, json=msg, timeout=3)
    except Exception:
        pass

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

def analyze_stock(symbol, capital, risk_budget):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 200: return None

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

        # Minervini 52 週判斷
        past_year = df.tail(252)
        high_52w, low_52w = float(past_year['High'].max()), float(past_year['Low'].min())
        pct_above_low = ((current_price - low_52w) / low_52w) * 100
        pct_below_high = ((high_52w - current_price) / high_52w) * 100

        score = 0
        if current_price > float(curr['MA150']) and current_price > float(curr['MA200']): score += 1
        if float(curr['MA150']) > float(curr['MA200']): score += 1
        if float(curr['MA200']) > float(prev_22['MA200']): score += 1
        if float(curr['MA50']) > float(curr['MA150']): score += 1
        if pct_above_low >= 25.0: score += 1
        if pct_below_high <= 25.0: score += 1

        # VCP 收斂
        w1 = df.tail(60); d1 = (w1['High'].max() - w1['Low'].min()) / w1['High'].max()
        w2 = df.tail(30); d2 = (w2['High'].max() - w2['Low'].min()) / w2['High'].max()
        w3 = df.tail(10); d3 = (w3['High'].max() - w3['Low'].min()) / w3['High'].max()
        vcp_tight = (d1 > d2 and d2 > d3)

        atr_value = float(curr['ATR'])
        stop_loss = max(0.01, current_price - (atr_value * 1.5))
        risk_per_share = current_price - stop_loss
        shares = int(risk_budget // risk_per_share) if risk_per_share > 0 else 0

        action = "觀察中"
        if score >= 5 and vcp_tight:
            if d3 < 0.15:
                if current_price > float(prev_day['High']):
                    action = "🔥 立即買入 (Buy)"
                    # 若符合突破且顯著放量，觸發推播
                    if vol_multiple >= 1.5 and symbol not in st.session_state.alerted_stocks:
                        send_webhook_alert(discord_webhook_url, symbol, current_price, vol_multiple, stop_loss)
                        st.session_state.alerted_stocks.add(symbol)
                else:
                    action = "🚀 準備突破 (Ready)"
            else:
                action = "⌛ 等待進一步收斂"
        elif score >= 4:
            action = "📈 趨勢尚可"
        else:
            action = "🚫 趨勢偏弱"

        return {
            "代碼": symbol,
            "最新價": round(current_price, 2),
            "漲跌幅 (%)": round(change_pct, 2),
            "量能倍數": round(vol_multiple, 2),
            "趨勢分數": f"{score}/6",
            "距52W高點": round(pct_below_high, 1),
            "VCP狀態": "✅ 正在收斂" if vcp_tight else "❌ 波動較大",
            "建議行動": action,
            "建議停損": round(stop_loss, 2),
            "建議股數": shares,
            "預估總值": round(shares * current_price, 2)
        }
    except Exception:
        return None

# --- 核心功能 3: Plotly 互動式 K 線圖 ---
def plot_stock_chart(symbol, stop_price=None):
    df = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=True)
    if df.empty:
        st.error("無法取得圖表資料。")
        return

    df['MA20'] = ta.sma(df['Close'], length=20)
    df['MA50'] = ta.sma(df['Close'], length=50)
    df['MA200'] = ta.sma(df['Close'], length=200)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.04, row_heights=[0.75, 0.25]
    )

    # 主圖：K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K線", increasing_line_color="#00e676", decreasing_line_color="#ff5252"
    ), row=1, col=1)

    # 均線疊加
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#ffea00', width=1.2), name="20 MA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='#2979ff', width=1.5), name="50 MA"), row=1, col=1)
    if df['MA200'].dropna().shape[0] > 0:
        fig.add_trace(go.Scatter(x=df.index, y=df['MA200'], line=dict(color='#d500f9', width=1.8), name="200 MA"), row=1, col=1)

    # 建議停損線
    if stop_price:
        fig.add_hline(y=stop_price, line_dash="dash", line_color="#ff1744",
                      annotation_text=f"停損價 ${stop_price:.2f}", row=1, col=1)

    # 副圖：成交量柱狀圖
    colors = ['#00e676' if c >= o else '#ff5252' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name="成交量"), row=2, col=1)

    fig.update_layout(
        title=f"📈 {symbol} 互動式技術圖表 (疊加均線與停損位)",
        xaxis_rangeslider_visible=False,
        height=520,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_dark"
    )
    st.plotly_chart(fig, use_container_width=True)

# 執行掃描邏輯
if st.button("🚀 開始掃描清單") or enable_autorefresh:
    results = [res for s in tickers if (res := analyze_stock(s, account_capital, max_risk_amount))]
    
    if results:
        df_res = pd.DataFrame(results).sort_values(by=['建議行動', '距52W高點'], ascending=[False, True])
        
        st.subheader("📊 掃描報表")
        
        def highlight_row(row):
            if "立即買入" in str(row['建議行動']): return ['background-color: #4a1515; color: white'] * len(row)
            elif "準備突破" in str(row['建議行動']): return ['background-color: #1b3d22; color: white'] * len(row)
            return [''] * len(row)

        st.dataframe(
            df_res.style.apply(highlight_row, axis=1).format({
                "最新價": "${:.2f}", "漲跌幅 (%)": "{:+.2f}%", "量能倍數": "{:.2f}x",
                "距52W高點": "-{:.1f}%", "建議停損": "${:.2f}", "建議股數": "{:,} 股", "預估總值": "${:,.2f}"
            }),
            use_container_width=True
        )

        # --- 底部圖表二次確認區 ---
        st.divider()
        st.subheader("🔍 圖表二次視覺確認")
        
        # 預設優先選中「🔥 立即買入」或清單第一檔
        buy_candidates = df_res[df_res['建議行動'].str.contains("立即買入")]['代碼'].tolist()
        default_symbol = buy_candidates[0] if buy_candidates else df_res['代碼'].iloc[0]
        
        selected_symbol = st.selectbox("選擇要檢視詳細形態的標的：", df_res['代碼'].tolist(), index=df_res['代碼'].tolist().index(default_symbol))
        
        # 取得對應停損價帶入圖表
        matched_stop = df_res[df_res['代碼'] == selected_symbol]['建議停損'].iloc[0]
        plot_stock_chart(selected_symbol, stop_price=matched_stop)
