def create_pdf_report(results_data, last_scan_time):
    """Génère un rapport PDF optimisé pour analyse IA quotidienne"""
    
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(51, 58, 73)
            self.cell(0, 10, 'RAPPORT RSI & DIVERGENCE - ANALYSE QUOTIDIENNE', 0, 1, 'C')
            self.set_font('Arial', '', 10)
            self.set_text_color(100, 100, 100)
            self.cell(0, 6, f'Genere le: {last_scan_time}', 0, 1, 'C')
            self.ln(3)
        
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f'Page {self.page_no()} | Source: OANDA v20 API', 0, 0, 'C')
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Couleurs
    color_header_bg = (51, 58, 73)
    color_oversold_bg = (255, 75, 75)
    color_overbought_bg = (61, 153, 112)
    color_neutral_bg = (240, 240, 240)
    color_text_dark = (40, 40, 40)
    color_text_light = (100, 100, 100)
    
    # ===== SECTION 1: LÉGENDE =====
    pdf.set_font('Arial', 'B', 11)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(0, 8, 'LEGENDE DES INDICATEURS', 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    
    y_start = pdf.get_y()
    
    # Colonne 1: RSI
    pdf.set_xy(10, y_start)
    pdf.set_fill_color(*color_oversold_bg)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(25, 6, 'RSI <= 20', 1, 0, 'C', True)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(40, 6, 'Survente (Oversold)', 0, 1, 'L')
    
    pdf.set_x(10)
    pdf.set_fill_color(*color_overbought_bg)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(25, 6, 'RSI >= 80', 1, 0, 'C', True)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(40, 6, 'Surachat (Overbought)', 0, 1, 'L')
    
    # Colonne 2: Divergences
    pdf.set_xy(90, y_start)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(30, 6, '(BULL)', 1, 0, 'C')
    pdf.cell(55, 6, 'Divergence Haussiere', 0, 1, 'L')
    
    pdf.set_xy(90, y_start + 6)
    pdf.cell(30, 6, '(BEAR)', 1, 0, 'C')
    pdf.cell(55, 6, 'Divergence Baissiere', 0, 1, 'L')
    
    # Colonne 3: Config
    pdf.set_xy(190, y_start)
    pdf.set_text_color(*color_text_light)
    pdf.set_font('Arial', 'I', 8)
    pdf.multi_cell(90, 4, 'RSI Periode: 10 | Source: OHLC4\nDivergence: 30 dernieres bougies\nZones extremes: <20 / >80', 0, 'L')
    
    pdf.ln(5)
    
    # ===== SECTION 2: SYNTHÈSE =====
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(0, 8, 'SYNTHESE EXECUTIVE', 0, 1, 'L')
    
    # Calculer stats
    stats_by_tf = {}
    for tf in TIMEFRAMES_DISPLAY:
        tf_data = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        
        oversold = sum(1 for x in valid_rsi if x <= 20)
        overbought = sum(1 for x in valid_rsi if x >= 80)
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        
        stats_by_tf[tf] = {
            'oversold': oversold,
            'overbought': overbought,
            'bull_div': bull_div,
            'bear_div': bear_div
        }
    
    # Tableau stats
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(*color_header_bg)
    pdf.set_text_color(255, 255, 255)
    
    col_w = 50
    pdf.cell(col_w, 7, 'Timeframe', 1, 0, 'C', True)
    pdf.cell(col_w, 7, 'Survente', 1, 0, 'C', True)
    pdf.cell(col_w, 7, 'Surachat', 1, 0, 'C', True)
    pdf.cell(col_w, 7, 'Div.Bull', 1, 0, 'C', True)
    pdf.cell(col_w, 7, 'Div.Bear', 1, 1, 'C', True)
    
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(*color_text_dark)
    
    for tf, stats in stats_by_tf.items():
        pdf.set_fill_color(250, 250, 250)
        pdf.cell(col_w, 6, tf, 1, 0, 'C', True)
        
        if stats['oversold'] > 0:
            pdf.set_fill_color(255, 200, 200)
        else:
            pdf.set_fill_color(250, 250, 250)
        pdf.cell(col_w, 6, str(stats['oversold']), 1, 0, 'C', True)
        
        if stats['overbought'] > 0:
            pdf.set_fill_color(200, 255, 200)
        else:
            pdf.set_fill_color(250, 250, 250)
        pdf.cell(col_w, 6, str(stats['overbought']), 1, 0, 'C', True)
        
        pdf.set_fill_color(250, 250, 250)
        pdf.cell(col_w, 6, str(stats['bull_div']), 1, 0, 'C', True)
        pdf.cell(col_w, 6, str(stats['bear_div']), 1, 1, 'C', True)
    
    pdf.ln(5)
    
    # ===== SECTION 3: OPPORTUNITÉS =====
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(0, 8, 'OPPORTUNITES PRIORITAIRES', 0, 1, 'L')
    
    # Identifier opportunités
    opportunities = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            
            if pd.notna(rsi_val):
                score = 0
                signal = ""
                
                if rsi_val <= 20 and divergence == 'Haussière':
                    score = 10
                    signal = "SURVENTE + DIV.BULL"
                elif rsi_val >= 80 and divergence == 'Baissière':
                    score = 10
                    signal = "SURACHAT + DIV.BEAR"
                elif rsi_val <= 20:
                    score = 7
                    signal = "SURVENTE"
                elif rsi_val >= 80:
                    score = 7
                    signal = "SURACHAT"
                elif divergence == 'Haussière':
                    score = 5
                    signal = "DIV.HAUSSIERE"
                elif divergence == 'Baissière':
                    score = 5
                    signal = "DIV.BAISSIERE"
                
                if score > 0:
                    opportunities.append({
                        'asset': row['Devises'],
                        'tf': tf,
                        'rsi': rsi_val,
                        'signal': signal,
                        'score': score
                    })
    
    opportunities.sort(key=lambda x: (-x['score'], x['rsi']))
    top_opps = opportunities[:10]
    
    if top_opps:
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(*color_header_bg)
        pdf.set_text_color(255, 255, 255)
        
        pdf.cell(50, 7, 'Actif', 1, 0, 'C', True)
        pdf.cell(25, 7, 'TF', 1, 0, 'C', True)
        pdf.cell(25, 7, 'RSI', 1, 0, 'C', True)
        pdf.cell(70, 7, 'Signal', 1, 0, 'C', True)
        pdf.cell(20, 7, 'Score', 1, 1, 'C', True)
        
        pdf.set_font('Arial', '', 9)
        
        for opp in top_opps:
            pdf.set_fill_color(250, 250, 250)
            pdf.set_text_color(*color_text_dark)
            pdf.cell(50, 6, opp['asset'], 1, 0, 'C', True)
            pdf.cell(25, 6, opp['tf'], 1, 0, 'C', True)
            
            if opp['rsi'] <= 20:
                pdf.set_fill_color(*color_oversold_bg)
                pdf.set_text_color(255, 255, 255)
            elif opp['rsi'] >= 80:
                pdf.set_fill_color(*color_overbought_bg)
                pdf.set_text_color(255, 255, 255)
            else:
                pdf.set_fill_color(250, 250, 250)
                pdf.set_text_color(*color_text_dark)
            
            pdf.cell(25, 6, f"{opp['rsi']:.2f}", 1, 0, 'C', True)
            
            pdf.set_fill_color(250, 250, 250)
            pdf.set_text_color(*color_text_dark)
            pdf.cell(70, 6, opp['signal'], 1, 0, 'C', True)
            pdf.cell(20, 6, str(opp['score']), 1, 1, 'C', True)
    else:
        pdf.set_font('Arial', 'I', 9)
        pdf.set_text_color(*color_text_light)
        pdf.cell(0, 6, 'Aucune opportunite prioritaire (RSI en zones neutres)', 0, 1, 'L')
    
    pdf.ln(8)
    
    # ===== SECTION 4: DONNÉES DÉTAILLÉES =====
    pdf.add_page()
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(0, 8, 'DONNEES DETAILLEES PAR ACTIF', 0, 1, 'L')
    pdf.ln(2)
    
    # Catégories
    categories = {
        'FOREX MAJORS': ['EUR/USD', 'USD/JPY', 'GBP/USD', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD'],
        'CROSS JPY': ['EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY'],
        'CROSS EUR': ['EUR/GBP', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD', 'EUR/CHF'],
        'METAUX': ['XAU/USD', 'XPT/USD'],
        'INDICES US': ['US30/USD', 'NAS100/USD', 'SPX500/USD']
    }
    
    for cat_name, assets_list in categories.items():
        if pdf.get_y() > 170:
            pdf.add_page()
        
        # Titre catégorie
        pdf.set_font('Arial', 'B', 10)
        pdf.set_fill_color(220, 220, 220)
        pdf.set_text_color(*color_text_dark)
        pdf.cell(0, 7, cat_name, 1, 1, 'L', True)
        
        # En-tête
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(*color_header_bg)
        pdf.set_text_color(255, 255, 255)
        
        cell_w_pair = 50
        cell_w_tf = (pdf.w - pdf.l_margin - pdf.r_margin - cell_w_pair) / len(TIMEFRAMES_DISPLAY)
        
        pdf.cell(cell_w_pair, 8, 'Actif', 1, 0, 'C', True)
        for tf in TIMEFRAMES_DISPLAY:
            pdf.cell(cell_w_tf, 8, tf, 1, 0, 'C', True)
        pdf.ln()
        
        # Données
        pdf.set_font('Arial', '', 9)
        
        for row in results_data:
            if row['Devises'] not in assets_list:
                continue
            
            pdf.set_fill_color(*color_neutral_bg)
            pdf.set_text_color(*color_text_dark)
            pdf.cell(cell_w_pair, 7, row['Devises'], 1, 0, 'L', True)
            
            for tf_name in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf_name, {'rsi': np.nan, 'divergence': 'Aucune'})
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
                        pdf.set_text_color(*color_text_dark)
                else:
                    pdf.set_fill_color(*color_neutral_bg)
                    pdf.set_text_color(*color_text_light)
                
                formatted = format_rsi(rsi_val)
                div_text = ""
                if divergence == "Haussière":
                    div_text = " (BULL)"
                elif divergence == "Baissière":
                    div_text = " (BEAR)"
                
                pdf.cell(cell_w_tf, 7, f"{formatted}{div_text}", 1, 0, 'C', True)
            
            pdf.ln()
        
        pdf.ln(3)
    
    # ===== SECTION 5: NOTES IA =====
    pdf.add_page()
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(*color_text_dark)
    pdf.cell(0, 8, 'SECTION ANALYSE IA', 0, 1, 'L')
    
    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(*color_text_light)
    
    notes_text = """QUESTIONS POUR L'IA:

1. Quelles sont les 3 meilleures opportunites aujourd'hui?

2. Y a-t-il des convergences multi-timeframes?

3. Actifs avec signaux contradictoires?

4. Tendance generale du marche (risk-on/off)?

5. Correlations inhabituelles?


CONTEXTE MACRO:
- Evenements economiques
- Annonces banques centrales
- Tensions geopolitiques


RECOMMANDATIONS:
[Espace pour notes]
"""
    
    pdf.multi_cell(0, 5, notes_text, 0, 'L')
    
    return bytes(pdf.output())
