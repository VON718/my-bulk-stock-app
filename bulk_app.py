def analyze_vcp_and_trend(symbol):
    try:
        df = yf.download(symbol, period="2y", progress=False)
        if df.empty: return None
        
        # ... 原有的指標計算 ...
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        curr = df.iloc[-1]
        atr_value = curr['ATR']
        current_price = curr['Close']

        # 專業停損邏輯：使用 1.5 倍 ATR 作為初始停損
        # 這是為了確保停損位設在「市場正常噪音」之外
        stop_loss = current_price - (atr_value * 1.5)
        risk_percent = (atr_value * 1.5 / current_price)

        return {
            "代碼": symbol,
            "最新價": round(float(current_price), 2),
            "趨勢分數": f"{score}/4",
            "VCP狀態": vcp_status,
            "量能乾涸": vol_dry,
            "建議停損價": f"${stop_loss:.2f}",
            "單筆風險": f"{risk_percent:.1%}"
        }
