import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

from ml.ml_service import get_player_prediction

def get_db_connection():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_report_data(team_code, period_days=30, squad='all', target_date=None):
    """
    Fetches all data required for the team report.
    Returns a dictionary structured for the PDF generator.
    """
    if target_date is None:
        target_date = datetime.now()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d')
    
    start_date = target_date - timedelta(days=period_days)
    start_date_str = start_date.strftime('%Y-%m-%d')
    target_date_str = target_date.strftime('%Y-%m-%d')
    
    data = {
        'generated_on': target_date.strftime('%B %d, %Y'),
        'period_days': period_days,
        'total_players': 0,
        'high_risk_pct': 0,
        'avg_fatigue': 0,
        'avg_sleep': 'N/A',
        'risk_trend': 'Stable',
        'risk_dist': {'Low': 0, 'Medium': 0, 'High': 0},
        'players': [],
        'high_risk_alerts': [],
        'workload_trend_summary': '',
        'acwr_groups': {'undertraining': [], 'optimal': [], 'high_risk': []},
        'avg_sleep_quality': 'N/A',
        'avg_soreness': 'N/A',
        'poor_recovery_players': [],
        'active_injuries': [],
        'recommendations': []
    }
    
    conn = get_db_connection()
    try:
        # 1. Fetch Players
        query = '''
            SELECT p.player_id, p.name, p.position 
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND u.role = 'player'
        '''
        params = [team_code]
        if squad and squad != 'all':
            query += ' AND p.squad = ?'
            params.append(squad)
            
        players_db = conn.execute(query, params).fetchall()
        
        data['total_players'] = len(players_db)
        if data['total_players'] == 0:
            return data
            
        sum_fatigue = 0
        fatigue_count = 0
        sleep_scores = {'Poor': 1, 'Average': 2, 'Good': 3}
        soreness_scores = {'Low': 1, 'Medium': 2, 'High': 3}
        sum_sleep = 0
        sum_soreness = 0
        wellness_count = 0
        
        # Trend logic (Fatigue)
        hist_query = '''
            SELECT AVG(wd.fatigue_level) as hist_avg
            FROM wellness_data wd
            JOIN players p ON wd.player_id = p.player_id
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND wd.entry_date >= ? AND wd.entry_date < ?
        '''
        hist_params = [team_code, (target_date - timedelta(days=period_days * 2)).strftime('%Y-%m-%d'), start_date_str]
        if squad and squad != 'all':
            hist_query += ' AND p.squad = ?'
            hist_params.append(squad)
            
        historical_fatigue_data = conn.execute(hist_query, hist_params).fetchone()
        hist_avg_fatigue = historical_fatigue_data['hist_avg'] if historical_fatigue_data and historical_fatigue_data['hist_avg'] else 0

        # 3. Process Each Player's Metrics as of Target Date
        for p in players_db:
            p_id = p['player_id']
            name = p['name']
            
            # A. Latest Wellness Entry BEFORE OR ON target_date
            wellness = conn.execute('''
                SELECT fatigue_level, sleep_quality, muscle_soreness 
                FROM wellness_data 
                WHERE player_id = ? AND entry_date <= ?
                ORDER BY entry_date DESC LIMIT 1
            ''', (p_id, target_date_str)).fetchone()
            
            # B. Injury Status as of target_date (Check latest status up to target_date)
            injury_status_row = conn.execute('''
                SELECT active_injury FROM training_data 
                WHERE player_id = ? AND training_date <= ?
                ORDER BY training_date DESC, training_id DESC LIMIT 1
            ''', (p_id, target_date_str)).fetchone()
            
            is_injured = True if injury_status_row and injury_status_row['active_injury'] == 1 else False
            
            # C. Prediction as of target_date
            pred_row = conn.execute('''
                SELECT risk_level, risk_score 
                FROM predictions 
                WHERE player_id = ? AND date(prediction_date) <= date(?)
                ORDER BY prediction_date DESC, prediction_id DESC LIMIT 1
            ''', (p_id, target_date_str)).fetchone()
            
            if not pred_row:
                # Trigger live prediction and save to DB
                prediction = get_player_prediction(p_id)
                risk_level = prediction.get('risk_level', 'Low')
                risk_score = float(prediction.get('risk_score', 0))
            else:
                risk_level = pred_row['risk_level']
                risk_score = float(pred_row['risk_score'])
            
            data['risk_dist'][risk_level] = data['risk_dist'].get(risk_level, 0) + 1
            
            fatigue = 'N/A'
            sleep = 'N/A'
            soreness = 'N/A'
            
            if wellness:
                fatigue_val = wellness['fatigue_level']
                if fatigue_val:
                    sum_fatigue += fatigue_val
                    fatigue_count += 1
                    fatigue = str(fatigue_val)
                    
                sleep = wellness['sleep_quality'] or 'Average'
                soreness = wellness['muscle_soreness'] or 'Low'
                
                sum_sleep += sleep_scores.get(sleep, 2)
                sum_soreness += soreness_scores.get(soreness, 1)
                wellness_count += 1
                
                if sleep == 'Poor' or soreness == 'High':
                    data['poor_recovery_players'].append(name)
            
            # D. Workload (ACWR) - Trailing from target_date
            acute_res = conn.execute('''
                SELECT SUM(training_minutes) as total
                FROM training_data
                WHERE player_id = ? AND training_date > ? AND training_date <= ?
            ''', (p_id, (target_date - timedelta(days=7)).strftime('%Y-%m-%d'), target_date_str)).fetchone()
            
            chronic_res = conn.execute('''
                SELECT SUM(training_minutes) as total
                FROM training_data
                WHERE player_id = ? AND training_date > ? AND training_date <= ?
            ''', (p_id, (target_date - timedelta(days=28)).strftime('%Y-%m-%d'), target_date_str)).fetchone()
            
            acute = acute_res['total'] or 0
            chronic = chronic_res['total'] or 0
            acwr = round(acute / (chronic / 4), 2) if chronic > 0 else 0.0
            
            # Categorize ACWR
            if acwr < 0.8:
                data['acwr_groups']['undertraining'].append(name)
            elif acwr > 1.3:
                data['acwr_groups']['high_risk'].append(name)
            else:
                data['acwr_groups']['optimal'].append(name)
                
            status = 'Fit'
            if is_injured:
                status = 'Recovering'
                if not any(inj['name'] == name for inj in data['active_injuries']):
                    data['active_injuries'].append({'name': name, 'type': 'Recent Injury', 'recommendation': 'Monitor load closely.'})
            elif risk_level == 'High' or acwr > 1.3:
                status = 'At Risk'
            
            # High Risk Alerts logic
            if risk_level == 'High' or risk_score > 60 or acwr > 1.3:
                reasons = []
                if fatigue != 'N/A' and int(fatigue) >= 7: reasons.append("High fatigue")
                if sleep == 'Poor': reasons.append("Poor sleep")
                if acwr > 1.3: reasons.append("ACWR spike (>1.3)")
                if not reasons: reasons.append("Elevated ML Risk Score")
                
                data['high_risk_alerts'].append({
                    'name': name,
                    'risk_score': risk_score,
                    'reasons': reasons
                })
            
            # Add to players list
            data['players'].append({
                'name': name,
                'position': p['position'],
                'risk_score': risk_score,
                'risk_level': risk_level,
                'acwr': acwr,
                'fatigue': fatigue,
                'sleep': sleep,
                'soreness': soreness,
                'status': status
            })

        # Calculate Averages and Summary Data
        if fatigue_count > 0:
            avg_temp = sum_fatigue / fatigue_count
            data['avg_fatigue'] = round(avg_temp, 1)
            
            if hist_avg_fatigue > 0:
                pct_change = ((avg_temp - hist_avg_fatigue) / hist_avg_fatigue) * 100
                if pct_change >= 5:
                    data['risk_trend'] = f"Increased (+{int(pct_change)}%)"
                    data['workload_trend_summary'] = f"Warning: Team fatigue has increased by {int(pct_change)}% over the selected period. Consider reducing high-intensity sessions."
                elif pct_change <= -5:
                    data['risk_trend'] = f"Decreased ({int(pct_change)}%)"
                    data['workload_trend_summary'] = f"Positive: Team fatigue has decreased by {abs(int(pct_change))}% over the selected period. Players are adapting well to load."
                else:
                    data['risk_trend'] = "Stable"
                    data['workload_trend_summary'] = "Team workload and fatigue levels have remained stable over the period."
                    
        if wellness_count > 0:
            avg_s = sum_sleep / wellness_count
            data['avg_sleep_quality'] = 'Good' if avg_s >= 2.5 else ('Average' if avg_s >= 1.5 else 'Poor')
            data['avg_sleep'] = data['avg_sleep_quality']
            avg_sor = sum_soreness / wellness_count
            data['avg_soreness'] = 'High' if avg_sor >= 2.5 else ('Medium' if avg_sor >= 1.5 else 'Low')
            
        data['high_risk_pct'] = int(round((data['risk_dist']['High'] / data['total_players']) * 100)) if data['total_players'] > 0 else 0

        # Generate Actionable Recommendations
        if data['risk_dist']['High'] > 0:
            data['recommendations'].append(f"Reduce training intensity for the {data['risk_dist']['High']} high-risk players.")
        if len(data['acwr_groups']['high_risk']) > 0:
            data['recommendations'].append(f"Monitor ACWR spikes: {len(data['acwr_groups']['high_risk'])} players are over 1.3. Schedule recovery sessions.")
        if data['avg_sleep_quality'] == 'Poor':
            data['recommendations'].append("Team sleep quality is poor. Improve environment and consider later start times.")
        if not data['recommendations']:
            data['recommendations'].append("Current team metrics are optimal. Maintain current training and recovery routines.")

    except sqlite3.Error as e:
        print(f"Database error in report_service: {e}")
    finally:
        conn.close()
        
    return data
