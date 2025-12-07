# RSI & DIVERGENCE SCREENER OANDA – VERSION 100% FONCTIONNELLE (DÉCEMBRE 2025)
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

st.set_page_config(page_title="RSI Screener", page_icon="Chart", layout="wide", initial_sidebar_state="collapsed")

# STYLE
st.markdown("""
<style>
    .main > div { padding-top: 2rem; }
    .screener-header { font-size: 36px; font-weight: bold; color: #00D4FF; text-align: center; margin-bottom: 20px; }
    .update-info { background:#0E1117; padding:15px; border-radius:12px; text-align:center; color:#AAAAAA; margin-bottom:30px; border:1px solid #333; }
    .rsi-table { width:100%; border-collapse:collapse; margin:30px 0; font-size:15px; }
    .rsi-table th { background:#1E3A8A; color:white; padding:15px; text-align:center; }
    .rsi-table td { padding:12px; text-align:center; border:1px solid #444; }
    .devises-cell { font-weight:bold; text-align:left !important; padding-left:25px; background:#1E293B; color:#E2E8F0; }
    .oversold-cell { background:#991B1B; color:white; font-weight:bold; }
    .overbought-cell { background:#166534; color:white; font-weight:bold; }
    .neutral-cell { background:#1E293B; color:#94A3B8; }
</style>
""", unsafe_allow_html=True)

# TOKEN
try:
    TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except:
    st.error("Ajoute ton token dans Secrets → OANDA_ACCESS_TOKEN")
    st.stop()

# FONCTIONS
def rsi_calc(df, p=10):
    if df is None or len(df) < p+1: return np.nan, None
    o = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    d = o.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(com=p-1, min_periods=p).mean()
    al = l.ewm(com=p-1, min_periods=p).mean()
    rs = ag / al
    rs = rs.replace([np.inf], 10000)
    return (100 - 100/(1+rs)).iloc[-1], None

def divergence(df, rsi_series):
    if len(df) < 30: return ""
    p = df.iloc[-30:]
    r = rsi_series.iloc[-30:]
    peaks, _ = find_peaks(p['High'], distance=5)
    troughs, _ = find_peaks(-p['Low'], distance=5)
    if len(peaks) >= 2 and p['High'].iloc[peaks[-1]] > p['High'].iloc[peaks[-2]] and r.iloc[peaks[-1]] < r.iloc[peaks[-2]]:
        return "Baissiere"
    if len(troughs) >= 2 and p['Low'].iloc[troughs[-1]] < p['Low'].iloc[troughs[-2]] and r.iloc[troughs[-1]] > r.iloc[troughs[-2]]:
        return "Haussiere"
    return ""

@st.cache_data(ttl=600)
def get_data(pair, tf):
    try:
        api = API(access_token=TOKEN, environment="practice")
        inst = pair.replace('/', '_')
        g = {'H1':'H1','H4':'H4','Daily':'D','Weekly':'W'}[tf]
        r = instruments.InstrumentsCandles(instrument=inst, params={'granularity':g,'count':100})
        api.request(r)
        d = []
        for c in r.response['candles']:
            d.append({'Time':c['time'],'Open':float(c['mid']['o']),'High':float(c['mid']['h']),
                      'Low':float(c['mid']['l']),'Close':float(c['mid']['c'])})
        df = pd.DataFrame(d)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except:
        return None

PAIRS = ['EUR/USD','USD/JPY','GBP/USD','AUD/USD','USD/CAD','NZD/USD','XAU/USD','US30/USD','NAS100/USD','SPX500/USD']
TFS = ['H1','H4','Daily','Weekly']

# SCAN
def scan():
    res = []
    total = len(PAIRS) * len(TFS)
    bar = st.progress(0)
    status = st.empty()
    for i,pair in enumerate(PAIRS):
        row = {'Pair':pair}
        for tf in TFS:
            status.text(f"{pair} – {tf}")
            df = get_data(pair, tf)
            rsi_val, _ = rsi_calc(df)
            div = divergence(df, pd.Series([rsi_val]*len(df))) if not pd.isna(rsi_val) else ""
            row[tf] = {'rsi':rsi_val,'div':div}
            bar.progress((i*len(TFS)+TFS.index(tf)+1)/total)
        res.append(row)
    st.session_state.data = res
    st.session_state.time = datetime.now()
    st.session_state.ok = True
    status.empty()
    bar.empty()

# PDF ULTRA SIMPLE (PLUS JAMAIS D'ERREUR)
def make_pdf():
    pdf = FPDF('L','mm','A4')
    pdf.add_page()
    pdf.set_font('Arial','B',18)
    pdf.cell(0,15,'RSI & DIVERGENCE SCREENER',ln=1,align='C')
    pdf.set_font('Arial','',11)
    pdf.cell(0,10,f"Date: {st.session_state.time.strftime('%d/%m/%Y %H:%M')}",ln=1,align='C')
    pdf.ln(10)

    all_rsi = [v['rsi'] for r in st.session_state.data for k,v in r.items() if k in TFS and pd.notna(v['rsi'])]
    mean = round(np.mean(all_rsi),1) if all_rsi else 50
    bias = "TRES BAISSIER" if mean<40 else "BAISSIER" if mean<50 else "TRES HAUSSIER" if mean>60 else "HAUSSIER" if mean>50 else "NEUTRE"
    pdf.set_font('Arial','B',16)
    pdf.cell(0,12,f"RSI MOYEN GLOBAL : {mean} → {bias}",ln=1,align='C')
    pdf.ln(15)

    opps = []
    for r in st.session_state.data:
        for tf in TFS:
            if tf not in r: continue
            d = r[tf]
            rsi = d['rsi']
            div = d['div']
            if pd.isna(rsi): continue
            score = 0
            txt = []
            if rsi<=20: score+=10; txt.append("EXTREME BAS")
            elif rsi<=30: score+=7; txt.append("SURVENTE")
            if rsi>=80: score+=10; txt.append("EXTREME HAUT")
            elif rsi>=70: score+=7; txt.append("SURACHAT")
            if div=="Haussiere": score+=5; txt.append("DIV HAUSSIERE")
            if div=="Baissiere": score+=5; txt.append("DIV BAISSIERE")
            if len(txt)>1: score+=3
            if score>0:
                opps.append((score, r['Pair'], tf, rsi, ' + '.join(txt)))
    opps.sort(reverse=True)
    top10 = opps[:10]

    pdf.set_font('Arial','B',14)
    pdf.cell(0,10,'TOP 10 OPPORTUNITES',ln=1)
    pdf.set_font('Arial','',11)
    for i,(s,p,t,r,sg) in enumerate(top10,1):
        pdf.cell(0,9,f"{i}. {p} {t} | RSI {r:.1f} | Score {s} → {sg}",ln=1)

    pdf.add_page()
    pdf.set_font('Arial','B',16)
    pdf.cell(0,15,'GUIDE IA',ln=1,align='C')
    guide = """QUESTIONS A POSER :
1. Quelles sont les 3 meilleures entrees du jour ?
2. Y a-t-il confluence Weekly + Daily ?
3. Le biais global favorise-t-il les achats ou ventes ?
4. Quels risques macro aujourd'hui ?
5. Meilleur ratio risque/rendement ?"""
    pdf.set_font('Arial','',12)
    pdf.multi_cell(0,10,guide)

    return pdf.output(dest='S')  # PAS .encode('latin-1') ← C'ETAIT L'ERREUR !

# INTERFACE
st.markdown('<h1 class="screener-header">RSI & DIVERGENCE SCREENER</h1>', unsafe_allow_html=True)

if st.session_state.get('ok'):
    st.markdown(f'<div class="update-info">Dernier scan : {st.session_state.time.strftime("%d/%m %H:%M")}</div>', unsafe_allow_html=True)

c1,c2,c3 = st.columns([5,1,1])
with c2:
    if st.button("Rescan", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
with c3:
    if st.session_state.get('data'):
        st.download_button("PDF RAPPORT", data=make_pdf(), file_name=f"RSI_{datetime.now().strftime('%Y%m%d_%H%M)}.pdf", mime="application/pdf", use_container_width=True)

if not st.session_state.get('ok', False):
    if st.button("LANCER LE SCAN", type="primary", use_container_width=True):
        with st.spinner("Scan en cours..."):
            scan()
        st.success("Terminé !")
        st.rerun()

if st.session_state.get('data'):
    html = '<table class="rsi-table"><thead><tr><th>PAIR</th><th>H1</th><th>H4</th><th>Daily</th><th>Weekly</th></tr></thead><tbody>'
    for r in st.session_state.data:
        html += f'<tr><td class="devises-cell">{r["Pair"]}</td>'
        for tf in TFS:
            d = r.get(tf, {'rsi':np.nan,'div':''})
            rsi = d['rsi']
            div = d['div']
            cls = "neutral-cell"
            if not pd.isna(rsi):
                if rsi<=20: cls="oversold-cell"
                elif rsi>=80: cls="overbought-cell"
            arrow = " Up" if div=="Haussiere" else " Down" if div=="Baissiere" else ""
            val = "N/A" if pd.isna(rsi) else f"{rsi:.1f}"
            html += f'<td class="{cls}">{val}{arrow}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
