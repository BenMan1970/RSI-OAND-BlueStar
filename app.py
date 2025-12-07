# --- START OF FILE app.py ---
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
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
# === REMPLACE TOUTE LA FONCTION create_pdf_report PAR CELLE-CI ===
def create_pdf_report(results_data, last_scan_time):
    from fpdf import FPDF

    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(0, 0, 0)
            self.cell(0, 12, 'SCREENER RSI & DIVERGENCE - RAPPORT COMPLET', ln=1, align='C')
            self.set_font('Arial', '', 9)
            self.set_text_color(80, 80, 80)
            self.cell(0, 6, f'Généré le : {last_scan_time}', ln=1, align='C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(100, 100, 100)
            self.cell(0, 10, f'Page {self.page_no()}', align='C')

    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Arial', '', 10)

    # Couleurs
    R = lambda r,g,b: (r,g,b)
    RED     = R(220,20,20)
    GREEN   = R(20,150,70)
    BLUE    = R(30,30,100)
    GRAY    = R(100,100,100)

    # =============================================
    # 1. RÉSUMÉ EXÉCUTIF
    # =============================================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(230, 230, 250)
    pdf.cell(0, 10, 'RÉSUMÉ EXÉCUTIF', ln=1, fill=True)

    all_rsi = [row[tf].get('rsi') for row in results_data for tf in TIMEFRAMES_DISPLAY 
               if pd.notna(row[tf].get('rsi'))]

    if all_rsi:
        mean_rsi = np.mean(all_rsi)
        if mean_rsi < 40:
            biais = "FORTEMENT BAISSIER"; col = RED
        elif mean_rsi < 50:
            biais = "BAISSIER"; col = RED
        elif mean_rsi > 60:
            biais = "FORTEMENT HAUSSIER"; col = GREEN
        elif mean_rsi > 50:
            biais = "HAUSSIER"; col = GREEN
        else:
            biais = "NEUTRE"; col = GRAY

        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, f'RSI Moyen Global : {mean_rsi:.2f} → {biais}', ln=1)
        pdf.ln(3)

    # Signaux globaux
    oversold   = sum(1 for v in all_rsi if v <= 30)
    extreme_os = sum(1 for v in all_rsi if v <= 20)
    overbought = sum(1 for v in all_rsi if v >= 70)
    extreme_ob = sum(1 for v in all_rsi if v >= 80)
    bull_div   = sum(1 for r in results_data for tf in TIMEFRAMES_DISPLAY if r.get(tf, {}).get('divergence') == 'Haussière')
    bear_div   = sum(1 for r in results_data for tf in TIMEFRAMES_DISPLAY if r.get(tf, {}).get('divergence') == 'Baissière')

    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*RED)
    pdf.cell(0, 6, f'Survente (<30) : {oversold} | Extrême (<20) : {extreme_os}', ln=1)
    pdf.set_text_color(*GREEN)
    pdf.cell(0, 6, f'Surachat (>70) : {overbought} | Extrême (>80) : {extreme_ob}', ln=1)
    pdf.set_text_color(0, 180, 0)
    pdf.cell(0, 6, f'Divergences Haussières : {bull_div}', ln=1)
    pdf.set_text_color(255, 0, 0)
    pdf.cell(0, 6, f'Divergences Baissières : {bear_div}', ln=1)
    pdf.ln(8)

    # =============================================
    # 2. TOP 15 OPPORTUNITÉS (SCORING SIMPLE)
    # =============================================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(230, 230, 250)
    pdf.cell(0, 10, 'TOP 15 OPPORTUNITÉS', ln=1, fill=True)
    pdf.ln(2)

    opps = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {})
            rsi = d.get('rsi')
            div = d.get('divergence', 'Aucune')
            if pd.isna(rsi): continue

            score = 0
            txt = []
            if rsi <= 20:    score += 10; txt.append("RSI EXTRÊME BAS")
            elif rsi <= 30:  score += 7;  txt.append("SURVENTE")
            elif rsi >= 80:  score += 10; txt.append("RSI EXTRÊME HAUT")
            elif rsi >= 70:  score += 7;  txt.append("SURACHAT")

            if div == 'Haussière':  score += 5; txt.append("DIV BULL")
            if div == 'Baissière':  score += 5; txt.append("DIV BEAR")

            if len(txt) > 1: score += 3

            if score > 0:
                opps.append((score, abs(rsi-50), row['Devises'], tf, rsi, ' + '.join(txt)))

    opps.sort(reverse=True)
    top15 = opps[:15]

    if top15:
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(30,30,50)
        pdf.set_text_color(255,255,255)
        pdf.cell(12, 8, '#', 1, 0, 'C', True)
        pdf.cell(50, 8, 'Actif', 1, 0, 'C', True)
        pdf.cell(20, 8, 'TF', 1, 0, 'C', True)
        pdf.cell(25, 8, 'RSI', 1, 0, 'C', True)
        pdf.cell(20, 8, 'Score', 1, 0, 'C', True)
        pdf.cell(0, 8, 'Signal', 1, 1, 'C', True)

        pdf.set_font('Arial', '', 9)
        for i, (_, _, asset, tf, rsi, signal) in enumerate(top15, 1):
            if rsi <= 30:
                pdf.set_text_color(*RED)
                pdf.set_fill_color(255,220,220)
            else:
                pdf.set_text_color(*GREEN)
                pdf.set_fill_color(220,255,220)

            pdf.cell(12, 7, str(i), 1, 0, 'C', True)
            pdf.cell(50, 7, asset, 1, 0, 'L', True)
            pdf.cell(20, 7, tf, 1, 0, 'C', True)
            pdf.cell(25, 7, f'{rsi:.2f}', 1, 0, 'C', True)
            pdf.cell(20, 7, str(score), 1, 0, 'C', True)
            pdf.cell(0, 7, signal, 1, 1, 'L', True)
    else:
        pdf.set_font('Arial', 'I', 11)
        pdf.cell(0, 8, 'Aucune opportunité détectée pour le moment', ln=1)

    # =============================================
    # 3. GUIDE IA (texte brut, très lisible par toi ou moi)
    # =============================================
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.set_fill_color(255, 200, 80)
    pdf.cell(0, 12, 'GUIDE COMPLET POUR L\'ANALYSE IA', ln=1, fill=True, align='C')
    pdf.ln(8)

    guide_text = """
INTERPRÉTATION RAPIDE :

• RSI < 20 → EXTRÊME SURVENTE → très fort signal d'achat (surtout avec div bull)
• RSI > 80 → EXTRÊME SURACHAT → très fort signal de vente (surtout avec div bear)
• Divergence Haussière + RSI bas → priorité absolue
• Divergence Baissière + RSI haut → priorité absolue

QUESTIONS À ME POSER (copie-colle direct) :

1. Quelles sont les 3 meilleures opportunités du jour (score + confluence) ?
2. Y a-t-il des actifs avec signaux identiques sur Weekly + Daily ?
3. Le biais global du marché (RSI moyen) favorise-t-il les achats ou les ventes ?
4. Quels sont les risques macro risques aujourd'hui (news, banques centrales...) ?
5. Quels trades offrent le meilleur ratio risque/rendement ?

TEMPLATE D'ANALYSE (à remplir) :
Actif : 
Score :     RSI :     TF : 
Confluence multi-TF : Oui/Non
Compatibilité avec biais marché : Oui/Non
Décision : ACHAT / VENTE / ATTENDRE
"""

    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 6, guide_text)

    return pdf.output(dest='S').encode('latin-1')  # ← Important pour Streamlit
