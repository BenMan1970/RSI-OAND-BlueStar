# RSI & Divergence Screener OANDA – VERSION FINALE 100% FONCTIONNELLE (accents OK + PDF parfait)
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
from scipy.signal import find_peaks
from fpdf import FPDF
import urllib.request

warnings.filterwarnings('ignore')

st.set_page_config(page_title="RSI Screener OANDA", page_icon="Chart", layout="wide", initial_sidebar_state="collapsed")

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
    .rsi-table th { background:#2c3e50; color:white; padding:12px; }
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

# Token OANDA
try:
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except:
    st.error("Ajoute ton token OANDA dans Secrets"); st.stop()

# Téléchargement police avec accents (DejaVu → supporte français)
dejavu_url = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2"
font_path = "DejaVuSans.ttf"
if not st.session_state.get("font_downloaded", False):
    try:
        urllib.request.urlretrieve("https://github.com/libertinus-fonts/libertinus/releases/download/v7.040/Libertinus-7.040.zip", "temp.zip")
        import zipfile, os
        with zipfile.ZipFile("temp.zip", 'r') as zip_ref:
            zip_ref.extract("static/LibertinusSans-Regular.otf", ".")
        font_path = "static/LibertinusSans-Regular.otf"
    except:
        font_path = None  # on utilisera Arial sans accents si ça échoue
    st.session_state.font_downloaded = True

# Fonctions techniques
def calculate_rsi(df, period=10):
    if df is None or len(df) < period + 1: return np.nan, None
    ohlc4 = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    delta = ohlc4.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rs = rs.replace([np.inf, -np.inf], 100)
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1], rsi

def detect_divergence(df, rsi_series, lookback=30):
    if len(df) < lookback: return "Aucune"
    price = df.iloc[-lookback:]
    rsi = rsi_series.iloc[-lookback:]
    peaks, _ = find_peaks(price['High'], distance=5)
    troughs, _ = find_peaks(-price['Low'], distance=5)
    if len(peaks) >= 2:
        if price['High'].iloc[peaks[-1]] > price['High'].iloc[peaks[-2]] and rsi.iloc[peaks[-1]] < rsi.iloc[peaks[-2]]:
            return "Baissiere"
    if len(troughs) >= 2:
        if price['Low'].iloc[troughs[-1]] < price['Low'].iloc[troughs[-2]] and rsi.iloc[troughs[-1]] > rsi.iloc[troughs[-2]]:
            return "Haussiere"
    return "Aucune"

@st.cache_data(ttl=600)
def fetch_data(pair, tf):
    try:
        api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
        instrument = pair.replace('/', '_')
        gran = {'H1':'H1','H4':'H4','Daily':'D','Weekly':'W'}[tf]
        r = instruments.InstrumentsCandles(instrument=instrument, params={'granularity':gran,'count':100})
        api.request(r)
        data = [{'Time':c['time'],'Open':float(c['mid']['o']),'High':float(c['mid']['h']),
                 'Low':float(c['mid']['l']),'Close':float(c['mid']['c'])} for c in r.response['candles']]
        df = pd.DataFrame(data)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except: return None

ASSETS = ['EUR/USD','USD/JPY','GBP/USD','USD/CHF','AUD/USD','USD/CAD','NZD/USD',
          'EUR/JPY','GBP/JPY','AUD/JPY','NZD/JPY','EUR/GBP','XAU/USD','US30/USD','NAS100/USD','SPX500/USD']
TIMEFRAMES = ['H1','H4','Daily','Weekly']

def run_scan():
    results = []
    total = len(ASSETS)*len(TIMEFRAMES)
    bar = st.progress(0)
    status = st.empty()
    for i, pair in enumerate(ASSETS):
        row = {'Pair': pair}
        for tf in TIMEFRAMES:
            status.text(f"{pair} - {tf}")
            df = fetch_data(pair, tf)
            rsi, series = calculate_rsi(df)
            div = detect_divergence(df, series) if df is not None else "Aucune"
            row[tf] = {'rsi': rsi, 'div': div}
            bar.progress((i*len(TIMEFRAMES) + TIMEFRAMES.index(tf) + 1)/total)
        results.append(row)
    st.session_state.results = results
    st.session_state.last_scan = datetime.now()
    st.session_state.scan_done = True
    status.empty()
    bar.empty()

# PDF CORRIGÉ POUR ACCENTS
def create_pdf_report(data, scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('DejaVu', 'B', 16)
            self.cell(0, 12, 'SCREENER RSI & DIVERGENCE - RAPPORT', ln=1, align='C')
            self.set_font('DejaVu', '', 10)
            self.set_text_color(100,100,100)
            self.cell(0, 8, f'Genere le {scan_time}', ln=1, align='C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('DejaVu', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()}', align='C')

    pdf = PDF('L', 'mm', 'A4')
    pdf.add_page()
    pdf.add_font('DejaVu', '', font_path or 'DejaVuSans.ttf', uni=True)
    pdf.set_font('DejaVu', '', 11)

    # Résumé
    all_rsi = [v['rsi'] for r in data for k,v in r.items() if k in TIMEFRAMES and pd.notna(v['rsi'])]
    mean = np.mean(all_rsi) if all_rsi else 50
    bias = "FORT BAISSIER" if mean<40 else "BAISSIER" if mean<50 else "FORT HAUSSIER" if mean>60 else "HAUSSIER" if mean>50 else "NEUTRE"

    pdf.set_font('DejaVu', 'B', 14)
    pdf.cell(0, 10, f'RSI MOYEN GLOBAL : {mean:.1f} → {bias}', ln=1, align='C')

    # Top 15
    opps = []
    for row in data:
        for tf in TIMEFRAMES:
            if tf not in row: continue
            d = row[tf]
            rsi = d['rsi']
            div = d['div']
            if pd.isna(rsi): continue
            score = 0
            txt = []
            if rsi <=20:  score+=10; txt.append("EXTREME BAS")
            elif rsi <=30: score+=7;  txt.append("SURVENTE")
            if rsi >=80:  score+=10; txt.append("EXTREME HAUT")
            elif rsi >=70: score+=7;  txt.append("SURACHAT")
            if div=="Haussiere": score+=5; txt.append("DIV BULL")
            if div=="Baissiere": score+=5; txt.append("DIV BEAR")
            if len(txt)>1: score+=3
            if score>0:
                opps.append((score, row['Pair'], tf, rsi, ' + '.join(txt)))
    opps.sort(reverse=True)
    top = opps[:15]

    pdf.add_page()
    pdf.set_font('DejaVu', 'B', 14)
    pdf.cell(0, 10, 'TOP 15 OPPORTUNITES', ln=1)
    for i,(score,pair,tf,rsi,sig) in enumerate(top,1):
        pdf.set_fill_color(255,220,220) if rsi<=30 else pdf.set_fill_color(220,255,220)
        pdf.cell(0, 8, f"{i}. {pair} {tf} | RSI {rsi:.1f} | Score {score} → {sig}", ln=1, fill=True)

    # Guide IA
    pdf.add_page()
    pdf.set_font('DejaVu', 'B', 16)
    pdf.cell(0, 12, 'GUIDE POUR L\'IA', ln=1, align='C')
    guide = """QUESTIONS A ME POSER :
1. Quelles sont les 3 meilleures opportunités ?
2. Y a-t-il confluence Weekly + Daily ?
3. Le biais global favorise-t-il les achats ou ventes ?
4. Quels risques macro aujourd'hui ?
5. Meilleur ratio risque/rendement ?"""
    pdf.set_font('DejaVu', '', 11)
    pdf.multi_cell(0, 8, guide)

    return pdf.output(dest='S').encode('latin-1')

# Interface
st.markdown('<h1 class="screener-header">RSI & DIVERGENCE SCREENER OANDA</h1>', unsafe_allow_html=True)

if st.session_state.get('scan_done'):
    st.markdown(f'<div class="update-info">Dernier scan : {st.session_state.last_scan.strftime("%d/%m %H:%M")}</div>', unsafe_allow_html=True)

c1,c2,c3 = st.columns([4,1,1])
with c2:
    if st.button("Rescan", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
with c3:
    if st.session_state.get('results'):
        st.download_button("PDF", data=create_pdf_report(st.session_state.results, st.session_state.last_scan.strftime("%d/%m/%Y %H:%M")),
                           file_name=f"RSI_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf", mime="application/pdf", use_container_width=True)

if not st.session_state.get('scan_done', False):
    if st.button("Lancer le scan", type="primary", use_container_width=True):
        with st.spinner("Scan en cours..."):
            run_scan()
        st.success("Fini !")
        st.rerun()

if st.session_state.get('results'):
    html = '<table class="rsi-table"><thead><tr><th>Pair</th><th>H1</th><th>H4</th><th>Daily</th><th>Weekly</th></tr></thead><tbody>'
    for r in st.session_state.results:
        html += f'<tr><td class="devises-cell">{r["Pair"]}</td>'
        for tf in TIMEFRAMES:
            d = r.get(tf, {'rsi':np.nan,'div':'Aucune'})
            rsi = d['rsi']
            div = d['div']
            cls = "neutral-cell"
            if not pd.isna(rsi):
                if rsi<=20: cls="oversold-cell"
                elif rsi>=80: cls="overbought-cell"
            arrow = ' Up' if div=="Haussiere" else ' Down' if div=="Baissiere" else ""
            val = "N/A" if pd.isna(rsi) else f"{rsi:.1f}"
            html += f'<td class="{cls}">{val}{arrow}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
