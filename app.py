import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import threading
import logging
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from fpdf import FPDF
import concurrent.futures
import time
import random
import json
import io

# --- CONFIGURATION ---
warnings.filterwarnings('ignore')

# Logging (remplace les except silencieux)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("rsi_screener")

RSI_PERIOD     = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
MAX_RETRIES    = 3
API_TIMEOUT    = 10  # secondes — FIX #3 : timeout explicite

# FIX #11 — Rate-limiter : max 3 requêtes OANDA simultanées
_oanda_semaphore = threading.Semaphore(3)

st.set_page_config(
    page_title="RSI & Divergence Screener Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS STYLES ---
st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 28px; font-weight: bold; color: #FAFAFA; margin-bottom: 15px; text-align: center; }
    .update-info { background-color: #262730; padding: 8px 15px; border-radius: 5px; margin-bottom: 20px;
                   font-size: 14px; color: #A9A9A9; border: 1px solid #333A49; text-align: center; }
    .legend-container { display: flex; justify-content: center; flex-wrap: wrap; gap: 25px; margin: 25px 0;
                        padding: 15px; border-radius: 5px; background-color: #1A1C22; }
    .legend-item { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #D3D3D3; }
    .legend-dot { width: 12px; height: 12px; border-radius: 50%; }
    .oversold-dot { background-color: #FF4B4B; }
    .overbought-dot { background-color: #3D9970; }
    h3 { color: #EAEAEA; text-align: center; margin-top: 30px; margin-bottom: 15px; }
    .rsi-table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px;
                 box-shadow: 0 4px 8px 0 rgba(0,0,0,0.1); }
    .rsi-table th { background-color: #333A49; color: #EAEAEA !important; padding: 14px 10px;
                    text-align: center; font-weight: bold; font-size: 15px; border: 1px solid #262730; }
    .rsi-table td { padding: 12px 10px; text-align: center; border: 1px solid #262730; font-size: 14px; }
    .devises-cell { font-weight: bold !important; color: #E0E0E0 !important; font-size: 15px !important;
                    text-align: left !important; padding-left: 15px !important; }
    .oversold-cell { background-color: rgba(255, 75, 75, 0.7) !important; color: white !important; font-weight: bold; }
    .overbought-cell { background-color: rgba(61, 153, 112, 0.7) !important; color: white !important; font-weight: bold; }
    .neutral-cell { color: #C0C0C0 !important; background-color: #161A1D; }
    .divergence-arrow { font-size: 20px; font-weight: bold; vertical-align: middle; margin-left: 6px; }
    .bullish-arrow { color: #3D9970; }
    .bearish-arrow { color: #FF4B4B; }
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #D32F2F; color: white; border: 1px solid #B71C1C; transition: all 0.2s;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover {
        background-color: #B71C1C; border-color: #D32F2F; box-shadow: 0 4px 12px rgba(211,47,47,0.4);
    }
    div[data-testid="stButton"] > button[kind="primary"]:active {
        background-color: #D32F2F; transform: scale(0.98);
    }
    div[data-testid="stButton"] > button { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# --- SECRETS OANDA ---
try:
    OANDA_ACCOUNT_ID   = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except KeyError:
    st.error("Secrets non trouvés ! Vérifiez votre fichier .streamlit/secrets.toml")
    st.stop()

# ===================== ASSETS — LISTE CANONIQUE 33 INSTRUMENTS =====================
ASSETS = [
    # 28 paires Forex
    'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'USD/CAD', 'AUD/USD', 'NZD/USD',
    'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD',
    'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/CAD', 'GBP/NZD',
    'AUD/JPY', 'AUD/CAD', 'AUD/CHF', 'AUD/NZD',
    'CAD/JPY', 'CAD/CHF', 'CHF/JPY', 'NZD/JPY', 'NZD/CAD', 'NZD/CHF',
    # 4 indices + 1 métal
    'DE30/EUR', 'XAU/USD', 'SPX500/USD', 'NAS100/USD', 'US30/USD',
]

# FIX #8 — Assets indices : historique limité sur TF longs
INDEX_ASSETS = {'DE30/EUR', 'SPX500/USD', 'NAS100/USD', 'US30/USD'}

TIMEFRAMES_DISPLAY    = ['H1', 'H4', 'Daily', 'Weekly', 'Monthly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D',     'W',      'M']

CANDLE_COUNT = {'H1': 200, 'H4': 200, 'D': 150, 'W': 100, 'M': 60}
# Comptages réduits pour les indices (données moins disponibles sur OANDA)
CANDLE_COUNT_INDEX = {'H1': 200, 'H4': 200, 'D': 100, 'W': 52, 'M': 24}

DIVERGENCE_LOOKBACK = {'H1': 40, 'H4': 35, 'D': 30, 'W': 20, 'M': 15}


# =============================================================================
# INDICATEURS
# =============================================================================

def calculate_rsi(prices, period=RSI_PERIOD):
    """
    RSI Wilder (EWM).
    FIX #7 — nécessite 2×period bougies pour une valeur stable (au lieu de period+1).
    """
    try:
        if prices is None or len(prices) < 2 * period:
            return np.nan, None
        close_prices = prices['Close']
        delta      = close_prices.diff()
        gains      = delta.where(delta > 0, 0.0)
        losses     = -delta.where(delta < 0, 0.0)
        avg_gains  = gains.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        avg_losses = losses.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        rs = avg_gains / avg_losses
        rs[avg_losses == 0] = np.inf
        rsi_series = 100.0 - (100.0 / (1.0 + rs))
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return np.nan, None
        return rsi_series.iloc[-1], rsi_series
    except Exception as e:
        logger.warning("calculate_rsi error: %s", e)
        return np.nan, None


def detect_divergence(price_data, rsi_series, timeframe_key):
    """
    Détection divergence avec lookback adaptatif par TF.
    FIX #4 — utilise .values (numpy) pour éviter tout bug d'alignement d'index
              entre price_data et rsi_series après slicing.
    """
    if rsi_series is None or len(price_data) < 10:
        return "Aucune"
    lookback = DIVERGENCE_LOOKBACK.get(timeframe_key, 30)
    if len(price_data) < lookback:
        lookback = len(price_data)

    distance_map  = {'H1': 3, 'H4': 5, 'D': 4, 'W': 3, 'M': 2}
    peak_distance = distance_map.get(timeframe_key, 5)

    recent_price = price_data.iloc[-lookback:]
    recent_rsi   = rsi_series.iloc[-lookback:]

    # Conversion en tableaux numpy — alignement garanti, pas de jeu d'index
    price_high = recent_price['High'].values
    price_low  = recent_price['Low'].values
    rsi_vals   = recent_rsi.values

    # Divergence baissière
    price_peaks_idx, _ = find_peaks(price_high, distance=peak_distance)
    if len(price_peaks_idx) >= 2:
        lp, pp = price_peaks_idx[-1], price_peaks_idx[-2]
        if price_high[lp] > price_high[pp] and rsi_vals[lp] < rsi_vals[pp]:
            return "Baissière"

    # Divergence haussière
    price_troughs_idx, _ = find_peaks(-price_low, distance=peak_distance)
    if len(price_troughs_idx) >= 2:
        lt, pt = price_troughs_idx[-1], price_troughs_idx[-2]
        if price_low[lt] < price_low[pt] and rsi_vals[lt] > rsi_vals[pt]:
            return "Haussière"

    return "Aucune"


# =============================================================================
# FETCH OANDA
# =============================================================================

@st.cache_data(ttl=600, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key):
    """
    Fetch OANDA avec retry, timeout et rate-limit semaphore.
    FIX #3  — timeout=API_TIMEOUT sur chaque requête.
    FIX #11 — semaphore pour limiter la concurrence à 3 requêtes simultanées.
    FIX #8  — CANDLE_COUNT adapté selon le type d'asset (indice vs forex).
    """
    is_index = pair in INDEX_ASSETS
    count_map = CANDLE_COUNT_INDEX if is_index else CANDLE_COUNT
    count     = count_map.get(timeframe_key, 150)

    instrument = pair.replace('/', '_')
    params     = {'granularity': timeframe_key, 'count': count}

    for attempt in range(MAX_RETRIES):
        try:
            # FIX #11 — acquis le semaphore avant la requête réseau
            with _oanda_semaphore:
                time.sleep(random.uniform(0.05, 0.15))
                # FIX #3 — timeout via request_params
                api_client = API(
                    access_token=OANDA_ACCESS_TOKEN,
                    environment="practice",
                    request_params={"timeout": API_TIMEOUT}
                )
                r = instruments.InstrumentsCandles(instrument=instrument, params=params)
                api_client.request(r)

            data_list = []
            for c in r.response['candles']:
                if c['complete']:
                    data_list.append({
                        'Time':   c['time'],
                        'Open':   float(c['mid']['o']),
                        'High':   float(c['mid']['h']),
                        'Low':    float(c['mid']['l']),
                        'Close':  float(c['mid']['c']),
                        'Volume': int(c['volume'])
                    })
            if not data_list:
                logger.warning("fetch_forex_data_oanda: no candles for %s %s", pair, timeframe_key)
                return None
            df = pd.DataFrame(data_list)
            df['Time'] = pd.to_datetime(df['Time'])
            df.set_index('Time', inplace=True)
            return df

        except Exception as e:
            logger.warning(
                "fetch_forex_data_oanda attempt %d/%d failed for %s %s: %s",
                attempt + 1, MAX_RETRIES, pair, timeframe_key, e
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))  # backoff progressif

    return None


# =============================================================================
# HELPERS UI
# =============================================================================

def format_rsi(value):
    return "N/A" if pd.isna(value) else f"{value:.2f}"

def get_rsi_class(value):
    if pd.isna(value):            return "neutral-cell"
    elif value <= RSI_OVERSOLD:   return "oversold-cell"
    elif value >= RSI_OVERBOUGHT: return "overbought-cell"
    return "neutral-cell"

# FIX #10 — Encodage latin-1 sûr pour FPDF (Arial intégré ne supporte pas UTF-8)
def _pdf_str(text):
    """Convertit une chaîne UTF-8 en latin-1 en remplaçant les caractères inconnus."""
    return text.encode('latin-1', errors='replace').decode('latin-1')


# =============================================================================
# TRAITEMENT D'UN ASSET
# =============================================================================

def process_single_asset(pair_name):
    row_data = {'Devises': pair_name}
    for tf_key, tf_display_name in zip(TIMEFRAMES_FETCH_KEYS, TIMEFRAMES_DISPLAY):
        data_ohlc             = fetch_forex_data_oanda(pair_name, tf_key)
        rsi_value, rsi_series = calculate_rsi(data_ohlc)
        divergence_signal     = "Aucune"
        if data_ohlc is not None and rsi_series is not None:
            divergence_signal = detect_divergence(data_ohlc, rsi_series, tf_key)
        row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}
    return row_data


def run_analysis_process():
    results_list = []
    progress_bar = st.progress(0)
    status_text  = st.empty()
    status_text.text("Initialisation du scan parallèle...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_asset = {
            executor.submit(process_single_asset, asset): asset
            for asset in ASSETS
        }
        completed = 0
        total     = len(ASSETS)
        for future in concurrent.futures.as_completed(future_to_asset):
            asset_name = future_to_asset[future]
            try:
                data = future.result()
                if data:
                    results_list.append(data)
            except Exception as e:
                # FIX #5 — log au lieu de pass silencieux
                logger.error("process_single_asset failed for %s: %s", asset_name, e)
            completed += 1
            progress_bar.progress(completed / total)
            status_text.text(f"Scan terminé : {asset_name} ({completed}/{total})")

    results_list.sort(key=lambda x: ASSETS.index(x['Devises']))

    st.session_state.results        = results_list
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done      = True

    # FIX #9 — Génération des exports une seule fois après le scan
    scan_ts = st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M:%S")
    st.session_state.pdf_data  = create_pdf_report(results_list, scan_ts)
    st.session_state.json_data = create_json_export(results_list)
    st.session_state.csv_data  = create_csv_export(results_list)

    status_text.empty()
    progress_bar.empty()


# =============================================================================
# EXPORTS
# =============================================================================

def _flatten_results(results_data):
    """Structure plate commune à JSON / CSV."""
    records = []
    for row in results_data:
        record = {"Devises": row["Devises"]}
        for tf in TIMEFRAMES_DISPLAY:
            cell = row.get(tf, {})
            rsi  = cell.get("rsi", np.nan)
            record[f"RSI_{tf}"] = round(float(rsi), 2) if pd.notna(rsi) else None
            record[f"DIV_{tf}"] = cell.get("divergence", "Aucune")
        records.append(record)
    return records


def create_json_export(results_data):
    """Export JSON — une ligne par paire, colonnes RSI_<TF> et DIV_<TF>."""
    return json.dumps(_flatten_results(results_data), ensure_ascii=False, indent=2).encode("utf-8")


def create_csv_export(results_data):
    """
    Export CSV compatible Excel (BOM UTF-8).
    Une ligne par paire, colonnes RSI_<TF> et DIV_<TF> pour chaque timeframe.
    """
    df = pd.DataFrame(_flatten_results(results_data))
    return df.to_csv(index=False).encode("utf-8-sig")  # utf-8-sig = BOM pour Excel


def create_pdf_report(results_data, last_scan_time):
    """
    FIX #10 — Tous les textes passent par _pdf_str() pour l'encodage latin-1.
    Contenu : résumé global + stats TF + tableau complet paires × TF.
    """
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(20, 20, 20)
            self.cell(0, 10, _pdf_str('MARKET SCANNER - RAPPORT STRATEGIQUE'), 0, 1, 'C')
            self.set_font('Arial', 'I', 9)
            self.set_text_color(100, 100, 100)
            self.cell(0, 5, _pdf_str('Genere le: ' + str(last_scan_time)), 0, 1, 'C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(150, 150, 150)
            self.cell(
                0, 10,
                _pdf_str('Page ' + str(self.page_no()) + ' | Analyse technique automatisee'),
                0, 0, 'C'
            )

    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    C_BG_HEADER   = (44,  62,  80)
    C_TEXT_HEADER = (255, 255, 255)
    C_OVERSOLD    = (220, 20,  60)
    C_OVERBOUGHT  = (0,   180, 80)
    C_NEUTRAL_BG  = (240, 240, 240)
    C_TEXT_DARK   = (10,  10,  10)

    # --- Métriques globales ---
    all_rsi_values, total_bull_div, total_bear_div = [], 0, 0
    extreme_oversold_count = extreme_overbought_count = 0

    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            data = row.get(tf, {})
            rsi  = data.get('rsi')
            div  = data.get('divergence')
            if pd.notna(rsi):
                all_rsi_values.append(rsi)
                if rsi <= 20: extreme_oversold_count   += 1
                if rsi >= 80: extreme_overbought_count += 1
            if div == 'Haussière': total_bull_div += 1
            if div == 'Baissière': total_bear_div += 1

    avg_global_rsi = np.mean(all_rsi_values) if all_rsi_values else 50.0
    if avg_global_rsi < 45:   market_bias = "BEARISH (Pression Vendeuse)"
    elif avg_global_rsi > 55: market_bias = "BULLISH (Pression Acheteuse)"
    else:                     market_bias = "NEUTRE / INCERTAIN"
    bias_color = (
        C_OVERSOLD   if avg_global_rsi < 45 else
        C_OVERBOUGHT if avg_global_rsi > 55 else
        (100, 100, 100)
    )

    # --- PAGE 1 ---
    pdf.add_page()

    # Résumé global
    pdf.set_fill_color(245, 247, 250)
    pdf.rect(10, 25, 277, 35, 'F')
    pdf.set_xy(15, 30)
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.cell(50, 8, _pdf_str("BIAIS DE MARCHE:"), 0, 0, 'L')
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(*bias_color)
    pdf.cell(100, 8, _pdf_str(market_bias), 0, 1, 'L')
    pdf.set_xy(15, 40)
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.set_font('Arial', '', 10)
    pdf.cell(
        0, 6,
        _pdf_str(
            f"RSI Moyen Global: {avg_global_rsi:.2f} | "
            f"Signaux Extremes (<20/>80): {extreme_oversold_count + extreme_overbought_count}"
        ),
        0, 1, 'L'
    )
    pdf.cell(
        0, 6,
        _pdf_str(
            f"Divergences: {total_bull_div} Haussieres (BULL) vs {total_bear_div} Baissieres (BEAR)"
        ),
        0, 1, 'L'
    )
    pdf.ln(15)

    # Stats par TF
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, _pdf_str("STATISTIQUES PAR TIMEFRAME"), 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    for tf in TIMEFRAMES_DISPLAY:
        tf_data   = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        c_eos  = sum(1 for x in valid_rsi if x <= 20)
        c_os   = sum(1 for x in valid_rsi if x <= 30)
        c_eob  = sum(1 for x in valid_rsi if x >= 80)
        c_ob   = sum(1 for x in valid_rsi if x >= 70)
        c_bull = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        c_bear = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        pdf.cell(
            0, 6,
            _pdf_str(
                f"[{tf}] :: <20: {c_eos} | <30: {c_os} || "
                f">80: {c_eob} | >70: {c_ob} || "
                f"DIV.BULL: {c_bull} | DIV.BEAR: {c_bear}"
            ),
            0, 1, 'L'
        )
    pdf.ln(5)

    # Tableau complet
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(*C_BG_HEADER)
    pdf.set_text_color(*C_TEXT_HEADER)
    w_pair = 40
    w_tf   = (277 - w_pair) / len(TIMEFRAMES_DISPLAY)
    pdf.cell(w_pair, 9, _pdf_str("Paire"), 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(w_tf, 9, _pdf_str(tf), 1, 0, 'C', True)
    pdf.ln()

    pdf.set_font('Arial', '', 9)
    for row in results_data:
        pdf.set_fill_color(*C_NEUTRAL_BG)
        pdf.set_text_color(*C_TEXT_DARK)
        pdf.cell(w_pair, 8, _pdf_str(row['Devises']), 1, 0, 'C', True)
        for tf in TIMEFRAMES_DISPLAY:
            cell = row.get(tf, {})
            val  = cell.get('rsi', np.nan)
            div  = cell.get('divergence', 'Aucune')
            if pd.notna(val):
                if val <= 20:   pdf.set_fill_color(255, 100, 100); pdf.set_text_color(255, 255, 255)
                elif val <= 30: pdf.set_fill_color(*C_OVERSOLD);   pdf.set_text_color(255, 255, 255)
                elif val >= 80: pdf.set_fill_color(100, 255, 100); pdf.set_text_color(0,   0,   0)
                elif val >= 70: pdf.set_fill_color(*C_OVERBOUGHT); pdf.set_text_color(255, 255, 255)
                else:           pdf.set_fill_color(*C_NEUTRAL_BG); pdf.set_text_color(*C_TEXT_DARK)
            else:
                pdf.set_fill_color(*C_NEUTRAL_BG)
                pdf.set_text_color(*C_TEXT_DARK)

            txt = f"{val:.2f}" if pd.notna(val) else "N/A"
            if div == 'Haussière':   txt += " (BULL)"
            elif div == 'Baissière': txt += " (BEAR)"
            pdf.cell(w_tf, 8, _pdf_str(txt), 1, 0, 'C', True)
        pdf.ln()

    return bytes(pdf.output())


# =============================================================================
# MAIN UI
# =============================================================================

st.markdown('<h1 class="screener-header">Screener RSI & Divergence Pro</h1>', unsafe_allow_html=True)

if 'scan_done' in st.session_state and st.session_state.scan_done:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(
        f'<div class="update-info">Dernière mise à jour : {last_scan_time_str}</div>',
        unsafe_allow_html=True
    )

# FIX #9 — Boutons export utilisent les données pré-calculées dans session_state
col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])

with col2:
    if st.button("Rescan", use_container_width=True):
        st.session_state.scan_done = False
        # FIX #14 — Invalide uniquement le cache des données OANDA (pas tout le cache)
        fetch_forex_data_oanda.clear()
        st.rerun()

with col3:
    if st.session_state.get('pdf_data'):
        st.download_button(
            label="⬇ PDF",
            data=st.session_state.pdf_data,
            file_name=f"RSI_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

with col4:
    if st.session_state.get('json_data'):
        st.download_button(
            label="⬇ JSON",
            data=st.session_state.json_data,
            file_name=f"RSI_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True
        )

with col5:
    if st.session_state.get('csv_data'):
        st.download_button(
            label="⬇ CSV",
            data=st.session_state.csv_data,
            file_name=f"RSI_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )

if 'scan_done' not in st.session_state or not st.session_state.scan_done:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("LANCER LE SCAN COMPLET", type="primary", use_container_width=True):
        run_analysis_process()
        st.rerun()

if st.session_state.get('results'):
    st.markdown(f"""
    <div class="legend-container">
        <div class="legend-item">
            <div class="legend-dot oversold-dot"></div>
            <span>Oversold (RSI &le; {RSI_OVERSOLD})</span>
        </div>
        <div class="legend-item">
            <div class="legend-dot overbought-dot"></div>
            <span>Overbought (RSI &ge; {RSI_OVERBOUGHT})</span>
        </div>
        <div class="legend-item">
            <span class="divergence-arrow bullish-arrow">&#8593;</span>
            <span>Bullish Divergence</span>
        </div>
        <div class="legend-item">
            <span class="divergence-arrow bearish-arrow">&#8595;</span>
            <span>Bearish Divergence</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### RSI & Divergence Analysis Results")
    html_table = '<table class="rsi-table"><thead><tr><th>Devises</th>'
    for tf in TIMEFRAMES_DISPLAY:
        html_table += f'<th>{tf}</th>'
    html_table += '</tr></thead><tbody>'

    for row in st.session_state.results:
        html_table += f'<tr><td class="devises-cell">{row["Devises"]}</td>'
        for tf in TIMEFRAMES_DISPLAY:
            cell_data       = row.get(tf, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val         = cell_data.get('rsi', np.nan)
            divergence      = cell_data.get('divergence', 'Aucune')
            css_class       = get_rsi_class(rsi_val)
            formatted_val   = format_rsi(rsi_val)
            divergence_icon = (
                '<span class="divergence-arrow bullish-arrow">&#8593;</span>' if divergence == "Haussière"
                else '<span class="divergence-arrow bearish-arrow">&#8595;</span>' if divergence == "Baissière"
                else ""
            )
            html_table += f'<td class="{css_class}">{formatted_val} {divergence_icon}</td>'
        html_table += '</tr>'
    html_table += '</tbody></table>'
    st.markdown(html_table, unsafe_allow_html=True)

    st.markdown("### Signal Statistics")
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf in enumerate(TIMEFRAMES_DISPLAY):
        tf_data   = [row.get(tf, {}) for row in st.session_state.results]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        bull_div  = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div  = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        if valid_rsi:
            oversold   = sum(1 for x in valid_rsi if x <= RSI_OVERSOLD)
            overbought = sum(1 for x in valid_rsi if x >= RSI_OVERBOUGHT)
            total      = oversold + overbought + bull_div + bear_div
            with stat_cols[i]:
                st.metric(label=f"Signals {tf}", value=str(total))
                st.markdown(f"S:{oversold} | B:{overbought} | ↑{bull_div} | ↓{bear_div}")
        else:
            with stat_cols[i]:
                st.metric(label=f"Signals {tf}", value="N/A")

with st.expander("Configuration", expanded=False):
    st.markdown(f"""
    **RSI Period:** {RSI_PERIOD} | **Oversold ≤** {RSI_OVERSOLD} | **Overbought ≥** {RSI_OVERBOUGHT}  
    **Bougies Forex:** H1=200 | H4=200 | Daily=150 | Weekly=100 | Monthly=60  
    **Bougies Indices:** H1=200 | H4=200 | Daily=100 | Weekly=52 | Monthly=24  
    **Workers:** 6 Threads | **Semaphore:** 3 req. simultanées | **Timeout:** {API_TIMEOUT}s | **Cache:** 10 min  
    **Assets:** {len(ASSETS)} instruments ({len(ASSETS) - len(INDEX_ASSETS)} Forex + {len(INDEX_ASSETS)} Indices + 1 Métal)
    """)

# --- END OF FILE app.py ---
