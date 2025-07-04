# --- Interface Utilisateur ---
st.markdown('<h1 class="screener-header">Screener RSI & Divergence (OANDA)</h1>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button("🔄 Rescan All Forex Pairs", key="rescan_button", use_container_width=True):
        st.session_state.scan_done = False
        st.cache_data.clear()
        st.rerun()

# Lancer l'analyse automatiquement si aucun résultat n'existe ou si le scan n'est pas terminé
if 'results' not in st.session_state or not st.session_state.get('scan_done', False):
    with st.spinner("🚀 Performing high-speed scan with OANDA..."):
        run_analysis_process()
    st.success(f"✅ Analysis complete! {len(FOREX_PAIRS)} pairs analyzed.")

if 'results' in st.session_state and st.session_state.results:
    last_scan_time_str = st.session_state.last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(f"""<div class="update-info">🔄 Last update: {last_scan_time_str} (Data from OANDA)</div>""", unsafe_allow_html=True)
    
    st.markdown("""<div class="legend-container">
        <div class="legend-item"><div class="legend-dot oversold-dot"></div><span>Oversold (RSI ≤ 20)</span></div>
        <div class="legend-item"><div class="legend-dot overbought-dot"></div><span>Overbought (RSI ≥ 80)</span></div>
        <div class="legend-item"><span class="divergence-arrow bullish-arrow">↑</span><span>Bullish Divergence</span></div>
        <div class="legend-item"><span class="divergence-arrow bearish-arrow">↓</span><span>Bearish Divergence</span></div>
    </div>""", unsafe_allow_html=True)

    # --- Affichage du tableau de résultats ---
    st.markdown("### 📈 RSI & Divergence Analysis Results")
    html_table = '<table class="rsi-table">'
    html_table += '<thead><tr><th>Devises</th>'
    for tf_display_name in TIMEFRAMES_DISPLAY: html_table += f'<th>{tf_display_name}</th>'
    html_table += '</tr></thead><tbody>'

    for row in st.session_state.results:
        html_table += f'<tr><td class="devises-cell">{row["Devises"]}</td>'
        for tf_display_name in TIMEFRAMES_DISPLAY:
            cell_data = row.get(tf_display_name, {'rsi': np.nan, 'divergence': 'Aucune'})
            rsi_val = cell_data.get('rsi', np.nan)
            divergence = cell_data.get('divergence', 'Aucune')
            css_class = get_rsi_class(rsi_val)
            formatted_val = format_rsi(rsi_val)
            divergence_icon = ""
            if divergence == "Haussière":
                divergence_icon = '<span class="divergence-arrow bullish-arrow">↑</span>'
            elif divergence == "Baissière":
                divergence_icon = '<span class="divergence-arrow bearish-arrow">↓</span>'
            html_table += f'<td class="{css_class}">{formatted_val} {divergence_icon}</td>'
        html_table += '</tr>'
    html_table += '</tbody></table>'
    st.markdown(html_table, unsafe_allow_html=True)
    
    # --- Section de téléchargement d'image ---
    st.divider()
    image_bytes = create_image_report_with_colors(st.session_state.results, "Screener RSI & Divergence")
    
    st.download_button(
        label="🖼️ Télécharger les résultats (Image)",
        data=image_bytes,
        file_name=f"rsi_screener_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
        mime='image/png',
        use_container_width=True
    )

    # --- Affichage des statistiques ---
    st.markdown("### 📊 Signal Statistics")
    stat_cols = st.columns(len(TIMEFRAMES_DISPLAY))
    for i, tf_display_name in enumerate(TIMEFRAMES_DISPLAY):
        tf_data = [row.get(tf_display_name, {}) for row in st.session_state.results]
        valid_rsi_values = [d.get('rsi') for d in tf_data if pd.notna(d.get('rsi'))]
        bullish_div_count = sum(1 for d in tf_data if d.get('divergence') == 'Haussière')
        bearish_div_count = sum(1 for d in tf_data if d.get('divergence') == 'Baissière')

        if valid_rsi_values:
            oversold_count = sum(1 for x in valid_rsi_values if x <= 20)
            overbought_count = sum(1 for x in valid_rsi_values if x >= 80)
            total_signals = oversold_count + overbought_count + bullish_div_count + bearish_div_count
            delta_text = f"🔴 {oversold_count} S | 🟢 {overbought_count} B | <span class='bullish-arrow'>↑</span> {bullish_div_count} | <span class='bearish-arrow'>↓</span> {bearish_div_count}"
            with stat_cols[i]:
                st.metric(label=f"Signals {tf_display_name}", value=str(total_signals))
                st.markdown(delta_text, unsafe_allow_html=True)
        else:
            with stat_cols[i]: st.metric(label=f"Signals {tf_display_name}", value="N/A", delta="No data")
