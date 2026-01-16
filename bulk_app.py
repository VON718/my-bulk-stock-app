import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time

# 頁面配置
st.set_page_config(page_title="專業級美股清單掃描儀", layout="wide")

st.title("🚀 專業級美股清單掃描儀 (修復版)")
st.markdown("已修正 SyntaxError，並優化數據結構處理。")

# 1. 用戶輸入名單
raw_input = st.text_area("請輸入股票代碼 (用逗號或空格隔開)", value="NVDA, TSLA, AAPL, PLTR, AMD, MSFT, META, GOOGL", height=100)
tickers = [t.strip().upper() for t in raw_input.replace(',', ' ').split() if t.strip()]

def analyze_stock(symbol):
    try:
        # 下載數據
        df = yf.download(symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
        
        if df.empty or len(df) < 200:
            return None
        
        # 處理 yfinance 可能出現的 Multi-Index 欄位
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 計算技術指標
        df['MA50'] = ta.sma(df['Close'], length=50)
        df['MA150'] = ta.sma(df['Close'], length=150)
        df['MA200'] = ta.sma(df['Close'], length=200)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        curr = df.iloc[-1]
        prev_22 = df.iloc[-22] 
        
        # --- 趨勢評分 (0-4) ---
        score = 0
        if float(curr['Close']) > float(curr['MA150']) and float(curr['Close']) > float(curr['MA200']): score += 1
        if float(curr['MA150']) > float(curr['MA200']): score += 1
        if float(curr['MA200']) > float(prev_22['MA200']): score += 1
        if float(curr['MA50']) > float(curr['MA150']): score += 1
        
        # --- VCP 波動收斂偵測 ---
        w1 = df.tail(60); d1 = (w1['High'].max() - w1['Low'].min()) / w1['High'].max()
        w2 = df.tail(30); d2 = (w2['High'].max() - w2['Low'].min()) / w2['High'].max()
        w3 = df.tail(10); d3 = (w3['High'].max() - w3['Low'].min()) / w3['High'].max()
        
        vcp_signal = "✅ 正在收斂" if (d1 > d2 and d2 > d3) else "❌ 波動較大"
        
        # --- 停損與風險 ---
        current_price = float(curr['Close'])
        atr_value = float(curr['ATR'])
        stop_loss = current_price - (atr_value * 1.5)
        risk_pct = (atr_value * 1.5 / current_price) * 100

        return {
            "代碼": symbol,
            "最新價": round(current_price, 2),
            "趨勢分數": score,
            "VCP狀態": vcp_signal,
            "波幅演變": f"{d1:.0%} > {d2:.0%} > {d3:.0%}",
            "建議停損價": round(stop_loss, 2),
            "單筆風險 (%)": round(risk_pct, 1),
            "量能乾涸": "是" if curr['Volume'] < df['Volume'].tail(20).mean() else "否"
        }
    except Exception as e:
        # 這就是之前漏掉的 except 區塊
        st.error(f"分析 {symbol} 時發生錯誤: {e}")
        return None

# 2. 執行按鈕邏輯
if st.button("開始深度分析清單"):
    if not tickers:
        st.warning("請先輸入至少一個代碼。")
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
            # 排序：分數高（強勢）優先，風險低（穩健）優先
            final_df = final_df.sort_values(by=['趨勢分數', '單筆風險 (%)'], ascending=[False, True])
            
            st.subheader("📊 掃描報表 (自動排序)")
            st.dataframe(final_df, use_container_width=True)
        else:
            st.error("分析失敗，未能獲取任何有效數據。")
