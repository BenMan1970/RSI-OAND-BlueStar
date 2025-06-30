# --- START OF FILE app.py ---

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import oanda_api_v20 as oanda
from oanda_api_v20 import API
import oanda_api_v20.endpoints.instruments as instruments
from scipy.signal import find_peaks

warnings.filterwarnings('ignore')

# --- Configuration de la page Streamlit ---
st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS (identique) ---
st.markdown("""<style> /* ... VOTRE CSS COMPLET ICI ... */ </style>""", unsafe_allow_html=True) # Masqué pour la lisibilité

# --- Accès aux secrets OANDA ---
try:
    OANDA_ACCOUNT_ID = st.secrets["oanda_account_id"]
    OANDA_ACCESS_TOKEN = st.secrets["oanda_access_token"]
    api_context = {
        "id": OANDA_ACCOUNT_ID,
        "token": OANDA_ACCESS_TOKEN
    }
except KeyError:
    st.error("🔑 Secrets OANDA non trouvés !")
    st.info("Veuillez ajouter votre ID de compte et token d'accès dans les 'Secrets' de l'application.")
    st.code('oanda_account_id = "..."\noanda_access_token = "..."')
    st.stop()


# --- Fonctions de calcul (RSI, Divergence) - Inchangées ---
def calculate_rsi(prices, period=10):
    # Cette fonction reste identique
    try:
        if prices is None or len(prices) < period + 1: return np.nan, None
        ohlc4 = (prices['Open'] + prices['High'] + prices['Low'] + prices['Close']) / 4
        delta = ohlc4.diff()
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        if len(gains.dropna()) < period or len(losses.dropna()) < period: return np.nan, None
        avg_gains = gains.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        avg_losses = losses.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        rs = avg_gains / avg_losses
        rs[avg_losses == 0] = np.inf
        rsi_series = 100.0 - (100.0 / (1.0 + rs))
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]): return np.nan, None
        return rsi_series.iloc[-1], rsi_series
    except Exception:
        return np.nan, None

def detect_divergence(price_data, rsi_series, lookback=30, peak_distance=5):
    # Cette fonction reste identique
    if rsi_series is None or len(price_data) < lookback: return "Aucune"
    recent_price = price_data.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]
    price_peaks_idx, _ = find_peaks(recent_price['High'], distance=peak_distance)
    if len(price_peaks_idx) >= 2 and recent_price['High'].iloc[price_peaks_idx[-1]] > recent_price['High'].iloc[price_peaks_idx[-2]] and recent_rsi.iloc[price_peaks_idx[-1]] < recent_rsi.iloc[price_peaks_idx[-2]]:
        return "Baissière"
    price_troughs_idx, _ = find_peaks(-recent_price['Low'], distance=peak_distance)
    if len(price_troughs_idx) >= 2 and recent_price['Low'].iloc[price_troughs_idx[-1]] < recent_price['Low'].iloc[price_troughs_idx[-2]] and recent_rsi.iloc[price_troughs_idx[-1]] > recent_rsi.iloc[price_troughs_idx[-2]]:
        return "Haussière"
    return "Aucune"

# --- MODIFIÉ: Nouvelle fonction pour récupérer les données depuis OANDA ---
@st.cache_data(ttl=600, show_spinner=False) # Cache de 10 minutes
def fetch_forex_data_oanda(pair, timeframe_key, context):
    try:
        api = API(access_token=context["token"], environment="practice") # "live" pour un compte réel
        instrument = pair.replace('/', '_')
        
        # Mapping des timeframes
        params = {
            'H1': {'granularity': 'H1', 'count': 100},
            'H4': {'granularity': 'H4', 'count': 100},
            'D1': {'granularity': 'D', 'count': 100},
            'W1': {'granularity': 'W', 'count': 100}
        }
        
        r = instruments.InstrumentsCandles(instrument=instrument, params=params[timeframe_key])
        api.request(r)
        
        # Traitement des données
        data_list = []
        for candle in r.response['candles']:
            data_list.append({
                'Time': candle['time'],
                'Open': float(candle['mid']['o']),
                'High': float(candle['mid']['h']),
                'Low': float(candle['mid']['l']),
                'Close': float(candle['mid']['c']),
                'Volume': int(candle['volume'])
            })
        
        if not data_list: return None
        
        df = pd.DataFrame(data_list)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df

    except Exception as e:
        # st.warning(f"Could not fetch data for {pair} ({timeframe_key}): {e}")
        return None

def format_rsi(value): return "N/A" if pd.isna(value) else f"{value:.2f}"
def get_rsi_class(value):
    if pd.isna(value): return "neutral-cell"
    elif value <= 20: return "oversold-cell"
    elif value >= 80: return "overbought-cell"
    return "neutral-cell"

# --- Constantes (inchangées) ---
FOREX_PAIRS = [ 'EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF' ]
TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D1', 'W1']

# --- Fonction principale d'analyse ---
def run_analysis_process(context):
    results_list = []
    total_calls = len(FOREX_PAIRS) * len(TIMEFRAMES_FETCH_KEYS)
    progress_widget = st.progress(0)
    status_widget = st.empty()
    call_count = 0

    for pair_name in FOREX_PAIRS:
        row_data = {'Devises': pair_name}
        for tf_key, tf_display_name in zip(TIMEFRAMES_FETCH_KEYS, TIMEFRAMES_DISPLAY):
            call_count += 1
            status_widget.text(f"Scanning: {pair_name} on {tf_display_name} ({call_count}/{total_calls})")
            
            data_ohlc = fetch_forex_data_oanda(pair_name, tf_key, context)
            
            rsi_value, rsi_series = calculate_rsi(data_ohlc, period=10)
            divergence_signal = "Aucune"
            if data_ohlc is not None and rsi_series is not None:
                divergence_signal = detect_divergence(data_ohlc, rsi_series)
            
            row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}
            progress_widget.progress(call_count / total_calls)

        results_list.append(row_data)

    st.session_state.results = results_list
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done = True
    status_widget.empty()
    progress_widget.empty()

# --- Interface Utilisateur ---
st.markdown('<h1 class="screener-header">⚡ Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button("🔄 Rescan All Forex Pairs", key="rescan_button", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

if 'scan_done' not in st.session_state or not st.session_state.scan_done:
    run_analysis_process(api_context)
    st.success(f"✅ Analysis complete! {len(FOREX_PAIRS)} pairs analyzed.")

if 'results' in st.session_state and st.session_state.results:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(f"""<div class="update-info">🔄 Last update: {last_scan_time_str} (Data from OANDA)</div>""", unsafe_allow_html=True)
    
    # Le reste de l'affichage (légende, tableau, stats) est identique et n'a pas besoin d'être modifié.
    # ...

# --- END OF FILE app.py ---
