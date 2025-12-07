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
            self.cell(0, 12, 'SCREENER RSI & DIVERGENCE - RAPPORT COMPLET', 0, 1, 'C')
            self.set_font('Arial', '', 9)
            self.set_text_color(80, 80, 80)
            self.cell(0, 6, 'Genere le: ' + str(last_scan_time), 0, 1, 'C')
            self.ln(3)
       
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(100, 100, 100)
            self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')
   
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
   
    # Couleurs vives et intenses
    COLOR_HEADER = (30, 30, 50)
    COLOR_OVERSOLD = (220, 20, 20) # Rouge intense
    COLOR_OVERBOUGHT = (20, 150, 70) # Vert intense
    COLOR_NEUTRAL = (240, 240, 240)
    COLOR_BULLISH = (0, 180, 0) # Vert vif
    COLOR_BEARISH = (255, 0, 0) # Rouge vif
   
    # ============================================================================
    # SECTION 1: RÉSUMÉ EXÉCUTIF
    # ============================================================================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 230, 250)
    pdf.cell(0, 10, 'RESUME EXECUTIF', 0, 1, 'L', True)
    pdf.ln(3)
   
    # Calcul RSI moyen global et biais marché
    all_rsi_values = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            if pd.notna(rsi_val):
                all_rsi_values.append(rsi_val)
   
    if all_rsi_values:
        rsi_moyen_global = np.mean(all_rsi_values)
        rsi_median = np.median(all_rsi_values)
       
        # Déterminer le biais marché
        if rsi_moyen_global < 40:
            biais_marche = "FORTEMENT BAISSIER"
            biais_color = COLOR_BEARISH
        elif rsi_moyen_global < 50:
            biais_marche = "BAISSIER"
            biais_color = COLOR_BEARISH
        elif rsi_moyen_global > 60:
            biais_marche = "FORTEMENT HAUSSIER"
            biais_color = COLOR_BULLISH
        elif rsi_moyen_global > 50:
            biais_marche = "HAUSSIER"
            biais_color = COLOR_BULLISH
        else:
            biais_marche = "NEUTRE"
            biais_color = (100, 100, 100)
       
        # Affichage RSI moyen
        pdf.set_font('Arial', 'B', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(70, 8, 'RSI Moyen Global:', 0, 0, 'L')
        pdf.set_font('Arial', 'B', 12)
        pdf.set_text_color(*biais_color)
        pdf.cell(30, 8, '{:.2f}'.format(rsi_moyen_global), 0, 0, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 8, '(Mediane: {:.2f})'.format(rsi_median), 0, 1, 'L')
       
        # Biais marché
        pdf.set_font('Arial', 'B', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(70, 8, 'Biais Marche:', 0, 0, 'L')
        pdf.set_font('Arial', 'B', 12)
        pdf.set_text_color(*biais_color)
        pdf.cell(0, 8, biais_marche, 0, 1, 'L')
       
        pdf.ln(2)
   
    # Compter les signaux globaux
    total_oversold = sum(1 for v in all_rsi_values if v <= 30)
    total_overbought = sum(1 for v in all_rsi_values if v >= 70)
    total_extreme_oversold = sum(1 for v in all_rsi_values if v <= 20)
    total_extreme_overbought = sum(1 for v in all_rsi_values if v >= 80)
   
    total_bull_div = sum(1 for row in results_data for tf in TIMEFRAMES_DISPLAY if row.get(tf, {}).get('divergence') == 'Haussière')
    total_bear_div = sum(1 for row in results_data for tf in TIMEFRAMES_DISPLAY if row.get(tf, {}).get('divergence') == 'Baissière')
   
    # Affichage signaux globaux avec couleurs vives
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 7, 'Signaux Globaux:', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
   
    pdf.set_text_color(*COLOR_OVERSOLD)
    pdf.cell(0, 6, ' Survente (<30): {} signaux | Extreme (<20): {} signaux'.format(total_oversold, total_extreme_oversold), 0, 1, 'L')
   
    pdf.set_text_color(*COLOR_OVERBOUGHT)
    pdf.cell(0, 6, ' Surachat (>70): {} signaux | Extreme (>80): {} signaux'.format(total_overbought, total_extreme_overbought), 0, 1, 'L')
   
    pdf.set_text_color(*COLOR_BULLISH)
    pdf.cell(0, 6, ' Divergences Haussieres: {} signaux'.format(total_bull_div), 0, 1, 'L')
   
    pdf.set_text_color(*COLOR_BEARISH)
    pdf.cell(0, 6, ' Divergences Baissieres: {} signaux'.format(total_bear_div), 0, 1, 'L')
   
    pdf.ln(5)
   
    # ============================================================================
    # SECTION 2: STATISTIQUES DÉTAILLÉES PAR TIMEFRAME
    # ============================================================================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 230, 250)
    pdf.cell(0, 10, 'STATISTIQUES PAR TIMEFRAME', 0, 1, 'L', True)
    pdf.ln(3)
   
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
       
        rsi_mean = np.mean(valid_rsi) if valid_rsi else 0
       
        stats_by_tf[tf] = {
            'oversold': oversold,
            'overbought': overbought,
            'extreme_oversold': extreme_oversold,
            'extreme_overbought': extreme_overbought,
            'bull_div': bull_div,
            'bear_div': bear_div,
            'rsi_mean': rsi_mean
        }
   
    for tf, stats in stats_by_tf.items():
        pdf.set_font('Arial', 'B', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, 'Timeframe: {}'.format(tf), 0, 1, 'L')
       
        pdf.set_font('Arial', '', 9)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 5, ' RSI Moyen: {:.2f}'.format(stats['rsi_mean']), 0, 1, 'L')
       
        pdf.set_text_color(*COLOR_OVERSOLD)
        pdf.cell(0, 5, ' Survente: {} (<30) | Extreme: {} (<20)'.format(stats['oversold'], stats['extreme_oversold']), 0, 1, 'L')
       
        pdf.set_text_color(*COLOR_OVERBOUGHT)
        pdf.cell(0, 5, ' Surachat: {} (>70) | Extreme: {} (>80)'.format(stats['overbought'], stats['extreme_overbought']), 0, 1, 'L')
       
        pdf.set_text_color(*COLOR_BULLISH)
        pdf.cell(0, 5, ' Divergences Haussieres: {}'.format(stats['bull_div']), 0, 1, 'L')
       
        pdf.set_text_color(*COLOR_BEARISH)
        pdf.cell(0, 5, ' Divergences Baissieres: {}'.format(stats['bear_div']), 0, 1, 'L')
       
        pdf.ln(2)
   
    pdf.ln(3)
   
    # ============================================================================
    # SECTION 3: TOP 15 OPPORTUNITÉS AVEC SCORING
    # ============================================================================
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 230, 250)
    pdf.cell(0, 10, 'TOP 15 OPPORTUNITES (SCORING)', 0, 1, 'L', True)
    pdf.ln(3)
   
    # Calcul des opportunités avec scoring amélioré
    opportunities = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
           
            if pd.notna(rsi_val):
                score = 0
                signal_parts = []
               
                # Scoring RSI
                if rsi_val <= 20:
                    score += 10
                    signal_parts.append("RSI EXTREME BAS")
                elif rsi_val <= 30:
                    score += 7
                    signal_parts.append("RSI SURVENTE")
                elif rsi_val >= 80:
                    score += 10
                    signal_parts.append("RSI EXTREME HAUT")
                elif rsi_val >= 70:
                    score += 7
                    signal_parts.append("RSI SURACHAT")
               
                # Scoring Divergences
                if divergence == 'Haussière':
                    score += 5
                    signal_parts.append("DIV BULL")
                elif divergence == 'Baissière':
                    score += 5
                    signal_parts.append("DIV BEAR")
               
                # Bonus pour signaux multiples
                if len(signal_parts) > 1:
                    score += 3
               
                if score > 0:
                    opportunities.append({
                        'asset': row['Devises'],
                        'tf': tf,
                        'rsi': rsi_val,
                        'signal': ' + '.join(signal_parts),
                        'score': score,
                        'divergence': divergence
                    })
   
    # Trier par score décroissant
    opportunities.sort(key=lambda x: (-x['score'], abs(50 - x['rsi'])))
    top_opps = opportunities[:15]
   
    if top_opps:
        # En-tête du tableau
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(*COLOR_HEADER)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(10, 8, '#', 1, 0, 'C', True)
        pdf.cell(40, 8, 'Actif', 1, 0, 'C', True)
        pdf.cell(15, 8, 'TF', 1, 0, 'C', True)
        pdf.cell(20, 8, 'RSI', 1, 0, 'C', True)
        pdf.cell(20, 8, 'Score', 1, 0, 'C', True)
        pdf.cell(0, 8, 'Signal', 1, 1, 'C', True)
       
        pdf.set_font('Arial', '', 9)
        for i, opp in enumerate(top_opps, 1):
            # Couleur de fond selon le type de signal
            if opp['rsi'] <= 30:
                pdf.set_fill_color(255, 200, 200) # Rouge clair
                pdf.set_text_color(*COLOR_OVERSOLD)
            elif opp['rsi'] >= 70:
                pdf.set_fill_color(200, 255, 200) # Vert clair
                pdf.set_text_color(*COLOR_OVERBOUGHT)
            else:
                pdf.set_fill_color(245, 245, 245)
                pdf.set_text_color(0, 0, 0)
           
            pdf.cell(10, 7, str(i), 1, 0, 'C', True)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(40, 7, opp['asset'], 1, 0, 'L', True)
            pdf.cell(15, 7, opp['tf'], 1, 0, 'C', True)
           
            # RSI avec couleur
            if opp['rsi'] <= 30:
                pdf.set_text_color(*COLOR_OVERSOLD)
            elif opp['rsi'] >= 70:
                pdf.set_text_color(*COLOR_OVERBOUGHT)
            pdf.cell(20, 7, '{:.2f}'.format(opp['rsi']), 1, 0, 'C', True)
           
            # Score avec couleur gradient
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Arial', 'B', 9)
            pdf.cell(20, 7, str(opp['score']), 1, 0, 'C', True)
           
            pdf.set_font('Arial', '', 8)
            pdf.cell(0, 7, opp['signal'], 1, 1, 'L', True)
    else:
        pdf.set_font('Arial', 'I', 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, 'Aucune opportunite significative detectee', 0, 1, 'L')
   
    # ============================================================================
    # NOUVELLE PAGE: GUIDE COMPLET POUR L'IA
    # ============================================================================
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(255, 220, 100)
    pdf.cell(0, 12, 'GUIDE COMPLET POUR L\'ANALYSE IA', 0, 1, 'C', True)
    pdf.ln(5)
   
    # Section 1: Interprétation des métriques RSI
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(0, 8, '1. INTERPRETATION DES METRIQUES RSI', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*COLOR_OVERSOLD)
    pdf.cell(0, 6, 'Zones de Survente (RSI < 30):', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, ' - RSI < 20: EXTREME - Signal d\'achat tres fort, potentiel rebond imminent\n - RSI 20-30: MODERE - Signal d\'achat, attendre confirmation\n - Action: Rechercher des signaux de retournement (divergences, patterns chandelier)')
    pdf.ln(2)
   
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*COLOR_OVERBOUGHT)
    pdf.cell(0, 6, 'Zones de Surachat (RSI > 70):', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, ' - RSI > 80: EXTREME - Signal de vente tres fort, correction probable\n - RSI 70-80: MODERE - Signal de vente, surveiller\n - Action: Envisager prise de profits ou positions short')
    pdf.ln(2)
   
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, 'Zone Neutre (RSI 30-70):', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, ' - Pas de signal clair de surachat/survente\n - Analyser les divergences et tendances pour identifier opportunites')
    pdf.ln(3)
   
    # Section 2: Divergences
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(230, 255, 230)
    pdf.cell(0, 8, '2. INTERPRETATION DES DIVERGENCES', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*COLOR_BULLISH)
    pdf.cell(0, 6, 'Divergence Haussiere (BULL):', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, ' - Definition: Prix fait des creux plus bas MAIS RSI fait des creux plus hauts\n - Signification: La pression vendeuse s\'affaiblit, potentiel retournement haussier\n - Action: Signal d\'ACHAT - Entrer en position longue avec stop-loss sous dernier creux\n - Force maximale: Quand combinee avec RSI < 30 (survente)')
    pdf.ln(2)
   
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*COLOR_BEARISH)
    pdf.cell(0, 6, 'Divergence Baissiere (BEAR):', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, ' - Definition: Prix fait des sommets plus hauts MAIS RSI fait des sommets plus bas\n - Signification: La pression acheteuse s\'affaiblit, potentiel retournement baissier\n - Action: Signal de VENTE - Entrer en position short avec stop-loss au-dessus dernier sommet\n - Force maximale: Quand combinee avec RSI > 70 (surachat)')
    pdf.ln(3)
   
    # Section 3: Scoring et priorisation
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(255, 240, 230)
    pdf.cell(0, 8, '3. SYSTEME DE SCORING ET PRIORISATION', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 5, 'Le score calcule la force du signal:\n\n Score 10+ (TRES FORT):\n - RSI extreme (<20 ou >80) seul = 10 pts\n - RSI extreme + divergence = 15 pts\n - Action: Opportunite prioritaire, analyser immediatement\n\n Score 7-9 (FORT):\n - RSI modere (<30 ou >70) = 7 pts\n - RSI modere + divergence = 12 pts\n - Action: Bonne opportunite, valider avec contexte\n\n Score 5-6 (MOYEN):\n - Divergence seule = 5 pts\n - Action: Signal interessant mais necessitant confirmation\n\n Bonus +3: Signaux multiples (RSI + divergence)')
    pdf.ln(3)
   
    # Section 4: Analyse multi-timeframe
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(240, 230, 255)
    pdf.cell(0, 8, '4. ANALYSE MULTI-TIMEFRAME', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', '', 9)
    pdf.multi_cell(0, 5, 'Comment interpreter les differents timeframes:\n\n Weekly (W1) - Vision macro:\n - Definit la tendance de fond\n - Signaux les plus fiables mais plus lents\n - Ideal pour: Positions long-terme, identification de retournements majeurs\n\n Daily (D1) - Vision intermediaire:\n - Equilibre entre fiabilite et reactivite\n - Confirme ou infirme les signaux court terme\n - Ideal pour: Swing trading, validation des entrees\n\n H4 - Vision court terme:\n - Signaux plus frequents mais moins fiables\n - Bon pour timing d\'entree precis\n - Ideal pour: Day trading, optimisation des points d\'entree\n\n H1 - Vision tres court terme:\n - Signaux tres reactifs mais bruites\n - Utiliser uniquement pour timing intraday\n - Ideal pour: Scalping, ajustements rapides')
    pdf.ln(3)
   
    # Section 5: Confluence de signaux
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(255, 230, 230)
    pdf.cell(0, 8, '5. RECHERCHE DE CONFLUENCE (SIGNAUX CONCORDANTS)', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', '', 9)
    pdf.multi_cell(0, 5, 'Les meilleurs trades combinent plusieurs signaux:\n\n Confluence MAXIMALE (Score 20+):\n - RSI extreme sur 2+ timeframes\n - Divergence sur timeframe superieur\n - Exemple: EUR/USD survente (<20) en Daily + H4 avec div bull en Daily\n\n Confluence FORTE (Score 15-20):\n - RSI extreme sur 1 TF + RSI modere sur TF superieur\n - Divergence confirmee sur 2 TF\n\n Signaux CONTRADICTOIRES (a eviter):\n - RSI survente en H1 mais surachat en Daily\n - Divergence bull en H4 mais bear en Daily\n - Action: Attendre clarification ou eviter le trade')
    pdf.ln(3)
   
    # Section 6: Contexte de marché
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(230, 255, 255)
    pdf.cell(0, 8, '6. INTEGRATION DU CONTEXTE MARCHE', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', '', 9)
    pdf.multi_cell(0, 5, 'Elements contextuels a considerer:\n\n Biais Marche Global:\n - RSI moyen < 40: Marche baissier - Privilegier signaux de vente\n - RSI moyen > 60: Marche haussier - Privilegier signaux d\'achat\n - RSI moyen 40-60: Marche neutre - Trader les extremes\n\n Calendrier Economique:\n - Avant annonce majeure: Reduire positions ou eviter nouveaux trades\n - Apres annonce: Attendre stabilisation (15-30min) avant d\'agir\n\n Correlations:\n - USD fort + survente EUR/USD = opportunite achat limitee\n - Or survente + indices surachetes = potentiel risk-off\n\n Sentiment:\n - Beaucoup de surventes = capitulation possible (bullish)\n - Beaucoup de surachats = euphorie (bearish)')
    pdf.ln(3)
   
    # Section 7: Questions clés pour l'IA
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(255, 220, 100)
    pdf.cell(0, 10, 'QUESTIONS CLES POUR ANALYSE IA', 0, 1, 'L', True)
    pdf.ln(3)
   
    questions = [
        ('Analyse des Top Opportunites', [
            'Quelles sont les 3 opportunites avec le score le plus eleve?',
            'Ces opportunites sont-elles confirmees sur plusieurs timeframes?',
            'Y a-t-il des risques specifiques a chaque opportunite?'
        ]),
        ('Confluence Multi-Timeframe', [
            'Quels actifs montrent des signaux concordants sur 2+ timeframes?',
            'Y a-t-il des divergences entre timeframes courts et longs?',
            'Quel timeframe offre le meilleur ratio risque/rendement?'
        ]),
        ('Contexte de Marche', [
            'Le biais marche global favorise-t-il les achats ou ventes?',
            'Y a-t-il une concentration sectorielle des signaux?',
            'Les correlations habituelles sont-elles respectees?'
        ]),
        ('Gestion du Risque', [
            'Quels trades ont le meilleur ratio score/risque?',
            'Y a-t-il trop de positions dans une meme direction?',
            'Quel serait l\'impact d\'une annonce economique majeure?'
        ]),
        ('Timing d\'Execution', [
            'Quels trades sont a executer en priorite (score + timing)?',
            'Quels signaux necessitent une confirmation supplementaire?',
            'Y a-t-il des trades a eviter malgre un score eleve?'
        ])
    ]
   
    for section, qs in questions:
        pdf.set_font('Arial', 'B', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, section + ':', 0, 1, 'L')
        pdf.set_font('Arial', '', 9)
        for q in qs:
            pdf.cell(5, 5, '', 0, 0)
            pdf.multi_cell(0, 5, '- ' + q)
        pdf.ln(2)
   
    # Section 8: Template d'analyse
    pdf.ln(3)
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, 'TEMPLATE D\'ANALYSE QUOTIDIENNE', 0, 1, 'L', True)
    pdf.ln(2)
   
    pdf.set_font('Arial', '', 9)
    pdf.multi_cell(0, 5, 'Pour chaque opportunite Top 5:\n\n1. Actif: _______________\n2. Score: ___ | RSI: ___ | Timeframe: ___\n3. Type signal: Survente / Surachat / Divergence\n4. Confluence TF: Oui / Non - Details: _______________\n5. Coherence avec biais marche:')

    return bytes(pdf.output())

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
        with st.spinner("Scan en cours..."):
            run_analysis_process()
        st.success("Analyse terminée!")
        st.rerun()
    elif 'scan_done' in st.session_state and not st.session_state.scan_done:
        with st.spinner("Scan en cours..."):
            run_analysis_process()
        st.success("Analyse terminée!")
        st.rerun()

if 'results' in st.session_state and st.session_state.results:
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ 20)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ 80)</span></div>
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
            oversold = sum(1 for x in valid_rsi if x <= 20)
            overbought = sum(1 for x in valid_rsi if x >= 80)
            total = oversold + overbought + bull_div + bear_div
            delta_text = "🔴 {} S | 🟢 {} B | ↑ {} | ↓ {}".format(oversold, overbought, bull_div, bear_div)
            with stat_cols[i]:
                st.metric(label="Signals {}".format(tf), value=str(total))
                st.markdown(delta_text, unsafe_allow_html=True)
        else:
            with stat_cols[i]: 
                st.metric(label="Signals {}".format(tf), value="N/A")

with st.expander("ℹ️ Configuration", expanded=False):
    st.markdown("""
    **Data Source:** OANDA v20 API (practice account)
    **RSI Period:** 10 | **Source:** OHLC4
    **Divergence:** Last 30 candles
    """)
