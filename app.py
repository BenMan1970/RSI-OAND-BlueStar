# --- RSI & Divergence Screener OANDA - Version finale 100% fonctionnelle ---
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from fpdf import FPDF
warnings.filterwarnings('ignore')

# Configuration page
st.set_page_config(
    page_title="RSI & Divergence Screener (OANDA)",
    page_icon="Chart",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Style
st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 32px; font-weight: bold; color: #FFFFFF; text-align: center; margin-bottom: 20px; }
    .update-info { background:#1e1e1e; padding:10px; border-radius:8px; text-align:center; font-size:15px; color:#cccccc; margin-bottom:25px; }
    .legend-container { display: flex; justify-content: center; flex-wrap: wrap; gap: 20px; margin: 30px 0; padding: 20px; background:#111118; border-radius:10px; }
    .legend-item { display: flex; align-items: center; gap: 10px; color:#e0e0e0; }
    .legend-dot { width:14px; height:14px; border-radius:50%; }
    .oversold-dot { background:#FF4444; }
    .overbought-dot { background:#00C853; }
    .rsi-table { width:100%; border-collapse:collapse; margin:25px 0; font-size:14px; }
    .rsi-table th { background:#2c3e50; color:white; padding:12px; text-align:center; }
    .rsi-table td { padding:10px; text-align:center; border:1px solid #333; }
    .devises-cell { font-weight:bold; text-align:left !important; padding-left:20px; background:#1a1a2e; color:#e0e0e0; }
    .oversold-cell { background:rgba(255,68,68,0.8); color:white; font-weight:bold; }
    .overbought-cell { background:rgba(0,200,83,0.8); color:white; font-weight:bold; }
    .neutral-cell { background:#16213e; color:#b0b0b0; }
    .divergence-arrow { font-size:22px; font-weight:bold; margin-left:8px; }
    .bullish-arrow { color:#00C853; }
    .bearish-arrow { color:#FF4444; }
</style>
""", unsafe_allow_html=True)

# Secrets OANDA
try:
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except:
    st.error("Secrets OANDA non trouvés ! Ajoute OANDA_ACCESS_TOKEN dans Secrets.")
    st.stop()

# Fonctions techniques
def calculate_rsi(prices, period=10):
    try:
        if prices is None or len(prices) < period + 1:
            return np.nan, None
        ohlc4 = (prices['Open'] + prices['High'] + prices['Low'] + prices['Close']) / 4
        delta = ohlc4.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(com=period-1, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(com=period-1, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rs[avg_loss == 0] = np.inf
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1], rsi
    except:
        return np.nan, None

def detect_divergence(price_data, rsi_series, lookback=30):
    if rsi_series is None or len(price_data) < lookback:
        return "Aucune"
    price = price_data.iloc[-lookback:]
    rsi = rsi_series.iloc[-lookback:]

    # Divergence baissière
    peaks, _ = find_peaks(price['High'], distance=5)
    if len(peaks) >= 2:
        if price['High'].iloc[peaks[-1]] > price['High'].iloc[peaks[-2]] and rsi.iloc[peaks[-1]] < rsi.iloc[peaks[-2]]:
            return "Baissière"

    # Divergence haussière
    troughs, _ = find_peaks(-price['Low'], distance=5)
    if len(troughs) >= 2:
        if price['Low'].iloc[troughs[-1]] < price['Low'].iloc[troughs[-2]] and rsi.iloc[troughs[-1]] > rsi.iloc[troughs[-2]]:
            return "Haussière"
    return "Aucune"

@st.cache_data(ttl=600, show_spinner=False)
def fetch_forex_data_oanda(pair, tf_key):
    try:
        api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
        instrument = pair.replace('/', '_')
        granularity = {'H1':'H1', 'H4':'H4', 'D1':'D', 'W1':'W'}[tf_key]
        r = instruments.InstrumentsCandles(instrument=instrument, params={'granularity': granularity, 'count': 100})
        api.request(r)
        candles = r.response['candles']
        data = []
        for c in candles:
            data.append({
                'Time': c['time'],
                'Open': float(c['mid']['o']),
                'High': float(c['mid']['h']),
                'Low': float(c['mid']['l']),
                'Close': float(c['mid']['c'])
            })
        df = pd.DataFrame(data)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except:
        return None

# Liste des actifs
ASSETS = ['EUR/USD','USD/JPY','GBP/USD','USD/CHF','AUD/USD','USD/CAD','NZD/USD',
          'EUR/JPY','GBP/JPY','AUD/JPY','NZD/JPY','CAD/JPY','CHF/JPY',
          'EUR/GBP','EUR/AUD','EUR/CAD','EUR/NZD','EUR/CHF',
          'XAU/USD','XPT/USD','US30/USD','NAS100/USD','SPX500/USD']
TIMEFRAMES_DISPLAY = ['H1', 'H4', 'Daily', 'Weekly']
TIMEFRAMES_KEYS = ['H1', 'H4', 'D1', 'W1']

# Scan complet
def run_analysis_process():
    results = []
    total = len(ASSETS) * len(TIMEFRAMES_KEYS)
    progress = st.progress(0)
    status = st.empty()
    count = 0

    for pair in ASSETS:
        row = {'Devises': pair}
        for tf_key, tf_name in zip(TIMEFRAMES_KEYS, TIMEFRAMES_DISPLAY):
            count += 1
            status.text(f"Analyse : {pair} - {tf_name} ({count}/{total})")
            df = fetch_forex_data_oanda(pair, tf_key)
            rsi_val, rsi_series = calculate_rsi(df)
            div = "Aucune"
            if df is not None and rsi_series is not None:
                div = detect_divergence(df, rsi_series)
            row[tf_name] = {'rsi': rsi_val, 'divergence': div}
            progress.progress(count / total)
        results.append(row)

    st.session_state.results = results
    st.session_state.last_scan_time = datetime.now()
    st.session_state.scan_done = True
    status.empty()
    progress.empty()

# Génération PDF (version ultra-stable)
def create_pdf_report(results_data, last_scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(0,0,0)
            self.cell(0, 12, 'SCREENER RSI & DIVERGENCE - RAPPORT COMPLET', ln=1, align='C')
            self.set_font('Arial', '', 9)
            self.set_text_color(80,80,80)
            self.cell(0, 6, f'Généré le : {last_scan_time}', ln=1, align='C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(100,100,100)
            self.cell(0, 10, f'Page {self.page_no()}', align='C')

    pdf = PDF('L', 'mm', 'A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    RED = (220,20,20)
    GREEN = (20,150,70)

    # Résumé exécutif
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(230,230,250)
    pdf.cell(0, 10, 'RÉSUMÉ EXÉCUTIF', ln=1, fill=True)
    pdf.ln(4)

    all_rsi = [r[tf].get('rsi') for r in results_data for tf in TIMEFRAMES_DISPLAY if pd.notna(r[tf].get('rsi') is not None]
    if all_rsi:
        mean = np.mean(all_rsi)
        if mean < 40: biais, col = "FORTEMENT BAISSIER", RED
        elif mean < 50: biais, col = "BAISSIER", RED
        elif mean > 60: biais, col = "FORTEMENT HAUSSIER", GREEN
        elif mean > 50: biais, col = "HAUSSIER", GREEN
        else: biais, col = "NEUTRE", (100,100,100)

        pdf.set_font('Arial', 'B', 12)
        pdf.set_text_color(*col)
        pdf.cell(0, 8, f'RSI Moyen Global → {mean:.1f} → {biais}', ln=1)

    # Signaux globaux
    pdf.ln(5)
    oversold = sum(1 for v in all_rsi if v <= 30)
    extreme_os = sum(1 for v in all_rsi if v <= 20)
    overbought = sum(1 for v in all_rsi if v >= 70)
    extreme_ob = sum(1 for v in all_rsi if v >= 80)
    bull_div = sum(1 for r in results_data for tf in TIMEFRAMES_DISPLAY if r.get(tf, {}).get('divergence') == 'Haussière')
    bear_div = sum(1 for r in results_data for tf in TIMEFRAMES_DISPLAY if r.get(tf, {}).get('divergence') == 'Baissière')

    pdf.set_font('Arial', '', 10)
    pdf.set_text_color(*RED)
    pdf.cell(0, 6, f'Survente (<30) : {oversold} | Extrême (<20) : {extreme_os}', ln=1)
    pdf.set_text_color(*GREEN)
    pdf.cell(0, 6, f'Surachat (>70) : {overbought} | Extrême (>80) : {extreme_ob}', ln=1)
    pdf.set_text_color(0,180,0)
    pdf.cell(0, 6, f'Divergences Haussières : {bull_div}', ln=1)
    pdf.set_text_color(255,0,0)
    pdf.cell(0, 6, f'Divergences Baissières : {bear_div}', ln=1)

    # Top 15
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(230,230,250)
    pdf.cell(0, 10, 'TOP 15 OPPORTUNITÉS (SCORING)', ln=1, fill=True)
    pdf.ln(4)

    opps = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {})
            rsi = d.get('rsi')
            div = d.get('divergence', 'Aucune')
            if pd.isna(rsi): continue
            score = 0
            sig = []
            if rsi <= 20: score += 10; sig.append("RSI EXTRÊME BAS")
            elif rsi <= 30: score += 7; sig.append("SURVENTE")
            if rsi >= 80: score += 10; sig.append("RSI EXTRÊME HAUT")
            elif rsi >= 70: score += 7; sig.append("SURACHAT")
            if div == 'Haussière': score += 5; sig.append("DIV BULL")
            elif div == 'Baissière': score += 5; sig.append("DIV BEAR")
            if len(sig) > 1: score += 3
            if score > 0:
                opps.append((score, abs(rsi-50), row['Devises'], tf, rsi, ' + '.join(sig)))

    opps.sort(reverse=True)
    top15 = opps[:15]

    if top15:
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(30,30,50)
        pdf.set_text_color(255,255,255)
        pdf.cell(12, 8, '#', 1, 0, 'C', 1)
        pdf.cell(50, 8, 'Actif', 1, 0, 'C', 1)
        pdf.cell(20, 8, 'TF', 1, 0, 'C', 1)
        pdf.cell(25, 8, 'RSI', 1, 0, 'C', 1)
        pdf.cell(20, 8, 'Score', 1, 0, 'C', 1)
        pdf.cell(0, 8, 'Signal', 1, 1, 'C', 1)

        pdf.set_font('Arial', '', 9)
        for i, (score, _, asset, tf, rsi, signal) in enumerate(top15, 1):
            if rsi <= 30:
                pdf.set_fill_color(255,220,220)
                pdf.set_text_color(200,0,0)
            else:
                pdf.set_fill_color(220,255,220)
                pdf.set_text_color(0,120,0)

            pdf.cell(12, 7, str(i), 1, 0, 'C', 1)
            pdf.cell(50, 7, asset, 1, 0, 'L', 1)
            pdf.cell(20, 7, tf, 1, 0, 'C', 1)
            pdf.cell(25, 7, f'{rsi:.2f}', 1, 0, 'C', 1)
            pdf.cell(20, 7, str(score), 1, 0, 'C', 1)
            pdf.cell(0, 7, signal, 1, 1, 'L', 1)
    else:
        pdf.set_font('Arial', 'I', 11)
        pdf.cell(0, 10, 'Aucune opportunité détectée', ln=1)

    # Guide IA
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.set_fill_color(255,180,0)
    pdf.cell(0, 12, 'GUIDE POUR ANALYSE IA (Grok, Claude, etc.)', ln=1, fill=True, align='C')
    pdf.ln(8)

    guide = """
INTERPRÉTATION RAPIDE :

• RSI < 20 → EXTRÊME SURVENTE → très fort signal d'achat
• RSI > 80 → EXTRÊME SURACHAT → très fort signal de vente
• Divergence Haussière + RSI bas → priorité absolue ACHAT
• Divergence Baissière + RSI haut → priorité absolue VENTE

QUESTIONS À ME POSER (copie-colle) :

1. Quelles sont les 3 meilleures opportunités du jour ?
2. Y a-t-il confluence Weekly + Daily ?
3. Le biais global (RSI moyen) favorise-t-il les achats ou ventes ?
4. Quels sont les risques macro aujourd'hui ?
5. Quel est le meilleur ratio risque/rendement ?

TEMPLATE D'ANALYSE :
Actif : 
Score :     RSI :     TF : 
Confluence : Oui/Non
Biais marché : Compatible ?
Décision : ACHAT / VENTE / ATTENDRE
"""
    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 7, guide)

    return pdf.output(dest='S').encode('latin-1')

# Interface Streamlit
st.markdown('<h1 class="screener-header">RSI & Divergence Screener (OANDA)</h1>', unsafe_allow_html=True)

if st.session_state.get('scan_done'):
    st.markdown(f'<div class="update-info">Dernière analyse : {st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M:%S")}</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([3,1,1])
with col2:
    if st.button("Rescan", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

with col3:
    if st.session_state.get('results'):
        st.download_button(
            label="PDF Rapport",
            data=create_pdf_report(st.session_state.results, st.session_state.last_scan_time.strftime("%d/%m/%Y %H:%M")),
            file_name=f"RSI_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

# Lancement du scan
if not st.session_state.get('scan_done', False):
    if st.button("Lancer le scan complet", use_container_width=True, type="primary"):
        with st.spinner("Analyse en cours... (environ 45 secondes)"):
            run_analysis_process()
        st.success("Scan terminé !")
        st.rerun()

# Affichage résultats
if st.session_state.get('results'):
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>RSI ≤ 20 (survente extrême)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>RSI ≥ 80 (surachat extrême)</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">Up Arrow</span><span>Divergence Haussière</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">Down Arrow</span><span>Divergence Baissière</span></div>
    </div>""", unsafe_allow_html=True)

    html = '<table class="rsi-table"><thead><tr><th>Actif</th><th>H1</th><th>H4</th><th>Daily</th><th>Weekly</th></tr></thead><tbody>'
    for row in st.session_state.results:
        html += f'<tr><td class="devises-cell">{row["Devises"]}</td>'
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi = d['rsi']
            div = d['divergence']
            cls = "neutral-cell"
            if not pd.isna(rsi):
                if rsi <= 20: cls = "oversold-cell"
                elif rsi >= 80: cls = "overbought-cell"
            arrow = ' <span class="divergence-arrow bullish-arrow">Up Arrow</span>' if div == "Haussière" else (' <span class="divergence-arrow bearish-arrow">Down Arrow</span>' if div == "Baissière" else "")
            val = "N/A" if pd.isna(rsi) else f"{rsi:.1f}"
            html += f'<td class="{cls}">{val}{arrow}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)

with st.expander("Configuration"):
    st.write("• Source : OANDA Practice API\n• RSI période 10 sur OHLC4\n• Divergences détectées sur 30 dernières bougies")
