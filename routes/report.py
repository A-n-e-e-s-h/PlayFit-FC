from flask import Blueprint, request, make_response, flash, redirect, url_for
from flask_login import current_user, login_required
import sys
import os
from datetime import datetime

# Add parent directory to path to allow importing utilities
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from services.report_service import generate_report_data
from utils.pdf_generator import generate_team_report_pdf

report_bp = Blueprint('report_bp', __name__)

@report_bp.route('/download_report')
@login_required
def download_report():
    if current_user.role != 'coach':
        flash('Unauthorized access. Only coaches can download reports.', 'error')
        return redirect(url_for('dashboard'))
        
    try:
        # Get parameters
        target_date_str = request.args.get('date')
        squad = request.args.get('squad', 'all')
        
        # Default to 30 days window for aggregation
        period = 30
            
        squad = request.args.get('squad', 'all')
        squad_name = None
        if squad and squad != 'all':
            squad_name = squad.replace("mens", "Men's Team").replace("womens", "Women's Team").capitalize()
            if "Team" not in squad_name and squad in ["mens", "womens"]:
               # Re-apply correctly if capitalize messed it up
               if squad == "mens": squad_name = "Men's Team"
               if squad == "womens": squad_name = "Women's Team"
            
        team_code = current_user.team_code
        team_name = current_user.team_name or "Independent Protocol"
        coach_name = current_user.full_name if current_user.full_name else current_user.username
        
        # 1. Fetch Aggregated Data
        report_data = generate_report_data(team_code, period_days=period, squad=squad, target_date=target_date_str)
        
        if report_data.get('total_players', 0) == 0:
            flash('No players found in your team to generate a report.', 'error')
            return redirect(url_for('dashboard'))
            
        # 2. Generate PDF Bytes
        pdf_bytes = generate_team_report_pdf(
            team_name=team_name,
            coach_name=coach_name,
            period=period,
            data=report_data,
            squad_name=squad_name
        )
        
        # 3. Log Report Generation in Database
        try:
            from services.report_service import get_db_connection
            conn = get_db_connection()
            report_name = f"Team_Injury_Report_{team_name.replace(' ', '_')}_{target_date_str or 'Today'}.pdf"
            conn.execute('''
                INSERT INTO generated_reports (coach_id, report_name, report_type, squad, period, generated_date, report_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (current_user.id, report_name, 'Team Injury Risk', squad, period, datetime.now().strftime('%Y-%m-%d'), target_date_str or datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            conn.close()
        except Exception as log_err:
            print(f"Log Error: {log_err}")

        # 4. Create Download Response
        response = make_response(pdf_bytes)
        filename = f"Team_Injury_Report_{team_name.replace(' ', '_')}_{target_date_str or 'Today'}.pdf"
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        print(f"Error generating report: {e}")
        flash('An unexpected error occurred while generating the report.', 'error')
        return redirect(url_for('dashboard'))
