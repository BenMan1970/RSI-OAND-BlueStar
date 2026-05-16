import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import html as html_lib
import threading
import logging
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from oandapyV20.exceptions import V20Error          # FIX [RETRY] : import explicite pour distinguer erreurs fatales vs retryables
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
    OANDA_ACCOUNT_ID   = st.secrets["OANDA_ACCOUNT_ID"]   # lu pour validation ; non utilisé dans les appels instruments
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
    OANDA_ENVIRONMENT  = st.secrets.get("OANDA_ENVIRONMENT", "practice")
except KeyError:
    st.error("Secrets non trouvés ! Vérifiez votre fichier .streamlit/secrets.toml")
    st.stop()

# FIX [ENV] : whitelist stricte — une typo ne connecte plus silencieusement
# au compte live (rate-limits différents, token exposé à un endpoint différent).
if OANDA_ENVIRONMENT not in ("practice", "live"):
    st.error(
        f"OANDA_ENVIRONMENT invalide : '{OANDA_ENVIRONMENT}'. "
        "Valeurs acceptées : 'practice' ou 'live'."
    )
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

# Source canonique unique en tuples (display_name, fetch_key)
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
    # Sémaphore global au process — OANDA limite par compte, pas par session.
    return threading.Semaphore(3)


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
    RSI Wilder — seed SMA correct + gestion explicite de tous les cas limites.

    Cas limites :
    - avg_gain == 0 et avg_loss == 0  (marché plat)  → RSI = 50
    - avg_gain >  0 et avg_loss == 0  (tendance pure) → RSI = 100
    - avg_gain == 0 et avg_loss >  0  (chute pure)    → RSI = 0
    - données insuffisantes (< period+1)              → np.nan
    """
    try:
        if prices is None or len(prices) < period + 1:
            return np.nan, None

        close_prices = prices['Close']
        delta  = close_prices.diff()
        gains  = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)

        # Seed Wilder : SMA sur les `period` premiers deltas
        avg_gain = gains.iloc[1:period + 1].mean()
        avg_loss = losses.iloc[1:period + 1].mean()

        rsi_list = [np.nan] * period

        for i in range(period, len(close_prices)):
            avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

            if avg_gain == 0 and avg_loss == 0:
                rsi_list.append(50.0)
            elif avg_loss == 0:
                rsi_list.append(100.0)
            elif avg_gain == 0:
                rsi_list.append(0.0)
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
    Seuil MIN_PRICE_DELTA adapté au type d'instrument.
    """
    if 'JPY' in pair_name:
        return 0.0003
    elif 'XAU' in pair_name:
        return 0.002
    elif any(idx in pair_name for idx in ('DE30', 'SPX500', 'NAS100', 'US30')):
        return 0.003
    return 0.001


def detect_divergence(price_data, rsi_series, timeframe_key, pair_name=""):
    """
    Détection divergence avec lookback adaptatif par TF.

    FIX [DIVERGENCE-CLOSE] : utilisation du prix de clôture au lieu de High/Low.
    Les mèches extrêmes (spikes) créent des pics sur High/Low sans que le RSI
    ne réagisse, générant de faux signaux. Le Close reflète le consensus de la
    bougie et s'aligne mieux avec la dynamique du RSI.

    FIX [PROMINENCE] : ajout d'un seuil de prominence adaptatif via np.std().
    Sans ce paramètre, find_peaks capte du bruit de tick, particulièrement sur H1
    et H4, produisant des divergences sur des micro-variations sans intérêt.

    Alignement index : rsi_series réindexé sur price_data via .reindex() pour
    éviter tout décalage en cas de trous de marché.
    """
    if rsi_series is None or len(price_data) < 10:
        return "Aucune"

    lookback = DIVERGENCE_LOOKBACK.get(timeframe_key, 30)
    if len(price_data) < lookback:
        lookback = len(price_data)

    distance_map  = {'H1': 3, 'H4': 5, 'D': 4, 'W': 3, 'M': 2}
    peak_distance = distance_map.get(timeframe_key, 5)

    MIN_PRICE_DELTA = _get_price_delta(pair_name)
    MIN_RSI_DELTA   = 2.0

    recent_price = price_data.iloc[-lookback:]
    recent_rsi   = rsi_series.reindex(recent_price.index)

    # FIX [DIVERGENCE-CLOSE] : Close au lieu de High/Low
    price_close = recent_price['Close'].values
    rsi_vals    = recent_rsi.values
    n           = len(rsi_vals)

    # FIX [PROMINENCE] : prominence proportionnelle à la dispersion des clôtures.
    # Filtre les micro-pics sans intérêt analytique.
    price_std      = np.std(price_close)
    prominence_val = price_std * 0.5 if price_std > 0 else 0.0

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

    # --- Divergence baissière (higher high prix clôture + lower high RSI) ---
    price_peaks_idx, _ = find_peaks(
        price_close,
        distance=peak_distance,
        prominence=prominence_val
    )
    if len(price_peaks_idx) >= 2:
        pp, lp = price_peaks_idx[-2], price_peaks_idx[-1]
        price_diff_ok = price_close[lp] > price_close[pp] * (1 + MIN_PRICE_DELTA)
        rsi_max_lp    = rsi_window_max(lp)
        rsi_max_pp    = rsi_window_max(pp)
        if price_diff_ok and not (np.isnan(rsi_max_lp) or np.isnan(rsi_max_pp)):
            if rsi_max_lp < rsi_max_pp - MIN_RSI_DELTA:
                return "Baissière"

    # --- Divergence haussière (lower low prix clôture + higher low RSI) ---
    price_troughs_idx, _ = find_peaks(
        -price_close,
        distance=peak_distance,
        prominence=prominence_val
    )
    if len(price_troughs_idx) >= 2:
        pt, lt = price_troughs_idx[-2], price_troughs_idx[-1]
        price_diff_ok = price_close[lt] < price_close[pt] * (1 - MIN_PRICE_DELTA)
        rsi_min_lt    = rsi_window_min(lt)
        rsi_min_pt    = rsi_window_min(pt)
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
    Fetch OANDA avec retry sélectif, timeout, rate-limit et gestion assets restreints.

    FIX [RETRY] : distinction explicite erreurs fatales (4xx hors 429) vs retryables
    (429, 5xx, timeout réseau). Une erreur 401/403 (token invalide) ne doit jamais
    être retentée : elle retournerait None immédiatement au lieu de saturer
    les rate-limits OANDA sur 3 tentatives inutiles.

    FIX [BACKOFF] : backoff exponentiel avec jitter (min(60, 2^attempt) + random())
    au lieu du sleep linéaire fixe 1.5*(attempt+1). Réduit les collisions de threads
    sur OANDA lors des rafales d'erreurs.

    cache_version : incrémenté au Rescan pour invalider le cache de cette session
    sans purger le cache global des autres utilisateurs.
    """
    count_map = CANDLE_COUNT_RESTRICTED if pair in RESTRICTED_ASSETS else CANDLE_COUNT
    count     = count_map.get(timeframe_key, 150)

    instrument = pair.replace('/', '_')
    params     = {'granularity': timeframe_key, 'count': count}

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

        except V20Error as e:
            # FIX [RETRY] : pas de retry sur erreurs d'authentification ou de
            # paramètres invalides — échouer vite évite de saturer les rate-limits.
            err_code = getattr(e, 'code', None)
            if err_code in (400, 401, 403):
                logger.error(
                    "Fatal OANDA error %s for %s %s — aborting retries: %s",
                    err_code, pair, timeframe_key, e
                )
                return None
            # 429 (rate limit) et 5xx (server error) → retry avec backoff
            logger.warning(
                "fetch_forex_data_oanda attempt %d/%d V20Error %s for %s %s: %s",
                attempt + 1, MAX_RETRIES, err_code, pair, timeframe_key, e
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(min(60, 2 ** attempt) + random.random())

        except Exception as e:
            logger.warning(
                "fetch_forex_data_oanda attempt %d/%d failed for %s %s: %s",
                attempt + 1, MAX_RETRIES, pair, timeframe_key, e
            )
            if attempt < MAX_RETRIES - 1:
                # FIX [BACKOFF] : exponentiel avec jitter
                time.sleep(min(60, 2 ** attempt) + random.random())

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
    FIX [ERROR-CONSISTENCY] : en cas d'exception, TOUS les timeframes sont
    écrasés avec NaN — y compris ceux déjà calculés avant le crash. Un asset
    en erreur ne doit jamais afficher de données partielles valides : l'utilisateur
    ne peut pas distinguer un RSI H1 fiable d'un placeholder si le badge ⚠ERR
    n'est pas immédiatement visible.
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
        # FIX [ERROR-CONSISTENCY] : écrasement de TOUS les TF (pas seulement
        # les manquants) — cohérence garantie, aucune donnée partielle exposée.
        for tf_display, _ in TIMEFRAMES:
            row_data[tf_display] = {'rsi': np.nan, 'divergence': 'Aucune'}

    return row_data


def run_analysis_process():
    results_list = []
    progress_bar = st.progress(0)
    status_text  = st.empty()
    status_text.text("Initialisation du scan parallèle...")

    cv = st.session_state.get('cache_version', 0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_asset = {
            executor.submit(process_single_asset, asset, cv): asset
            for asset in ASSETS
        }
        completed = 0
        total     = len(ASSETS)

        try:
            # FIX [TIMEOUT] : 300s au lieu de 120s.
            # Calcul réaliste : 33 assets × 5 TF = 165 appels, sémaphore=3,
            # soit ~55 batches × (sleep 0.1s + latence OANDA ~1-2s) ≈ 110-165s
            # en conditions normales. Avec retries et backoff exponentiel, les
            # cas dégradés dépassent facilement 120s. 300s couvre les scénarios
            # de cache froid sur réseau lent sans couper un scan valide.
            for future in concurrent.futures.as_completed(future_to_asset, timeout=300):
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
            logger.error("Scan global timeout after 300s — %d/%d assets completed", completed, total)
            st.warning(f"⏱ Timeout du scan après 300s — {completed}/{total} actifs traités.")

    results_list.sort(key=lambda x: ASSET_ORDER.get(x['Devises'], 999))

    scan_ts   = datetime.now()
    stats     = compute_statistics(results_list)
    scan_ts_s = scan_ts.strftime("%d/%m/%Y %H:%M:%S")

    new_state = {
        'results':        results_list,
        'last_scan_time': scan_ts,
        'scan_done':      True,
        'stats':          stats,
        'pdf_data':       create_pdf_report(results_list, stats, scan_ts_s),
        'json_data':      create_json_export(results_list, stats, scan_ts),
        'csv_data':       create_csv_export(results_list),
    }
    st.session_state.update(new_state)

    status_text.empty()
    progress_bar.empty()


# =============================================================================
# EXPORTS
# =============================================================================

def _flatten_results(results_data):
    """Structure plate pour l'export CSV uniquement."""
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


# Mapping interne FR → enum neutre pour le JSON LLM
_DIV_ENUM = {"Haussière": "BULL", "Baissière": "BEAR", "Aucune": "NONE"}

# Clé fetch OANDA → label display pour les timeframes dans le JSON
_TF_KEY_MAP = {display: fetch for display, fetch in TIMEFRAMES}


def _market_status(scan_ts):
    """
    Statut simplifié basé sur le jour de la semaine (UTC).
    Samedi (5) et dimanche (6) → fermé pour le Forex.
    Suffisant pour contextualiser le JSON sans appel API supplémentaire.
    """
    weekday = scan_ts.weekday()
    if weekday == 5:
        return "closed_saturday"
    elif weekday == 6:
        return "closed_sunday"
    return "open"


def create_json_export(results_data, stats, scan_ts):
    """
    Export JSON enrichi, optimisé pour exploitation par un LLM.

    Structure :
    - meta     : paramètres du scan (timestamp ISO, période RSI, seuils, statut marché)
    - summary  : agrégats pré-calculés (biais, RSI moyen, divergences, extrêmes par TF)
    - instruments : données imbriquées par timeframe avec enums neutres (BULL/BEAR/NONE)

    Les valeurs de divergence sont normalisées en enum anglais invariant pour
    éviter toute dépendance linguistique lors du chaînage de prompts.
    Les agrégats du bloc summary sont directement issus de compute_statistics()
    — aucun recalcul nécessaire côté LLM.
    """
    # --- Bloc meta ---
    meta = {
        "scan_ts":       scan_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rsi_period":    RSI_PERIOD,
        "thresholds": {
            "oversold":    RSI_OVERSOLD,
            "overbought":  RSI_OVERBOUGHT,
            "extreme_low": 20,
            "extreme_high": 80,
        },
        "market_status": _market_status(scan_ts),
        "instruments_count": len(results_data),
        "timeframes": TIMEFRAMES_FETCH_KEYS,
    }

    # --- Bloc summary (depuis stats pré-calculées) ---
    by_tf_summary = {}
    for tf in TIMEFRAMES_DISPLAY:
        s = stats["by_tf"][tf]
        fetch_key = _TF_KEY_MAP[tf]
        by_tf_summary[fetch_key] = {
            "extreme_oversold":   s["extreme_oversold"],
            "oversold":           s["oversold"],
            "overbought":         s["overbought"],
            "extreme_overbought": s["extreme_overbought"],
            "div_bull":           s["bull_div"],
            "div_bear":           s["bear_div"],
            "valid_count":        s["valid_count"],
        }

    # Biais : extraire le mot-clé court (BEARISH / BULLISH / NEUTRAL)
    raw_bias = stats["market_bias"]
    if "BEARISH" in raw_bias:
        bias_key = "BEARISH"
    elif "BULLISH" in raw_bias:
        bias_key = "BULLISH"
    else:
        bias_key = "NEUTRAL"

    summary = {
        "market_bias":   bias_key,
        "avg_rsi":       round(stats["avg_rsi"], 2),
        "total_div_bull": stats["total_bull_div"],
        "total_div_bear": stats["total_bear_div"],
        "total_extremes": stats["extreme_count"],
        "by_timeframe":  by_tf_summary,
    }

    # --- Bloc instruments (structure imbriquée) ---
    instruments_out = []
    for row in results_data:
        tf_data = {}
        for tf_display, tf_fetch in TIMEFRAMES:
            cell = row.get(tf_display, {})
            rsi  = cell.get("rsi", np.nan)
            div  = cell.get("divergence", "Aucune")
            tf_data[tf_fetch] = {
                "rsi": round(float(rsi), 2) if pd.notna(rsi) else None,
                "div": _DIV_ENUM.get(div, "NONE"),
            }

        instruments_out.append({
            "pair":       row["Devises"],
            "status":     row.get("Status", "OK"),
            "timeframes": tf_data,
        })

    payload = {
        "meta":        meta,
        "summary":     summary,
        "instruments": instruments_out,
    }

    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def create_csv_export(results_data):
    df = pd.DataFrame(_flatten_results(results_data))
    return df.to_csv(index=False).encode("utf-8-sig")


class _ReportPDF(FPDF):
    """Classe PDF interne avec header/footer personnalisés."""

    def __init__(self, scan_ts="", **kwargs):
        super().__init__(**kwargs)
        self._scan_ts = scan_ts

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
    """Génération PDF avec stats pré-calculées."""
    C_BG_HEADER   = (44,  62,  80)
    C_TEXT_HEADER = (255, 255, 255)
    C_OVERSOLD    = (220, 20,  60)
    C_OVERBOUGHT  = (0,   180, 80)
    C_NEUTRAL_BG  = (240, 240, 240)
    C_TEXT_DARK   = (10,  10,  10)

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
