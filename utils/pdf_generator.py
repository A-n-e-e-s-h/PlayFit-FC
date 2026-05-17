import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

def generate_team_report_pdf(team_name, coach_name, period, data, squad_name=None):
    """
    Generates a PDF report for the coach's team.
    `data` contains aggregated dicts and lists from the report_service.
    Returns a bytes object of the PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        name='TitleStyle',
        parent=styles['Heading1'],
        alignment=TA_CENTER,
        fontSize=20,
        spaceAfter=15,
        textColor=colors.HexColor('#1f2937')
    )
    
    section_title = ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=10,
        textColor=colors.HexColor('#374151')
    )
    
    normal_style = styles['Normal']
    
    elements = []
    
    # --- SECTION 1: HEADER ---
    title_text = "Team Injury Risk Report"
    if squad_name:
        title_text = f"{squad_name} Injury Risk Report"
        
    elements.append(Paragraph(title_text, title_style))
    elements.append(Paragraph(f"<b>Team Name:</b> {team_name}", normal_style))
    elements.append(Paragraph(f"<b>Coach Name:</b> {coach_name}", normal_style))
    elements.append(Paragraph(f"<b>Report Date:</b> {data.get('generated_on', 'N/A')}", normal_style))
    elements.append(Spacer(1, 20))
    
    # --- SECTION 2: OVERVIEW SUMMARY ---
    elements.append(Paragraph("Overview Summary", section_title))
    overview_data = [
        ['Total Players', str(data.get('total_players', 0))],
        ['High Risk Players', f"{data.get('high_risk_pct', '0')}%"],
        ['Avg Fatigue', str(data.get('avg_fatigue', 0))],
        ['Avg Sleep', str(data.get('avg_sleep', 'N/A'))],
        ['Risk Trend', data.get('risk_trend', 'Stable')]
    ]
    t_overview = Table(overview_data, colWidths=[200, 100])
    t_overview.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f3f4f6')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#1f2937')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
    ]))
    elements.append(t_overview)
    elements.append(Spacer(1, 15))
    
    # --- SECTION 3: TEAM RISK DISTRIBUTION ---
    elements.append(Paragraph("Team Risk Distribution", section_title))
    dist_data = [
        ['Low Risk', 'Medium Risk', 'High Risk'],
        [str(data.get('risk_dist', {}).get('Low', 0)), 
         str(data.get('risk_dist', {}).get('Medium', 0)), 
         str(data.get('risk_dist', {}).get('High', 0))]
    ]
    t_dist = Table(dist_data, colWidths=[150, 150, 150])
    t_dist.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#dcfce7')), # Low
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#fef08a')), # Medium
        ('BACKGROUND', (2,0), (2,0), colors.HexColor('#fecaca')), # High
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#1f2937')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#9ca3af')),
    ]))
    elements.append(t_dist)
    elements.append(Spacer(1, 15))
    
    # --- SECTION 4: PLAYER RISK TABLE ---
    elements.append(Paragraph("Player Risk Table", section_title))
    player_headers = ['Name', 'Position', 'Risk %', 'Level', 'ACWR', 'Fatigue', 'Sleep', 'Soreness', 'Status']
    table_data = [player_headers]
    for p in data.get('players', []):
        # Clean risk level for professional report display
        risk_level = str(p.get('risk_level', '')).replace(' (Wellness-only)', '')
        
        table_data.append([
            str(p.get('name', '')),
            str(p.get('position', '')),
            f"{p.get('risk_score', 0)}%",
            risk_level,
            str(p.get('acwr', 0)),
            str(p.get('fatigue', '')),
            str(p.get('sleep', '')),
            str(p.get('soreness', '')),
            str(p.get('status', ''))
        ])
    
    # Adjust widths to fit 532pt usable area (Letter width 612 - 80 margins)
    t_players = Table(table_data, colWidths=[90, 60, 45, 60, 45, 45, 45, 60, 60])
    t_players.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#374151')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
    ]))
    elements.append(t_players)
    elements.append(Spacer(1, 15))
    
    # --- SECTION 5: HIGH-RISK ALERTS ---
    elements.append(Paragraph("High-Risk Alerts", section_title))
    alerts = data.get('high_risk_alerts', [])
    if not alerts:
        elements.append(Paragraph("No players are currently at high risk.", normal_style))
    else:
        for a in alerts:
            reasons = ", ".join(a.get('reasons', []))
            elements.append(Paragraph(f"• <b>{a['name']}</b> (Risk: {a['risk_score']}%): {reasons}", normal_style))
    elements.append(Spacer(1, 15))
    
    # --- SECTION 6: WORKLOAD & FATIGUE TRENDS ---
    elements.append(Paragraph("Workload & Fatigue Trends", section_title))
    elements.append(Paragraph(data.get('workload_trend_summary', 'Insufficient data to calculate trends for this period.'), normal_style))
    elements.append(Spacer(1, 15))
    
    # --- SECTION 7: ACWR ANALYSIS ---
    elements.append(Paragraph("ACWR Analysis", section_title))
    acwr_groups = data.get('acwr_groups', {'undertraining': [], 'optimal': [], 'high_risk': []})
    elements.append(Paragraph(f"• <b>Undertraining (<0.8):</b> {', '.join(acwr_groups['undertraining']) or 'None'}", normal_style))
    elements.append(Paragraph(f"• <b>Optimal (0.8 - 1.3):</b> {', '.join(acwr_groups['optimal']) or 'None'}", normal_style))
    elements.append(Paragraph(f"• <b>High Risk (>1.3):</b> {', '.join(acwr_groups['high_risk']) or 'None'}", normal_style))
    elements.append(Spacer(1, 15))
    
    # --- SECTION 8: WELLNESS ANALYSIS ---
    elements.append(Paragraph("Wellness Analysis", section_title))
    elements.append(Paragraph(f"<b>Average Sleep Quality:</b> {data.get('avg_sleep_quality', 'N/A')}", normal_style))
    elements.append(Paragraph(f"<b>Average Soreness:</b> {data.get('avg_soreness', 'N/A')}", normal_style))
    elements.append(Paragraph(f"<b>Players with poor recovery:</b> {', '.join(data.get('poor_recovery_players', [])) or 'None'}", normal_style))
    elements.append(Spacer(1, 15))
    
    # --- SECTION 9: ACTIVE INJURY STATUS ---
    elements.append(Paragraph("Active Injury Status", section_title))
    injuries = data.get('active_injuries', [])
    if not injuries:
        elements.append(Paragraph("No players are currently recovering from active injuries.", normal_style))
    else:
        for inj in injuries:
            elements.append(Paragraph(f"• <b>{inj['name']}:</b> Recovering. {inj.get('recommendation', 'Monitor closely.')}", normal_style))
    elements.append(Spacer(1, 15))
    
    # --- SECTION 10: RECOMMENDATIONS ---
    elements.append(Paragraph("Recommendations", section_title))
    recs = data.get('recommendations', [])
    if not recs:
        elements.append(Paragraph("Continue current training protocols. No specific interventions needed.", normal_style))
    else:
        for r in recs:
            elements.append(Paragraph(f"• {r}", normal_style))
            
    doc.build(elements)
    buffer.seek(0)
    return buffer.read()
