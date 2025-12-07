import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
import traceback
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from fpdf import FPDF

# Configuration de la page
st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

warnings.filterwarnings('ignore')

# --- CSS STYLES ---
st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 28px; font-weight: bold; color: #FAFAFA; margin-bottom: 15px; text-align: center; }
    .update-info { background-color: #202225; padding: 8px 15px; border-radius: 5px; margin-bottom: 20px; font-size: 14px; color: #A9A9A9; border: 1px solid #111315; text-align: center; }
    .legend-container { display: flex; justify-content: center; flex-wrap: wrap; gap: 25px; margin: 25px 0; padding: 15px; border-radius: 5px; background-color: #0F1113; }
    .legend-item { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #D3D3D3; }
    .legend-dot { width: 12px; height: 12px; border-radius: 50%; }
    .oversold-dot { background-color: #FF4B4B; }
    .overbought-dot { background-color: #3D9970; }
    h3 { color: #EAEAEA; text-align: center; margin-top: 30px; margin-bottom: 15px; }
    .rsi-table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; box-shadow: 0 4px 8px 0 rgba(0,0,0,0.1); }
    .rsi-table th { background-color: #151617; color: #EAEAEA !important; padding: 14px 10px; text-align: center; font-weight: bold; font-size: 15px; border: 1px solid #0E0F11; }
    .rsi-table td { padding: 12px 10px; text-align: center; border: 1px solid #0E0F11; font-size: 14px; }
    .devises-cell { font-weight: bold !important; color: #E0E0E0 !important; font-size: 15px !important; text-align: left !important; padding-left: 15px !important; }
    .oversold-cell { background-color: rgba(255, 75, 75, 0.85) !important; color: white !important; font-weight: bold; }
    .overbought-cell { background-color: rgba(61, 153, 112, 0.85) !important; color: white !important; font-weight: bold; }
    .neutral-cell { color: #C0C0C0 !important; background-color: #0B0C0D; }
    .divergence-arrow { font-size: 20px; font-weight: bold; vertical-align: middle; margin-left: 6px; }
    .bullish-arrow { color: #3D9970; }
    .bearish-arrow { color: #FF4B4B; }
</style>
""", unsafe_allow_html=True)

# --- OANDA AUTHENTICATION ---
try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except Exception:
    st.error("🔑 Secrets OANDA non trouvés! Ajoute OANDA_ACCOUNT_ID et OANDA_ACCESS_TOKEN dans les Secrets.")
    st.stop()

# --- UTILS FUNCTIONS ---
def calculate_rsi(prices, period=10):
    try:
        if prices is None or len(prices) < period + 1:
            return np.nan, None
        ohlc4 = (prices['Open'] + prices['High'] + prices['Low'] + prices['Close']) / 4
        delta = ohlc4.diff()
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        
        if len(gains.dropna()) < period or len(losses.dropna()) < period:
            return np.nan, None
            
        avg_gains = gains.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        avg_losses = losses.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        
        rs = avg_gains / avg_losses
        rs = rs.replace([np.inf, -np.inf], np.nan)
        rsi_series = 100.0 - (100.0 / (1.0 + rs))
        
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return np.nan, None
        return rsi_series.iloc[-1], rsi_series
    except Exception:
        return np.nan, None

def detect_divergence(price_data, rsi_series, lookback=30, peak_distance=5):
    try:
        if rsi_series is None or price_data is None or len(price_data) < lookback:
            return "Aucune"
        
        recent_price = price_data.iloc[-lookback:]
        recent_rsi = rsi_series.iloc[-lookback:]
        
        # Divergence Baissière (Bearish) : Prix fait un sommet plus haut, RSI fait un sommet plus bas
        price_peaks_idx, _ = find_peaks(recent_price['High'], distance=peak_distance)
        if len(price_peaks_idx) >= 2:
            last, prev = price_peaks_idx[-1], price_peaks_idx[-2]
            if recent_price['High'].iloc[last] > recent_price['High'].iloc[prev]:
                if recent_rsi.iloc[last] < recent_rsi.iloc[prev]:
                    return "Baissière"
        
        # Divergence Haussière (Bullish) : Prix fait un creux plus bas, RSI fait un creux plus haut
        price_troughs_idx, _ = find_peaks(-recent_price['Low'], distance=peak_distance)
        if len(price_troughs_idx) >= 2:
            last, prev = price_troughs_idx[-1], price_troughs_idx[-2]
            if recent_price['Low'].iloc[last] < recent_price['Low'].iloc[prev]:
                if recent_rsi.iloc[last] > recent_rsi.iloc[prev]:
                    return "Haussière"
                    
        return "Aucune"
    except Exception:
        return "Aucune"

@st.cache_data(ttl=600, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key):
    try:
        api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
        instrument = pair.replace('/', '_')
        gran_map = {'H1':'H1', 'H4':'H4', 'D1':'D', 'W1':'W'}
        
        params = {'granularity': gran_map[timeframe_key], 'count': 200}
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        api.request(r)
        
        data_list = []
        for c in r.response.get('candles', []):
            mid = c.get('mid', {})
            if not mid:
                continue
            data_list.append({
                'Time': c.get('time'),
                'Open': float(mid.get('o', np.nan)),
                'High': float(mid.get('h', np.nan)),
                'Low': float(mid.get('l', np.nan)),
                'Close': float(mid.get('c', np.nan)),
                'Volume': int(c.get('volume', 0))
            })
            
        if not data_list:
            return None
            
        df = pd.DataFrame(data_list)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except Exception:
        return None

def format_rsi(value):
    return "N/A" if pd.isna(value) else "{:.2f}".format(value)

def get_rsi_class(value):
    if pd.isna(value):
        return "neutral-cell"
    elif value <= 30: # Standard RSI oversold is usually 30, adjusted from 20 for safety
        return "oversold-cell"
    elif value >= 70: # Standard RSI overbought is usually 70, adjusted from 80
        return "overbought-cell"
    return "neutral-cell"

# --- CONFIGURATION ASSETS ---
ASSETS = [
    'EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD',
    'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY',
    'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF',
    'XAU/USD', 'XPT/USD', 'US30/USD', 'NAS100/USD', 'SPX500/USD'
]
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
            status_widget.text(f"Scanning: {pair_name} on {tf_display_name} ({call_count}/{total_calls})")
            
            data_ohlc = fetch_forex_data_oanda(pair_name, tf_key)
            
            # Anti-throttle: petite pause pour éviter les erreurs API
            time.sleep(0.05) 
            
            rsi_value, rsi_series = calculate_rsi(data_ohlc, period=10)
            divergence_signal = "Aucune"
            
            if data_ohlc is not None and rsi_series is not None:
                divergence_signal = detect_divergence(data_ohlc, rsi_series)
            
            row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}
            
            progress_widget.progress(min(call_count / total_calls, 1.0))
            
        results_list.append(row_data)
    
    st.session_state.results = results_list
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done = True
    
    status_widget.empty()
    progress_widget.empty()

# --- PDF GENERATION ---
def create_pdf_report(results_data, last_scan_time):
    try:
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
        
        # Couleurs
        color_header_bg = (30, 33, 36)
        color_oversold_bg = (180, 40, 40)
        color_overbought_bg = (25, 110, 80)
        color_neutral_bg = (240, 240, 240) # Fond clair pour le PDF pour lisibilité
        color_neutral_text = (0, 0, 0)
        
        # Section Guide
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'GUIDE DE LECTURE', 0, 1, 'L')
        pdf.set_font('Arial', '', 9)
        pdf.ln(2)
        pdf.cell(0, 5, 'RSI < 30 : SURVENTE | RSI > 70 : SURACHAT', 0, 1, 'L')
        pdf.cell(0, 5, '(BULL) = Div. Haussiere | (BEAR) = Div. Baissiere', 0, 1, 'L')
        pdf.ln(5)

        # Section Top Opportunités
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'TOP OPPORTUNITES (Priorite)', 0, 1, 'L')
        
        opportunities = []
        for row in results_data:
            for tf in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf, {})
                rsi_val = cell_data.get('rsi', np.nan)
                divergence = cell_data.get('divergence', 'Aucune')
                
                if pd.notna(rsi_val):
                    priority = 0
                    signal = ""
                    if rsi_val <= 30: priority += 5; signal = "SURVENTE"
                    elif rsi_val >= 70: priority += 5; signal = "SURACHAT"
                    
                    if divergence == 'Haussière': priority += 3; signal += " + DIV.BULL"
                    elif divergence == 'Baissière': priority += 3; signal += " + DIV.BEAR"
                    
                    if priority > 0:
                        opportunities.append({'asset': row['Devises'], 'tf': tf, 'rsi': rsi_val, 'signal': signal, 'priority': priority})

        opportunities.sort(key=lambda x: (-x['priority'], x['rsi']))
        
        pdf.set_font('Arial', '', 9)
        if opportunities:
            for i, opp in enumerate(opportunities[:10], 1):
                line = f"{i}. {opp['asset']} ({opp['tf']}) - RSI: {opp['rsi']:.2f} - {opp['signal']}"
                pdf.cell(0, 6, line, 0, 1, 'L')
        else:
            pdf.cell(0, 6, 'Aucun signal majeur detecte.', 0, 1, 'L')
        pdf.ln(5)

        # Tableau Complet
        pdf.add_page()
        pdf.set_font('Arial', 'B', 10)
        
        # En-tête tableau
        cell_width_pair = 40
        cell_width_tf = 45
        
        pdf.cell(cell_width_pair, 10, 'Pair', 1, 0, 'C')
        for tf in TIMEFRAMES_DISPLAY:
            pdf.cell(cell_width_tf, 10, tf, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font('Arial', '', 9)
        for row in results_data:
            pdf.cell(cell_width_pair, 10, row['Devises'], 1, 0, 'L')
            
            for tf in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf, {})
                rsi_val = cell_data.get('rsi', np.nan)
                div = cell_data.get('divergence', 'Aucune')
                
                # Couleur conditionnelle (texte simple pour PDF)
                txt_display = format_rsi(rsi_val)
                if div == "Haussière": txt_display += " (BULL)"
                elif div == "Baissière": txt_display += " (BEAR)"
                
                # Fill color si extreme
                fill = False
                if pd.notna(rsi_val):
                    if rsi_val <= 30: 
                        pdf.set_fill_color(*color_oversold_bg)
                        pdf.set_text_color(255,255,255)
                        fill = True
                    elif rsi_val >= 70:
                        pdf.set_fill_color(*color_overbought_bg)
                        pdf.set_text_color(255,255,255)
                        fill = True
                    else:
                        pdf.set_text_color(0,0,0)
                else:
                    pdf.set_text_color(0,0,0)
                    
                pdf.cell(cell_width_tf, 10, txt_display, 1, 0, 'C', fill)
                pdf.set_text_color(0,0,0) # Reset
            pdf.ln()

        # Output compatible bytearray
        return pdf.output(dest='S').encode('latin-1')

    except Exception:
        # En cas d'erreur PDF, on retourne un PDF d'erreur minimal
        try:
            err_pdf = FPDF()
            err_pdf.add_page()
            err_pdf.set_font("Arial", size=12)
            err_pdf.cell(200, 10, txt="Erreur generation PDF: " + traceback.format_exc(), ln=1, align="C")
            return err_pdf.output(dest='S').encode('latin-1')
        except:
            return b""

# --- MAIN UI ---
st.markdown('<h1 class="screener-header">Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

if st.session_state.get('scan_done'):
    last_scan_time = st.session_state.get('last_scan_time')
    if last_scan_time:
        last_scan_time_str = last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
        st.markdown(f'<div class="update-info">🔄 Dernière mise à jour: {last_scan_time_str}</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([4, 1, 1])

# Bouton Rescan
with col2:
    if st.button("🔄 Rescan", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear() # Force le rafraîchissement
        st.rerun()

# Bouton PDF
with col3:
    if st.session_state.get('results'):
        pdf_data = create_pdf_report(st.session_state.results, st.session_state.get('last_scan_time', datetime.now()))
        st.download_button(
            label="📄 PDF",
            data=pdf_data,
            file_name=f"RSI_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

# Logique de lancement
if not st.session_state.get('scan_done'):
    if st.button("🚀 Lancer le scan", use_container_width=True):
        with st.spinner("Analyse des marchés en cours..."):
            run_analysis_process()
        st.success("Analyse terminée!")
        st.rerun()

# Affichage des résultats
if st.session_state.get('results'):
    # Légende
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ 30)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ 70)</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">↑</span><span>Bullish Divergence</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">↓</span><span>Bearish Divergence</span></div>
    </div>""", unsafe_allow_html=True)

    # Table HTML
    html_table = '<table class="rsi-table"><thead><tr><th>Devises</th>'
    for tf in TIMEFRAMES_DISPLAY:
        html_table += f'<th>{tf}</th>'
    html_table += '</tr></thead><tbody>'

    for row in st.session_state.results:
        html_table += f'<tr><td class="devises-cell">{row["Devises"]}</td>'
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {'rsi': np.nan, 'divergence': 'Aucune'})
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
    
    # Stats rapides
    st.markdown("### 📊 Statistiques")
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf in enumerate(TIMEFRAMES_DISPLAY):
        tf_data = [row.get(tf, {}) for row in st.session_state.results]
        # Count stats
        oversold = sum(1 for d in tf_data if pd.notna(d.get('rsi')) and d.get('rsi') <= 30)
        overbought = sum(1 for d in tf_data if pd.notna(d.get('rsi')) and d.get('rsi') >= 70)
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        
        with stat_cols[i]:
            st.metric(label=tf, value=f"{oversold + overbought} Alerts", delta=f"{bull_div} Div. Bull")

with st.expander("ℹ️ Configuration & Info"):
    st.markdown("""
    **Data Source:** OANDA v20 API  
    **RSI:** Period 10, OHLC4  
    **Divergence:** Lookback 30 bougies
    """)
