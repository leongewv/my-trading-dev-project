# File: stock_analyzer_ui.py

import yfinance as yf
import pandas_ta as ta
import pandas as pd
import streamlit as st
import numpy as np
import time

# --- Analysis Functions ---

def get_data(ticker, period="2y", interval="1d"):
    """Fetches and prepares data."""
    if interval != "1d": period = "60d"
    data = yf.Ticker(ticker).history(period=period, interval=interval)
    if data.empty or len(data) < 200: return None
    
    data.ta.ema(length=200, append=True)
    data.ta.bbands(length=20, append=True)
    data['BB_WIDTH'] = (data['BBU_20_2.0'] - data['BBL_20_2.0']) / data['BBM_20_2.0']
    data = data.round(4)
    return data

def analyze_signal(df):
    """Analyzes a dataframe for signals with multiple contextual checks."""
    lookback_period = 120
    squeeze_percentile = 0.20

    if df is None or len(df) < lookback_period: return "Insufficient Data"

    latest = df.iloc[-1]
    previous = df.iloc[-2]
    middle_bb = latest['BBM_20_2.0']
    ema_200 = latest['EMA_200']
    if pd.isna(middle_bb) or pd.isna(ema_200) or pd.isna(previous['BB_WIDTH']):
        return "Insufficient Data"

    # --- Condition 1: Primary Crossover Trend ---
    crossover_signal = "Hold"
    if middle_bb > ema_200: crossover_signal = "Buy"
    elif middle_bb < ema_200: crossover_signal = "Sell"

    # --- Squeeze Calculation ---
    historical_bandwidth = df['BB_WIDTH'].iloc[-lookback_period:-1]
    if historical_bandwidth.count() < lookback_period - 1: return crossover_signal
    squeeze_threshold = historical_bandwidth.quantile(squeeze_percentile)
    is_squeeze_today = latest['BB_WIDTH'] < squeeze_threshold
    is_squeeze_yesterday = previous['BB_WIDTH'] < squeeze_threshold

    # --- Strong Signal Check 1: Squeeze Breakout (NEW) ---
    if is_squeeze_yesterday and not is_squeeze_today:
        if crossover_signal == "Buy" and latest['Close'] > latest['BBU_20_2.0']:
            return "Strong Buy"
        if crossover_signal == "Sell" and latest['Close'] < latest['BBL_20_2.0']:
            return "Strong Sell"

    # --- Strong Signal Check 2: Squeeze Consolidation (Existing) ---
    if is_squeeze_today:
        # Context Check 2: Trend Slope
        context_check_2 = False
        trend_lookback = 60
        prices_for_trend = df.iloc[-trend_lookback:-1]
        time_index = np.arange(len(prices_for_trend))
        if crossover_signal == "Buy":
            slope, _ = np.polyfit(time_index, prices_for_trend['Low'], 1)
            if slope > 0: context_check_2 = True
        if crossover_signal == "Sell":
            slope, _ = np.polyfit(time_index, prices_for_trend['High'], 1)
            if slope < 0: context_check_2 = True
        
        # Context Check 3: Pullback to 200 EMA
        context_check_3 = False
        is_near_ema = abs(middle_bb - ema_200) / ema_200 < 0.03
        if is_near_ema:
            past_price_period = df['Close'].iloc[-80:-20]
            if crossover_signal == "Buy" and past_price_period.max() > ema_200 * 1.05: context_check_3 = True
            if crossover_signal == "Sell" and past_price_period.min() < ema_200 * 0.95: context_check_3 = True
        
        if context_check_2 or context_check_3:
            return "Strong Buy" if crossover_signal == "Buy" else "Strong Sell"

    # If no strong conditions are met, return the basic crossover signal
    return crossover_signal

# --- Streamlit User Interface ---
def run_streamlit_app():
    st.set_page_config(layout="wide")
    st.title("📈 Advanced Signal Screener")
    st.write("Identifies Consolidation and Breakout setups on the Daily, then confirms on the 30-minute chart.")
    
    st.subheader("Enter Tickers to Analyze")
    uploaded_file = st.file_uploader("Choose a .csv or .txt file.", type=["csv", "txt"])
    user_input = st.text_area("Or enter tickers manually")

    if st.button("Find Setups"):
        # ... logic to get tickers_to_analyze list ...
        tickers_to_analyze = []
        if uploaded_file is not None:
            if uploaded_file.name.endswith('.csv'):
                df_from_csv = pd.read_csv(uploaded_file)
                tickers_to_analyze = df_from_csv.iloc[:, 0].dropna().tolist()
            else:
                string_data = uploaded_file.getvalue().decode("utf-8")
                tickers_to_analyze = string_data.upper().replace(',', ' ').split()
            st.info(f"Loaded {len(tickers_to_analyze)} tickers from {uploaded_file.name}")
        elif user_input:
            tickers_to_analyze = user_input.upper().replace(',', ' ').split()

        if not tickers_to_analyze:
            st.warning("Please enter at least one ticker.")
        else:
            status_text = st.empty()
            results_list = []
            for i, ticker in enumerate(tickers_to_analyze):
                status_text.text(f"Analyzing {ticker}... ({i+1}/{len(tickers_to_analyze)})")
                
                daily_signal = analyze_signal(get_data(ticker=ticker, interval="1d"))
                
                final_signal = daily_signal
                confirmation_status = "N/A"
                
                if daily_signal in ["Strong Buy", "Strong Sell"]:
                    confirmed_signal = analyze_signal(get_data(ticker=ticker, interval="30m"))
                    
                    if (daily_signal == "Strong Buy" and confirmed_signal == "Strong Buy") or \
                       (daily_signal == "Strong Sell" and confirmed_signal == "Strong Sell"):
                        final_signal = "Super Strong Buy"
                        confirmation_status = "Pass"
                    else:
                        confirmation_status = "Fail"
                
                if final_signal.startswith("Super Strong") or final_signal.startswith("Strong"):
                    display_signal = final_signal
                else:
                    display_signal = "Hold for now"

                results_list.append({
                    "Instrument": ticker,
                    "Signal": display_signal,
                    "30m Confirmation": confirmation_status
                })
                time.sleep(1)
            
            status_text.success("Analysis Complete!")
            full_results_df = pd.DataFrame(results_list)
            actionable_df = full_results_df[full_results_df['Signal'] != 'Hold for now'].reset_index(drop=True)
            if not actionable_df.empty:
                st.dataframe(actionable_df, use_container_width=True)
            else:
                st.info("No 'Strong' or 'Super Strong' signals found among the analyzed instruments.")

if __name__ == "__main__":
    run_streamlit_app()