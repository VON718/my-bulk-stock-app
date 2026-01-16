import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta

# 頁面配置
st.set_page_config(page_title="美股清單深度分析", layout="wide")

st.title("📋 美股自選名單 - 深度掃描儀")
st.markdown("輸入你的心儀名單，系統將自動進行 **VCP 形態偵測**、**趨勢評分**與**動能掃描**。")

# 1. 用戶輸入名單
raw_input = st.text_area("請輸入股票代碼 (用逗號或空格隔開)", value="AAPL, NVDA, TSLA, PLTR, AMD, MSFT")

# 處理輸入字串
tickers = [t.strip().upper() for t in raw_input.replace(',', ' ').split() if t.strip()]

def analyze_vcp_and_trend(symbol):
    try:
        # 下載數據 (2年數據以計算200MA)
        df = yf.download(symbol, period="2y", progress=False)
        if df.empty: return None
        
        # 計算技術指標
        df['MA50'] = ta.sma(df['Close'], length=50)
        df['MA150'] = ta.sma(df['Close'], length=150)
        df['MA200'] = ta.sma(df['Close'], length=200)
        
        # 當前狀態
        curr = df.iloc[-1]
        prev_22 = df.iloc[-22] # 約一個月前
        
        # --- 趨勢評分 (Trend Template) ---
        score = 0
        if curr['Close'] > curr['MA150'] and curr['Close'] > curr['MA200']: score += 1
        if curr['MA150'] > curr['MA200']: score += 1
        if curr['MA200'] > prev_22['MA200']: score += 1
        if curr['MA50'] > curr['MA150']: score += 1
        
        # --- VCP 波動收斂偵測 ---
        # 計算最近三個波段的波幅 (Depth)
        w1 = df.tail(60); d1 = (w1['High'].max() - w1['Low'].min()) / w1['High'].max()
        w2 = df.tail(30); d2 = (w2['High'].max() - w2['Low'].min()) / w2['High'].max()
        w3 = df.tail(10); d3 = (w3['High'].max() - w3['Low'].min()) / w3['High'].max()
        
        vcp_status = "✅ 正在收斂" if (d1 > d2 and d2 > d3) else "❌ 波動大"
        vcp_pattern = f"{d1:.1%} > {d2:.1%} > {d3:.1%}"
        
        # --- 成交量乾涸 ---
        avg_vol = df['Volume'].tail(20).mean()
        vol_dry = "是" if curr['Volume'] < avg_vol else "否"

        return {
            "代碼": symbol,
            "最新價": round(float(curr['Close']), 2),
            "趨勢分數": f"{score}/4",
            "VCP狀態": vcp_status,
            "波幅演變 (60d > 30d > 10d)": vcp_pattern,
            "量能乾涸": vol_dry,
            "距離200MA": f"{((curr['Close'] / curr['MA200']) - 1):.1%}"
        }
    except:
        return None

# 2. 執行分析
if st.button("開始批量分析"):
    if not tickers:
        st.warning("請先輸入代碼")
    else:
        results = []
        progress_bar = st.progress(0)
        
        for i, t in enumerate(tickers):
            res = analyze_vcp_and_trend(t)
            if res:
                results.append(res)
            progress_bar.progress((i + 1) / len(tickers))
        
        # 3. 顯示結果表格
        if results:
            final_df = pd.DataFrame(results)
            
            # 亮點顯示：分數最高且符合 VCP 的股票
            st.subheader("🚀 分析結果摘要")
            
            # 使用 Dataframe 樣式
            def highlight_vcp(val):
                color = '#2ecc71' if '✅' in str(val) else 'white'
                return f'color: {color}'

            st.dataframe(final_df.style.applymap(highlight_vcp, subset=['VCP狀態']))
            
            # 導出 CSV
            csv = final_df.to_csv(index=False).encode('utf-8')
            st.download_button("下載分析報表 (CSV)", csv, "stock_analysis.csv", "text/csv")
        else:
            st.error("分析失敗，請檢查代碼是否輸入正確。")