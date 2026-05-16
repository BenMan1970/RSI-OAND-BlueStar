import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import html as html_lib
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

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logging.captureWarnings(True)
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

# --- CSS STYLES --- (inchangé)
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
    OANDA_ENVIRONMENT  = st.secrets.get("OANDA_ENVIRONMENT", "practice")
except KeyError:
    st.error("Secrets non trouvés ! Vérifiez votre fichier .streamlit/secrets.toml")
    st.stop()

# ===================== ASSETS — LISTE CANONIQUE 33 INSTRUMENTS =====================
ASSETS = [
    'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'USD/CAD', 'AUD/USD', 'NZD/USD',
    'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD',
    'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/CAD', 'GBP/NZD',
    'AUD/JPY', 'AUD/CAD', 'AUD/CHF', 'AUD/NZD',
    'CAD/JPY', 'CAD/CHF', 'CHF/JPY', 'NZD/JPY', 'NZD/CAD', 'NZD/CHF',
    'DE30/EUR', 'XAU/USD', 'SPX500/USD', 'NAS100/USD', 'US30/USD',
]

RESTRICTED_ASSETS = {'DE30/EUR', 'SPX500/USD', 'NAS100/USD', 'US30/USD', 'XAU/USD'}

# FIX [BUG-002 / BUG-dérive liste parallèle] : source canonique unique en tuples
# (display_name, fetch_key) — TIMEFRAMES_DISPLAY et TIMEFRAMES_FETCH_KEYS sont
# dérivés automatiquement. Toute modification n'a lieu qu'ici, sans risque de
# désalignement silencieux entre les deux listes.
TIMEFRAMES = [
    ('H1',     'H1'),
    ('H4',     'H4'),
    ('Daily',  'D'),
    ('Weekly', 'W'),
    ('Monthly','M'),
]
TIMEFRAMES_DISPLAY    = [tf[0] for tf in TIMEFRAMES]
TIMEFRAMES_FETCH_KEYS = [tf[1] for tf in TIMEFRAMES]

CANDLE_COUNT            = {'H1': 200, 'H4': 200, 'D': 150, 'W': 100, 'M': 60}
CANDLE_COUNT_RESTRICTED = {'H1': 200, 'H4': 200, 'D': 100, 'W': 52,  'M': 24}

DIVERGENCE_LOOKBACK = {'H1': 40, 'H4': 35, 'D': 30, 'W': 20, 'M': 15}

ASSET_ORDER = {a: i for i, a in enumerate(ASSETS)}


@st.cache_resource
def get_oanda_semaphore():
    # Sémaphore global au process — intentionnel : OANDA a une limite de taux
    # par compte, pas par session. Ce sémaphore garantit ≤3 requêtes simultanées
    # quelle que soit le nombre d'utilisateurs connectés au même process.
    return threading.Semaphore(3)


# FIX [BUG-010] : client OANDA singleton via @st.cache_resource.
# Évite la création de 165 sessions TCP par scan (1 par appel cache-miss).
# Le client est partagé entre toutes les sessions du process — thread-safe
# car oandapyV20.API n'a pas d'état mutable entre requêtes.
@st.cache_resource
def get_oanda_client():
    return API(
        access_token=OANDA_ACCESS_TOKEN,
        environment=OANDA_ENVIRONMENT,
        request_params={"timeout": API_TIMEOUT}
    )


# =============================================================================
# INDICATEURS
# =============================================================================

def calculate_rsi(prices, period=RSI_PERIOD):
    """
    RSI Wilder — implémentation rigoureuse avec seed SMA correct.

    FIX [BUG-003] : l'ancienne version utilisait EWM(com=period-1, adjust=False)
    sans seed SMA préalable. Le lissage Wilder exige :
      1. Seed = moyenne simple (SMA) sur les `period` premiers deltas.
      2. Lissage récursif : avg = (avg * (period-1) + val) / period.
    L'EWM sans seed produit un RSI biaisé de ±5-15 pts sur les séries courtes
    (ex : Monthly avec 24 bougies et period=14 → seulement 10 pts utiles).

    Cas limites conservés :
    - avg_gain==0 et avg_loss==0 (marché plat) → RSI=50 (neutre)
    - avg_gain>0  et avg_loss==0               → RSI=100 (correct)
    - données insuffisantes (< period+1)        → np.nan
    """
    try:
        if prices is None or len(prices) < period + 1:
            return np.nan, None

        close_prices = prices['Close']
        delta  = close_prices.diff()
        gains  = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)

        # Seed Wilder : SMA sur les `period` premiers deltas (indices 1..period)
        avg_gain = gains.iloc[1:period + 1].mean()
        avg_loss = losses.iloc[1:period + 1].mean()

        rsi_list = [np.nan] * period  # warm-up : NaN pour les period premières valeurs

        for i in range(period, len(close_prices)):
            avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

            if avg_gain == 0 and avg_loss == 0:
                rsi_list.append(50.0)   # marché plat : neutre
            elif avg_loss == 0:
                rsi_list.append(100.0)  # que des gains
            else:
                rs = avg_gain / avg_loss
                rsi_list.append(100.0 - 100.0 / (1.0 + rs))

        rsi_series = pd.Series(rsi_list, index=close_prices.index)

        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return np.nan, None

        return float(rsi_series.iloc[-1]), rsi_series

    except Exception as e:
        logger.warning("calculate_rsi error: %s", e)
        return np.nan, None


def _get_price_delta(pair_name):
    """
    FIX [BUG-006] : seuil MIN_PRICE_DELTA adapté au type d'instrument.
    Un seuil unique 0.1% est incohérent : trop fin pour XAU (3000$),
    trop large pour les paires JPY (niveaux ~100-160).
    """
    if 'JPY' in pair_name:
        return 0.0003   # paires JPY : niveaux ~100-160, sensibilité plus faible
    elif 'XAU' in pair_name:
        return 0.002    # or : volatilité structurelle plus haute
    elif any(idx in pair_name for idx in ('DE30', 'SPX500', 'NAS100', 'US30')):
        return 0.003    # indices : très volatils, seuil plus haut
    return 0.001        # forex majeur/mineur standard


def detect_divergence(price_data, rsi_series, timeframe_key, pair_name=""):
    """
    Détection divergence avec lookback adaptatif par TF.

    FIX [BUG-002] : rsi_series est réindexé sur l'index de price_data via
    .reindex() avant le slicing. Évite le décalage d'indices si l'EWM a produit
    une série légèrement plus courte (trous de marché, index non contigu).

    FIX [BUG-006] : MIN_PRICE_DELTA adaptatif par instrument via _get_price_delta().

    FIX [BUG-011] : rsi_window_max/min gère les slices vides et les NaN —
    retourne np.nan au lieu de lever ValueError sur np.max([]).

    PATCH [Gemini] : fenêtre de tolérance ±2 bougies autour du pic de prix.
    PATCH [ChatGPT] : seuils MIN_RSI_DELTA pour filtrer les micro-variations.
    """
    if rsi_series is None or len(price_data) < 10:
        return "Aucune"

    lookback = DIVERGENCE_LOOKBACK.get(timeframe_key, 30)
    if len(price_data) < lookback:
        lookback = len(price_data)

    distance_map  = {'H1': 3, 'H4': 5, 'D': 4, 'W': 3, 'M': 2}
    peak_distance = distance_map.get(timeframe_key, 5)

    # FIX [BUG-006] : seuil adaptatif par instrument
    MIN_PRICE_DELTA = _get_price_delta(pair_name)
    MIN_RSI_DELTA   = 2.0

    recent_price = price_data.iloc[-lookback:]

    # FIX [BUG-002] : alignement explicite sur l'index de price_data
    # avant de découper — corrige le décalage si rsi_series a des trous d'index.
    recent_rsi = rsi_series.reindex(recent_price.index)

    price_high = recent_price['High'].values
    price_low  = recent_price['Low'].values
    rsi_vals   = recent_rsi.values
    n          = len(rsi_vals)

    # FIX [BUG-011] : protection contre slice vide et NaN
    def rsi_window_max(idx):
        lo = max(0, idx - 2)
        hi = min(n, idx + 3)
        window = rsi_vals[lo:hi]
        if len(window) == 0:
            return np.nan
        valid = window[~np.isnan(window)]
        return float(np.max(valid)) if len(valid) > 0 else np.nan

    def rsi_window_min(idx):
        lo = max(0, idx - 2)
        hi = min(n, idx + 3)
        window = rsi_vals[lo:hi]
        if len(window) == 0:
            return np.nan
        valid = window[~np.isnan(window)]
        return float(np.min(valid)) if len(valid) > 0 else np.nan

    # --- Divergence baissière (higher high prix + lower high RSI) ---
    price_peaks_idx, _ = find_peaks(price_high, distance=peak_distance)
    if len(price_peaks_idx) >= 2:
        pp, lp = price_peaks_idx[-2], price_peaks_idx[-1]
        price_diff_ok = price_high[lp] > price_high[pp] * (1 + MIN_PRICE_DELTA)
        rsi_max_lp    = rsi_window_max(lp)
        rsi_max_pp    = rsi_window_max(pp)
        # FIX [BUG-011] : vérifier que les valeurs RSI sont valides avant comparaison
        if price_diff_ok and not (np.isnan(rsi_max_lp) or np.isnan(rsi_max_pp)):
            if rsi_max_lp < rsi_max_pp - MIN_RSI_DELTA:
                return "Baissière"

    # --- Divergence haussière (lower low prix + higher low RSI) ---
    price_troughs_idx, _ = find_peaks(-price_low, distance=peak_distance)
    if len(price_troughs_idx) >= 2:
        pt, lt = price_troughs_idx[-2], price_troughs_idx[-1]
        price_diff_ok = price_low[lt] < price_low[pt] * (1 - MIN_PRICE_DELTA)
        rsi_min_lt    = rsi_window_min(lt)
        rsi_min_pt    = rsi_window_min(pt)
        # FIX [BUG-011] : idem
        if price_diff_ok and not (np.isnan(rsi_min_lt) or np.isnan(rsi_min_pt)):
            if rsi_min_lt > rsi_min_pt + MIN_RSI_DELTA:
                return "Haussière"

    return "Aucune"


# =============================================================================
# FETCH OANDA
# =============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key, cache_version=0):
    """
    Fetch OANDA avec retry, timeout, rate-limit et gestion assets restreints.

    FIX [BUG-005] : le paramètre `cache_version` (int) est inclus dans la clé
    de cache de @st.cache_data. Incrémenter st.session_state.cache_version
    au Rescan invalide les entrées de CETTE session uniquement, sans purger
    le cache global partagé avec les autres utilisateurs (.clear() supprimé).

    FIX [BUG-010] : api_client récupéré via get_oanda_client() (singleton
    @st.cache_resource) — une seule session TCP par process au lieu de 165.

    PATCH [Claude] : sleep() avant le sémaphore, pas à l'intérieur.
    PATCH [Qwen]   : accès défensif r.response.get('candles', []).
    PATCH [Claude] : ttl=300s.
    """
    count_map = CANDLE_COUNT_RESTRICTED if pair in RESTRICTED_ASSETS else CANDLE_COUNT
    count     = count_map.get(timeframe_key, 150)

    instrument = pair.replace('/', '_')
    params     = {'granularity': timeframe_key, 'count': count}

    # FIX [BUG-010] : singleton — pas de nouvelle session TCP à chaque appel
    api_client      = get_oanda_client()
    oanda_semaphore = get_oanda_semaphore()

    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(random.uniform(0.05, 0.15))

            with oanda_semaphore:
                r = instruments.InstrumentsCandles(instrument=instrument, params=params)
                api_client.request(r)

            data_list = []
            candles = r.response.get('candles', [])

            for c in candles:
                if not c.get('complete'):
                    continue
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
    Calcul centralisé des statistiques — appelé une seule fois après le scan.
    Buckets RSI mutuellement exclusifs.
    """
    global_rsi_values = []
    stats_by_tf = {}

    for tf in TIMEFRAMES_DISPLAY:
        tf_data   = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]

        stats_by_tf[tf] = {
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

def process_single_asset(pair_name, cache_version=0):
    """
    FIX [BUG-005] : cache_version transmis à fetch_forex_data_oanda pour
    partitionner le cache par session sans .clear() global.

    FIX [BUG-002] : pair_name transmis à detect_divergence pour le calcul
    du MIN_PRICE_DELTA adaptatif par instrument.

    PATCH [Qwen] : retourne un champ 'Status' ('OK' / 'PARTIAL' / 'ERROR').
    """
    row_data = {'Devises': pair_name, 'Status': 'OK'}
    try:
        for tf_display_name, tf_key in TIMEFRAMES:
            data_ohlc = fetch_forex_data_oanda(pair_name, tf_key, cache_version)

            if data_ohlc is None:
                row_data[tf_display_name] = {'rsi': np.nan, 'divergence': 'Aucune'}
                row_data['Status'] = 'PARTIAL'
                continue

            rsi_value, rsi_series = calculate_rsi(data_ohlc)
            divergence_signal = (
                detect_divergence(data_ohlc, rsi_series, tf_key, pair_name)
                if rsi_series is not None else "Aucune"
            )
            row_data[tf_display_name] = {'rsi': rsi_value, 'divergence': divergence_signal}

    except Exception as e:
        logger.exception("Crash in process_single_asset for %s: %s", pair_name, e)
        row_data['Status'] = 'ERROR'
        for tf_display, _ in TIMEFRAMES:
            if tf_display not in row_data:
                row_data[tf_display] = {'rsi': np.nan, 'divergence': 'Aucune'}

    return row_data


def run_analysis_process():
    results_list = []
    progress_bar = st.progress(0)
    status_text  = st.empty()
    status_text.text("Initialisation du scan parallèle...")

    # FIX [BUG-005] : cache_version lu une seule fois avant le pool de threads
    cv = st.session_state.get('cache_version', 0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_asset = {
            executor.submit(process_single_asset, asset, cv): asset
            for asset in ASSETS
        }
        completed = 0
        total     = len(ASSETS)

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

    results_list.sort(key=lambda x: ASSET_ORDER.get(x['Devises'], 999))

    # FIX [BUG-001] : construction complète du nouvel état AVANT toute écriture
    # dans st.session_state. Une écriture partielle suivie d'un rerun Streamlit
    # exposait l'UI à un état incohérent (scan_done=True mais pdf_data=None).
    scan_ts   = datetime.now()
    stats     = compute_statistics(results_list)
    scan_ts_s = scan_ts.strftime("%d/%m/%Y %H:%M:%S")

    new_state = {
        'results':        results_list,
        'last_scan_time': scan_ts,
        'scan_done':      True,
        'stats':          stats,
        'pdf_data':       create_pdf_report(results_list, stats, scan_ts_s),
        'json_data':      create_json_export(results_list),
        'csv_data':       create_csv_export(results_list),
    }
    # Écriture groupée — fenêtre de vulnérabilité minimisée
    st.session_state.update(new_state)

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


# FIX [BUG-008] : _scan_ts passé en paramètre d'instance via __init__ au lieu
# d'être un attribut de classe partagé entre toutes les instances. L'ancienne
# approche (_scan_ts = classe) causait une race condition si deux utilisateurs
# généraient un PDF simultanément : le second écrasait _scan_ts avant que le
# premier ait terminé son rendu → horodatage incorrect dans le PDF du premier.
class _ReportPDF(FPDF):
    """Classe PDF interne avec header/footer personnalisés."""

    def __init__(self, scan_ts="", **kwargs):
        super().__init__(**kwargs)
        self._scan_ts = scan_ts  # instance, pas classe

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
    Génération PDF avec stats pré-calculées.
    FIX [BUG-008] : scan_ts injecté via __init__ (instance), plus d'attribut de classe.
    """
    C_BG_HEADER   = (44,  62,  80)
    C_TEXT_HEADER = (255, 255, 255)
    C_OVERSOLD    = (220, 20,  60)
    C_OVERBOUGHT  = (0,   180, 80)
    C_NEUTRAL_BG  = (240, 240, 240)
    C_TEXT_DARK   = (10,  10,  10)

    # FIX [BUG-008] : scan_ts en paramètre d'instance, pas attribut de classe
    pdf = _ReportPDF(scan_ts=str(last_scan_time), orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)

    avg_global_rsi = stats['avg_rsi']
    market_bias    = stats['market_bias']
    bias_color     = stats['bias_color']
    total_bull_div = stats['total_bull_div']
    total_bear_div = stats['total_bear_div']
    extreme_count  = stats['extreme_count']

    # --- PAGE 1 ---
    pdf.add_page()

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
        # FIX [BUG-005] : incrémenter cache_version invalide le cache de CETTE
        # session uniquement, sans toucher au cache global des autres utilisateurs.
        # La version est passée comme paramètre à fetch_forex_data_oanda, créant
        # des entrées de cache distinctes par session.
        # .clear() (qui purgeait tout) est volontairement supprimé.
        st.session_state.cache_version = st.session_state.get('cache_version', 0) + 1
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

    # FIX [BUG-007] : accès explicite à session_state.stats sans opérateur `or`
    # (un dict non-None mais vide est falsy → déclenchait un recalcul inattendu).
    stats = st.session_state.get('stats')
    if stats is None:
        stats = compute_statistics(st.session_state.get('results', []))

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
