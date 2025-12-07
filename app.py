# --- START OF FILE app.py ---
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from fpdf import FPDF
import concurrent.futures
warnings.filterwarnings('ignore')

st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 28px; font-weight: bold; color: #FAFAFA; margin-bottom: 15px; text-align: center; }
    .update-info { background-color: #262730; padding: 8px 15px; border-radius: 5px; margin-bottom: 20px; font-size: 14px; color: #A9A9A9; border: 1px solid #333A49; text-align: center; }
    .legend-container { display: flex; justify-content: center; flex-wrap: wrap; gap: 25px; margin: 25px 0; padding: 15px; border-radius: 5px; background-color: #1A1C22; }
    .legend-item { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #D3D3D3; }
    .legend-dot { width: 12px; height: 12px; border-radius: 50%; }
    .oversold-dot { background-color: #FF4B4B; }
    .overbought-dot { background-color: #3D9970; }
    h3 { color: #EAEAEA; text-align: center; margin-top: 30px; margin-bottom: 15px; }
    .rsi-table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; box-shadow: 0 4px 8px 0 rgba(0,0,0,0.1); }
    .rsi-table th { background-color: #333A49; color: #EAEAEA !important; padding: 14px 10px; text-align: center; font-weight: bold; font-size: 15px; border: 1px solid #262730; }
    .rsi-table td { padding: 12px 10px; text-align: center; border: 1px solid #262730; font-size: 14px; }
    .devises-cell { font-weight: bold !important; color: #E0E0E0 !important; font-size: 15px !important; text-align: left !important; padding-left: 15px !important; }
    .oversold-cell { background-color: rgba(255, 75, 75, 0.7) !important; color: white !important; font-weight: bold; }
    .overbought-cell { background-color: rgba(61, 153, 112, 0.7) !important; color: white !important; font-weight: bold; }
    .neutral-cell { color: #C0C0C0 !important; background-color: #161A1D; }
    .divergence-arrow { font-size: 20px; font-weight: bold; vertical-align: middle; margin-left: 6px; }
    .bullish-arrow { color: #3D9970; }
    .bearish-arrow { color: #FF4B4B; }
</style>
""", unsafe_allow_html=True)

try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except KeyError:
    st.error("🔑 Secrets OANDA non trouvés!")
    st.stop()

def calculate_rsi(prices, period=10):
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

@st.cache_data(ttl=600, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key):
    try:
        api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
        instrument = pair.replace('/', '_')
        params = {'granularity': {'H1':'H1', 'H4':'H4', 'D1':'D', 'W1':'W'}[timeframe_key], 'count': 100}
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        api.request(r)
        data_list = [{'Time':c['time'], 'Open':float(c['mid']['o']), 'High':float(c['mid']['h']), 'Low':float(c['mid']['l']), 'Close':float(c['mid']['c']), 'Volume':int(c['volume'])} for c in r.response['candles']]
        if not data_list: return None
        df = pd.DataFrame(data_list)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except Exception:
        return None

def format_rsi(value): 
    return "N/A" if pd.isna(value) else "{:.2f}".format(value)

def get_rsi_class(value):
    if pd.isna(value): return "neutral-cell"
    elif value <= 20: return "oversold-cell"
    elif value >= 80: return "overbought-cell"
    return "neutral-cell"

ASSETS = ['EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF', 'XAU/USD', 'XPT/USD', 'US30/USD', 'NAS100/USD', 'SPX500/USD']
TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D1', 'W1']

def run_analysis_process():
    results_list = []
    total_calls = len(ASSETS) * len(TIMEFRAMES_FETCH_KEYS)
    progress_widget = st.progress(0)
    status_widget = st.empty()
    call_count = 0
    for pair_name in ASSETS:
        row_data = {'Devises': pair_name}
        for tf_key, tf_display_name in zip(TIMEFRAMES_FETCH_KEYS, TIMEFRAMES_DISPLAY):
            call_count += 1
            status_widget.text("Scanning: {} on {} ({}/{})".format(pair_name, tf_display_name, call_count, total_calls))
            data_ohlc = fetch_forex_data_oanda(pair_name, tf_key)
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

def create_pdf_report(results_data, last_scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(0, 0, 0)
            self.cell(0, 10, 'RAPPORT RSI & DIVERGENCE - ANALYSE QUOTIDIENNE', 0, 1, 'C')
            self.set_font('Arial', '', 9)
            self.set_text_color(80, 80, 80)
            self.cell(0, 5, 'Genere le: ' + str(last_scan_time), 0, 1, 'C')
            self.ln(3)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(100, 100, 100)
            self.cell(0, 10, 'Page ' + str(self.page_no()) + ' | Source: OANDA v20 API', 0, 0, 'C')
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    color_header = (30, 60, 114)
    color_oversold = (220, 20, 60)
    color_overbought = (34, 139, 34)
    color_warning = (255, 140, 0)
    color_neutral = (245, 245, 245)
    color_text_dark = (20, 20, 20)
    
    # SECTION 1: RESUME EXECUTIF
    pdf.set_font('Arial', 'B', 13)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, ' RESUME EXECUTIF ', 0, 1, 'L', True)
    pdf.ln(2)
    
    all_rsi_values = []
    oversold_count = 0
    overbought_count = 0
    bull_div_count = 0
    bear_div_count = 0
    
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {})
            rsi = d.get('rsi', np.nan)
            div = d.get('divergence', 'Aucune')
            if pd.notna(rsi):
                all_rsi_values.append(rsi)
                if rsi <= 30: oversold_count += 1
                elif rsi >= 70: overbought_count += 1
            if div == 'Haussière': bull_div_count += 1
            elif div == 'Baissière': bear_div_count += 1
    
    avg_rsi = np.mean(all_rsi_values) if all_rsi_values else 50
    total_signals = oversold_count + overbought_count
    
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(70, 8, 'RSI MOYEN GLOBAL:', 0, 0, 'L')
    pdf.set_font('Arial', '', 10)
    
    if avg_rsi < 40:
        pdf.set_text_color(*color_oversold)
        market_bias = "BEARISH (survente)"
    elif avg_rsi > 60:
        pdf.set_text_color(*color_overbought)
        market_bias = "BULLISH (surachat)"
    else:
        pdf.set_text_color(*color_text_dark)
        market_bias = "NEUTRE"
    
    pdf.cell(0, 8, '{:.1f} - Biais marche: {}'.format(avg_rsi, market_bias), 0, 1, 'L')
    
    pdf.set_text_color(*color_text_dark)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(70, 6, 'TOTAL SIGNAUX ACTIFS:', 0, 0, 'L')
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, '{} ({} survente, {} surachat)'.format(total_signals, oversold_count, overbought_count), 0, 1, 'L')
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(70, 6, 'DIVERGENCES DETECTEES:', 0, 0, 'L')
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, '{} haussiere, {} baissiere'.format(bull_div_count, bear_div_count), 0, 1, 'L')
    pdf.ln(5)
    
    # SECTION 2: ANALYSE PAR TIMEFRAME
    pdf.set_font('Arial', 'B', 13)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, ' ANALYSE PAR TIMEFRAME ', 0, 1, 'L', True)
    pdf.ln(2)
    
    stats_by_tf = {}
    for tf in TIMEFRAMES_DISPLAY:
        tf_data = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        oversold = sum(1 for x in valid_rsi if x <= 30)
        overbought = sum(1 for x in valid_rsi if x >= 70)
        extreme_oversold = sum(1 for x in valid_rsi if x <= 20)
        extreme_overbought = sum(1 for x in valid_rsi if x >= 80)
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        avg = np.mean(valid_rsi) if valid_rsi else 50
        stats_by_tf[tf] = {
            'oversold': oversold, 'overbought': overbought,
            'extreme_os': extreme_oversold, 'extreme_ob': extreme_overbought,
            'bull_div': bull_div, 'bear_div': bear_div, 'avg': avg
        }
    
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    w = 35
    pdf.cell(w, 8, 'TF', 1, 0, 'C', True)
    pdf.cell(w, 8, 'RSI Moy', 1, 0, 'C', True)
    pdf.cell(w, 8, 'Survente', 1, 0, 'C', True)
    pdf.cell(w, 8, 'Surachat', 1, 0, 'C', True)
    pdf.cell(w, 8, 'Extreme <20', 1, 0, 'C', True)
    pdf.cell(w, 8, 'Extreme >80', 1, 0, 'C', True)
    pdf.cell(w, 8, 'Div.Bull', 1, 0, 'C', True)
    pdf.cell(w, 8, 'Div.Bear', 1, 1, 'C', True)
    
    pdf.set_font('Arial', '', 9)
    for tf, st in stats_by_tf.items():
        pdf.set_text_color(*color_text_dark)
        pdf.set_fill_color(*color_neutral)
        pdf.cell(w, 7, tf, 1, 0, 'C', True)
        
        if st['avg'] < 40:
            pdf.set_fill_color(255, 200, 200)
        elif st['avg'] > 60:
            pdf.set_fill_color(200, 255, 200)
        else:
            pdf.set_fill_color(*color_neutral)
        pdf.cell(w, 7, '{:.1f}'.format(st['avg']), 1, 0, 'C', True)
        
        pdf.set_fill_color(255, 220, 220) if st['oversold'] > 0 else pdf.set_fill_color(*color_neutral)
        pdf.cell(w, 7, str(st['oversold']), 1, 0, 'C', True)
        
        pdf.set_fill_color(220, 255, 220) if st['overbought'] > 0 else pdf.set_fill_color(*color_neutral)
        pdf.cell(w, 7, str(st['overbought']), 1, 0, 'C', True)
        
        if st['extreme_os'] > 0:
            pdf.set_fill_color(*color_oversold)
            pdf.set_text_color(255, 255, 255)
        else:
            pdf.set_fill_color(*color_neutral)
            pdf.set_text_color(*color_text_dark)
        pdf.cell(w, 7, str(st['extreme_os']), 1, 0, 'C', True)
        
        if st['extreme_ob'] > 0:
            pdf.set_fill_color(*color_overbought)
            pdf.set_text_color(255, 255, 255)
        else:
            pdf.set_fill_color(*color_neutral)
            pdf.set_text_color(*color_text_dark)
        pdf.cell(w, 7, str(st['extreme_ob']), 1, 0, 'C', True)
        
        pdf.set_fill_color(*color_neutral)
        pdf.set_text_color(*color_text_dark)
        pdf.cell(w, 7, str(st['bull_div']), 1, 0, 'C', True)
        pdf.cell(w, 7, str(st['bear_div']), 1, 1, 'C', True)
    
    pdf.ln(5)
    
    # SECTION 3: CONVERGENCE MULTI-TIMEFRAME
    pdf.set_font('Arial', 'B', 13)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, ' CONVERGENCES MULTI-TIMEFRAME (Score de force) ', 0, 1, 'L', True)
    pdf.ln(2)
    
    convergence_scores = []
    for row in results_data:
        oversold_tfs = []
        overbought_tfs = []
        for tf in TIMEFRAMES_DISPLAY:
            rsi = row.get(tf, {}).get('rsi', np.nan)
            if pd.notna(rsi):
                if rsi <= 30: oversold_tfs.append(tf)
                elif rsi >= 70: overbought_tfs.append(tf)
        
        if len(oversold_tfs) >= 2:
            convergence_scores.append({
                'asset': row['Devises'],
                'type': 'SURVENTE',
                'tfs': ', '.join(oversold_tfs),
                'score': len(oversold_tfs)
            })
        elif len(overbought_tfs) >= 2:
            convergence_scores.append({
                'asset': row['Devises'],
                'type': 'SURACHAT',
                'tfs': ', '.join(overbought_tfs),
                'score': len(overbought_tfs)
            })
    
    convergence_scores.sort(key=lambda x: -x['score'])
    
    if convergence_scores:
        pdf.set_font('Arial', '', 9)
        pdf.set_text_color(*color_text_dark)
        pdf.cell(0, 5, 'Actifs montrant des signaux concordants sur plusieurs timeframes:', 0, 1, 'L')
        pdf.ln(1)
        
        for conv in convergence_scores[:10]:
            if conv['type'] == 'SURVENTE':
                pdf.set_fill_color(255, 200, 200)
            else:
                pdf.set_fill_color(200, 255, 200)
            
            pdf.cell(50, 6, conv['asset'], 1, 0, 'L', True)
            pdf.cell(35, 6, conv['type'], 1, 0, 'C', True)
            pdf.cell(80, 6, 'TF: ' + conv['tfs'], 1, 0, 'L', True)
            pdf.set_fill_color(*color_warning)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(20, 6, 'Score: ' + str(conv['score']), 1, 1, 'C', True)
            pdf.set_text_color(*color_text_dark)
    else:
        pdf.set_font('Arial', 'I', 9)
        pdf.cell(0, 6, 'Aucune convergence significative detectee', 0, 1, 'L')
    
    pdf.ln(5)
    
    # SECTION 4: TOP OPPORTUNITES
    pdf.set_font('Arial', 'B', 13)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, ' TOP 10 OPPORTUNITES (Score de priorite) ', 0, 1, 'L', True)
    pdf.ln(2)
    
    opportunities = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            if pd.notna(rsi_val):
                priority = 0
                signal = ""
                if rsi_val <= 20:
                    priority += 10
                    signal = "SURVENTE EXTREME"
                elif rsi_val <= 30:
                    priority += 5
                    signal = "SURVENTE"
                elif rsi_val >= 80:
                    priority += 10
                    signal = "SURACHAT EXTREME"
                elif rsi_val >= 70:
                    priority += 5
                    signal = "SURACHAT"
                if divergence == 'Haussière':
                    priority += 5
                    signal = signal + " + DIV.BULL" if signal else "DIV.BULL"
                elif divergence == 'Baissière':
                    priority += 5
                    signal = signal + " + DIV.BEAR" if signal else "DIV.BEAR"
                if priority > 0:
                    opportunities.append({
                        'asset': row['Devises'], 'tf': tf, 'rsi': rsi_val,
                        'signal': signal, 'priority': priority
                    })
    
    opportunities.sort(key=lambda x: (-x['priority'], abs(50 - x['rsi'])))
    top_opps = opportunities[:10]
    
    if top_opps:
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(*color_header)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(10, 8, '#', 1, 0, 'C', True)
        pdf.cell(45, 8, 'Actif', 1, 0, 'C', True)
        pdf.cell(20, 8, 'TF', 1, 0, 'C', True)
        pdf.cell(25, 8, 'RSI', 1, 0, 'C', True)
        pdf.cell(80, 8, 'Signal', 1, 0, 'C', True)
        pdf.cell(20, 8, 'Score', 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        for i, opp in enumerate(top_opps, 1):
            pdf.set_fill_color(*color_neutral)
            pdf.set_text_color(*color_text_dark)
            pdf.cell(10, 7, str(i), 1, 0, 'C', True)
            pdf.cell(45, 7, opp['asset'], 1, 0, 'L', True)
            pdf.cell(20, 7, opp['tf'], 1, 0, 'C', True)
            
            if opp['rsi'] <= 20:
                pdf.set_fill_color(*color_oversold)
                pdf.set_text_color(255, 255, 255)
            elif opp['rsi'] >= 80:
                pdf.set_fill_color(*color_overbought)
                pdf.set_text_color(255, 255, 255)
            elif opp['rsi'] <= 30:
                pdf.set_fill_color(255, 200, 200)
                pdf.set_text_color(*color_text_dark)
            elif opp['rsi'] >= 70:
                pdf.set_fill_color(200, 255, 200)
                pdf.set_text_color(*color_text_dark)
            else:
                pdf.set_fill_color(*color_neutral)
                pdf.set_text_color(*color_text_dark)
            
            pdf.cell(25, 7, '{:.2f}'.format(opp['rsi']), 1, 0, 'C', True)
            
            pdf.set_fill_color(*color_neutral)
            pdf.set_text_color(*color_text_dark)
            pdf.cell(80, 7, opp['signal'], 1, 0, 'L', True)
            
            pdf.set_fill_color(*color_warning)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(20, 7, str(opp['priority']), 1, 1, 'C', True)
    
    pdf.ln(3)
    
    # SECTION 5: DONNEES BRUTES
    pdf.add_page()
    pdf.set_font('Arial', 'B', 13)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, ' DONNEES DETAILLEES (Toutes les paires) ', 0, 1, 'L', True)
    pdf.ln(2)
    
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(*color_header)
    pdf.set_text_color(255, 255, 255)
    cell_w_pair = 50
    cell_w_tf = (pdf.w - pdf.l_margin - pdf.r_margin - cell_w_pair) / len(TIMEFRAMES_DISPLAY)
    pdf.cell(cell_w_pair, 9, 'Actif', 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(cell_w_tf, 9, tf, 1, 0, 'C', True)
    pdf.ln()
    
    pdf.set_font('Arial', '', 8)
    for row in results_data:
        pdf.set_fill_color(*color_neutral)
        pdf.set_text_color(*color_text_dark)
        pdf.cell(cell_w_pair, 8, row['Devises'], 1, 0, 'L', True)
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {})
            rsi = d.get('rsi', np.nan)
            div = d.get('divergence', 'Aucune')
            if pd.notna(rsi):
                if rsi <= 20:
                    pdf.set_fill_color(*color_oversold)
                    pdf.set_text_color(255, 255, 255)
                elif rsi >= 80:
                    pdf.set_fill_color(*color_overbought)
                    pdf.set_text
