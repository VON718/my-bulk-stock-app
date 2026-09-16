import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta

# 頁面配置
st.set_page_config(page_title="專業級美股清單掃描儀", layout="wide")
st.title("🚀 專業級美股清單掃描儀 (Buy Signal 版)")
st.markdown("本工具整合 **即時市價/盤前盤後報價**，自動偵測 **VCP 收斂** 與 **趨勢強度**。")

# 用戶輸入名單
raw_input = st.text_area("請輸入股票代碼 (用逗號或空格隔開)", value="NVDA, TSLA, AAPL, PLTR, AMD, MSFT, META, GOOGL", height=100)
tickers = [t.strip().upper() for t in raw_input.replace(',', ' ').split() if t.strip()]

def get_latest_price(ticker, fallback_price):
    """
    多層備援取得最即時成交價：
    1. fast_info.last_price (低延遲即時撮合價)
    2. 1分鐘 K 線 (含盤前盤後延長時段)
    3. 歷史日K收盤價兜底
    """
    # 方案 1: fast_info
    try:
        fast = ticker.fast_info
        price = getattr(fast, 'last_price', None) or getattr(fast, 'lastPrice', None)
        if price is None and hasattr(fast, 'get'):
            price = fast.get('last_price') or fast.get('lastPrice') or fast.get('regular_market_price')
        if price is not None and not pd.isna(price) and price > 0:
            return float(price)
    except Exception:
        pass

    # 方案 2: 抓取最新 1 分鐘即時分時數據 (涵蓋 prepost 延長交易時段)
    try:
        intra_df = ticker.history(period="1d", interval="1m", prepost=True)
        if not intra_df.empty and 'Close' in intra_df:
            latest_intra = intra_df['Close'].dropna()
            if not latest_intra.empty:
                return float(latest_intra.iloc[-1])
    except Exception:
        pass

    # 方案 3: 兜底歷史收盤價
    return float(fallback_price)

def analyze_stock(symbol):
    try:
        ticker = yf.Ticker(symbol)
        
        # 1. 抓取歷史數據（計算均線與趨勢指標）
        df = ticker.history(period="2y", interval="1d", auto_adjust=True)
        
        if df.empty or len(df) < 200:
            return None

        # 2. 技術指標計算
        df['MA50'] = ta.sma(df['Close'], length=50)
        df['MA150'] = ta.sma(df['Close'], length=150)
        df['MA200'] = ta.sma(df['Close'], length=200)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        df = df.dropna()
        if len(df) < 25:
            return None

        curr = df.iloc[-1]
        prev_day = df.iloc[-2]
        prev_22 = df.iloc[-22] 

        # 3. 獲取精準即時價
        current_price = get_latest_price(ticker, curr['Close'])
        
        # --- 趨勢評分 (0-4) ---
        score = 0
        if current_price > float(curr['MA150']) and current_price > float(curr['MA200']): score += 1
        if float(curr['MA150']) > float(curr['MA200']): score += 1
        if float(curr['MA200']) > float(prev_22['MA200']): score += 1
        if float(curr['MA50']) > float(curr['MA150']): score += 1
        
        # --- VCP 波動收斂偵測 ---
        w1 = df.tail(60); d1 = (w1['High'].max() - w1['Low'].min()) / w1['High'].max()
        w2 = df.tail(30); d2 = (w2['High'].max() - w2['Low'].min()) / w2['High'].max()
        w3 = df.tail(10); d3 = (w3['High'].max() - w3['Low'].min()) / w3['High'].max()
        
        vcp_signal = "✅ 正在收斂" if (d1 > d2 and d2 > d3) else "❌ 波動較大"
        
        # --- 買入訊號邏輯 (Buy Signal) ---
        action = "觀察中"
        if score == 4 and (d1 > d2 and d2 > d3):
            if d3 < 0.15:
                if current_price > float(prev_day['High']):
                    action = "🔥 立即買入 (Buy)"
                else:
                    action = "🚀 準備突破 (Ready)"
            else:
                action = "⌛ 等待進一步收斂"
        elif score >= 3:
            action = "📈 趨勢尚可"
        else:
            action = "🚫 趨勢過弱"

        # --- 停損與風險 ---
        atr_value = float(curr['ATR'])
        stop_loss = current_price - (atr_value * 1.5)
        risk_pct = (atr_value * 1.5 / current_price) * 100

        return {
            "代碼": symbol,
            "最新價": round(current_price, 2),
            "建議行動": action,
            "趨勢分數": score,
            "VCP狀態": vcp_signal,
            "波幅演變": f"{d1:.0%} > {d2:.0%} > {d3:.0%}",
            "建議停損價": round(stop_loss, 2),
            "單筆風險 (%)": round(risk_pct, 1),
            "量能乾涸": "是" if curr['Volume'] < df['Volume'].tail(20).mean() else "否"
        }
    except Exception as e:
        st.warning(f"分析 {symbol} 時發生錯誤: {e}")
        return None

# 執行按鈕
if st.button("開始深度分析清單"):
    if not tickers:
        st.warning("請先輸入代碼。")
    else:
        results = []
        progress_bar = st.progress(0)
        
        for i, t in enumerate(tickers):
            res = analyze_stock(t)
            if res:
                results.append(res)
            progress_bar.progress((i + 1) / len(tickers))
        
        if results:
            final_df = pd.DataFrame(results)
            final_df = final_df.sort_values(by=['趨勢分數', '最新價'], ascending=[False, False])
            
            st.subheader("📊 掃描報表")

            def highlight_action(row):
                if "立即買入" in str(row['建議行動']):
                    return ['background-color: #781d1d; color: white'] * len(row)
                elif "準備突破" in str(row['建議行動']):
                    return ['background-color: #1e3d20; color: white'] * len(row)
                return [''] * len(row)

            st.dataframe(
                final_df.style.apply(highlight_action, axis=1),
                use_container_width=True
            )
            st.info("💡 註：最新價已接入交易所即時報價機制（包含盤前/盤後交易時段最新撮合價）。")
        else:
            st.error("分析失敗，未能獲取任何有效數據。")
