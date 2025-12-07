# app.py
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
import io
import traceback

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

# OANDA secrets
try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except Exception:
    st.error("🔑 Secrets OANDA non trouvés! Ajoute OANDA_ACCOUNT_ID et OANDA_ACCESS_TOKEN dans les Secrets.")
    st.stop()

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
        price_peaks_idx, _ = find_peaks(recent_price['High'], distance=peak_distance)
        if len(price_peaks_idx) >= 2:
            last, prev = price_peaks_idx[-1], price_peaks_idx[-2]
            if recent_price['High'].iloc[last] > recent_price['High'].iloc[prev] and recent_rsi.iloc[last] < recent_rsi.iloc[prev]:
                return "Baissière"
        price_troughs_idx, _ = find_peaks(-recent_price['Low'], distance=peak_distance)
        if len(price_troughs_idx) >= 2:
            last, prev = price_troughs_idx[-1], price_troughs_idx[-2]
            if recent_price['Low'].iloc[last] < recent_price['Low'].iloc[prev] and recent_rsi.iloc[last] > recent_rsi.iloc[prev]:
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
            # Candles can be 'complete' or not; using mid prices (if exist)
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
    elif value <= 20:
        return "oversold-cell"
    elif value >= 80:
        return "overbought-cell"
    return "neutral-cell"

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
    """
    Retourne des bytes (PDF). Gestion robuste si FPDF.output renvoie str ou bytes.
    """
    try:
        class PDF(FPDF):
            def header(self):
                self.set_font('Arial', 'B', 14)
                self.cell(0, 10, 'Rapport Screener RSI & Divergence', 0, 1, 'C')
                self.set_font('Arial', '', 8)
                self.cell(0, 5, 'Généré le: ' + str(last_scan_time), 0, 1, 'C')
                self.ln(5)
            def footer(self):
                self.set_y(-15)
                self.set_font('Arial', 'I', 8)
                self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')

        pdf = PDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()

        color_header_bg = (51, 58, 73)
        color_oversold_bg = (255, 75, 75)
        color_overbought_bg = (61, 153, 112)
        color_neutral_bg = (22, 26, 29)
        color_neutral_text = (192, 192, 192)

        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'GUIDE DE LECTURE', 0, 1, 'L')
        pdf.set_font('Arial', '', 9)
        pdf.ln(2)
        pdf.cell(0, 5, 'RSI (Relative Strength Index):', 0, 1, 'L')
        pdf.cell(0, 5, '  - RSI < 30 : Zone de SURVENTE (potentiel rebond haussier)', 0, 1, 'L')
        pdf.cell(0, 5, '  - RSI > 70 : Zone de SURACHAT (potentiel rebond baissier)', 0, 1, 'L')
        pdf.cell(0, 5, '  - RSI entre 30-70 : Zone NEUTRE', 0, 1, 'L')
        pdf.ln(2)
        pdf.cell(0, 5, 'Divergences:', 0, 1, 'L')
        pdf.cell(0, 5, '  - (BULL) = Divergence Haussiere : Prix baisse mais RSI monte', 0, 1, 'L')
        pdf.cell(0, 5, '  - (BEAR) = Divergence Baissiere : Prix monte mais RSI baisse', 0, 1, 'L')
        pdf.ln(2)
        pdf.cell(0, 5, 'Timeframes: H1=1h | H4=4h | Daily=Journalier | Weekly=Hebdomadaire', 0, 1, 'L')
        pdf.ln(5)

        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'SYNTHESE DES SIGNAUX', 0, 1, 'L')

        # Stats par TF
        stats_by_tf = {}
        for tf in TIMEFRAMES_DISPLAY:
            tf_data = [row.get(tf, {}) for row in results_data]
            valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
            oversold = sum(1 for x in valid_rsi if x <= 30)
            overbought = sum(1 for x in valid_rsi if x >= 70)
            bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
            bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
            stats_by_tf[tf] = {'oversold': oversold, 'overbought': overbought, 'bull_div': bull_div, 'bear_div': bear_div}

        pdf.set_font('Arial', '', 9)
        for tf, stats in stats_by_tf.items():
            line = f"{tf}: {stats['oversold']} survente | {stats['overbought']} surachat | {stats['bull_div']} div.bull | {stats['bear_div']} div.bear"
            pdf.cell(0, 6, line, 0, 1, 'L')
        pdf.ln(5)

        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'OPPORTUNITES PRIORITAIRES (Top 10)', 0, 1, 'L')

        opportunities = []
        for row in results_data:
            for tf in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf, {})
                rsi_val = cell_data.get('rsi', np.nan)
                divergence = cell_data.get('divergence', 'Aucune')
                if pd.notna(rsi_val):
                    priority = 0
                    signal = ""
                    if rsi_val <= 30:
                        priority += 5
                        signal = "SURVENTE"
                    elif rsi_val >= 70:
                        priority += 5
                        signal = "SURACHAT"
                    if divergence == 'Haussière':
                        priority += 3
                        signal = (signal + " + DIV.BULL") if signal else "DIV.BULL"
                    elif divergence == 'Baissière':
                        priority += 3
                        signal = (signal + " + DIV.BEAR") if signal else "DIV.BEAR"
                    if priority > 0:
                        opportunities.append({'asset': row['Devises'], 'tf': tf, 'rsi': rsi_val, 'signal': signal, 'priority': priority})

        opportunities.sort(key=lambda x: (-x['priority'], x['rsi']))
        top_opps = opportunities[:10]

        if top_opps:
            pdf.set_font('Arial', '', 9)
            for i, opp in enumerate(top_opps, 1):
                line = f"{i}. {opp['asset']} ({opp['tf']}) - RSI: {opp['rsi']:.2f} - Signal: {opp['signal']}"
                pdf.cell(0, 6, line, 0, 1, 'L')
        else:
            pdf.set_font('Arial', 'I', 9)
            pdf.cell(0, 6, 'Aucun signal prioritaire detecte', 0, 1, 'L')
        pdf.ln(5)

        # Détails par actif (table)
        pdf.add_page()
        pdf.set_font('Arial', 'B', 10)
        pdf.set_fill_color(*color_header_bg)
        pdf.set_text_color(234, 234, 234)
        cell_width_pair = 50
        cell_width_tf = (pdf.w - pdf.l_margin - pdf.r_margin - cell_width_pair) / len(TIMEFRAMES_DISPLAY)
        pdf.cell(cell_width_pair, 10, 'Devises', 1, 0, 'C', True)
        for tf in TIMEFRAMES_DISPLAY:
            pdf.cell(cell_width_tf, 10, tf, 1, 0, 'C', True)
        pdf.ln()
        pdf.set_font('Arial', '', 9)

        for row in results_data:
            pdf.set_fill_color(*color_neutral_bg)
            pdf.set_text_color(234, 234, 234)
            pdf.cell(cell_width_pair, 10, row['Devises'], 1, 0, 'L', True)
            for tf_display_name in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf_display_name, {'rsi': np.nan, 'divergence': 'Aucune'})
                rsi_val = cell_data.get('rsi', np.nan)
                divergence = cell_data.get('divergence', 'Aucune')
                if pd.notna(rsi_val):
                    if rsi_val <= 20:
                        pdf.set_fill_color(*color_oversold_bg)
                        pdf.set_text_color(255, 255, 255)
                    elif rsi_val >= 80:
                        pdf.set_fill_color(*color_overbought_bg)
                        pdf.set_text_color(255, 255, 255)
                    else:
                        pdf.set_fill_color(*color_neutral_bg)
                        pdf.set_text_color(*color_neutral_text)
                else:
                    pdf.set_fill_color(*color_neutral_bg)
                    pdf.set_text_color(*color_neutral_text)
                formatted_val = format_rsi(rsi_val)
                divergence_text = " (BULL)" if divergence == "Haussière" else (" (BEAR)" if divergence == "Baissière" else "")
                cell_text = formatted_val + divergence_text
                pdf.cell(cell_width_tf, 10, cell_text, 1, 0, 'C', True)
            pdf.ln()

        pdf.add_page()
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'SECTION ANALYSE IA', 0, 1, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.ln(2)
        pdf.cell(0, 6, 'QUESTIONS POUR L\'IA:', 0, 1, 'L')
        pdf.ln(2)
        pdf.set_font('Arial', '', 9)
        pdf.cell(0, 5, '1. Quelles sont les 3 meilleures opportunites de trading aujourd\'hui?', 0, 1, 'L')
        pdf.cell(0, 5, '2. Y a-t-il des actifs avec signaux concordants sur plusieurs timeframes?', 0, 1, 'L')
        pdf.cell(0, 5, '3. Quels actifs montrent des signaux contradictoires?', 0, 1, 'L')
        pdf.cell(0, 5, '4. Quelle est la tendance generale du marche?', 0, 1, 'L')
        pdf.cell(0, 5, '5. Y a-t-il des correlations inhabituelles?', 0, 1, 'L')
        pdf.ln(5)

        # Génération du PDF en bytes - gestion robuste selon type renvoyé par fpdf
        output = pdf.output(dest='S')
        if isinstance(output, str):
            # FPDF parfois renvoie str (texte), on encode en latin-1 (PDF standard)
            pdf_bytes = output.encode('latin-1')
        else:
            pdf_bytes = bytes(output)
        return pdf_bytes

    except Exception as e:
        # En cas d'erreur, log dans Streamlit et retourne un PDF minimal indiquant l'erreur
        tb = traceback.format_exc()
        st.error("Erreur lors de la génération du PDF (voir détails ci-dessous).")
        st.text_area("Traceback", tb, height=300)
        # Générer un PDF minimal décrivant l'erreur
        try:
            pdf_err = FPDF(orientation='L', unit='mm', format='A4')
            pdf_err.add_page()
            pdf_err.set_font('Arial', 'B', 12)
            pdf_err.cell(0, 10, 'ERREUR: impossible de generer le rapport complet', 0, 1, 'C')
            pdf_err.set_font('Arial', '', 10)
            pdf_err.multi_cell(0, 6, "Traceback:\n" + tb)
            out = pdf_err.output(dest='S')
            return out.encode('latin-1') if isinstance(out, str) else bytes(out)
        except Exception:
            # Last resort: return an empty bytes object
            return b''

# UI
st.markdown('<h1 class="screener-header">Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

if st.session_state.get('scan_done'):
    last_scan_time = st.session_state.get('last_scan_time')
    if last_scan_time:
        last_scan_time_str = last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
        st.markdown(f'<div class="update-info">🔄 Dernière mise à jour: {last_scan_time_str} (OANDA)</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([4, 1, 1])
with col2:
    if st.button("🔄 Rescan", use_container_width=True):
        st.session_state.scan_done = False
        # clear cache safely (compatibilité)
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.rerun()

with col3:
    if st.session_state.get('results'):
        # Crée le PDF à la demande (ne pas stocker dans session_state si volumineux)
        pdf_bytes = None
        try:
            pdf_bytes = create_pdf_report(st.session_state.results, st.session_state.get('last_scan_time', 'N/A'))
        except Exception:
            pdf_bytes = b''
        st.download_button(
            label="📄 PDF",
            data=pdf_bytes,
            file_name=f"RSI_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

if not st.session_state.get('scan_done'):
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

if st.session_state.get('results'):
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ 20)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ 80)</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">↑</span><span>Bullish Divergence</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">↓</span><span>Bearish Divergence</span></div>
    </div>""", unsafe_allow_html=True)

    st.markdown("### 📈 RSI & Divergence Analysis Results")
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
            divergence_icon = '<span class="divergence-arrow bullish-arrow">↑</span>' if divergence == "Haussière" else ('<span class="divergence-arrow bearish-arrow">↓</span>' if divergence == "Baissière" else "")
            html_table += f'<td class="{css_class}">{formatted_val} {divergence_icon}</td>'
        html_table += '</tr>'
    html_table += '</tbody></table>'
    st.markdown(html_table, unsafe_allow_html=True)

    st.markdown("### 📊 Signal Statistics")
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf in enumerate(TIMEFRAMES_DISPLAY):
        tf_data = [row.get(tf, {}) for row in st.session_state.results]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissièr' or d.get('divergence') == 'Baissière')  # tolérance typo
        if valid_rsi:
            oversold = sum(1 for x in valid_rsi if x <= 20)
            overbought = sum(1 for x in valid_rsi if x >= 80)
            total = oversold + overbought + bull_div + bear_div
            delta_text = f"🔴 {oversold} S | 🟢 {overbought} B | ↑ {bull_div} | ↓ {bear_div}"
            with stat_cols[i]:
                st.metric(label=f"Signals {tf}", value=str(total))
                st.markdown(delta_text, unsafe_allow_html=True)
        else:
            with stat_cols[i]:
                st.metric(label=f"Signals {tf}", value="N/A")

with st.expander("ℹ️ Configuration", expanded=False):
    st.markdown("""
    **Data Source:** OANDA v20 API (practice account)  
    **RSI Period:** 10 | **Source:** OHLC4  
    **Divergence:** Last 30 candles
    """)
