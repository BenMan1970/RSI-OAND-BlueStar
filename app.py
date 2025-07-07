# --- START OF FILE app.py ---

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from fpdf import FPDF ### NOUVEAU ### : Importation pour la génération de PDF

warnings.filterwarnings('ignore')

# --- Configuration de la page Streamlit ---
st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS personnalisé (Inchangé) ---
st.markdown("""
<style>
    /* ... (VOTRE CSS PRÉCÉDENT EST CONSERVÉ) ... */
    /* Styles généraux */
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
    
    /* NOUVEAU: Styles pour les flèches de divergence */
    .divergence-arrow {
        font-size: 20px;
        font-weight: bold;
        vertical-align: middle;
        margin-left: 6px;
    }
    .bullish-arrow {
        color: #3D9970; /* Vert */
    }
    .bearish-arrow {
        color: #FF4B4B; /* Rouge */
    }
</style>
""", unsafe_allow_html=True)


# --- Accès aux secrets OANDA (Inchangé) ---
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

# --- Constantes (Inchangées) ---
FOREX_PAIRS = [ 'EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF' ]
TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D1', 'W1']

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

# ### NOUVEAU ### : Fonction de création du rapport PDF
def create_pdf_report(results_data, last_scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, 'Rapport Screener RSI & Divergence', 0, 1, 'C')
            self.set_font('Arial', '', 8)
            self.cell(0, 5, f'Généré le: {last_scan_time}', 0, 1, 'C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    pdf = PDF(orientation='L', unit='mm', format='A4') # L for landscape
    pdf.add_page()
    
    # Couleurs (RGB)
    color_header_bg = (51, 58, 73)
    color_text_light = (234, 234, 234)
    color_oversold_bg = (255, 75, 75)
    color_overbought_bg = (61, 153, 112)
    color_neutral_bg = (22, 26, 29)
    color_neutral_text = (192, 192, 192)

    # Entête du tableau
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(*color_header_bg)
    pdf.set_text_color(*color_text_light)
    cell_width_pair = 50
    cell_width_tf = (pdf.w - pdf.l_margin - pdf.r_margin - cell_width_pair) / len(TIMEFRAMES_DISPLAY)
    pdf.cell(cell_width_pair, 10, 'Devises', 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(cell_width_tf, 10, tf, 1, 0, 'C', True)
    pdf.ln()

    # Corps du tableau
    pdf.set_font('Arial', '', 9)
    for row in results_data:
        # Cellule de la devise
        pdf.set_fill_color(*color_neutral_bg)
        pdf.set_text_color(*color_text_light)
        pdf.cell(cell_width_pair, 10, row['Devises'], 1, 0, 'L', True)
        
        # Cellules des timeframes
        for tf_display_name in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf_display_name, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            
            # Définir la couleur de fond et du texte
            if pd.notna(rsi_val):
                if rsi_val <= 20: pdf.set_fill_color(*color_oversold_bg); pdf.set_text_color(255, 255, 255)
                elif rsi_val >= 80: pdf.set_fill_color(*color_overbought_bg); pdf.set_text_color(255, 255, 255)
                else: pdf.set_fill_color(*color_neutral_bg); pdf.set_text_color(*color_neutral_text)
            else:
                pdf.set_fill_color(*color_neutral_bg); pdf.set_text_color(*color_neutral_text)
            
            # Formater le texte de la cellule
            formatted_val = format_rsi(rsi_val)
            divergence_text = ""
            if divergence == "Haussière": divergence_text = " (BULL)"
            elif divergence == "Baissière": divergence_text = " (BEAR)"
            
            cell_text = f"{formatted_val}{divergence_text}"
            pdf.cell(cell_width_tf, 10, cell_text, 1, 0, 'C', True)
        pdf.ln()

    return pdf.output(dest='S').encode('latin-1')


# --- Interface Utilisateur ---
st.markdown('<h1 class="screener-header">Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

# ### MODIFIÉ ### : Nouveaux boutons d'action en haut de la page
if 'scan_done' in st.session_state and st.session_state.scan_done:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(f"""<div class="update-info">🔄 Dernière mise à jour : {last_scan_time_str} (Données OANDA)</div>""", unsafe_allow_html=True)

col1, col2, col3 = st.columns([4, 1, 1]) # Création de colonnes pour les boutons

with col2:
    if st.button("🔄 Rescan", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

with col3:
    if 'results' in st.session_state and st.session_state.results:
        pdf_data = create_pdf_report(st.session_state.results, st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M:%S"))
        st.download_button(
            label="📄 Exporter en PDF",
            data=pdf_data,
            file_name=f"RSI_Screener_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

# Logique de scan initiale
if 'scan_done' not in st.session_state or not st.session_state.scan_done:
    # Affiche le bouton de scan initial si aucun scan n'a encore été fait
    if st.button("🚀 Lancer le premier scan", use_container_width=True):
        with st.spinner("🚀 Performing high-speed scan with OANDA..."):
            run_analysis_process()
        st.success(f"✅ Analysis complete! {len(FOREX_PAIRS)} pairs analyzed.")
        st.rerun()
    # Logique pour le cas où le scan est déclenché par le bouton rescan
    elif 'scan_done' in st.session_state and not st.session_state.scan_done:
         with st.spinner("🚀 Performing high-speed scan with OANDA..."):
            run_analysis_process()
         st.success(f"✅ Analysis complete! {len(FOREX_PAIRS)} pairs analyzed.")
         st.rerun()


if 'results' in st.session_state and st.session_state.results:
    # Légende (inchangée)
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ 20)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ 80)</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">↑</span><span>Bullish Divergence</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">↓</span><span>Bearish Divergence</span></div>
    </div>""", unsafe_allow_html=True)

    # Affichage du tableau de résultats (inchangé)
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

    # Affichage des statistiques (inchangé)
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

# Guide Utilisateur et Footer (inchangés)
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

# --- END OF FILE app.py ---
