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
import time
import random

# --- CONFIGURATION ---
warnings.filterwarnings('ignore')
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MAX_RETRIES = 3  # Tentatives en cas d'échec API

st.set_page_config(
    page_title="RSI & Divergence Screener Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS STYLES ---
st.markdown(f"""
<style>
    /* Style global */
    .main > div {{ padding-top: 2rem; }}
    .screener-header {{ font-size: 28px; font-weight: bold; color: #FAFAFA; margin-bottom: 15px; text-align: center; }}
    .update-info {{ background-color: #262730; padding: 8px 15px; border-radius: 5px; margin-bottom: 20px; font-size: 14px; color: #A9A9A9; border: 1px solid #333A49; text-align: center; }}
    
    /* Table Styles */
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

    /* BOUTON SCAN ROUGE SPÉCIFIQUE */
    /* On cible le bouton avec l'attribut data-testid="stBaseButton-primary" généré par Streamlit 
       ou on utilise une astuce de conteneur. Ici, on style le bouton primaire en rouge. */
    div[data-testid="stButton"] > button[kind="primary"] {{
        background-color: #D32F2F;
        color: white;
        border: 1px solid #B71C1C;
        transition: all 0.2s;
    }}
    div[data-testid="stButton"] > button[kind="primary"]:hover {{
        background-color: #B71C1C;
        border-color: #D32F2F;
        box-shadow: 0 4px 12px rgba(211, 47, 47, 0.4);
    }}
    div[data-testid="stButton"] > button[kind="primary"]:active {{
        background-color: #D32F2F;
        transform: scale(0.98);
    }}
    
    /* Pour ne pas colorer les autres boutons si on change le type plus tard, 
       on assure que les boutons secondaires restent neutres */
    div[data-testid="stButton"] > button {{
        font-weight: 600;
    }}
</style>
""", unsafe_allow_html=True)

# --- SECRETS OANDA ---
try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except KeyError:
    st.error("🔑 Secrets non trouvés! Vérifiez votre fichier .streamlit/secrets.toml")
    st.stop()

# --- ASSETS CONFIG ---
ASSETS = [
    'EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 
    'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 
    'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF', 
    'XAU/USD', 'XPT/USD', 'US30/USD', 'NAS100/USD', 'SPX500/USD'
]

TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly', 'Monthly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D', 'W', 'M']

# --- FUNCTIONS ---

def calculate_rsi(prices, period=RSI_PERIOD):
    try:
        if prices is None or len(prices) < period + 1: return np.nan, None
        
        close_prices = prices['Close']
        delta = close_prices.diff()
        
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        
        # Everage Wilder's Smoothing
        avg_gains = gains.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        avg_losses = losses.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        
        rs = avg_gains / avg_losses
        rs[avg_losses == 0] = np.inf
        rsi_series = 100.0 - (100.0 / (1.0 + rs))
        
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]): return np.nan, None
        return rsi_series.iloc[-1], rsi_series
    except Exception:
        return np.nan, None

def detect_divergence(price_data, rsi_series, timeframe_key, lookback=30):
    if rsi_series is None or len(price_data) < lookback: return "Aucune"
    
    # DYNAMIC PEAK DISTANCE : Plus le timeframe est grand, plus on augmente la distance entre les pics
    # H1=3, H4=5, D=4, W=3, M=2
    distance_map = {'H1': 3, 'H4': 5, 'D': 4, 'W': 3, 'M': 2}
    peak_distance = distance_map.get(timeframe_key, 5)
    
    recent_price = price_data.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]
    
    # Bearish Divergence (Price Higher, RSI Lower)
    price_peaks_idx, _ = find_peaks(recent_price['High'], distance=peak_distance)
    if len(price_peaks_idx) >= 2:
        last_peak = price_peaks_idx[-1]
        prev_peak = price_peaks_idx[-2]
        if (recent_price['High'].iloc[last_peak] > recent_price['High'].iloc[prev_peak] and 
            recent_rsi.iloc[last_peak] < recent_rsi.iloc[prev_peak]):
            return "Baissière"
            
    # Bullish Divergence (Price Lower, RSI Higher)
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
    """
    Fetch data with retry mechanism to handle API throttling or temporary network issues.
    """
    api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
    instrument = pair.replace('/', '_')
    
    params = {
        'granularity': timeframe_key, 
        'count': 120
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            # Random jitter to prevent synchronized requests
            time.sleep(random.uniform(0.05, 0.2)) 
            
            r = instruments.InstrumentsCandles(instrument=instrument, params=params)
            api.request(r)
            
            data_list = []
            for c in r.response['candles']:
                if c['complete']:
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
            if attempt == MAX_RETRIES - 1:
                # Log error silently or handle as needed
                return None
            time.sleep(1) # Wait before retrying
    return None

def format_rsi(value): 
    return "N/A" if pd.isna(value) else "{:.2f}".format(value)

def get_rsi_class(value):
    if pd.isna(value): return "neutral-cell"
    elif value <= RSI_OVERSOLD: return "oversold-cell"
    elif value >= RSI_OVERBOUGHT: return "overbought-cell"
    return "neutral-cell"

def process_single_asset(pair_name):
    row_data = {'Devises': pair_name}
    for tf_key, tf_display_name in zip(TIMEFRAMES_FETCH_KEYS, TIMEFRAMES_DISPLAY):
        data_ohlc = fetch_forex_data_oanda(pair_name, tf_key)
        rsi_value, rsi_series = calculate_rsi(data_ohlc)
        divergence_signal = "Aucune"
        if data_ohlc is not None and rsi_series is not None:
            # Pass tf_key for dynamic distance calculation
            divergence_signal = detect_divergence(data_ohlc, rsi_series, tf_key)
        row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}
    return row_data

def run_analysis_process():
    results_list = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    status_text.text("Initialisation du scan parallèle...")
    
    # Reduced workers slightly to ensure stability with OANDA limits (8->5 is safer, 8 is faster)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_asset = {executor.submit(process_single_asset, asset): asset for asset in ASSETS}
        completed = 0
        total = len(ASSETS)
        
        for future in concurrent.futures.as_completed(future_to_asset):
            asset_name = future_to_asset[future]
            try:
                data = future.result()
                if data:
                    results_list.append(data)
            except Exception as e:
                # Silent fail for single asset to not stop whole scan
                pass
            
            completed += 1
            progress_bar.progress(completed / total)
            status_text.text(f"Scan terminé: {asset_name} ({completed}/{total})")

    results_list.sort(key=lambda x: ASSETS.index(x['Devises']))
    st.session_state.results = results_list
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done = True
    status_text.empty()
    progress_bar.empty()

# --- PDF GENERATION UPDATED ---
def create_pdf_report(results_data, last_scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(20, 20, 20)
            self.cell(0, 10, 'MARKET SCANNER - RAPPORT STRATEGIQUE', 0, 1, 'C')
            self.set_font('Arial', 'I', 9)
            self.set_text_color(100, 100, 100)
            self.cell(0, 5, 'Genere le: ' + str(last_scan_time), 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, 'Page ' + str(self.page_no()) + ' | Analyse technique automatisee', 0, 0, 'C')

    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    
    C_BG_HEADER = (44, 62, 80)
    C_TEXT_HEADER = (255, 255, 255)
    C_OVERSOLD = (220, 20, 60)
    C_OVERBOUGHT = (0, 180, 80)
    C_NEUTRAL_BG = (240, 240, 240)
    C_TEXT_DARK = (10, 10, 10)
    
    all_rsi_values = []
    total_bull_div = 0
    total_bear_div = 0
    extreme_oversold_count = 0 
    extreme_overbought_count = 0
    
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            data = row.get(tf, {})
            rsi = data.get('rsi')
            div = data.get('divergence')
            if pd.notna(rsi):
                all_rsi_values.append(rsi)
                if rsi <= 20: extreme_oversold_count += 1
                if rsi >= 80: extreme_overbought_count += 1
            if div == 'Haussière': total_bull_div += 1
            if div == 'Baissière': total_bear_div += 1
            
    avg_global_rsi = np.mean(all_rsi_values) if all_rsi_values else 50.0
    
    if avg_global_rsi < 45: market_bias = "BEARISH (Pression Vendeuse)"
    elif avg_global_rsi > 55: market_bias = "BULLISH (Pression Acheteuse)"
    else: market_bias = "NEUTRE / INCERTAIN"
    
    bias_color = C_OVERSOLD if avg_global_rsi < 45 else (C_OVERBOUGHT if avg_global_rsi > 55 else (100, 100, 100))

    pdf.add_page()
    
    pdf.set_fill_color(245, 247, 250)
    pdf.rect(10, 25, 277, 35, 'F')
    
    pdf.set_xy(15, 30)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(50, 8, "BIAIS DE MARCHE:", 0, 0, 'L')
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(*bias_color)
    pdf.cell(100, 8, market_bias, 0, 1, 'L')
    
    pdf.set_xy(15, 40)
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.set_font('Arial', '', 10)
    summary_text = f"RSI Moyen Global: {avg_global_rsi:.2f} | Total Signaux Extremes (<20/>80): {extreme_oversold_count + extreme_overbought_count}"
    pdf.cell(0, 6, summary_text, 0, 1, 'L')
    summary_div = f"Divergences Detectees: {total_bull_div} Haussieres (BULL) vs {total_bear_div} Baissieres (BEAR)"
    pdf.cell(0, 6, summary_div, 0, 1, 'L')
    
    pdf.ln(15)
    
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(*C_BG_HEADER)
    pdf.set_text_color(*C_TEXT_HEADER)
    pdf.cell(0, 10, ' TOP 15 OPPORTUNITES PRIORITAIRES (Scoring Algo)', 0, 1, 'L', True)
    pdf.ln(2)
    
    opportunities = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            
            if pd.notna(rsi_val):
                score = 0
                signal_type = ""
                
                if rsi_val <= 20: 
                    score += 10
                    signal_type = "SURVENTE EXTREME"
                elif rsi_val <= 30: 
                    score += 5
                    signal_type = "SURVENTE"
                elif rsi_val >= 80: 
                    score += 10
                    signal_type = "SURACHAT EXTREME"
                elif rsi_val >= 70: 
                    score += 5
                    signal_type = "SURACHAT"
                
                if divergence == 'Haussière':
                    score += 4
                    signal_type += " + DIV.BULL"
                elif divergence == 'Baissière':
                    score += 4
                    signal_type += " + DIV.BEAR"
                
                if score > 0:
                    opportunities.append({
                        'asset': row['Devises'],
                        'tf': tf,
                        'rsi': rsi_val,
                        'signal': signal_type,
                        'score': score
                    })

    opportunities.sort(key=lambda x: (-x['score'], abs(50 - x['rsi'])))
    top_15 = opportunities[:15]
    
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.cell(15, 8, "#", 1, 0, 'C', True)
    pdf.cell(30, 8, "Actif", 1, 0, 'C', True)
    pdf.cell(20, 8, "TF", 1, 0, 'C', True)
    pdf.cell(25, 8, "RSI", 1, 0, 'C', True)
    pdf.cell(20, 8, "Score", 1, 0, 'C', True)
    pdf.cell(0, 8, "Signal Detecte", 1, 1, 'L', True)
    
    pdf.set_font('Arial', '', 10)
    for i, opp in enumerate(top_15, 1):
        if "SURVENTE" in opp['signal']: pdf.set_text_color(*C_OVERSOLD)
        elif "SURACHAT" in opp['signal']: pdf.set_text_color(*C_OVERBOUGHT)
        else: pdf.set_text_color(*C_TEXT_DARK)
        
        pdf.cell(15, 8, str(i), 1, 0, 'C')
        pdf.cell(30, 8, opp['asset'], 1, 0, 'C')
        pdf.cell(20, 8, opp['tf'], 1, 0, 'C')
        pdf.cell(25, 8, f"{opp['rsi']:.2f}", 1, 0, 'C')
        pdf.cell(20, 8, str(opp['score']), 1, 0, 'C')
        pdf.cell(0, 8, opp['signal'], 1, 1, 'L')
        
    pdf.add_page()
    pdf.set_text_color(*C_TEXT_DARK)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, "STATISTIQUES PAR TIMEFRAME (Vue d'ensemble)", 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    
    for tf in TIMEFRAMES_DISPLAY:
        tf_data = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        
        c_extreme_os = sum(1 for x in valid_rsi if x <= 20)
        c_os = sum(1 for x in valid_rsi if x <= 30)
        c_extreme_ob = sum(1 for x in valid_rsi if x >= 80)
        c_ob = sum(1 for x in valid_rsi if x >= 70)
        c_bull = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        c_bear = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        
        line = f"[{tf}] :: <20 (Extrême): {c_extreme_os} | <30: {c_os} || >80 (Extrême): {c_extreme_ob} | >70: {c_ob} || DIV.BULL: {c_bull} | DIV.BEAR: {c_bear}"
        pdf.cell(0, 6, line, 0, 1, 'L')
        
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(*C_BG_HEADER)
    pdf.set_text_color(*C_TEXT_HEADER)
    
    w_pair = 40
    w_tf = (277 - w_pair) / len(TIMEFRAMES_DISPLAY)
    
    pdf.cell(w_pair, 9, "Paire", 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(w_tf, 9, tf, 1, 0, 'C', True)
    pdf.ln()
    
    pdf.set_font('Arial', '', 9)
    for row in results_data:
        pdf.set_fill_color(*C_NEUTRAL_BG)
        pdf.set_text_color(*C_TEXT_DARK)
        pdf.cell(w_pair, 8, row['Devises'], 1, 0, 'C', True)
        
        for tf in TIMEFRAMES_DISPLAY:
            cell = row.get(tf, {})
            val = cell.get('rsi', np.nan)
            div = cell.get('divergence', 'Aucune')
            
            if pd.notna(val):
                if val <= 20: 
                    pdf.set_fill_color(255, 100, 100)
                    pdf.set_text_color(255, 255, 255)
                elif val <= 30: 
                    pdf.set_fill_color(*C_OVERSOLD)
                    pdf.set_text_color(255, 255, 255)
                elif val >= 80:
                    pdf.set_fill_color(100, 255, 100)
                    pdf.set_text_color(0, 0, 0)
                elif val >= 70:
                    pdf.set_fill_color(*C_OVERBOUGHT)
                    pdf.set_text_color(255, 255, 255)
                else:
                    pdf.set_fill_color(*C_NEUTRAL_BG)
                    pdf.set_text_color(*C_TEXT_DARK)
            else:
                pdf.set_fill_color(*C_NEUTRAL_BG)
                pdf.set_text_color(*C_TEXT_DARK)
                
            txt = f"{val:.2f}" if pd.notna(val) else "N/A"
            if div == 'Haussière': txt += " (BULL)"
            elif div == 'Baissière': txt += " (BEAR)"
            
            pdf.cell(w_tf, 8, txt, 1, 0, 'C', True)
        pdf.ln()

    pdf.add_page()
    pdf.set_text_color(*C_TEXT_DARK)
    
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, "GUIDE D'ANALYSE POUR ASSISTANT IA (CONTEXTE LLM)", 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 6, """Ce document est genere automatiquement pour servir de base a une analyse financiere assistee par IA. Voici les regles strictes d'interpretation des donnees ci-dessus :

1. HIERARCHIE DES SIGNAUX (SCORING)
   - Priorite Absolue : Un RSI < 20 ou > 80 est une anomalie statistique majeure. Cela indique un mouvement de panique (vente) ou d'euphorie (achat). Le retour a la moyenne est probable a court terme.
   - Le "Combo en Or" : Une Divergence + un RSI Extreme sur le meme Timeframe. Probabilite de retournement > 80%.
   - Concordance des Temps : Si H1, H4 et Daily sont tous en zone de survente (ou tous en surachat), le signal est renforce (Tendance lourde).

2. LECTURE DES TIMEFRAMES
   - H1 (1 Heure) : Signal tactique pour entree immediate (Day Trading). Bruit de marche possible.
   - H4 (4 Heures) : Signal Swing Trading. Plus fiable. Indique la tendance pour les 2-3 prochains jours.
   - Weekly : Tendance de fond. Ne pas trader CONTRE un signal Weekly sauf pour du scalping tres court terme.
   - Monthly : Vue d'investissement Long Terme. Un signal Monthly prend des mois a se construire.

3. GESTION DES CONFLITS
   - Si H1 est SURVENTE mais Weekly est SURACHAT : C'est une correction dans une tendance haussiere (Buy the Dip).
   - Si tous les Timeframes sont opposes : Marche en range ou indécis -> RESTER A L'ECART.

4. INTERPRETATION DES DIVERGENCES
   - Divergence Haussiere (BULL) : Le prix fait un plus bas, mais le RSI monte. Indique un epuisement des vendeurs.
   - Divergence Baissiere (BEAR) : Le prix fait un plus haut, mais le RSI descend. Indique un epuisement des acheteurs.

5. BIAIS GLOBAL
   - Utiliser le 'RSI Moyen Global' en page 1 pour determiner si le dollar (USD) ou le Yen (JPY) dominent le marche. Si tout est rouge, chercher quelle devise est le denominateur commun.
""")
    
    return bytes(pdf.output())

# --- MAIN APP UI ---

st.markdown('<h1 class="screener-header">Screener RSI & Divergence Pro</h1>', unsafe_allow_html=True)

if 'scan_done' in st.session_state and st.session_state.scan_done:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown('<div class="update-info">🔄 Dernière mise à jour: {}</div>'.format(last_scan_time_str), unsafe_allow_html=True)

col1, col2, col3 = st.columns([4, 1, 1])

# Bouton Rescan (Secondaire, couleur standard)
with col2:
    if st.button("🔄 Rescan", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

# Bouton Download (Secondaire)
with col3:
    if 'results' in st.session_state and st.session_state.results:
        st.download_button(
            label="📄 PDF",
            data=create_pdf_report(st.session_state.results, st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M:%S")),
            file_name="RSI_Report_{}.pdf".format(datetime.now().strftime('%Y%m%d_%H%M')),
            mime="application/pdf",
            use_container_width=True
        )

# Bouton Lancer le Scan (PRIMAIRE -> ROUGE via CSS)
if 'scan_done' not in st.session_state or not st.session_state.scan_done:
    # On force le bouton à être centré et large avec type='primary'
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚀 LANCER LE SCAN COMPLET", type="primary", use_container_width=True):
        run_analysis_process()
        st.rerun()

if 'results' in st.session_state and st.session_state.results:
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
    **Data Source:** API Private (OANDA)
    **RSI Period:** {RSI_PERIOD} | **Source:** Close Price
    **Thresholds:** Oversold ≤ {RSI_OVERSOLD} | Overbought ≥ {RSI_OVERBOUGHT}
    **Divergence:** Algorithme dynamique adapté au Timeframe
    **Workers:** 6 Threads (Optimisé stabilité)
    """)
# --- END OF FILE app.py ---
