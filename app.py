def create_pdf_report(results_data, last_scan_time):
    """Version PDF simplifiee pour analyse IA"""
    
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, 'Rapport Screener RSI & Divergence', 0, 1, 'C')
            self.set_font('Arial', '', 8)
            self.cell(0, 5, 'Genere le: ' + str(last_scan_time), 0, 1, 'C')
            self.ln(5)
        
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Couleurs
    color_header_bg = (51, 58, 73)
    color_oversold_bg = (255, 75, 75)
    color_overbought_bg = (61, 153, 112)
    color_neutral_bg = (22, 26, 29)
    color_neutral_text = (192, 192, 192)
    
    # SECTION 1: LEGENDE
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
    
    pdf.cell(0, 5, 'Timeframes analyses:', 0, 1, 'L')
    pdf.cell(0, 5, '  - H1 = 1 heure | H4 = 4 heures | Daily = Journalier | Weekly = Hebdomadaire', 0, 1, 'L')
    pdf.ln(5)
    
    # SECTION 2: SYNTHESE
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'SYNTHESE DES SIGNAUX', 0, 1, 'L')
    
    # Calculer les stats
    stats_by_tf = {}
    for tf in TIMEFRAMES_DISPLAY:
        tf_data = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        
        oversold = sum(1 for x in valid_rsi if x <= 30)
        overbought = sum(1 for x in valid_rsi if x >= 70)
        bull_div = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bear_div = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        
        stats_by_tf[tf] = {
            'oversold': oversold,
            'overbought': overbought,
            'bull_div': bull_div,
            'bear_div': bear_div
        }
    
    # Afficher les stats
    pdf.set_font('Arial', '', 9)
    for tf, stats in stats_by_tf.items():
        line = '{}: {} survente | {} surachat | {} div.bull | {} div.bear'.format(
            tf, stats['oversold'], stats['overbought'], stats['bull_div'], stats['bear_div']
        )
        pdf.cell(0, 6, line, 0, 1, 'L')
    
    pdf.ln(5)
    
    # SECTION 3: SIGNAUX PRIORITAIRES
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'SIGNAUX PRIORITAIRES (Top Opportunites)', 0, 1, 'L')
    
    # Identifier opportunites
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
                    if signal:
                        signal = signal + " + DIV.BULL"
                    else:
                        signal = "DIV.BULL"
                elif divergence == 'Baissière':
                    priority += 3
                    if signal:
                        signal = signal + " + DIV.BEAR"
                    else:
                        signal = "DIV.BEAR"
                
                if priority > 0:
                    opportunities.append({
                        'asset': row['Devises'],
                        'tf': tf,
                        'rsi': rsi_val,
                        'signal': signal,
                        'priority': priority
                    })
    
    opportunities.sort(key=lambda x: (-x['priority'], x['rsi']))
    top_opps = opportunities[:10]
    
    if top_opps:
        pdf.set_font('Arial', '', 9)
        for i, opp in enumerate(top_opps, 1):
            line = '{}. {} ({}) - RSI: {:.2f} - Signal: {}'.format(
                i, opp['asset'], opp['tf'], opp['rsi'], opp['signal']
            )
            pdf.cell(0, 6, line, 0, 1, 'L')
    else:
        pdf.set_font('Arial', 'I', 9)
        pdf.cell(0, 6, 'Aucun signal prioritaire detecte', 0, 1, 'L')
    
    pdf.ln(5)
    
    # SECTION 4: TABLEAU DETAILLE
    pdf.add_page()
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, 'DONNEES DETAILLEES PAR ACTIF', 0, 1, 'L')
    pdf.ln(2)
    
    # En-tete tableau
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(*color_header_bg)
    pdf.set_text_color(234, 234, 234)
    
    cell_width_pair = 50
    cell_width_tf = (pdf.w - pdf.l_margin - pdf.r_margin - cell_width_pair) / len(TIMEFRAMES_DISPLAY)
    
    pdf.cell(cell_width_pair, 10, 'Devises', 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(cell_width_tf, 10, tf, 1, 0, 'C', True)
    pdf.ln()
    
    # Donnees
    pdf.set_font('Arial', '', 9)
    
    for row in results_data:
        pdf.set_fill_color(*color_neutral_bg)
        pdf.set_text_color(234, 234, 234)
        pdf.cell(cell_width_pair, 10, row['Devises'], 1, 0, 'L', True)
        
        for tf_display_name in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf_display_name, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            
            # Couleur selon RSI
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
            divergence_text = ""
            if divergence == "Haussière":
                divergence_text = " (BULL)"
            elif divergence == "Baissière":
                divergence_text = " (BEAR)"
            
            cell_text = formatted_val + divergence_text
            pdf.cell(cell_width_tf, 10, cell_text, 1, 0, 'C', True)
        
        pdf.ln()
    
    # SECTION 5: NOTES POUR IA
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
    
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, 'CONTEXTE A CONSIDERER:', 0, 1, 'L')
    pdf.ln(2)
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, '- Calendrier economique du jour', 0, 1, 'L')
    pdf.cell(0, 5, '- Decisions banques centrales', 0, 1, 'L')
    pdf.cell(0, 5, '- Contexte geopolitique', 0, 1, 'L')
    pdf.cell(0, 5, '- Volatilite generale', 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, 'RECOMMANDATIONS & NOTES:', 0, 1, 'L')
    pdf.ln(2)
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, '[Espace pour votre analyse quotidienne]', 0, 1, 'L')
    
    return bytes(pdf.output())
