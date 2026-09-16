import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta

# 頁面配置
st.set_page_config(page_title="專業級美股清單掃描儀", layout="wide")
st.title("🚀 專業級美股清單掃描儀 (即時漲跌與量能版)")
st.markdown("本工具整合 **即時市價、當日漲跌幅、量能放大倍數** 與 **VCP 收斂突破**。")

# 用戶輸入名單
raw_input = st.text_area("請輸入股票代碼 (用逗號或空格隔開)", value="NVDA, TSLA, AAPL, PLTR, AMD, MSFT, META, GOOGL", height=100)
tickers = [t.strip().upper() for t in raw_input.replace(',', ' ').split() if t.strip()]

def get_latest_market_data(ticker, fallback_price, fallback_vol):
    """
    從 fast_info 與即時線獲取：最新價、昨收價、今日即時量
    """
    latest_price = None
    prev_close = None
    today_volume = None

    try:
        fast = ticker.fast_info
        # 1. 價格
        p = getattr(fast, 'last_price', None) or getattr(fast, 'lastPrice', None)
        if p is not None and not pd.isna(p) and p > 0:
            latest_price = float(p)
        
        # 2. 昨收價
        pc = getattr(fast, 'previous_close', None) or getattr(fast, 'previousClose', None)
        if pc is not None and not pd.isna(pc) and pc > 0:
            prev_close = float(pc)
            
        # 3. 今日即時成交量
        vol = getattr(fast, 'last_volume', None) or getattr(fast, 'lastVolume', None)
        if vol is not None and not pd.isna(vol) and vol > 0:
            today_volume = float(vol)
    except Exception:
        pass

    # 備援機制 (Fallback)
    if latest_price is None:
        try:
            intra_df = ticker.history(period="1d", interval="1m", prepost=True)
            if not intra_df.empty and 'Close' in intra_df:
                latest_price = float(intra_df['Close'].dropna().iloc[-1])
        except Exception:
            latest_price = float(fallback_price)

    if latest_price is None:
        latest_price = float(fallback_price)
    if today_volume is None:
        today_volume = float(fallback_vol)

    return latest_price, prev_close, today_volume

def analyze_stock(symbol):
    try:
        ticker = yf.Ticker(symbol)
        
        # 1. 下載歷史數據 (2 年日 K)
        df = ticker.history(period="2y", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 200:
            return None

        # 2. 計算技術指標
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

        # 3. 獲取最即時市場數據
        current_price, prev_close, current_vol = get_latest_market_data(
            ticker, 
            fallback_price=curr['Close'], 
            fallback_vol=curr['Volume']
        )
        
        # 若未抓到 fast_info 的昨收，以日 K 前一日收盤價替代
        if prev_close is None:
            prev_close = float(prev_day['Close'])

        # --- 計算漲跌幅與成交量倍數 ---
        change_pct = ((current_price - prev_close) / prev_close) * 100
        
        # 前 20 日平均成交量（排除未收盤的當日，避免稀釋基準）
        avg_vol_20 = float(df['Volume'].iloc[-21:-1].mean()) if len(df) >= 21 else float(df['Volume'].mean())
        vol_multiple = (current_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

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
        
        # --- 買入訊號判斷 ---
        action = "觀察中"
        if score == 4 and (d1 > d2 and d2 > d3):
            if d3 < 0.15:
                # 需突破昨日高點，且若伴隨放量 (>= 1.2x) 尤佳
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

        # --- 停損與風險評估 ---
        atr_value = float(curr['ATR'])
        stop_loss = current_price - (atr_value * 1.5)
        risk_pct = (atr_value * 1.5 / current_price) * 100

        return {
            "代碼": symbol,
            "最新價": round(current_price, 2),
            "當日漲跌幅 (%)": round(change_pct, 2),
            "量能倍數": round(vol_multiple, 2),
            "建議行動": action,
            "趨勢分數": score,
            "VCP狀態": vcp_signal,
            "波幅演變": f"{d1:.0%} > {d2:.0%} > {d3:.0%}",
            "建議停損價": round(stop_loss, 2),
            "單筆風險 (%)": round(risk_pct, 1)
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
            # 優先按訊號強度、趨勢分數與量能倍數排序
            final_df = final_df.sort_values(by=['趨勢分數', '量能倍數'], ascending=[False, False])
            
            st.subheader("📊 掃描報表")

            # 美股風格高亮：綠漲紅跌，放量醒目
            def style_metrics(val):
                if isinstance(val, (int, float)):
                    if val > 0:
                        return 'color: #00c853; font-weight: bold;' # 綠漲 (美股慣用)
                    elif val < 0:
                        return 'color: #ff5252; font-weight: bold;' # 紅跌
                return ''

            def highlight_volume(val):
                if isinstance(val, (int, float)) and val >= 1.5:
                    return 'background-color: #2e4a38; color: #a5d6a7; font-weight: bold;' # 放量大於1.5倍亮顯
                return ''

            styled_df = (
                final_df.style
                .map(style_metrics, subset=['當日漲跌幅 (%)'])
                .map(highlight_volume, subset=['量能倍數'])
                .format({
                    "最新價": "${:.2f}",
                    "當日漲跌幅 (%)": "{:+.2f}%",
                    "量能倍數": "{:.2f}x",
                    "建議停損價": "${:.2f}",
                    "單筆風險 (%)": "{:.1f}%"
                })
            )

            st.dataframe(styled_df, use_container_width=True)
            st.caption("說明：美股習慣綠漲紅跌。量能倍數 $\\ge 1.5\\times$ 表示放量突破（以深綠標註）。")
        else:
            st.error("分析失敗，未能獲取任何有效數據。")
