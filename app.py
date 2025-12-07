# --- app.py - Version complete avec PDF ameliore ---
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
warnings.filterwarnings('ignore')

st.set_page_config(page_title="RSI & Divergence Screener (OANDA)", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")

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

try:
    OANDA_ACCOUNT_ID = st.secrets["OANDA_ACCOUNT_ID"]
    OANDA_ACCESS_TOKEN = st.secrets["OANDA_ACCESS_TOKEN"]
except KeyError:
    st.error("Secrets OANDA non trouves!")
    st.stop()

def calculate_rsi(prices, period=10):
    try:
        if prices is None or len(prices) < period + 1: return np.nan, None
        ohlc4 = (prices['Open'] + prices['High'] + prices['Low'] + prices['Close']) / 4
        delta = ohlc4.diff()
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        if len(gains.dropna()) < period or len(losses.dropna()) < period: return np.nan, None
        avg_gains = gains.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        avg_losses = losses.ewm(com=period - 1, adjust=False, min_periods=period).mean()
        rs = avg_gains / avg_losses
        rs[avg_losses == 0] = np.inf
        rsi_series = 100.0 - (100.0 / (1.0 + rs))
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]): return np.nan, None
        return rsi_series.iloc[-1], rsi_series
    except Exception:
        return np.nan, None

def detect_divergence(price_data, rsi_series, lookback=30, peak_distance=5):
    if rsi_series is None or len(price_data) < lookback: return "Aucune"
    recent_price = price_data.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]
    price_peaks_idx, _ = find_peaks(recent_price['High'], distance=peak_distance)
    if len(price_peaks_idx) >= 2 and recent_price['High'].iloc[price_peaks_idx[-1]] > recent_price['High'].iloc[price_peaks_idx[-2]] and recent_rsi.iloc[price_peaks_idx[-1]] < recent_rsi.iloc[price_peaks_idx[-2]]:
        return "Baissière"
    price_troughs_idx, _ = find_peaks(-recent_price['Low'], distance=peak_distance)
    if len(price_troughs_idx) >= 2 and recent_price['Low'].iloc[price_troughs_idx[-1]] < recent_price['Low'].iloc[price_troughs_idx[-2]] and recent_rsi.iloc[price_troughs_idx[-1]] > recent_rsi.iloc[price_troughs_idx[-2]]:
        return "Haussière"
    return "Aucune"

@st.cache_data(ttl=600, show_spinner=False)
def fetch_forex_data_oanda(pair, timeframe_key):
    try:
        api = API(access_token=OANDA_ACCESS_TOKEN, environment="practice")
        instrument = pair.replace('/', '_')
        params = {'granularity': {'H1':'H1', 'H4':'H4', 'D1':'D', 'W1':'W'}[timeframe_key], 'count': 100}
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        api.request(r)
        data_list = [{'Time':c['time'], 'Open':float(c['mid']['o']), 'High':float(c['mid']['h']), 'Low':float(c['mid']['l']), 'Close':float(c['mid']['c']), 'Volume':int(c['volume'])} for c in r.response['candles']]
        if not data_list: return None
        df = pd.DataFrame(data_list)
        df['Time'] = pd.to_datetime(df['Time'])
        df.set_index('Time', inplace=True)
        return df
    except Exception:
        return None

def format_rsi(value): 
    return "N/A" if pd.isna(value) else "{:.2f}".format(value)

def get_rsi_class(value):
    if pd.isna(value): return "neutral-cell"
    elif value <= 20: return "oversold-cell"
    elif value >= 80: return "overbought-cell"
    return "neutral-cell"

ASSETS = ['EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF', 'XAU/USD', 'XPT/USD', 'US30/USD', 'NAS100/USD', 'SPX500/USD']
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
            status_widget.text("Scanning: {} ({}/{})".format(pair_name, call_count, total_calls))
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
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, 'Rapport RSI & Divergence', 0, 1, 'C')
            self.set_font('Arial', '', 8)
            self.cell(0, 5, 'Genere: ' + str(last_scan_time), 0, 1, 'C')
            self.ln(3)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Couleurs vives
    ch = (30, 60, 114)
    cos = (220, 20, 60)
    cob = (34, 139, 34)
    cw = (255, 140, 0)
    cn = (245, 245, 245)
    ct = (20, 20, 20)
    
    # Page 1: Resume executif + Stats
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, ' RESUME EXECUTIF ', 0, 1, 'L', True)
    pdf.ln(2)
    
    all_rsi = []
    os_cnt = 0
    ob_cnt = 0
    bd_cnt = 0
    br_cnt = 0
    
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {})
            rsi = d.get('rsi', np.nan)
            div = d.get('divergence', 'Aucune')
            if pd.notna(rsi):
                all_rsi.append(rsi)
                if rsi <= 30: os_cnt += 1
                elif rsi >= 70: ob_cnt += 1
            if div == 'Haussière': bd_cnt += 1
            elif div == 'Baissière': br_cnt += 1
    
    avg_rsi = np.mean(all_rsi) if all_rsi else 50
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(*ct)
    
    if avg_rsi < 40:
        bias = "BEARISH"
        pdf.set_text_color(*cos)
    elif avg_rsi > 60:
        bias = "BULLISH"
        pdf.set_text_color(*cob)
    else:
        bias = "NEUTRE"
    
    pdf.cell(0, 6, 'RSI Moyen Global: {:.1f} - Biais: {}'.format(avg_rsi, bias), 0, 1, 'L')
    pdf.set_text_color(*ct)
    pdf.cell(0, 6, 'Signaux: {} ({} survente, {} surachat)'.format(os_cnt + ob_cnt, os_cnt, ob_cnt), 0, 1, 'L')
    pdf.cell(0, 6, 'Divergences: {} bull, {} bear'.format(bd_cnt, br_cnt), 0, 1, 'L')
    pdf.ln(4)
    
    # Stats par TF
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, ' ANALYSE PAR TIMEFRAME ', 0, 1, 'L', True)
    pdf.ln(2)
    
    stats = {}
    for tf in TIMEFRAMES_DISPLAY:
        td = [row.get(tf, {}) for row in results_data]
        vr = [d.get('rsi') for d in td if pd.notna(d.get('rsi'))]
        stats[tf] = {
            'os': sum(1 for x in vr if x <= 30),
            'ob': sum(1 for x in vr if x >= 70),
            'eos': sum(1 for x in vr if x <= 20),
            'eob': sum(1 for x in vr if x >= 80),
            'bd': sum(1 for d in td if d.get('divergence') == 'Haussière'),
            'br': sum(1 for d in td if d.get('divergence') == 'Baissière'),
            'avg': np.mean(vr) if vr else 50
        }
    
    pdf.set_font('Arial', 'B', 8)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    w = 35
    pdf.cell(w, 7, 'TF', 1, 0, 'C', True)
    pdf.cell(w, 7, 'Moy', 1, 0, 'C', True)
    pdf.cell(w, 7, 'OS<30', 1, 0, 'C', True)
    pdf.cell(w, 7, 'OB>70', 1, 0, 'C', True)
    pdf.cell(w, 7, 'EOS<20', 1, 0, 'C', True)
    pdf.cell(w, 7, 'EOB>80', 1, 0, 'C', True)
    pdf.cell(w, 7, 'Bull', 1, 0, 'C', True)
    pdf.cell(w, 7, 'Bear', 1, 1, 'C', True)
    
    pdf.set_font('Arial', '', 8)
    for tf, st in stats.items():
        pdf.set_text_color(*ct)
        pdf.set_fill_color(*cn)
        pdf.cell(w, 6, tf, 1, 0, 'C', True)
        
        if st['avg'] < 40: pdf.set_fill_color(255, 200, 200)
        elif st['avg'] > 60: pdf.set_fill_color(200, 255, 200)
        else: pdf.set_fill_color(*cn)
        pdf.cell(w, 6, '{:.1f}'.format(st['avg']), 1, 0, 'C', True)
        
        pdf.set_fill_color(255, 220, 220) if st['os'] > 0 else pdf.set_fill_color(*cn)
        pdf.cell(w, 6, str(st['os']), 1, 0, 'C', True)
        
        pdf.set_fill_color(220, 255, 220) if st['ob'] > 0 else pdf.set_fill_color(*cn)
        pdf.cell(w, 6, str(st['ob']), 1, 0, 'C', True)
        
        if st['eos'] > 0:
            pdf.set_fill_color(*cos)
            pdf.set_text_color(255, 255, 255)
        else:
            pdf.set_fill_color(*cn)
            pdf.set_text_color(*ct)
        pdf.cell(w, 6, str(st['eos']), 1, 0, 'C', True)
        
        if st['eob'] > 0:
            pdf.set_fill_color(*cob)
            pdf.set_text_color(255, 255, 255)
        else:
            pdf.set_fill_color(*cn)
            pdf.set_text_color(*ct)
        pdf.cell(w, 6, str(st['eob']), 1, 0, 'C', True)
        
        pdf.set_fill_color(*cn)
        pdf.set_text_color(*ct)
        pdf.cell(w, 6, str(st['bd']), 1, 0, 'C', True)
        pdf.cell(w, 6, str(st['br']), 1, 1, 'C', True)
    
    pdf.ln(4)
    
    # Convergences
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, ' CONVERGENCES MULTI-TF ', 0, 1, 'L', True)
    pdf.ln(2)
    
    convs = []
    for row in results_data:
        ostf = []
        obtf = []
        for tf in TIMEFRAMES_DISPLAY:
            rsi = row.get(tf, {}).get('rsi', np.nan)
            if pd.notna(rsi):
                if rsi <= 30: ostf.append(tf)
                elif rsi >= 70: obtf.append(tf)
        
        if len(ostf) >= 2:
            convs.append({'asset': row['Devises'], 'type': 'OS', 'tfs': ', '.join(ostf), 'sc': len(ostf)})
        elif len(obtf) >= 2:
            convs.append({'asset': row['Devises'], 'type': 'OB', 'tfs': ', '.join(obtf), 'sc': len(obtf)})
    
    convs.sort(key=lambda x: -x['sc'])
    
    if convs:
        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(*ct)
        for c in convs[:8]:
            pdf.set_fill_color(255, 200, 200) if c['type'] == 'OS' else pdf.set_fill_color(200, 255, 200)
            pdf.cell(45, 5, c['asset'], 1, 0, 'L', True)
            pdf.cell(25, 5, c['type'], 1, 0, 'C', True)
            pdf.cell(70, 5, c['tfs'], 1, 0, 'L', True)
            pdf.set_fill_color(*cw)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(15, 5, 'S:' + str(c['sc']), 1, 1, 'C', True)
            pdf.set_text_color(*ct)
    else:
        pdf.set_font('Arial', 'I', 8)
        pdf.cell(0, 5, 'Aucune convergence', 0, 1, 'L')
    
    pdf.ln(4)
    
    # Top opportunites
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, ' TOP 10 OPPORTUNITES ', 0, 1, 'L', True)
    pdf.ln(2)
    
    opps = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cd = row.get(tf, {})
            rsi = cd.get('rsi', np.nan)
            div = cd.get('divergence', 'Aucune')
            if pd.notna(rsi):
                pr = 0
                sig = ""
                if rsi <= 20:
                    pr += 10
                    sig = "OS-EXTREME"
                elif rsi <= 30:
                    pr += 5
                    sig = "SURVENTE"
                elif rsi >= 80:
                    pr += 10
                    sig = "OB-EXTREME"
                elif rsi >= 70:
                    pr += 5
                    sig = "SURACHAT"
                if div == 'Haussière':
                    pr += 5
                    sig = sig + "+BULL" if sig else "BULL"
                elif div == 'Baissière':
                    pr += 5
                    sig = sig + "+BEAR" if sig else "BEAR"
                if pr > 0:
                    opps.append({'a': row['Devises'], 't': tf, 'r': rsi, 's': sig, 'p': pr})
    
    opps.sort(key=lambda x: (-x['p'], abs(50 - x['r'])))
    top = opps[:10]
    
    if top:
        pdf.set_font('Arial', 'B', 8)
        pdf.set_fill_color(*ch)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(8, 7, '#', 1, 0, 'C', True)
        pdf.cell(40, 7, 'Actif', 1, 0, 'C', True)
        pdf.cell(18, 7, 'TF', 1, 0, 'C', True)
        pdf.cell(20, 7, 'RSI', 1, 0, 'C', True)
        pdf.cell(60, 7, 'Signal', 1, 0, 'C', True)
        pdf.cell(18, 7, 'Score', 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 8)
        for i, o in enumerate(top, 1):
            pdf.set_fill_color(*cn)
            pdf.set_text_color(*ct)
            pdf.cell(8, 6, str(i), 1, 0, 'C', True)
            pdf.cell(40, 6, o['a'], 1, 0, 'L', True)
            pdf.cell(18, 6, o['t'], 1, 0, 'C', True)
            
            if o['r'] <= 20:
                pdf.set_fill_color(*cos)
                pdf.set_text_color(255, 255, 255)
            elif o['r'] >= 80:
                pdf.set_fill_color(*cob)
                pdf.set_text_color(255, 255, 255)
            elif o['r'] <= 30:
                pdf.set_fill_color(255, 200, 200)
                pdf.set_text_color(*ct)
            elif o['r'] >= 70:
                pdf.set_fill_color(200, 255, 200)
                pdf.set_text_color(*ct)
            else:
                pdf.set_fill_color(*cn)
            
            pdf.cell(20, 6, '{:.2f}'.format(o['r']), 1, 0, 'C', True)
            
            pdf.set_fill_color(*cn)
            pdf.set_text_color(*ct)
            pdf.cell(60, 6, o['s'], 1, 0, 'L', True)
            
            pdf.set_fill_color(*cw)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(18, 6, str(o['p']), 1, 1, 'C', True)
    
    # Page 2: Donnees detaillees
    pdf.add_page()
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, ' DONNEES DETAILLEES ', 0, 1, 'L', True)
    pdf.ln(2)
    
    pdf.set_font('Arial', 'B', 8)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    wp = 50
    wtf = (pdf.w - pdf.l_margin - pdf.r_margin - wp) / len(TIMEFRAMES_DISPLAY)
    pdf.cell(wp, 8, 'Actif', 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(wtf, 8, tf, 1, 0, 'C', True)
    pdf.ln()
    
    pdf.set_font('Arial', '', 7)
    for row in results_data:
        pdf.set_fill_color(*cn)
        pdf.set_text_color(*ct)
        pdf.cell(wp, 7, row['Devises'], 1, 0, 'L', True)
        for tf in TIMEFRAMES_DISPLAY:
            d = row.get(tf, {})
            rsi = d.get('rsi', np.nan)
            div = d.get('divergence', 'Aucune')
            if pd.notna(rsi):
                if rsi <= 20:
                    pdf.set_fill_color(*cos)
                    pdf.set_text_color(255, 255, 255)
                elif rsi >= 80:
                    pdf.set_fill_color(*cob)
                    pdf.set_text_color(255, 255, 255)
                else:
                    pdf.set_fill_color(*cn)
                    pdf.set_text_color(*ct)
            else:
                pdf.set_fill_color(*cn)
                pdf.set_text_color(120, 120, 120)
            txt = format_rsi(rsi)
            if div == "Haussière": txt += "(B)"
            elif div == "Baissière": txt += "(b)"
            pdf.cell(wtf, 7, txt, 1, 0, 'C', True)
        pdf.ln()
    
    # Page 3: Guide IA
    pdf.add_page()
    pdf.set_font('Arial', 'B', 13)
    pdf.set_fill_color(*ch)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, ' GUIDE INTERPRETATION IA ', 0, 1, 'C', True)
    pdf.ln(2)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*ct)
    pdf.cell(0, 6, 'SCORING:', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, '  Score 15: RSI extreme + Div = PRIORITE MAX', 0, 1, 'L')
    pdf.cell(0, 5, '  Score 10: RSI extreme = HAUTE PRIORITE', 0, 1, 'L')
    pdf.cell(0, 5, '  Score 5-8: Modere ou Div seule', 0, 1, 'L')
    pdf.ln(2)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(0, 6, 'CONVERGENCE:', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, '  Score 4: 4 TF alignes = TRES FORTE', 0, 1, 'L')
    pdf.cell(0, 5, '  Score 3: 3 TF = FORTE', 0, 1, 'L')
    pdf.cell(0, 5, '  Score 2: 2 TF = MODEREE', 0, 1, 'L')
    pdf.ln(2)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(0, 6, 'BIAIS MARCHE:', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, '  RSI moy <40: BEARISH', 0, 1, 'L')
    pdf.cell(0, 5, '  RSI moy 40-60: NEUTRE', 0, 1, 'L')
    pdf.cell(0, 5, '  RSI moy >60: BULLISH', 0, 1, 'L')
    pdf.ln(2)
    
    pdf.set_font('Arial',
