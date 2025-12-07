def create_pdf_report(results_data, last_scan_time):
    """
    Génère le PDF en nettoyant les caractères spéciaux pour éviter les erreurs d'encodage (page blanche).
    """
    try:
        class PDF(FPDF):
            def header(self):
                self.set_font('Arial', 'B', 14)
                # Pas d'accents ici pour la sécurité
                self.cell(0, 10, 'Rapport Screener RSI & Divergence', 0, 1, 'C')
                self.set_font('Arial', '', 8)
                # Conversion explicite en string
                self.cell(0, 5, 'Date: ' + str(last_scan_time), 0, 1, 'C')
                self.ln(5)
            def footer(self):
                self.set_y(-15)
                self.set_font('Arial', 'I', 8)
                self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')

        # Initialisation
        pdf = PDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        
        # Couleurs
        color_oversold_bg = (180, 40, 40)    # Rouge
        color_overbought_bg = (25, 110, 80)  # Vert
        
        # --- Section Guide (Texte sans accents) ---
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'GUIDE DE LECTURE', 0, 1, 'L')
        pdf.set_font('Arial', '', 9)
        pdf.ln(2)
        pdf.cell(0, 5, 'RSI < 30 : SURVENTE (Oversold)', 0, 1, 'L')
        pdf.cell(0, 5, 'RSI > 70 : SURACHAT (Overbought)', 0, 1, 'L')
        pdf.cell(0, 5, 'BULL = Divergence Haussiere | BEAR = Divergence Baissiere', 0, 1, 'L')
        pdf.ln(5)

        # --- Section Top Opportunités ---
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'TOP OPPORTUNITES', 0, 1, 'L')
        
        opportunities = []
        for row in results_data:
            for tf in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf, {})
                rsi_val = cell_data.get('rsi', np.nan)
                divergence = cell_data.get('divergence', 'Aucune')
                
                if pd.notna(rsi_val):
                    priority = 0
                    signal = ""
                    # Logique de priorité
                    if rsi_val <= 30: priority += 5; signal = "SURVENTE"
                    elif rsi_val >= 70: priority += 5; signal = "SURACHAT"
                    
                    # Nettoyage des textes de divergence pour le PDF (pas d'accents !)
                    div_clean = ""
                    if "Haussi" in divergence: # Haussière
                        priority += 3
                        div_clean = "DIV.BULL"
                    elif "Baissi" in divergence: # Baissière
                        priority += 3
                        div_clean = "DIV.BEAR"
                    
                    if div_clean:
                        signal = f"{signal} + {div_clean}" if signal else div_clean
                    
                    if priority > 0:
                        opportunities.append({'asset': row['Devises'], 'tf': tf, 'rsi': rsi_val, 'signal': signal, 'priority': priority})

        # Tri et affichage
        opportunities.sort(key=lambda x: (-x['priority'], x['rsi']))
        
        pdf.set_font('Arial', '', 9)
        if opportunities:
            for i, opp in enumerate(opportunities[:10], 1):
                # Texte formaté simple sans caractères bizarres
                line = f"{i}. {opp['asset']} ({opp['tf']}) - RSI: {opp['rsi']:.2f} - {opp['signal']}"
                pdf.cell(0, 6, line, 0, 1, 'L')
        else:
            pdf.cell(0, 6, 'Aucun signal majeur detecte.', 0, 1, 'L')
        pdf.ln(5)

        # --- Tableau Complet ---
        pdf.add_page()
        pdf.set_font('Arial', 'B', 10)
        
        # En-têtes
        cell_width_pair = 40
        cell_width_tf = 45
        
        pdf.cell(cell_width_pair, 10, 'Paires', 1, 0, 'C')
        for tf in TIMEFRAMES_DISPLAY:
            pdf.cell(cell_width_tf, 10, tf, 1, 0, 'C')
        pdf.ln()
        
        pdf.set_font('Arial', '', 9)
        
        for row in results_data:
            # Colonne Nom de la paire
            pdf.set_text_color(0, 0, 0) # Noir par défaut
            pdf.cell(cell_width_pair, 10, row['Devises'], 1, 0, 'L')
            
            for tf in TIMEFRAMES_DISPLAY:
                cell_data = row.get(tf, {})
                rsi_val = cell_data.get('rsi', np.nan)
                div = cell_data.get('divergence', 'Aucune')
                
                # Formatage du texte
                txt_display = format_rsi(rsi_val)
                if "Haussi" in div: txt_display += " (BULL)"
                elif "Baissi" in div: txt_display += " (BEAR)"
                
                # Gestion couleur de fond
                fill = False
                if pd.notna(rsi_val):
                    if rsi_val <= 30: 
                        pdf.set_fill_color(*color_oversold_bg)
                        pdf.set_text_color(255, 255, 255) # Blanc sur fond rouge
                        fill = True
                    elif rsi_val >= 70:
                        pdf.set_fill_color(*color_overbought_bg)
                        pdf.set_text_color(255, 255, 255) # Blanc sur fond vert
                        fill = True
                    else:
                        pdf.set_text_color(0, 0, 0) # Noir sur fond blanc
                else:
                    pdf.set_text_color(0, 0, 0)
                    
                pdf.cell(cell_width_tf, 10, txt_display, 1, 0, 'C', fill)
                
            pdf.ln() # Nouvelle ligne après chaque paire

        # --- Sortie du fichier (Méthode Robuste) ---
        # On essaie d'abord la méthode standard string -> latin-1
        try:
            return pdf.output(dest='S').encode('latin-1')
        except AttributeError:
            # Si fpdf2 est utilisé, output() retourne déjà des bytes parfois
            out = pdf.output()
            if isinstance(out, str):
                return out.encode('latin-1')
            return out

    except Exception as e:
        # En cas de crash total, on renvoie un PDF avec l'erreur
        err_pdf = FPDF()
        err_pdf.add_page()
        err_pdf.set_font("Arial", size=10)
        err_pdf.multi_cell(0, 10, txt=f"Erreur PDF: {str(e)}")
        return err_pdf.output(dest='S').encode('latin-1')
