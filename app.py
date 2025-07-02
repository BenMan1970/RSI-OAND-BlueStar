# --- START OF FILE app.py ---

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from io import BytesIO

### AJOUT : L'UNIQUE IMPORT NÉCESSAIRE POUR L'IMAGE ###
from PIL import Image, ImageDraw, ImageFont

warnings.filterwarnings('ignore')

# --- Configuration de la page Streamlit ---
st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS personnalisé (inchangé) ---
st.markdown("""
<style>
    /* ... (VOTRE CSS PRÉCÉDENT EST CONSERVÉ) ... */
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


# --- Accès aux secrets OANDA (inchangé) ---
try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except KeyError:
    st.error("🔑 Secrets OANDA non trouvés !")
    st.info("Veuillez vérifier que les noms de vos secrets sont bien en MAJUSCULES dans les paramètres de l'application.")
    st.code('OANDA_ACCOUNT_ID = "..."\nOANDA_ACCESS_TOKEN = "..."')
    st.stop()


# --- Fonctions de calcul et de récupération de données (Inchangées) ---
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

def format_rsi(value): return "N/A" if pd.isna(value) else f"{value:.2f}"
def get_rsi_class(value):
    if pd.isna(value): return "neutral-cell"
    elif value <= 20: return "oversold-cell"
    elif value >= 80: return "overbought-cell"
    return "neutral-cell"

# --- Constantes ---
FOREX_PAIRS = [ 'EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF' ]
TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D1', 'W1']

### AJOUT : FONCTION FIABLE DE CRÉATION D'IMAGE ###
def create_simple_image_report(dataframe, report_title):
    """Crée une image simple à partir du texte d'un DataFrame."""
    
    report_text = report_title + "\n" + ("-" * len(report_title)) + "\n"
    report_text += dataframe.to_string(index=False) if not dataframe.empty else "Aucune donnée."

    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 12)
    except IOError:
        font = ImageFont.load_default()

    temp_img = Image.new('RGB', (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)
    text_bbox = temp_draw.multiline_textbbox((0, 0), report_text, font=font)
    
    padding = 20
    width = text_bbox[2] + 2 * padding
    height = text_bbox[3] + 2 * padding
    
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    draw.multiline_text((padding, padding), report_text, font=font, fill='black')
    
    output_buffer = BytesIO()
    img.save(output_buffer, format="PNG")
    return output_buffer.getvalue()

# --- Fonction principale d'analyse (Inchangée) ---
def run_analysis_process():
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

# --- Interface Utilisateur ---
st.markdown('<h1 class="screener-header">Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button("🔄 Rescan All Forex Pairs", key="rescan_button", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

if 'scan_done' not in st.session_state or not st.session_state.scan_done:
    with st.spinner("🚀 Performing high-speed scan with OANDA..."):
        run_analysis_process()
    st.success(f"✅ Analysis complete! {len(FOREX_PAIRS)} pairs analyzed.")

if 'results' in st.session_state and st.session_state.results:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(f"""<div class="update-info">🔄 Last update: {last_scan_time_str} (Data from OANDA)</div>""", unsafe_allow_html=True)
    
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ 20)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ 80)</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">↑</span><span>Bullish Divergence</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">↓</span><span>Bearish Divergence</span></div>
    </div>""", unsafe_allow_html=True)

    # --- Affichage du tableau de résultats ---
    st.markdown("### 📈 RSI & Divergence Analysis Results")
    html_table = '<table class="rsi-table">'
    html_table += '<thead><tr><th>Devises</th>'
    for tf_display_name in TIMEFRAMES_DISPLAY: html_table += f'<th>{tf_display_name}</th>'
    html_table += '</tr></thead><tbody>'

    for row in st.session_state.results:
        html_table += f'<tr><td class="devises-cell">{row["Devises"]}</td>'
        for tf_display_name in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf_display_name, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            css_class = get_rsi_class(rsi_val)
            formatted_val = format_rsi(rsi_val)
            divergence_icon = ""
            if divergence == "Haussière":
                divergence_icon = '<span class="divergence-arrow bullish-arrow">↑</span>'
            elif divergence == "Baissière":
                divergence_icon = '<span class="divergence-arrow bearish-arrow">↓</span>'
            html_table += f'<td class="{css_class}">{formatted_val} {divergence_icon}</td>'
        html_table += '</tr>'
    html_table += '</tbody></table>'
    st.markdown(html_table, unsafe_allow_html=True)
    
    ### AJOUT : SECTION DE TÉLÉCHARGEMENT D'IMAGE ###
    st.divider()

    # 1. Préparer un DataFrame propre pour l'exportation
    rows_for_df = []
    for item in st.session_state.results:
        row = {'Devises': item['Devises']}
        for tf_name in TIMEFRAMES_DISPLAY:
            rsi = item.get(tf_name, {}).get('rsi')
            div = item.get(tf_name, {}).get('divergence', 'Aucune')
            
            rsi_str = f"{rsi:.2f}" if pd.notna(rsi) else "N/A"
            
            div_char = ""
            if div == "Haussière": div_char = " ^"  # Flèche simple pour texte
            elif div == "Baissière": div_char = " v" # Flèche simple pour texte
            
            row[tf_name] = f"{rsi_str}{div_char}"
        rows_for_df.append(row)
    
    df_for_export = pd.DataFrame(rows_for_df)

    # 2. Générer l'image en mémoire
    image_bytes = create_simple_image_report(df_for_export, "Screener RSI & Divergence")
    
    # 3. Afficher le bouton de téléchargement
    st.download_button(
        label="🖼️ Télécharger les résultats (Image)",
        data=image_bytes,
        file_name=f"rsi_screener_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
        mime='image/png',
        use_container_width=True
    )
    ### FIN DE L'AJOUT ###

    # --- Affichage des statistiques (inchangé) ---
    st.markdown("### 📊 Signal Statistics")
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf_display_name in enumerate(TIMEFRAMES_DISPLAY):
        tf_data = [row.get(tf_display_name, {}) for row in st.session_state.results]
        valid_rsi_values = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        bullish_div_count = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bearish_div_count = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')

        if valid_rsi_values:
            oversold_count = sum(1 for x in valid_rsi_values if x <= 20)
            overbought_count = sum(1 for x in valid_rsi_values if x >= 80)
            total_signals = oversold_count + overbought_count + bullish_div_count + bearish_div_count
            delta_text = f"🔴 {oversold_count} S | 🟢 {overbought_count} B | <span class='bullish-arrow'>↑</span> {bullish_div_count} | <span class='bearish-arrow'>↓</span> {bearish_div_count}"
            with stat_cols[i]:
                st.metric(label=f"Signals {tf_display_name}", value=str(total_signals))
                st.markdown(delta_text, unsafe_allow_html=True)
        else:
            with stat_cols[i]: st.metric(label=f"Signals {tf_display_name}", value="N/A", delta="No data")

# --- Guide Utilisateur et Footer (inchangé) ---
with st.expander("ℹ️ User Guide & Configuration", expanded=False):
    st.markdown("""
    ## Data Source: OANDA
    - **API**: High-speed data from OANDA's v20 API.
    - **Account**: Using a practice (demo) account.
    ## Analysis Configuration
    - **RSI Period**: 10 | **Source**: OHLC4
    - **Divergence**: Checks for regular bullish/bearish divergences on the last 30 candles.
    """)
st.markdown("<div class='footer'>*Data provided by OANDA*</div>", unsafe_allow_html=True)
