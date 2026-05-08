import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import html as html_lib   # PATCH [Qwen] : échappement HTML table, import io supprimé
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

# --- CONFIGURATION ---

# PATCH [Qwen/Gemini] : suppression de warnings.filterwarnings('ignore')
# Les warnings sont désormais capturés dans les logs
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logging.captureWarnings(True)   # PATCH [Qwen] : warnings Python → logs, plus de suppression silencieuse
logger = logging.getLogger("rsi_screener")

RSI_PERIOD     = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
MAX_RETRIES    = 3
API_TIMEOUT    = 10

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
    # PATCH [Claude] : environment sorti des secrets — évite la bombe à retardement
    # production si seul le token est changé. Valeur par défaut = "practice" (sûre).
    OANDA_ENVIRONMENT  = st.secrets.get("OANDA_ENVIRONMENT", "practice")
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

# PATCH [Qwen] : XAU/USD ajouté aux actifs restreints (historique limité sur OANDA,
# identique aux indices). Renommé RESTRICTED_ASSETS pour clarté.
RESTRICTED_ASSETS = {'DE30/EUR', 'SPX500/USD', 'NAS100/USD', 'US30/USD', 'XAU/USD'}

TIMEFRAMES_DISPLAY    = ['H1', 'H4', 'Daily', 'Weekly', 'Monthly']
TIMEFRAMES_FETCH_KEYS = ['H1', 'H4', 'D',     'W',      'M']

CANDLE_COUNT            = {'H1': 200, 'H4': 200, 'D': 150, 'W': 100, 'M': 60}
CANDLE_COUNT_RESTRICTED = {'H1': 200, 'H4': 200, 'D': 100, 'W': 52,  'M': 24}

DIVERGENCE_LOOKBACK = {'H1': 40, 'H4': 35, 'D': 30, 'W': 20, 'M': 15}

# PATCH [Claude/ChatGPT] : dict de tri pré-calculé — O(1) au lieu de O(n) par élément
ASSET_ORDER = {a: i for i, a in enumerate(ASSETS)}

# PATCH [Gemini] : sémaphore via @st.cache_resource — correctement isolé par instance
# d'application, pas recréé à chaque rerun, thread-safe par construction Streamlit.
# Résout le problème du sémaphore module-level partagé entre sessions.
@st.cache_resource
def get_oanda_semaphore():
    return threading.Semaphore(3)


# =============================================================================
# INDICATEURS
# =============================================================================

def calculate_rsi(prices, period=RSI_PERIOD):
    """
    RSI Wilder (EWM) — version robuste.

    PATCH [Claude/ChatGPT] : correction bug flat market.
    Cas avg_gains==0 ET avg_losses==0 (marché plat) → RSI=50 (neutre)
    au lieu de RSI=100 (faux signal overbought).
    Cas avg_gains>0 ET avg_losses==0 → RSI=100 (correct).
    Warm-up (NaN dans avg_losses) → NaN conservé (correct).

    PATCH [ChatGPT] : utilisation de delta.clip() — plus explicite que .where().
    """
    try:
        if prices is None or len(prices) < 2 * period:
            return np.nan, None

        close_prices = prices['Close']
        delta  = close_prices.diff()
        gains  = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)

        avg_gains  = gains.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        avg_losses = losses.ewm(com=period - 1, adjust=False, min_periods=period).mean()

        # Remplace les 0 par NaN pour éviter la division 0/0 → inf
        avg_losses_safe = avg_losses.replace(0, np.nan)
        rs = avg_gains / avg_losses_safe

        rsi_series = 100.0 - (100.0 / (1.0 + rs))

        # Marché plat : gains==0 ET losses==0 → RSI=50 (neutre, non tradable)
        flat_mask = (avg_gains == 0) & (avg_losses == 0)
        rsi_series[flat_mask] = 50.0

        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return np.nan, None

        return float(rsi_series.iloc[-1]), rsi_series

    except Exception as e:
        logger.warning("calculate_rsi error: %s", e)
        return np.nan, None


def detect_divergence(price_data, rsi_series, timeframe_key):
    """
    Détection divergence avec lookback adaptatif par TF.

    PATCH [Gemini] : fenêtre de tolérance ±2 bougies autour du pic de prix.
    Le RSI peut atteindre son extrême 1-2 bougies avant/après le prix —
    comparer les valeurs exactes génère des faux négatifs. On cherche le
    max/min RSI dans une fenêtre locale autour de chaque pic identifié.

    PATCH [ChatGPT] : seuils MIN_PRICE_DELTA et MIN_RSI_DELTA pour filtrer
    les micro-variations et réduire les faux positifs.
    """
    if rsi_series is None or len(price_data) < 10:
        return "Aucune"

    lookback = DIVERGENCE_LOOKBACK.get(timeframe_key, 30)
    if len(price_data) < lookback:
        lookback = len(price_data)

    distance_map  = {'H1': 3, 'H4': 5, 'D': 4, 'W': 3, 'M': 2}
    peak_distance = distance_map.get(timeframe_key, 5)

    # Seuils anti-bruit
    MIN_PRICE_DELTA = 0.001   # 0.1% de différence minimale entre deux sommets/creux de prix
    MIN_RSI_DELTA   = 2.0     # 2 points de RSI minimum entre deux pics RSI

    recent_price = price_data.iloc[-lookback:]
    recent_rsi   = rsi_series.iloc[-lookback:]

    price_high = recent_price['High'].values
    price_low  = recent_price['Low'].values
    rsi_vals   = recent_rsi.values
    n          = len(rsi_vals)

    def rsi_window_max(idx):
        """Max RSI dans une fenêtre ±2 bougies autour de l'index."""
        lo = max(0, idx - 2)
        hi = min(n, idx + 3)
        return float(np.max(rsi_vals[lo:hi]))

    def rsi_window_min(idx):
        """Min RSI dans une fenêtre ±2 bougies autour de l'index."""
        lo = max(0, idx - 2)
        hi = min(n, idx + 3)
        return float(np.min(rsi_vals[lo:hi]))

    # --- Divergence baissière (higher high prix + lower high RSI) ---
    price_peaks_idx, _ = find_peaks(price_high, distance=peak_distance)
    if len(price_peaks_idx) >= 2:
        pp, lp = price_peaks_idx[-2], price_peaks_idx[-1]
        price_diff_ok = price_high[lp] > price_high[pp] * (1 + MIN_PRICE_DELTA)
        rsi_diff_ok   = rsi_window_max(lp) < rsi_window_max(pp) - MIN_RSI_DELTA
        if price_diff_ok and rsi_diff_ok:
            return "Baissière"

    # --- Divergence haussière (lower low prix + higher low RSI) ---
    price_troughs_idx, _ = find_peaks(-price_low, distance=peak_distance)
    if len(price_troughs_idx) >= 2:
        pt, lt = price_troughs_idx[-2], price_troughs_idx[-1]
        price_diff_ok = price_low[lt] < price_low[pt] * (1 - MIN_PRICE_DELTA)
        rsi_diff_ok   = rsi_window_min(lt) > rsi_window_min(pt) + MIN_RSI_DELTA
        if price_diff_ok and rsi_diff_ok:
            return "Haussière"

    return "Aucune"


# =============================================================================
# FETCH OANDA
# =============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key):
    """
    Fetch OANDA avec retry, timeout, rate-limit et gestion assets restreints.

    PATCH [Claude] : sleep() déplacé AVANT l'acquisition du sémaphore —
    tenir le sémaphore pendant un sleep bloque inutilement les autres threads.

    PATCH [Claude] : api_client instancié une seule fois par appel (hors
    boucle retry) — évite 3 sessions TCP identiques sur chaque tentative.

    PATCH [Claude] : OANDA_ENVIRONMENT lu depuis les secrets.

    PATCH [Qwen] : accès défensif r.response.get('candles', []) et
    vérification de la clé 'mid' avant float() — protège contre payload malformé.

    PATCH [Claude] : ttl réduit de 600→300s. 10 min trop long pour données
    financières live ; 1 min (Gemini) trop agressif pour les rate limits OANDA.
    300s est le bon compromis pour un screener d'analyse.
    """
    # PATCH [Qwen] : utilisation de RESTRICTED_ASSETS (inclut XAU/USD)
    count_map = CANDLE_COUNT_RESTRICTED if pair in RESTRICTED_ASSETS else CANDLE_COUNT
    count     = count_map.get(timeframe_key, 150)

    instrument = pair.replace('/', '_')
    params     = {'granularity': timeframe_key, 'count': count}

    # Client instancié une seule fois par appel (pas à chaque retry)
    api_client = API(
        access_token=OANDA_ACCESS_TOKEN,
        environment=OANDA_ENVIRONMENT,        # PATCH [Claude]
        request_params={"timeout": API_TIMEOUT}
    )

    oanda_semaphore = get_oanda_semaphore()   # PATCH [Gemini] : via cache_resource

    for attempt in range(MAX_RETRIES):
        try:
            # PATCH [Claude] : sleep AVANT le sémaphore, pas à l'intérieur
            time.sleep(random.uniform(0.05, 0.15))

            with oanda_semaphore:
                r = instruments.InstrumentsCandles(instrument=instrument, params=params)
                api_client.request(r)

            data_list = []
            # PATCH [Qwen] : accès défensif au payload
            candles = r.response.get('candles', [])

            for c in candles:
                if not c.get('complete'):
                    continue
                # PATCH [Qwen/Gemini] : vérification clé 'mid' avant float()
                if 'mid' not in c:
                    logger.error("Missing 'mid' key in candle for %s %s : %s", pair, timeframe_key, c)
                    continue
                try:
                    data_list.append({
                        'Time':   c['time'],
                        'Open':   float(c['mid']['o']),
                        'High':   float(c['mid']['h']),
                        'Low':    float(c['mid']['l']),
                        'Close':  float(c['mid']['c']),
                        'Volume': int(c['volume'])
                    })
                except (KeyError, ValueError) as parse_err:
                    logger.error("Candle parse error for %s %s: %s", pair, timeframe_key, parse_err)
                    continue

            if not data_list:
                logger.warning("No complete candles for %s %s", pair, timeframe_key)
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
                time.sleep(1.5 * (attempt + 1))

    logger.error("Fetch definitively failed for %s %s", pair, timeframe_key)
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

def _pdf_str(text):
    """Conversion UTF-8 → latin-1 pour FPDF (Arial intégré ne supporte pas UTF-8)."""
    return text.encode('latin-1', errors='replace').decode('latin-1')


# =============================================================================
# STATISTIQUES CENTRALISÉES
# =============================================================================

def compute_statistics(results_data):
    """
    PATCH [ChatGPT] : calcul centralisé des statistiques — évite de dupliquer
    la logique entre l'UI et le PDF. Appelé une seule fois après le scan.

    PATCH [ChatGPT] : correction du double-comptage dans les buckets RSI.
    L'original comptait c_eos (≤20) ET c_os (≤30), ce qui incluait les ≤20
    dans les deux colonnes — stats biaisées dans le PDF.
    Correction : buckets mutuellement exclusifs 10<x≤20, 20<x≤30, etc.
    """
    global_rsi_values = []
    stats_by_tf = {}

    for tf in TIMEFRAMES_DISPLAY:
        tf_data   = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]

        stats_by_tf[tf] = {
            # PATCH [ChatGPT] : buckets mutuellement exclusifs
            'extreme_oversold':   sum(1 for x in valid_rsi if x <= 20),
            'oversold':           sum(1 for x in valid_rsi if 20 < x <= RSI_OVERSOLD),
            'extreme_overbought': sum(1 for x in valid_rsi if x >= 80),
            'overbought':         sum(1 for x in valid_rsi if RSI_OVERBOUGHT <= x < 80),
            'bull_div':           sum(1 for d in tf_data if d.get('divergence') == 'Haussière'),
            'bear_div':           sum(1 for d in tf_data if d.get('divergence') == 'Baissière'),
            'valid_count':        len(valid_rsi),
        }
        global_rsi_values.extend(valid_rsi)

    avg_global_rsi = float(np.mean(global_rsi_values)) if global_rsi_values else 50.0
    total_bull_div = sum(s['bull_div'] for s in stats_by_tf.values())
    total_bear_div = sum(s['bear_div'] for s in stats_by_tf.values())
    extreme_count  = sum(
        s['extreme_oversold'] + s['extreme_overbought']
        for s in stats_by_tf.values()
    )

    if avg_global_rsi < 45:
        market_bias = "BEARISH (Pression Vendeuse)"
        bias_color  = (220, 20, 60)
    elif avg_global_rsi > 55:
        market_bias = "BULLISH (Pression Acheteuse)"
        bias_color  = (0, 180, 80)
    else:
        market_bias = "NEUTRE / INCERTAIN"
        bias_color  = (100, 100, 100)

    return {
        'by_tf':          stats_by_tf,
        'avg_rsi':        avg_global_rsi,
        'total_bull_div': total_bull_div,
        'total_bear_div': total_bear_div,
        'extreme_count':  extreme_count,
        'market_bias':    market_bias,
        'bias_color':     bias_color,
    }


# =============================================================================
# TRAITEMENT D'UN ASSET
# =============================================================================

def process_single_asset(pair_name):
    """
    PATCH [Qwen] : retourne un champ 'Status' ('OK' / 'PARTIAL' / 'ERROR')
    pour permettre à l'UI d'afficher un feedback visuel en cas de données
    manquantes sans crasher le scan complet.
    """
    row_data = {'Devises': pair_name, 'Status': 'OK'}
    try:
        for tf_key, tf_display_name in zip(TIMEFRAMES_FETCH_KEYS, TIMEFRAMES_DISPLAY):
            data_ohlc = fetch_forex_data_oanda(pair_name, tf_key)

            if data_ohlc is None:
                row_data[tf_display_name] = {'rsi': np.nan, 'divergence': 'Aucune'}
                row_data['Status'] = 'PARTIAL'
                continue

            rsi_value, rsi_series = calculate_rsi(data_ohlc)
            divergence_signal = (
                detect_divergence(data_ohlc, rsi_series, tf_key)
                if rsi_series is not None else "Aucune"
            )
            row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}

    except Exception as e:
        logger.exception("Crash in process_single_asset for %s: %s", pair_name, e)
        row_data['Status'] = 'ERROR'
        for tf in TIMEFRAMES_DISPLAY:
            if tf not in row_data:
                row_data[tf] = {'rsi': np.nan, 'divergence': 'Aucune'}

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

        # PATCH [Claude] : timeout=120s sur as_completed — évite le hang infini
        # si un thread se bloque malgré le timeout API (connexion TCP silencieuse).
        try:
            for future in concurrent.futures.as_completed(future_to_asset, timeout=120):
                asset_name = future_to_asset[future]
                try:
                    data = future.result()
                    if data:
                        results_list.append(data)
                        if data.get('Status') in ('ERROR', 'PARTIAL'):
                            logger.warning("Asset %s: status=%s", asset_name, data.get('Status'))
                except Exception as e:
                    logger.error("Future failed for %s: %s", asset_name, e)
                    results_list.append({
                        'Devises': asset_name,
                        'Status': 'ERROR',
                        **{tf: {'rsi': np.nan, 'divergence': 'Aucune'} for tf in TIMEFRAMES_DISPLAY}
                    })
                completed += 1
                progress_bar.progress(completed / total)
                status_text.text(f"Scan terminé : {asset_name} ({completed}/{total})")

        except concurrent.futures.TimeoutError:
            logger.error("Scan global timeout after 120s — %d/%d assets completed", completed, total)
            st.warning(f"⏱ Timeout du scan après 120s — {completed}/{total} actifs traités.")

    # PATCH [Claude] : tri avec dict O(1) au lieu de ASSETS.index() O(n) par élément,
    # protégé contre un nom d'asset absent de la liste canonique.
    results_list.sort(key=lambda x: ASSET_ORDER.get(x['Devises'], 999))

    st.session_state.results        = results_list
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done      = True

    # Calcul centralisé des stats (PATCH [ChatGPT])
    stats = compute_statistics(results_list)
    st.session_state.stats = stats

    scan_ts = st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M:%S")
    st.session_state.pdf_data  = create_pdf_report(results_list, stats, scan_ts)
    st.session_state.json_data = create_json_export(results_list)
    st.session_state.csv_data  = create_csv_export(results_list)

    status_text.empty()
    progress_bar.empty()


# =============================================================================
# EXPORTS
# =============================================================================

def _flatten_results(results_data):
    records = []
    for row in results_data:
        record = {"Devises": row["Devises"], "Status": row.get("Status", "OK")}
        for tf in TIMEFRAMES_DISPLAY:
            cell = row.get(tf, {})
            rsi  = cell.get("rsi", np.nan)
            record[f"RSI_{tf}"] = round(float(rsi), 2) if pd.notna(rsi) else None
            record[f"DIV_{tf}"] = cell.get("divergence", "Aucune")
        records.append(record)
    return records


def create_json_export(results_data):
    return json.dumps(_flatten_results(results_data), ensure_ascii=False, indent=2).encode("utf-8")


def create_csv_export(results_data):
    df = pd.DataFrame(_flatten_results(results_data))
    return df.to_csv(index=False).encode("utf-8-sig")


# PATCH [Gemini] : classe PDF définie au niveau module — évite la redéfinition
# (et la fuite mémoire associée) à chaque appel de create_pdf_report.
class _ReportPDF(FPDF):
    """Classe PDF interne avec header/footer personnalisés."""
    _scan_ts = ""  # injecté avant chaque génération

    def header(self):
        self.set_font('Arial', 'B', 16)
        self.set_text_color(20, 20, 20)
        self.cell(0, 10, _pdf_str('MARKET SCANNER - RAPPORT STRATEGIQUE'), 0, 1, 'C')
        self.set_font('Arial', 'I', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, _pdf_str('Genere le: ' + self._scan_ts), 0, 1, 'C')
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


def create_pdf_report(results_data, stats, last_scan_time):
    """
    PATCH [ChatGPT] : stats pré-calculées passées en paramètre (compute_statistics),
    plus de double-boucle interne. Buckets mutuellement exclusifs dans l'affichage.

    PATCH [Gemini] : classe PDF au niveau module (voir _ReportPDF).
    """
    C_BG_HEADER   = (44,  62,  80)
    C_TEXT_HEADER = (255, 255, 255)
    C_OVERSOLD    = (220, 20,  60)
    C_OVERBOUGHT  = (0,   180, 80)
    C_NEUTRAL_BG  = (240, 240, 240)
    C_TEXT_DARK   = (10,  10,  10)

    _ReportPDF._scan_ts = str(last_scan_time)
    pdf = _ReportPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    avg_global_rsi = stats['avg_rsi']
    market_bias    = stats['market_bias']
    bias_color     = stats['bias_color']
    total_bull_div = stats['total_bull_div']
    total_bear_div = stats['total_bear_div']
    extreme_count  = stats['extreme_count']

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
        _pdf_str(f"RSI Moyen Global: {avg_global_rsi:.2f} | Signaux Extremes (<20/>80): {extreme_count}"),
        0, 1, 'L'
    )
    pdf.cell(
        0, 6,
        _pdf_str(f"Divergences: {total_bull_div} Haussieres (BULL) vs {total_bear_div} Baissieres (BEAR)"),
        0, 1, 'L'
    )
    pdf.ln(15)

    # Stats par TF — PATCH [ChatGPT] : buckets mutuellement exclusifs
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, _pdf_str("STATISTIQUES PAR TIMEFRAME"), 0, 1, 'L')
    pdf.set_font('Arial', '', 9)

    for tf in TIMEFRAMES_DISPLAY:
        s = stats['by_tf'][tf]
        pdf.cell(
            0, 6,
            _pdf_str(
                f"[{tf}] :: <=20: {s['extreme_oversold']} | 20-30: {s['oversold']} || "
                f">=80: {s['extreme_overbought']} | 70-80: {s['overbought']} || "
                f"DIV.BULL: {s['bull_div']} | DIV.BEAR: {s['bear_div']}"
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

col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])

with col2:
    if st.button("Rescan", use_container_width=True):
        st.session_state.scan_done = False
        # PATCH [Claude] : cache_version par session — invalide le cache de cette session
        # seulement, sans toucher au cache global partagé avec les autres utilisateurs.
        st.session_state.cache_version = st.session_state.get('cache_version', 0) + 1
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

    # PATCH [Qwen] : html.escape() sur les noms de paires — bonne pratique défensive
    # même si le risque XSS est faible ici (noms provenant d'une liste canonique interne).
    html_table = '<table class="rsi-table"><thead><tr><th>Devises</th>'
    for tf in TIMEFRAMES_DISPLAY:
        html_table += f'<th>{tf}</th>'
    html_table += '</tr></thead><tbody>'

    error_count = 0
    for row in st.session_state.results:
        pair_safe    = html_lib.escape(str(row["Devises"]))
        status       = row.get('Status', 'OK')
        status_badge = ""
        if status == 'ERROR':
            status_badge = ' <span style="color:#FF4B4B;font-size:10px;">⚠ERR</span>'
            error_count += 1
        elif status == 'PARTIAL':
            status_badge = ' <span style="color:#FFA500;font-size:10px;">⚠PART</span>'

        html_table += f'<tr><td class="devises-cell">{pair_safe}{status_badge}</td>'
        for tf in TIMEFRAMES_DISPLAY:
            cell_data     = row.get(tf, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val       = cell_data.get('rsi', np.nan)
            divergence    = cell_data.get('divergence', 'Aucune')
            css_class     = get_rsi_class(rsi_val)
            formatted_val = format_rsi(rsi_val)
            divergence_icon = (
                '<span class="divergence-arrow bullish-arrow">&#8593;</span>' if divergence == "Haussière"
                else '<span class="divergence-arrow bearish-arrow">&#8595;</span>' if divergence == "Baissière"
                else ""
            )
            html_table += f'<td class="{css_class}">{formatted_val} {divergence_icon}</td>'
        html_table += '</tr>'
    html_table += '</tbody></table>'
    st.markdown(html_table, unsafe_allow_html=True)

    if error_count > 0:
        st.warning(f"⚠️ {error_count} actif(s) en erreur lors du scan. Vérifiez les logs ou relancez.")

    st.markdown("### Signal Statistics")
    # PATCH [ChatGPT] : stats lues depuis session_state (déjà calculées), pas recalculées
    stats = st.session_state.get('stats') or compute_statistics(st.session_state.results)
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf in enumerate(TIMEFRAMES_DISPLAY):
        s = stats['by_tf'][tf]
        total = (s['extreme_oversold'] + s['oversold'] +
                 s['extreme_overbought'] + s['overbought'] +
                 s['bull_div'] + s['bear_div'])
        with stat_cols[i]:
            st.metric(label=f"Signals {tf}", value=str(total))
            st.markdown(
                f"≤20:{s['extreme_oversold']} | 20-30:{s['oversold']} | "
                f"70-80:{s['overbought']} | ≥80:{s['extreme_overbought']} | "
                f"↑{s['bull_div']} | ↓{s['bear_div']}"
            )

with st.expander("Configuration", expanded=False):
    st.markdown(f"""
    **RSI Period:** {RSI_PERIOD} | **Oversold ≤** {RSI_OVERSOLD} | **Overbought ≥** {RSI_OVERBOUGHT}  
    **Bougies Forex:** H1=200 | H4=200 | Daily=150 | Weekly=100 | Monthly=60  
    **Bougies Restreints:** H1=200 | H4=200 | Daily=100 | Weekly=52 | Monthly=24  
    **Actifs restreints (historique limité) :** {', '.join(sorted(RESTRICTED_ASSETS))}  
    **Workers:** 6 Threads | **Semaphore:** 3 req. simultanées | **Timeout:** {API_TIMEOUT}s | **Cache:** 300s  
    **Environment OANDA :** `{OANDA_ENVIRONMENT}` (configurable via secrets.toml)  
    **Assets:** {len(ASSETS)} instruments ({len(ASSETS) - len(RESTRICTED_ASSETS)} Forex + {len(RESTRICTED_ASSETS)} Restreints)
    """)

# --- END OF FILE app.py ---
