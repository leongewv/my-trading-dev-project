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
    # NEW: Calculate the 14-day ATR
    data.ta.atr(length=14, append=True)
    
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

    # Condition 1: Primary Crossover Trend
    crossover_signal = "Hold"
    if middle_bb > ema_200: crossover_signal = "Buy"
    elif middle_bb < ema_200: crossover_signal = "Sell"

    # Squeeze Calculation
    historical_bandwidth = df['BB_WIDTH'].iloc[-lookback_period:-1]
    if historical_bandwidth.count() < lookback_period - 1: return crossover_signal
    squeeze_threshold = historical_bandwidth.quantile(squeeze_percentile)
    is_squeeze_today = latest['BB_WIDTH'] < squeeze_threshold
    is_squeeze_yesterday = previous['BB_WIDTH'] < squeeze_threshold

    # Strong Signal Check 1: Squeeze Breakout
    if is_squeeze_yesterday and not is_squeeze_today:
        if crossover_signal == "Buy" and latest['Close'] > latest['BBU_20_2.0']:
            return "Strong Buy"
        if crossover_signal == "Sell" and latest['Close'] < latest['BBL_20_2.0']:
            return "Strong Sell"

    # Strong Signal Check 2: Squeeze Consolidation
    if is_squeeze_today:
        context_check_2 = False # Trend Slope
        trend_lookback = 60
        prices_for_trend = df.iloc[-trend_lookback:-1]
        time_index = np.arange(len(prices_for_trend))
        if crossover_signal == "Buy":
            slope, _ = np.polyfit(time_index, prices_for_trend['Low'], 1)
            if slope > 0: context_check_2 = True
        if crossover_signal == "Sell":
            slope, _ = np.polyfit(time_index, prices_for_trend['High'], 1)
            if slope < 0: context_check_2 = True
        
        context_check_3 = False # Pullback to 200 EMA
        is_near_ema = abs(middle_bb - ema_200) / ema_200 < 0.03
        if is_near_ema:
            past_price_period = df['Close'].iloc[-80:-20]
            if crossover_signal == "Buy" and past_price_period.max() > ema_200 * 1.05: context_check_3 = True
            if crossover_signal == "Sell" and past_price_period.min() < ema_200 * 0.95: context_check_3 = True
        
        if context_check_2 or context_check_3:
            return "Strong Buy" if crossover_signal == "Buy" else "Strong Sell"

    return crossover_signal

# --- Risk Management Function ---
def calculate_stop_loss(daily_df, direction):
    """Calculates a stop loss based on the 200 EMA, swing points, and ATR."""
    latest_ema_200 = daily_df['EMA_200'].iloc[-1]
    # The default column name for a 14-period ATR from pandas-ta is 'ATRr_14'
    latest_atr = daily_df['ATRr_14'].iloc[-1]
    swing_lookback = 60
    
    if direction == "Buy":
        # UPDATED: Using ATR instead of a fixed percentage
        sl_ema = latest_ema_200 - latest_atr
        swing_low = daily_df['Low'].iloc[-swing_lookback:-1].min()
        return max(sl_ema, swing_low - latest_atr)
    elif direction == "Sell":
        # UPDATED: Using ATR instead of a fixed percentage
        sl_ema = latest_ema_200 + latest_atr
        swing_high = daily_df['High'].iloc[-swing_lookback:-1].max()
        return min(sl_ema, swing_high + latest_atr)
    return None

# --- Styling Function ---
def style_signals(val):
    """Applies CSS styling to the 'Signal' column."""
    if "Super Strong" in val:
        return 'color: blue; font-weight: bold;'
    return ''

# --- Streamlit User Interface ---
def run_streamlit_app():
    st.set_page_config(layout="wide")
    st.title("📈 High-Conviction Signal Screener")
    st.write("Displays 'Strong' (daily) and 'Super Strong' (daily + 30min) signals with ATR-based risk management.")
    
    st.subheader("Enter Tickers to Analyze")
    uploaded_file = st.file_uploader("Choose a .csv or .txt file.", type=["csv", "txt"])
    user_input = st.text_area("Or enter tickers manually")

    if st.button("Find Setups"):
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
                
                daily_df = get_data(ticker=ticker, interval="1d")
                daily_signal = analyze_signal(daily_df)
                
                final_signal = daily_signal
                confirmation_status = "N/A"
                entry_price = "N/A"
                stop_loss = "N/A"
                
                if daily_signal in ["Strong Buy", "Strong Sell"]:
                    intraday_df = get_data(ticker=ticker, interval="30m")
                    
                    if intraday_df is not None:
                        confirmed_signal = analyze_signal(intraday_df)
                        
                        if (daily_signal == "Strong Buy" and confirmed_signal == "Strong Buy"):
                            final_signal = "Super Strong Buy"
                            confirmation_status = "Pass"
                        elif (daily_signal == "Strong Sell" and confirmed_signal == "Strong Sell"):
                            final_signal = "Super Strong Sell"
                            confirmation_status = "Pass"
                        else:
                            confirmation_status = "Fail"
                        
                        direction = "Buy" if "Buy" in daily_signal else "Sell"
                        entry_price = f"{intraday_df['Close'].iloc[-1]:.4f}"
                        stop_loss_val = calculate_stop_loss(daily_df, direction)
                        stop_loss = f"{stop_loss_val:.4f}"
                    else:
                        confirmation_status = "30m Data Error"

                if final_signal.startswith("Super Strong") or final_signal.startswith("Strong"):
                    display_signal = final_signal
                else:
                    display_signal = "Hold for now"

                results_list.append({
                    "Instrument": ticker,
                    "Signal": display_signal,
                    "Entry Price": entry_price,
                    "Stop Loss": stop_loss,
                    "30m Confirmation": confirmation_status
                })
                time.sleep(1)
            
            status_text.success("Analysis Complete!")
            
            if results_list:
                full_results_df = pd.DataFrame(results_list)
                actionable_df = full_results_df[full_results_df['Signal'] != 'Hold for now'].reset_index(drop=True)

                if not actionable_df.empty:
                    styled_df = actionable_df.style.applymap(style_signals, subset=['Signal'])
                    st.dataframe(styled_df, use_container_width=True)
                else:
                    st.info("No 'Strong' or 'Super Strong' signals found.")
            else:
                st.info("No instruments were analyzed.")

if __name__ == "__main__":
    run_streamlit_app()