# RSI & DIVERGENCE SCREENER OANDA – VERSION QUI MARCHE À COUP SÛR (2025)
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

st.set_page_config(page_title="RSI Screener", page_icon="Chart", layout="wide")

st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 38px; font-weight: bold; color: #00FFAA; text-align: center; margin-bottom: 25px; }
    .update-info { background:#0a0a0a; padding:15px; border-radius:12px; text-align:center; color:#ccc; margin-bottom:30px; border:2px solid #333; }
    .rsi-table { width:100%; border-collapse:collapse; margin:40px 0; font-size:16px; }
    .rsi-table th { background:#1e40af; color:white; padding:16px; }
    .rsi-table td { padding:14px; text-align:center; border:1px solid #444; }
    .devises-cell { font-weight:bold; text-align:left !important; padding-left:30px; background:#172554; color:#e0e7ff; }
    .oversold-cell { background:#7f1d1d; color:white; font-weight:bold; }
    .overbought-cell { background:#14532d; color:white; font-weight:bold; }
    .neutral-cell { background:#1e293b; color:#cbd5e1; }
</style>
""", unsafe_allow_html=True)

# TOKEN
try:
    TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except:
    st.error("Ajoute OANDA_ACCESS_TOKEN dans les Secrets")
    st.stop()

# CALCUL RSI
def get_rsi(df):
    if df is None or len(df) < 15: return None
    close = df['Close']
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 1)

# DIVERGENCE SIMPLE
def get_divergence(df, rsi_val):
    if df is None or len(df) < 30: return ""
    recent = df.iloc[-30:]
    highs = recent['High']
    lows = recent['Low']
    if highs.iloc[-1] > highs.iloc[-10] and rsi_val < 50:
        return "Baissiere"
    if lows.iloc[-1] < lows.iloc[-10] and rsi_val > 50:
        return "Haussiere"
    return ""

# FETCH DATA
@st.cache_data(ttl=600)
def fetch(pair, tf):
    try:
        api = API(access_token=TOKEN, environment="practice")
        inst = pair.replace('/', '_')
        g = {'H1':'H1','H4':'H4','Daily':'D','Weekly':'W'}[tf]
        r = instruments.InstrumentsCandles(instrument=inst, params={'granularity':g,'count':100})
        api.request(r)
        data = []
        for c in r.response['candles']:
            data.append({'Time':c['time'],
                        'Open':float(c['mid']['o']),
                        'High':float(c['mid']['h']),
                        'Low':float(c['mid']['l']),
                        'Close':float(c['mid']['c'])})
        df = pd.DataFrame(data)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except:
        return None

PAIRS = ['EUR/USD','USD/JPY','GBP/USD','AUD/USD','USD/CAD','NZD/USD','XAU/USD','US30/USD','NAS100/USD','SPX500/USD']
TFS = ['H1','H4','Daily','Weekly']

# SCAN
def run_scan():
    results = []
    bar = st.progress(0)
    for i, pair in enumerate(PAIRS):
        row = {'Pair': pair}
        for j, tf in enumerate(TFS):
            bar.progress((i*4 + j + 1)/ (len(PAIRS)*4))
            df = fetch(pair, tf)
            rsi = get_rsi(df)
            div = get_divergence(df, rsi) if rsi else ""
            row[tf] = {'rsi': rsi, 'div': div}
        results.append(row)
    st.session_state.results = results
    st.session_state.time = datetime.now()
    st.session_state.done = True

# PDF ULTRA SIMPLE (aucune erreur possible)
def make_pdf():
    pdf = FPDF('L', 'mm', 'A4')
    pdf.add_page()
    pdf.set_font('Arial', 'B', 20)
    pdf.cell(0, 20, 'RSI SCREENER RAPPORT', ln=1, align='C')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 10, f'Date: {st.session_state.time.strftime("%d/%m/%Y %H:%M")}', ln=1, align='C')
    pdf.ln(15)

    all_rsi = [v['rsi'] for r in st.session_state.results for k,v in r.items() if k in TFS and v['rsi']]
    mean = round(np.mean(all_rsi),1) if all_rsi else 50
    bias = "TRES BAISSIER" if mean<40 else "BAISSIER" if mean<50 else "TRES HAUSSIER" if mean>60 else "HAUSSIER" if mean>50 else "NEUTRE"
    pdf.set_font('Arial', 'B', 18)
    pdf.cell(0, 15, f'RSI GLOBAL MOYEN : {mean} -> {bias}', ln=1, align='C')
    pdf.ln(20)

    opps = []
    for r in st.session_state.results:
        for tf in TFS:
            if tf not in r: continue
            d = r[tf]
            rsi = d['rsi']
            div = d['div']
            if not rsi: continue
            score = 0
            txt = []
            if rsi <=20: score +=10; txt.append("EXTREME BAS")
            elif rsi <=30: score +=7; txt.append("SURVENTE")
            if rsi >=80: score +=10; txt.append("EXTREME HAUT")
            elif rsi >=70: score +=7; txt.append("SURACHAT")
            if "Haussiere" in div: score +=5; txt.append("DIV HAUSSIERE")
            if "Baissiere" in div: score +=5; txt.append("DIV BAISSIERE")
            if len(txt)>1: score +=3
            if score>0:
                opps.append((score, r['Pair'], tf, rsi, " + ".join(txt)))
    opps.sort(reverse=True)
    top = opps[:10]

    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 15, 'TOP 10 OPPORTUNITES', ln=1)
    pdf.set_font('Arial', '', 12)
    for i,(s,p,t,r,sg) in enumerate(top,1):
        pdf.cell(0, 10, f"{i}. {p} {t} | RSI {r} | Score {s} -> {sg}", ln=1)

    pdf.add_page()
    pdf.set_font('Arial', 'B', 18)
    pdf.cell(0, 20, 'GUIDE IA', ln=1, align='C')
    guide = """QUESTIONS A POSER :
1. Quelles sont les 3 meilleures entrees ?
2. Confluence Weekly + Daily ?
3. Biais global du marche ?
4. Risques macro du jour ?
5. Meilleur ratio risque/rendement ?"""
    pdf.set_font('Arial', '', 14)
    pdf.multi_cell(0, 12, guide)

    return pdf.output(dest="S")   # <--- JUSTE ÇA, RIEN D'AUTRE

# INTERFACE
st.markdown('<h1 class="screener-header">RSI SCREENER OANDA</h1>', unsafe_allow_html=True)

if st.session_state.get('done'):
    st.markdown(f'<div class="update-info">Dernier scan : {st.session_state.time.strftime("%d/%m %H:%M")}</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([5,1,1])
with col2:
    if st.button("Rescan", use_container_width=True):
        st.session_state.clear()
        st.rerun()
with col3:
    if st.session_state.get('results'):
        st.download_button(
            label="TELECHARGER PDF",
            data=make_pdf(),
            file_name=f"RSI_Rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

if not st.session_state.get('done'):
    if st.button("LANCER LE SCAN", type="primary", use_container_width=True):
        with st.spinner("Scan en cours (30-50s)..."):
            run_scan()
        st.success("Scan terminé !")
        st.rerun()

if st.session_state.get('results'):
    html = '<table class="rsi-table"><thead><tr><th>PAIR</th><th>H1</th><th>H4</th><th>Daily</th><th>Weekly</th></tr></thead><tbody>'
    for r in st.session_state.results:
        html += f'<tr><td class="devises-cell">{r["Pair"]}</td>'
        for tf in TFS:
            d = r.get(tf, {'rsi':None,'div':''})
            val = "N/A" if not d['rsi'] else f"{d['rsi']}"
            cls = "neutral-cell"
            if d['rsi']:
                if d['rsi'] <=20: cls="oversold-cell"
                elif d['rsi'] >=80: cls="overbought-cell"
            arrow = " Up" if "Hauss" in d['div'] else " Down" if "Baiss" in d['div'] else ""
            html += f'<td class="{cls}">{val}{arrow}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
