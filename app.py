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

# --- CONFIGURATION ---
warnings.filterwarnings('ignore')
RSI_PERIOD = 14  # Standard habituel (10 est un peu court, mais modifiable ici)
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS STYLES ---
st.markdown(f"""
<style>
    .main > div {{ padding-top: 2rem; }}
    .screener-header {{ font-size: 28px; font-weight: bold; color: #FAFAFA; margin-bottom: 15px; text-align: center; }}
    .update-info {{ background-color: #262730; padding: 8px 15px; border-radius: 5px; margin-bottom: 20px; font-size: 14px; color: #A9A9A9; border: 1px solid #333A49; text-align: center; }}
    .legend-container {{ display: flex; justify-content: center; flex-wrap: wrap; gap: 25px; margin: 25px 0; padding: 15px; border-radius: 5px; background-color: #1A1C22; }}
    .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 14px; color: #D3D3D3; }}
    .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
    .oversold-dot {{ background-color: #FF4B4B; }}
    .overbought-dot {{ background-color: #3D9970; }}
    h3 {{ color: #EAEAEA; text-align: center; margin-top: 30px; margin-bottom: 15px; }}
    .rsi-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; box-shadow: 0 4px 8px 0 rgba(0,0,0,0.1); }}
    .rsi-table th {{ background-color: #333A49; color: #EAEAEA !important; padding: 14px 10px; text-align: center; font-weight: bold; font-size: 15px; border: 1px solid #262730; }}
    .rsi-table td {{ padding: 12px 10px; text-align: center; border: 1px solid #262730; font-size: 14px; }}
    .devises-cell {{ font-weight: bold !important; color: #E0E0E0 !important; font-size: 15px !important; text-align: left !important; padding-left: 15px !important; }}
    .oversold-cell {{ background-color: rgba(255, 75, 75, 0.7) !important; color: white !important; font-weight: bold; }}
    .overbought-cell {{ background-color: rgba(61, 153, 112, 0.7) !important; color: white !important; font-weight: bold; }}
    .neutral-cell {{ color: #C0C0C0 !important; background-color: #161A1D; }}
    .divergence-arrow {{ font-size: 20px; font-weight: bold; vertical-align: middle; margin-left: 6px; }}
    .bullish-arrow {{ color: #3D9970; }}
    .bearish-arrow {{ color: #FF4B4B; }}
</style>
""", unsafe_allow_html=True)

# --- SECRETS OANDA ---
try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except KeyError:
    st.error("🔑 Secrets OANDA non trouvés! Vérifiez votre fichier .streamlit/secrets.toml")
    st.stop()

# --- ASSETS CONFIG ---
ASSETS = [
    'EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 
    'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 
    'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF', 
    'XAU/USD', 'XPT/USD', 'US30/USD', 'NAS100/USD', 'SPX500/USD'
]
TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D1', 'W1']

# --- FUNCTIONS ---

def calculate_rsi(prices, period=RSI_PERIOD):
    try:
        if prices is None or len(prices) < period + 1: return np.nan, None
        
        # CORRECTION: Utilisation du Close uniquement (Standard TradingView/MT4)
        close_prices = prices['Close']
        delta = close_prices.diff()
        
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
    
    # Bearish Divergence (Prix monte, RSI descend)
    price_peaks_idx, _ = find_peaks(recent_price['High'], distance=peak_distance)
    if len(price_peaks_idx) >= 2:
        last_peak = price_peaks_idx[-1]
        prev_peak = price_peaks_idx[-2]
        if (recent_price['High'].iloc[last_peak] > recent_price['High'].iloc[prev_peak] and 
            recent_rsi.iloc[last_peak] < recent_rsi.iloc[prev_peak]):
            return "Baissière"
            
    # Bullish Divergence (Prix descend, RSI monte)
    price_troughs_idx, _ = find_peaks(-recent_price['Low'], distance=peak_distance)
    if len(price_troughs_idx) >= 2:
        last_trough = price_troughs_idx[-1]
        prev_trough = price_troughs_idx[-2]
        if (recent_price['Low'].iloc[last_trough] < recent_price['Low'].iloc[prev_trough] and 
            recent_rsi.iloc[last_trough] > recent_rsi.iloc[prev_trough]):
            return "Haussière"
            
    return "Aucune"

@st.cache_data(ttl=600, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key):
    try:
        api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
        instrument = pair.replace('/', '_')
        params = {
            'granularity': {'H1':'H1', 'H4':'H4', 'D1':'D', 'W1':'W'}[timeframe_key], 
            'count': 120 # Un peu plus de data pour le calcul RSI
        }
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        api.request(r)
        
        data_list = []
        for c in r.response['candles']:
            if c['complete']: # On ne prend que les bougies clôturées pour éviter le repaint
                data_list.append({
                    'Time': c['time'],
                    'Open': float(c['mid']['o']),
                    'High': float(c['mid']['h']),
                    'Low': float(c['mid']['l']),
                    'Close': float(c['mid']['c']),
                    'Volume': int(c['volume'])
                })
        
        if not data_list: return None
        df = pd.DataFrame(data_list)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except Exception as e:
        # En production, on pourrait logger l'erreur ici
        return None

def format_rsi(value): 
    return "N/A" if pd.isna(value) else "{:.2f}".format(value)

def get_rsi_class(value):
    if pd.isna(value): return "neutral-cell"
    elif value <= RSI_OVERSOLD: return "oversold-cell"
    elif value >= RSI_OVERBOUGHT: return "overbought-cell"
    return "neutral-cell"

# --- CORE LOGIC (PARALLELIZED) ---

def process_single_asset(pair_name):
    """Traite un actif sur tous les timeframes"""
    row_data = {'Devises': pair_name}
    for tf_key, tf_display_name in zip(TIMEFRAMES_FETCH_KEYS, TIMEFRAMES_DISPLAY):
        data_ohlc = fetch_forex_data_oanda(pair_name, tf_key)
        rsi_value, rsi_series = calculate_rsi(data_ohlc)
        divergence_signal = "Aucune"
        if data_ohlc is not None and rsi_series is not None:
            divergence_signal = detect_divergence(data_ohlc, rsi_series)
        row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}
    return row_data

def run_analysis_process():
    results_list = []
    
    # Barre de progression et status
    progress_bar = st.progress(0)
    status_text = st.empty()
    status_text.text("Initialisation du scan parallèle...")
    
    # Utilisation de ThreadPoolExecutor pour paralléliser les appels API
    # Max workers limité pour ne pas saturer l'API OANDA ou la CPU
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_asset = {executor.submit(process_single_asset, asset): asset for asset in ASSETS}
        completed = 0
        total = len(ASSETS)
        
        for future in concurrent.futures.as_completed(future_to_asset):
            asset_name = future_to_asset[future]
            try:
                data = future.result()
                results_list.append(data)
            except Exception as e:
                st.error(f"Erreur lors du scan de {asset_name}: {e}")
            
            completed += 1
            progress = completed / total
            progress_bar.progress(progress)
            status_text.text(f"Scan terminé: {asset_name} ({completed}/{total})")

    # IMPORTANT : Remettre les résultats dans l'ordre de la liste ASSETS d'origine
    # car le multithreading mélange l'ordre d'arrivée
    results_list.sort(key=lambda x: ASSETS.index(x['Devises']))

    st.session_state.results = results_list
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done = True
    
    status_text.empty()
    progress_bar.empty()

# --- PDF GENERATION ---

def create_pdf_report(results_data, last_scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, 'Rapport Screener RSI & Divergence', 0, 1, 'C')
            self.set_font('Arial', '', 8)
            self.cell(0, 5, 'Genere le: ' + str(last_scan_time), 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Couleurs PDF
    color_header_bg = (51, 58, 73)
    color_oversold_bg = (255, 75, 75)
    color_overbought_bg = (61, 153, 112)
    color_neutral_bg = (22, 26, 29)
    color_neutral_text = (192, 192, 192)
    
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'GUIDE DE LECTURE', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.ln(2)
    pdf.cell(0, 5, f'RSI (Period {RSI_PERIOD}):', 0, 1, 'L')
    pdf.cell(0, 5, f'  - RSI < {RSI_OVERSOLD} : Zone de SURVENTE (potentiel rebond haussier)', 0, 1, 'L')
    pdf.cell(0, 5, f'  - RSI > {RSI_OVERBOUGHT} : Zone de SURACHAT (potentiel rebond baissier)', 0, 1, 'L')
    pdf.cell(0, 5, f'  - RSI entre {RSI_OVERSOLD}-{RSI_OVERBOUGHT} : Zone NEUTRE', 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'SYNTHESE DES SIGNAUX', 0, 1, 'L')
    
    stats_by_tf = {}
    for tf in TIMEFRAMES_DISPLAY:
        tf_data = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        oversold = sum(1 for x in valid_rsi if x <= RSI_OVERSOLD)
        overbought = sum(1 for x in valid_rsi if x >= RSI_OVERBOUGHT)
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        stats_by_tf[tf] = {'oversold': oversold, 'overbought': overbought, 'bull_div': bull_div, 'bear_div': bear_div}
    
    pdf.set_font('Arial', '', 9)
    for tf, stats in stats_by_tf.items():
        line = '{}: {} survente | {} surachat | {} div.bull | {} div.bear'.format(tf, stats['oversold'], stats['overbought'], stats['bull_div'], stats['bear_div'])
        pdf.cell(0, 6, line, 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'OPPORTUNITES PRIORITAIRES (Top 10)', 0, 1, 'L')
    
    opportunities = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            if pd.notna(rsi_val):
                priority = 0
                signal = ""
                if rsi_val <= RSI_OVERSOLD:
                    priority += 5
                    signal = "SURVENTE"
                elif rsi_val >= RSI_OVERBOUGHT:
                    priority += 5
                    signal = "SURACHAT"
                if divergence == 'Haussière':
                    priority += 3
                    signal = signal + " + DIV.BULL" if signal else "DIV.BULL"
                elif divergence == 'Baissière':
                    priority += 3
                    signal = signal + " + DIV.BEAR" if signal else "DIV.BEAR"
                if priority > 0:
                    opportunities.append({'asset': row['Devises'], 'tf': tf, 'rsi': rsi_val, 'signal': signal, 'priority': priority})
    
    opportunities.sort(key=lambda x: (-x['priority'], x['rsi']))
    top_opps = opportunities[:10]
    
    if top_opps:
        pdf.set_font('Arial', '', 9)
        for i, opp in enumerate(top_opps, 1):
            line = '{}. {} ({}) - RSI: {:.2f} - Signal: {}'.format(i, opp['asset'], opp['tf'], opp['rsi'], opp['signal'])
            pdf.cell(0, 6, line, 0, 1, 'L')
    else:
        pdf.set_font('Arial', 'I', 9)
        pdf.cell(0, 6, 'Aucun signal prioritaire detecte', 0, 1, 'L')
    pdf.ln(5)
    
    pdf.add_page()
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'DONNEES DETAILLEES PAR ACTIF', 0, 1, 'L')
    pdf.ln(2)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(*color_header_bg)
    pdf.set_text_color(234, 234, 234)
    cell_width_pair = 50
    cell_width_tf = (pdf.w - pdf.l_margin - pdf.r_margin - cell_width_pair) / len(TIMEFRAMES_DISPLAY)
    pdf.cell(cell_width_pair, 10, 'Devises', 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(cell_width_tf, 10, tf, 1, 0, 'C', True)
    pdf.ln()
    
    pdf.set_font('Arial', '', 9)
    for row in results_data:
        pdf.set_fill_color(*color_neutral_bg)
        pdf.set_text_color(234, 234, 234)
        pdf.cell(cell_width_pair, 10, row['Devises'], 1, 0, 'L', True)
        for tf_display_name in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf_display_name, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            if pd.notna(rsi_val):
                if rsi_val <= RSI_OVERSOLD:
                    pdf.set_fill_color(*color_oversold_bg)
                    pdf.set_text_color(255, 255, 255)
                elif rsi_val >= RSI_OVERBOUGHT:
                    pdf.set_fill_color(*color_overbought_bg)
                    pdf.set_text_color(255, 255, 255)
                else:
                    pdf.set_fill_color(*color_neutral_bg)
                    pdf.set_text_color(*color_neutral_text)
            else:
                pdf.set_fill_color(*color_neutral_bg)
                pdf.set_text_color(*color_neutral_text)
            formatted_val = format_rsi(rsi_val)
            divergence_text = " (BULL)" if divergence == "Haussière" else (" (BEAR)" if divergence == "Baissière" else "")
            cell_text = formatted_val + divergence_text
            pdf.cell(cell_width_tf, 10, cell_text, 1, 0, 'C', True)
        pdf.ln()
    
    return bytes(pdf.output())

# --- MAIN APP UI ---

st.markdown('<h1 class="screener-header">Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

if 'scan_done' in st.session_state and st.session_state.scan_done:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown('<div class="update-info">🔄 Dernière mise à jour: {} (OANDA)</div>'.format(last_scan_time_str), unsafe_allow_html=True)

col1, col2, col3 = st.columns([4, 1, 1])
with col2:
    if st.button("🔄 Rescan", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

with col3:
    if 'results' in st.session_state and st.session_state.results:
        st.download_button(
            label="📄 PDF",
            data=create_pdf_report(st.session_state.results, st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M:%S")),
            file_name="RSI_Report_{}.pdf".format(datetime.now().strftime('%Y%m%d_%H%M')),
            mime="application/pdf",
            use_container_width=True
        )

if 'scan_done' not in st.session_state or not st.session_state.scan_done:
    if st.button("🚀 Lancer le scan", use_container_width=True):
        run_analysis_process() # Appel direct sans spinner global car géré dedans
        st.rerun()
    elif 'scan_done' in st.session_state and not st.session_state.scan_done:
        run_analysis_process()
        st.rerun()

if 'results' in st.session_state and st.session_state.results:
    # Légende dynamique selon les constantes
    st.markdown(f"""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ {RSI_OVERSOLD})</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ {RSI_OVERBOUGHT})</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">↑</span><span>Bullish Divergence</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">↓</span><span>Bearish Divergence</span></div>
    </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📈 RSI & Divergence Analysis Results")
    html_table = '<table class="rsi-table"><thead><tr><th>Devises</th>'
    for tf in TIMEFRAMES_DISPLAY: 
        html_table += '<th>{}</th>'.format(tf)
    html_table += '</tr></thead><tbody>'
    
    for row in st.session_state.results:
        html_table += '<tr><td class="devises-cell">{}</td>'.format(row["Devises"])
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            css_class = get_rsi_class(rsi_val)
            formatted_val = format_rsi(rsi_val)
            divergence_icon = '<span class="divergence-arrow bullish-arrow">↑</span>' if divergence == "Haussière" else ('<span class="divergence-arrow bearish-arrow">↓</span>' if divergence == "Baissière" else "")
            html_table += '<td class="{}">{} {}</td>'.format(css_class, formatted_val, divergence_icon)
        html_table += '</tr>'
    html_table += '</tbody></table>'
    st.markdown(html_table, unsafe_allow_html=True)
    
    st.markdown("### 📊 Signal Statistics")
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf in enumerate(TIMEFRAMES_DISPLAY):
        tf_data = [row.get(tf, {}) for row in st.session_state.results]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        if valid_rsi:
            oversold = sum(1 for x in valid_rsi if x <= RSI_OVERSOLD)
            overbought = sum(1 for x in valid_rsi if x >= RSI_OVERBOUGHT)
            total = oversold + overbought + bull_div + bear_div
            delta_text = "🔴 {} S | 🟢 {} B | ↑ {} | ↓ {}".format(oversold, overbought, bull_div, bear_div)
            with stat_cols[i]:
                st.metric(label="Signals {}".format(tf), value=str(total))
                st.markdown(delta_text, unsafe_allow_html=True)
        else:
            with stat_cols[i]: 
                st.metric(label="Signals {}".format(tf), value="N/A")

with st.expander("ℹ️ Configuration", expanded=False):
    st.markdown(f"""
    **Data Source:** OANDA v20 API (practice account)
    **RSI Period:** {RSI_PERIOD} | **Source:** Close Price
    **Thresholds:** Oversold ≤ {RSI_OVERSOLD} | Overbought ≥ {RSI_OVERBOUGHT}
    **Divergence:** Last 30 candles
    """)
# --- END OF FILE app.py ---
