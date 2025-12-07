def create_pdf_report(results_data, last_scan_time):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16)
            self.set_text_color(20, 20, 20)
            self.cell(0, 10, 'OANDA MARKET SCANNER - RAPPORT STRATEGIQUE', 0, 1, 'C')
            self.set_font('Arial', 'I', 9)
            self.set_text_color(100, 100, 100)
            self.cell(0, 5, 'Genere le: ' + str(last_scan_time) + ' | Source: OANDA v20 Practice', 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, 'Page ' + str(self.page_no()) + ' | Analyse technique automatisee', 0, 0, 'C')

    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # --- PALETTE DE COULEURS VIVES (VIVID COLORS) ---
    C_BG_HEADER = (44, 62, 80)      # Bleu nuit
    C_TEXT_HEADER = (255, 255, 255) # Blanc
    C_OVERSOLD = (220, 20, 60)      # Crimson Red (Vif)
    C_OVERBOUGHT = (0, 180, 80)     # Vivid Green
    C_NEUTRAL_BG = (240, 240, 240)  # Gris très clair
    C_TEXT_DARK = (10, 10, 10)
    
    # --- CALCULS PRELIMINAIRES (EXECUTIVE SUMMARY) ---
    all_rsi_values = []
    total_bull_div = 0
    total_bear_div = 0
    extreme_oversold_count = 0 # RSI < 20
    extreme_overbought_count = 0 # RSI > 80
    
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            data = row.get(tf, {})
            rsi = data.get('rsi')
            div = data.get('divergence')
            if pd.notna(rsi):
                all_rsi_values.append(rsi)
                if rsi <= 20: extreme_oversold_count += 1
                if rsi >= 80: extreme_overbought_count += 1
            if div == 'Haussière': total_bull_div += 1
            if div == 'Baissière': total_bear_div += 1
            
    avg_global_rsi = np.mean(all_rsi_values) if all_rsi_values else 50.0
    
    # Détermination du Biais de Marché
    if avg_global_rsi < 45: market_bias = "BEARISH (Pression Vendeuse)"
    elif avg_global_rsi > 55: market_bias = "BULLISH (Pression Acheteuse)"
    else: market_bias = "NEUTRE / INCERTAIN"
    
    bias_color = C_OVERSOLD if avg_global_rsi < 45 else (C_OVERBOUGHT if avg_global_rsi > 55 else (100, 100, 100))

    # --- PAGE 1: RESUME EXECUTIF & TOP OPPORTUNITES ---
    pdf.add_page()
    
    # 1. Executive Summary Box
    pdf.set_fill_color(245, 247, 250)
    pdf.rect(10, 25, 277, 35, 'F')
    
    pdf.set_xy(15, 30)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(50, 8, "BIAIS DE MARCHE:", 0, 0, 'L')
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(*bias_color)
    pdf.cell(100, 8, market_bias, 0, 1, 'L')
    
    pdf.set_xy(15, 40)
    pdf.set_text_color(*C_TEXT_DARK)
    pdf.set_font('Arial', '', 10)
    summary_text = f"RSI Moyen Global: {avg_global_rsi:.2f} | Total Signaux Extremes (<20/>80): {extreme_oversold_count + extreme_overbought_count}"
    pdf.cell(0, 6, summary_text, 0, 1, 'L')
    summary_div = f"Divergences Detectees: {total_bull_div} Haussieres (BULL) vs {total_bear_div} Baissieres (BEAR)"
    pdf.cell(0, 6, summary_div, 0, 1, 'L')
    
    pdf.ln(15)
    
    # 2. Top 15 Opportunités (Scoring)
    pdf.set_font('Arial', 'B', 14)
    pdf.set_fill_color(*C_BG_HEADER)
    pdf.set_text_color(*C_TEXT_HEADER)
    pdf.cell(0, 10, ' TOP 15 OPPORTUNITES PRIORITAIRES (Scoring Algo)', 0, 1, 'L', True)
    pdf.ln(2)
    
    opportunities = []
    for row in results_data:
        for tf in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf, {})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            
            if pd.notna(rsi_val):
                score = 0
                signal_type = ""
                
                # Scoring System
                if rsi_val <= 20: 
                    score += 10
                    signal_type = "SURVENTE EXTREME"
                elif rsi_val <= 30: 
                    score += 5
                    signal_type = "SURVENTE"
                elif rsi_val >= 80: 
                    score += 10
                    signal_type = "SURACHAT EXTREME"
                elif rsi_val >= 70: 
                    score += 5
                    signal_type = "SURACHAT"
                
                if divergence == 'Haussière':
                    score += 4
                    signal_type += " + DIV.BULL"
                elif divergence == 'Baissière':
                    score += 4
                    signal_type += " + DIV.BEAR"
                
                if score > 0:
                    opportunities.append({
                        'asset': row['Devises'],
                        'tf': tf,
                        'rsi': rsi_val,
                        'signal': signal_type,
                        'score': score
                    })

    # Tri par score décroissant, puis par intensité RSI
    opportunities.sort(key=lambda x: (-x['score'], abs(50 - x['rsi'])))
    top_15 = opportunities[:15]
    
    # Affichage Top 15
    pdf.set_font('Arial', 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(15, 8, "#", 1, 0, 'C', True)
    pdf.cell(30, 8, "Actif", 1, 0, 'C', True)
    pdf.cell(20, 8, "TF", 1, 0, 'C', True)
    pdf.cell(25, 8, "RSI", 1, 0, 'C', True)
    pdf.cell(20, 8, "Score", 1, 0, 'C', True)
    pdf.cell(0, 8, "Signal Detecte", 1, 1, 'L', True)
    
    pdf.set_font('Arial', '', 10)
    for i, opp in enumerate(top_15, 1):
        # Couleur dynamique du texte selon le signal
        if "SURVENTE" in opp['signal']: pdf.set_text_color(*C_OVERSOLD)
        elif "SURACHAT" in opp['signal']: pdf.set_text_color(*C_OVERBOUGHT)
        else: pdf.set_text_color(*C_TEXT_DARK)
        
        pdf.cell(15, 8, str(i), 1, 0, 'C')
        pdf.cell(30, 8, opp['asset'], 1, 0, 'C')
        pdf.cell(20, 8, opp['tf'], 1, 0, 'C')
        pdf.cell(25, 8, f"{opp['rsi']:.2f}", 1, 0, 'C')
        pdf.cell(20, 8, str(opp['score']), 1, 0, 'C')
        pdf.cell(0, 8, opp['signal'], 1, 1, 'L')
        
    # --- PAGE 2: TABLEAU DETAILLE & STATS ---
    pdf.add_page()
    pdf.set_text_color(*C_TEXT_DARK)
    
    # Stats détaillées
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, "STATISTIQUES PAR TIMEFRAME (Vue d'ensemble)", 0, 1, 'L')
    pdf.set_font('Arial', '', 9)
    
    for tf in TIMEFRAMES_DISPLAY:
        tf_data = [row.get(tf, {}) for row in results_data]
        valid_rsi = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        
        c_extreme_os = sum(1 for x in valid_rsi if x <= 20)
        c_os = sum(1 for x in valid_rsi if x <= 30)
        c_extreme_ob = sum(1 for x in valid_rsi if x >= 80)
        c_ob = sum(1 for x in valid_rsi if x >= 70)
        c_bull = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        c_bear = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')
        
        line = f"[{tf}] :: <20 (Extrême): {c_extreme_os} | <30: {c_os} || >80 (Extrême): {c_extreme_ob} | >70: {c_ob} || DIV.BULL: {c_bull} | DIV.BEAR: {c_bear}"
        pdf.cell(0, 6, line, 0, 1, 'L')
        
    pdf.ln(5)
    
    # Tableau Matrice
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(*C_BG_HEADER)
    pdf.set_text_color(*C_TEXT_HEADER)
    
    w_pair = 40
    w_tf = (277 - w_pair) / 4
    
    pdf.cell(w_pair, 9, "Paire", 1, 0, 'C', True)
    for tf in TIMEFRAMES_DISPLAY:
        pdf.cell(w_tf, 9, tf, 1, 0, 'C', True)
    pdf.ln()
    
    pdf.set_font('Arial', '', 9)
    for row in results_data:
        pdf.set_fill_color(*C_NEUTRAL_BG)
        pdf.set_text_color(*C_TEXT_DARK)
        pdf.cell(w_pair, 8, row['Devises'], 1, 0, 'C', True)
        
        for tf in TIMEFRAMES_DISPLAY:
            cell = row.get(tf, {})
            val = cell.get('rsi', np.nan)
            div = cell.get('divergence', 'Aucune')
            
            # Logique couleur de cellule
            if pd.notna(val):
                if val <= 20: 
                    pdf.set_fill_color(255, 100, 100) # Rouge clair intense
                    pdf.set_text_color(255, 255, 255)
                elif val <= 30: 
                    pdf.set_fill_color(*C_OVERSOLD)
                    pdf.set_text_color(255, 255, 255)
                elif val >= 80:
                    pdf.set_fill_color(100, 255, 100) # Vert clair intense
                    pdf.set_text_color(0, 0, 0)
                elif val >= 70:
                    pdf.set_fill_color(*C_OVERBOUGHT)
                    pdf.set_text_color(255, 255, 255)
                else:
                    pdf.set_fill_color(*C_NEUTRAL_BG)
                    pdf.set_text_color(*C_TEXT_DARK)
            else:
                pdf.set_fill_color(*C_NEUTRAL_BG)
                pdf.set_text_color(*C_TEXT_DARK)
                
            txt = f"{val:.2f}" if pd.notna(val) else "N/A"
            if div == 'Haussière': txt += " (BULL)"
            elif div == 'Baissière': txt += " (BEAR)"
            
            pdf.cell(w_tf, 8, txt, 1, 0, 'C', True)
        pdf.ln()

    # --- PAGE 3: GUIDE D'INTERPRETATION POUR IA ---
    pdf.add_page()
    pdf.set_text_color(*C_TEXT_DARK)
    
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, "GUIDE D'ANALYSE POUR ASSISTANT IA (CONTEXTE LLM)", 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 6, """Ce document est genere automatiquement pour servir de base a une analyse financiere assistee par IA. Voici les regles strictes d'interpretation des donnees ci-dessus :

1. HIERARCHIE DES SIGNAUX (SCORING)
   - Priorite Absolue : Un RSI < 20 ou > 80 est une anomalie statistique majeure. Cela indique un mouvement de panique (vente) ou d'euphorie (achat). Le retour a la moyenne est probable a court terme.
   - Le "Combo en Or" : Une Divergence + un RSI Extreme sur le meme Timeframe. Probabilite de retournement > 80%.
   - Concordance des Temps : Si H1, H4 et Daily sont tous en zone de survente (ou tous en surachat), le signal est renforce (Tendance lourde).

2. LECTURE DES TIMEFRAMES
   - H1 (1 Heure) : Signal tactique pour entree immediate (Day Trading). Bruit de marche possible.
   - H4 (4 Heures) : Signal Swing Trading. Plus fiable. Indique la tendance pour les 2-3 prochains jours.
   - Weekly : Tendance de fond. Ne pas trader CONTRE un signal Weekly sauf pour du scalping tres court terme.

3. GESTION DES CONFLITS
   - Si H1 est SURVENTE mais Weekly est SURACHAT : C'est une correction dans une tendance haussiere (Buy the Dip).
   - Si tous les Timeframes sont opposes : Marche en range ou indécis -> RESTER A L'ECART.

4. INTERPRETATION DES DIVERGENCES
   - Divergence Haussiere (BULL) : Le prix fait un plus bas, mais le RSI monte. Indique un epuisement des vendeurs.
   - Divergence Baissiere (BEAR) : Le prix fait un plus haut, mais le RSI descend. Indique un epuisement des acheteurs.

5. BIAIS GLOBAL
   - Utiliser le 'RSI Moyen Global' en page 1 pour determiner si le dollar (USD) ou le Yen (JPY) dominent le marche. Si tout est rouge, chercher quelle devise est le denominateur commun.
""")
    
    return bytes(pdf.output())
