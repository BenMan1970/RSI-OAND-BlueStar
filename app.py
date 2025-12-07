# RSI & Divergence Screener OANDA – VERSION 100% FONCTIONNELLE SUR STREAMLIT CLOUD (2025)
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

st.set_page_config(page_title="RSI Screener OANDA", page_icon="Chart", layout="wide", initial_sidebar_state="collapsed")

# ── STYLE ──────────────────────────────────────
st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 34px; font-weight: bold; color: #FFFFFF; text-align: center; margin-bottom: 20px; }
    .update-info { background:#1e1e1e; padding:12px; border-radius:10px; text-align:center; color:#cccccc; margin-bottom:30px; }
    .rsi-table { width:100%; border-collapse:collapse; margin:30px 0; font-size:15px; }
    .rsi-table th { background:#2c3e50; color:white; padding:14px; text-align:center; }
    .rsi-table td { padding:12px; text-align:center; border:1px solid #444; }
    .devises-cell { font-weight:bold; text-align:left !important; padding-left:20px; background:#1a1a2e; color:#e0e0e0; }
    .oversold-cell { background:#c0392b; color:white; font-weight:bold; }
    .overbought-cell { background:#27ae60; color:white; font-weight:bold; }
    .neutral-cell { background:#2c3e50; color:#bdc3c7; }
    .arrow { font-size:24px; font-weight:bold; }
</style>
""", unsafe_allow_html=True)

# ── TOKEN OANDA ──────────────────────────────────────
try:
    OANDA_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except:
    st.error("Ajoute OANDA_ACCESS_TOKEN dans Secrets")
    st.stop()

# ── FONCTIONS ──────────────────────────────────────
def calculate_rsi(df, period=10):
    if df is None or len(df) < period + 1: return np.nan, None
    ohlc4 = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    delta = ohlc4.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rs = rs.replace([np.inf], 10000)
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1], rsi

def detect_divergence(df, rsi_series, lookback=30):
    if len(df) < lookback: return "Aucune"
    p = df.iloc[-lookback:]
    r = rsi_series.iloc[-lookback:]
    peaks, _ = find_peaks(p['High'], distance=5)
    troughs, _ = find_peaks(-p['Low'], distance=5)
    if len(peaks) >= 2 and p['High'].iloc[peaks[-1]] > p['High'].iloc[peaks[-2]] and r.iloc[peaks[-1]] < r.iloc[peaks[-2]]:
        return "Baissiere"
    if len(troughs) >= 2 and p['Low'].iloc[troughs[-1]] < p['Low'].iloc[troughs[-2]] and r.iloc[troughs[-1]] > r.iloc[troughs[-2]]:
        return "Haussiere"
    return "Aucune"

@st.cache_data(ttl=600)
def fetch(pair, tf):
    try:
        api = API(access_token=OANDA_TOKEN, environment="practice")
        inst = pair.replace('/', '_')
        gran = {'H1':'H1','H4':'H4','Daily':'D','Weekly':'W'}[tf]
        r = instruments.InstrumentsCandles(instrument=inst, params={'granularity':gran,'count':100})
        api.request(r)
        d = [{'Time':c['time'],'Open':float(c['mid']['o']),'High':float(c['mid']['h']),
              'Low':float(c['mid']['l']),'Close':float(c['mid']['c'])} for c in r.response['candles']]
        df = pd.DataFrame(d)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except:
        return None

ASSETS = ['EUR/USD','USD/JPY','GBP/USD','USD/CHF','AUD/USD','USD/CAD','NZD/USD',
          'EUR/JPY','GBP/JPY','AUD/JPY','XAU/USD','US30/USD','NAS100/USD','SPX500/USD']
TFS = ['H1','H4','Daily','Weekly']

# ── SCAN ──────────────────────────────────────
def run_scan():
    results = []
    total = len(ASSETS) * len(TFS)
    bar = st.progress(0)
    status = st.empty()
    for i, pair in enumerate(ASSETS):
        row = {'Pair': pair}
        for tf in TFS:
            status.text(f"{pair} - {tf}")
            df = fetch(pair, tf)
            rsi, series = calculate_rsi(df)
            div = detect_divergence(df, series) if df is not None else "Aucune"
            row[tf] = {'rsi': rsi, 'div': div}
            bar.progress((i*len(TFS) + TFS.index(tf) + 1) / total)
        results.append(row)
    st.session_state.results = results
    st.session_state.scan_time = datetime.now()
    st.session_state.done = True
    status.empty()
    bar.empty()

# ── PDF SANS ACCENTS (100% SÛR) ──────────────────────────────────────
def create_pdf():
    pdf = FPDF('L', 'mm', 'A4')
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 15, 'SCREENER RSI & DIVERGENCE - RAPPORT', ln=1, align='C')
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 10, f'Generé le {st.session_state.scan_time.strftime("%d/%m/%Y %H:%M")}', ln=1, align='C')
    pdf.ln(10)

    # Résumé
    all_rsi = [v['rsi'] for r in st.session_state.results for k,v in r.items() if k in TFS and pd.notna(v['rsi'])]
    mean = np.mean(all_rsi) if all_rsi else 50
    bias = "TRES BAISSIER" if mean<40 else "BAISSIER" if mean<50 else "TRES HAUSSIER" if mean>60 else "HAUSSIER" if mean>50 else "NEUTRE"

    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 12, f'RSI MOYEN GLOBAL : {mean:.1f} -> {bias}', ln=1, align='C')
    pdf.ln(15)

    # Top 10
    opps = []
    for r in st.session_state.results:
        for tf in TFS:
            if tf not in r: continue
            d = r[tf]
            rsi = d['rsi']
            div = d['div']
            if pd.isna(rsi): continue
            score = 0
            txt = []
            if rsi <=20: score+=10; txt.append("RSI EXTREME BAS")
            elif rsi <=30: score+=7; txt.append("SURVENTE")
            if rsi >=80: score+=10; txt.append("RSI EXTREME HAUT")
            elif rsi >=70: score+=7; txt.append("SURACHAT")
            if div=="Haussiere": score+=5; txt.append("DIV HAUSSIERE")
            if div=="Baissiere": score+=5; txt.append("DIV BAISSIERE")
            if len(txt)>1: score+=3
            if score>0:
                opps.append((score, r['Pair'], tf, rsi, ' + '.join(txt)))
    opps.sort(reverse=True)
    top = opps[:10]

    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, 'TOP 10 OPPORTUNITES', ln=1)
    pdf.set_font('Arial', '', 11)
    for i,(s,p,t,r,sg) in enumerate(top,1):
        color = (220,20,20) if r<=30 else (20,150,70)
        pdf.set_text_color(*color)
        pdf.cell(0, 9, f"{i}. {p} {t} | RSI {r:.1f} | Score {s} -> {sg}", ln=1)

    # Guide IA
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 15, 'GUIDE POUR L IA', ln=1, align='C')
    pdf.set_font('Arial', '', 11)
    guide = """QUESTIONS A POSER A L'IA :
1. Quelles sont les 3 meilleures opportunités ?
2. Y a-t-il confluence Weekly + Daily ?
3. Le biais global favorise-t-il les achats ou ventes ?
4. Quels sont les risques macro aujourd'hui ?
5. Meilleur ratio risque/rendement ?"""
    pdf.multi_cell(0, 8, guide)

    return pdf.output(dest='S').encode('latin-1')

# ── INTERFACE ──────────────────────────────────────
st.markdown('<h1 class="screener-header">RSI & DIVERGENCE SCREENER</h1>', unsafe_allow_html=True)

if st.session_state.get('done'):
    st.markdown(f'<div class="update-info">Dernier scan : {st.session_state.scan_time.strftime("%d/%m %H:%M")}</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([4,1,1])
with col2:
    if st.button("Rescan", use_container_width=True):
        st.session_state.clear()
        st.rerun()
with col3:
    if st.session_state.get('results'):
        st.download_button("TELECHARGER PDF", data=create_pdf(), file_name=f"RSI_Rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                           mime="application/pdf", use_container_width=True)

if not st.session_state.get('done', False):
    if st.button("LANCER LE SCAN COMPLET", type="primary", use_container_width=True):
        with st.spinner("Analyse en cours (40-60s)..."):
            run_scan()
        st.success("Scan terminé !")
        st.rerun()

if st.session_state.get('results'):
    html = '<table class="rsi-table"><thead><tr><th>Pair</th><th>H1</th><th>H4</th><th>Daily</th><th>Weekly</th></tr></thead><tbody>'
    for r in st.session_state.results:
        html += f'<tr><td class="devises-cell">{r["Pair"]}</td>'
        for tf in TFS:
            d = r.get(tf, {'rsi':np.nan,'div':'Aucune'})
            rsi = d['rsi']
            div = d['div']
            cls = "neutral-cell"
            if not pd.isna(rsi):
                if rsi<=20: cls="oversold-cell"
                elif rsi>=80: cls="overbought-cell"
            arrow = " Up Arrow" if div=="Haussiere" else " Down Arrow" if div=="Baissiere" else ""
            val = "N/A" if pd.isna(rsi) else f"{rsi:.1f}"
            html += f'<td class="{cls}">{val}{arrow}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
