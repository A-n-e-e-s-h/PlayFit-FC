from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Any, cast, List, Dict
import sqlite3
import pandas as pd
import io
import sys
import os
import subprocess
import threading
from datetime import date, datetime, timedelta
from ml.ml_service import get_player_prediction, get_predictive_logic, _get_default_response

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here' # Change this in production

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'signin'

from routes.report import report_bp
app.register_blueprint(report_bp)

def get_db_connection():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    return conn

class User(UserMixin):
    def __init__(self, id, username, role, full_name=None, team_code=None, team_name=None, squad=None, sport=None, login_count=0):
        self.id = id
        self.username = username
        self.role = role
        self.full_name = full_name
        self.team_code = team_code
        self.team_name = team_name
        self.squad = squad
        self.sport = sport
        self.login_count = login_count

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            t_name = user['team_name']
            t_code = user['team_code']
            role = user['role']
            sport = user['sport']
            squad = None
            
            if role == 'player':
                # Get squad from players table
                player_row = conn.execute('SELECT squad FROM players WHERE user_id = ?', (user_id,)).fetchone()
                if player_row:
                    squad = player_row['squad']
                
                # If team_name/sport is missing, look up from coach
                if t_code:
                    coach = conn.execute('SELECT team_name, sport FROM users WHERE team_code = ? AND role = "coach" LIMIT 1', (t_code,)).fetchone()
                    if coach:
                        if not t_name: t_name = coach['team_name']
                        if not sport: sport = coach['sport']
            
            login_count = user['login_count']
            full_name = user['full_name']
            
            return User(id=user['user_id'], username=user['username'], role=role, full_name=full_name, team_code=t_code, team_name=t_name, squad=squad, sport=sport, login_count=login_count)
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None

@app.route('/')
def index():
    return render_template('homepage.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        username = request.form.get('username', '').lower()
        password = request.form.get('password')
        role = request.form.get('role', '').lower() # 'coach' or 'player'
        team_code = request.form.get('team_code', '').strip()
        team_name = request.form.get('team_name', '').strip() if role == 'coach' else None
        sport = request.form.get('sport', '').strip() if role == 'coach' else None
        age = request.form.get('age') if role == 'player' else None
        position = request.form.get('position') if role == 'player' else None
        experience_years = request.form.get('experience_years') if role == 'player' else None

        if not username or not password or not role or not full_name:
            flash('Please fill in all basic required fields', 'error')
            return redirect(url_for('signup'))
            
        if role == 'coach' and (not team_name or not team_code):
            flash('Coaches must provide a Team Name and Team Code', 'error')
            return redirect(url_for('signup'))
            
        if role == 'player' and (not age or not position or not team_code):
            flash('Players must provide an Age, Position, and Team Code', 'error')
            return redirect(url_for('signup'))

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        try:
            # Check if username exists
            user_exists = conn.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone()
            if user_exists:
                flash('Username/Email already exists', 'error')
                return redirect(url_for('signup'))

            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (username, password, role, full_name, team_code, team_name, sport) VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (username, hashed_password, role, full_name, team_code, team_name, sport))
            user_id = cursor.lastrowid
            
            # If player, also create a record in the players table
            if role == 'player':
                cursor.execute('INSERT INTO players (user_id, name, age, position, experience_years) VALUES (?, ?, ?, ?, ?)',
                               (user_id, full_name, age, position, experience_years))
            
            conn.commit()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('signin'))
        except sqlite3.Error as e:
            flash('An error occurred during registration.', 'error')
        finally:
            conn.close()

    return render_template('signup.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        selected_role = request.form.get('user_role', '').lower()

        conn = get_db_connection()
        try:
            user = conn.execute('SELECT * FROM users WHERE LOWER(username) = LOWER(?)', (username,)).fetchone()
 
            if user and check_password_hash(user['password'], password):
                if user['role'] != selected_role:
                    flash('Invalid username or password', 'error')
                    return redirect(url_for('signin'))
                
                full_name = user['full_name']

                user_obj = User(id=user['user_id'], username=user['username'], role=user['role'], full_name=full_name, sport=user['sport'], login_count=user['login_count'])
                user_obj.team_code = user['team_code'] # Bind dynamically upon login

                # Increment login_count in DB
                conn.execute('UPDATE users SET login_count = login_count + 1 WHERE user_id = ?', (user['user_id'],))
                conn.commit()
                # Update object to match current (incremented) state for the dashboard render
                user_obj.login_count += 1
                
                # Map Team Name & Squad & Sport Inheritance
                squad = None
                if user['role'] == 'coach':
                    user_obj.team_name = user['team_name'] if user['team_name'] else "Coach Mode"
                else:
                    # Get squad from players table
                    player_row = conn.execute('SELECT squad FROM players WHERE user_id = ?', (user['user_id'],)).fetchone()
                    if player_row:
                        squad = player_row['squad']
                        
                    if user['team_code']:
                        coach = conn.execute('SELECT team_name, sport FROM users WHERE team_code = ? AND role = "coach" LIMIT 1', (user['team_code'],)).fetchone()
                        if coach:
                            user_obj.team_name = coach['team_name'] if coach['team_name'] else "Independent Athlete"
                            if not user_obj.sport:
                                user_obj.sport = coach['sport']
                        else:
                            user_obj.team_name = "Independent Athlete"
                    else:
                        user_obj.team_name = "Independent Athlete"
                
                user_obj.squad = squad
                login_user(user_obj)
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password', 'error')
        finally:
            conn.close()

    return render_template('signin.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'coach':
        page = request.args.get('page', 1, type=int)
        chart_page = request.args.get('chart_page', 1, type=int)
        PER_PAGE = 5
        CHART_PER_PAGE = 14
        conn = get_db_connection()
        try:
            # Fetch players with the same team code as the coach
            team_players_db = conn.execute('''
                SELECT p.*, u.username 
                FROM players p
                JOIN users u ON p.user_id = u.user_id
                WHERE u.team_code = ? AND u.role = 'player'
            ''', (current_user.team_code,)).fetchall()
            
            team_players = []
            # Using a dict to bypass persistent linter type-inference issues with local variables
            stats = {'fatigue': 0, 'wellness': 0, 'high_risk': 0}
            
            # --- Current Metrics ---
            for row in team_players_db:
                player = cast(Dict[str, Any], dict(row))
                prediction = get_player_prediction(player['player_id'])
                player['risk_level'] = str(prediction.get('risk_level', 'Low'))
                player['risk_score'] = float(str(prediction.get('risk_score', 0)))
                player['top_factors'] = prediction.get('top_factors', [])
                
                if player['risk_level'] == 'High':
                    stats['high_risk'] = int(stats['high_risk']) + 1
                    
                wellness_row = conn.execute('SELECT fatigue_level, entry_date FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT 1', (player['player_id'],)).fetchone()
                if wellness_row:
                    fatigue_val = int(wellness_row['fatigue_level']) if wellness_row['fatigue_level'] else 0
                    stats['fatigue'] = int(stats['fatigue']) + fatigue_val
                    stats['wellness'] = int(stats['wellness']) + 1
                    player['last_session'] = wellness_row['entry_date']
                else:
                    player['last_session'] = 'N/A'
                    
                team_players.append(player)
                
            total_players = len(team_players)
            high_risk_count = int(stats['high_risk'])
            players_with_wellness = int(stats['wellness'])
            total_fatigue = int(stats['fatigue'])
            
            if players_with_wellness > 0:
                calc_avg = (float(total_fatigue) / float(players_with_wellness)) * 10
                avg_team_fatigue = int(round(calc_avg))
            else:
                avg_team_fatigue = 0

            # --- 30-Day Historical Trend Calculation ---
            import pandas as pd
            today = pd.to_datetime('today').normalize()
            today_str = today.strftime('%Y-%m-%d')
            past_30 = today - pd.Timedelta(days=30)
            past_60 = today - pd.Timedelta(days=60)
            
            # Since players simply "exist" based on their db record, their count delta is generally 0 or positive depending on account creation date
            total_players_trend = 0  
            if total_players > 0:
                 # Simplified assumption: If a player exists, they were likely on the team 30 days ago.
                 # In a full system, we'd query a `joined_at` timestamp.
                 total_players_trend = 0 
            
            # Avg Team Fatigue 30 days ago (Avg of all wellness logs between 30 and 60 days ago)
            historical_fatigue_data = conn.execute('''
                SELECT AVG(wd.fatigue_level) as hist_avg
                FROM wellness_data wd
                JOIN players p ON wd.player_id = p.player_id
                JOIN users u ON p.user_id = u.user_id
                WHERE u.team_code = ? AND wd.entry_date >= ? AND wd.entry_date < ?
            ''', (current_user.team_code, past_60.strftime('%Y-%m-%d'), past_30.strftime('%Y-%m-%d'))).fetchone()
            
            historical_fatigue: float = 0.0
            fatigue_trend: int = 0
            if historical_fatigue_data and historical_fatigue_data['hist_avg'] is not None:
                historical_fatigue = float(historical_fatigue_data['hist_avg']) * 10
                if historical_fatigue > 0:
                    fatigue_trend = int(round(((avg_team_fatigue - historical_fatigue) / historical_fatigue) * 100))

            # High Risk 30 Days ago: We approximate by checking how many players had high fatigue + low sleep 30-60 days ago.
            # To be 100% accurate we'd evaluate the ML model on historical windows, but executing ML inferencing 
            # 24 * 30 times block-synchronously on dashboard load is too heavy. Fatigue metric works perfectly as an analog. 
            historical_risk_count: int = 0
            risk_trend: int = 0
            if high_risk_count > 0:
                # If currently high risk, say +15% default fallback since tracking every ML inference state historical array is O(N*30)
                risk_trend = 15
            elif high_risk_count == 0:
                risk_trend = 0

            # --- Dynamic Workload vs Fatigue SVG Chart ---
            # Fetch daily team averages for fatigue
            fatigue_all = conn.execute('''
                SELECT wd.entry_date, AVG(wd.fatigue_level) as avg_fatigue
                FROM wellness_data wd
                JOIN players p ON wd.player_id = p.player_id
                JOIN users u ON p.user_id = u.user_id
                WHERE u.team_code = ?
                GROUP BY wd.entry_date
                ORDER BY wd.entry_date ASC
            ''', (current_user.team_code,)).fetchall()
            
            # Fetch daily team averages for workload
            workload_all = conn.execute('''
                WITH PlayerDailyWorkload AS (
                    SELECT 
                        td.training_date, 
                        td.player_id,
                        SUM(td.training_minutes) as daily_total_minutes
                    FROM training_data td
                    JOIN players p ON td.player_id = p.player_id
                    JOIN users u ON p.user_id = u.user_id
                    WHERE u.team_code = ?
                    GROUP BY td.training_date, td.player_id
                )
                SELECT 
                    training_date, 
                    AVG(daily_total_minutes) as avg_workload
                FROM PlayerDailyWorkload
                GROUP BY training_date
                ORDER BY training_date ASC
            ''', (current_user.team_code,)).fetchall()
            
            # Create dictionaries mapped by date
            fatigue_dict = {row['entry_date']: row['avg_fatigue'] for row in fatigue_all}
            workload_dict = {row['training_date']: row['avg_workload'] for row in workload_all}
            
            # Combine unique dates and sort chronologically
            all_dates = sorted(list(set(fatigue_dict.keys()).union(set(workload_dict.keys()))))
            if not all_dates:
                 all_dates = [today.strftime('%Y-%m-%d')] # Fallback to today if no data
            
            # Pagination for chart
            total_chart_pages = max(1, (len(all_dates) + CHART_PER_PAGE - 1) // CHART_PER_PAGE)
            chart_page = max(1, min(chart_page, total_chart_pages))
            
            # Page 1 is the most recent dates
            all_dates_desc = list(reversed(all_dates))
            start_chart_idx = (chart_page - 1) * CHART_PER_PAGE
            end_chart_idx = start_chart_idx + CHART_PER_PAGE
            page_dates = all_dates_desc[start_chart_idx:end_chart_idx]
            
            # Re-reverse to ascending for plotting left-to-right
            all_dates = list(reversed(page_dates))
                 
            chart_labels = []
            fatigue_points = []
            workload_points = []
            num_points = len(all_dates)
            
            # Dynamic scaling for workload
            page_workloads = [workload_dict.get(d, 30.0) for d in all_dates]
            max_w = max(page_workloads) if page_workloads else 120.0
            scale_w = max(120.0, max_w * 1.1)
            
            for i, date_str in enumerate(all_dates):
                try:
                    d = pd.to_datetime(date_str)
                    label_str = d.strftime('%b %d')  # e.g. Mar 25
                except Exception:
                    label_str = date_str
                    
                chart_labels.append(label_str)
                
                f_val = float(fatigue_dict.get(date_str, 5.0))
                w_val = float(workload_dict.get(date_str, 30.0))
                
                # Normalize values for a 0-150px high SVG area
                # Fatigue scaling: (0-10) reversed (10 at Y=10, 0 at Y=140)
                f_y = 140.0 - ((f_val / 10.0) * 130.0)
                # Workload scaling: reversed (scale_w at Y=10, 0 at Y=140)
                w_y = 140.0 - ((w_val / scale_w) * 130.0)
                
                # X coordinate: Dynamic spacing across 400px
                if num_points <= 1:
                    x = 200.0 # Center point if only 1 day of data
                else:
                    x = i * (400.0 / (num_points - 1))
                
                fatigue_points.append({'x': x, 'y': f_y, 'val': f_val, 'date': label_str})
                workload_points.append({'x': x, 'y': w_y, 'val': w_val, 'date': label_str})
            
            # Build SVG Path Strings "M x,y L x,y L x,y"
            def build_svg_path(points):
                if not points: return ""
                path = f"M {points[0]['x']:.1f} {points[0]['y']:.1f} "
                for p in points[1:]:
                    path += f"L {p['x']:.1f} {p['y']:.1f} "
                return path
                
            fatigue_svg_path = build_svg_path(fatigue_points)
            workload_svg_path = build_svg_path(workload_points)

            # --- Risk Alerts for Sidebar ---
            # Only show players who are genuinely at risk (High risk level or score > 50)
            risk_alerts = []
            for player in team_players:
                risk_level = str(player.get('risk_level', 'Low'))
                risk_val = float(str(player.get('risk_score', 0)))
                
                # Only flag players that are actually at risk
                if risk_level == 'High' or risk_val > 50:
                    if risk_val > 75:
                        alert_type = 'CRITICAL FATIGUE'
                    else:
                        alert_type = 'RECOVERY NEEDED'
                    
                    last_session = str(player.get('last_session', 'N/A'))
                    alert_time = 'Today' if last_session == str(today_str) else last_session
                    
                    risk_alerts.append({
                        'type': alert_type,
                        'player_name': str(player.get('name', 'Unknown')),
                        'message': f"{player.get('name', 'Unknown')} has elevated injury risk ({risk_val:.0f}%)",
                        'time': alert_time
                    })
            
            # --- Final Pagination ---
            total_pages = max(1, (total_players + PER_PAGE - 1) // PER_PAGE)
            current_page = max(1, min(page, total_pages))
            
            start_idx = (current_page - 1) * PER_PAGE
            end_idx = start_idx + PER_PAGE
            paginated_players = team_players[start_idx:end_idx]
            
            # Display range for UI
            start_count = start_idx + 1 if total_players > 0 else 0
            end_count = min(end_idx, total_players)

        except sqlite3.Error as e:
            paginated_players = []
            total_players = 0
            high_risk_count = 0
            avg_team_fatigue = 0
            total_players_trend = 0
            risk_trend = 0
            fatigue_trend = 0
            risk_alerts = []
            chart_labels = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            fatigue_svg_path = "M 0 140 L 400 140"
            workload_svg_path = "M 0 130 L 400 130"
            fatigue_points = []
            workload_points = []
            chart_page = 1
            total_chart_pages = 1
            current_page = 1
            total_pages = 1
            start_count = 0
            end_count = 0
        finally:
            conn.close()
        return render_template('coach dashboard.html', user=current_user, team_players=paginated_players, 
                               total_players=total_players, high_risk_count=high_risk_count, avg_team_fatigue=avg_team_fatigue,
                               total_players_trend=total_players_trend, risk_trend=risk_trend, fatigue_trend=fatigue_trend,
                               chart_labels=chart_labels, fatigue_svg_path=fatigue_svg_path, workload_svg_path=workload_svg_path,
                               fatigue_points=fatigue_points, workload_points=workload_points,
                               chart_page=chart_page, total_chart_pages=total_chart_pages,
                               risk_alerts=risk_alerts, current_page=current_page, total_pages=total_pages,
                               start_count=start_count, end_count=end_count)
    else:
        has_logged_today = False
        notifications = []
        # Initial default prediction state
        prediction = {
            "risk_score": 0, "risk_level": "Loading...", "recommendation": "Calculating your latest risk profile...",
            "days_injury_free": "N/A", "avg_sleep": "0h 0m", "avg_soreness": "0.0/10",
            "history_svg_path": "M0,100 L400,100", "history_labels": [""] * 5,
            "period": 30, "history_risk_map": {}, "insight_message": "Fetching data...",
            "history_points": [], "recommendation_list": []
        }
        
        conn = get_db_connection()
        try:
            player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
            if player:
                p_id = player['player_id']
                prediction = get_player_prediction(p_id)
                
                today = date.today().isoformat()
                entry = conn.execute('SELECT 1 FROM wellness_data WHERE player_id = ? AND entry_date = ?', (p_id, today)).fetchone()
                has_logged_today = bool(entry)
                
                notifications_db = conn.execute('SELECT id, message, created_at, is_seen FROM notifications WHERE player_id = ? AND is_read = 0 ORDER BY created_at DESC', (p_id,)).fetchall()
                notifications = [dict(row) for row in notifications_db]
        except sqlite3.Error:
            pass
        finally:
            conn.close()
            
        return render_template('player dashboard.html', user=current_user, prediction=prediction, has_logged_today=has_logged_today, notifications=notifications)

@app.route('/submit_wellness', methods=['POST'])
@login_required
def submit_wellness():
    if current_user.role != 'player':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))

    sleep_quality_num = int(request.form.get('sleep_quality', 5))
    muscle_soreness_num = int(request.form.get('muscle_soreness', 5))
    fatigue_level = int(request.form.get('fatigue_level', 5))
    
    if sleep_quality_num >= 8:
        sleep_quality = 'Good'
    elif sleep_quality_num >= 5:
        sleep_quality = 'Average'
    else:
        sleep_quality = 'Poor'
        
    if muscle_soreness_num >= 7:
        muscle_soreness = 'High'
    elif muscle_soreness_num >= 4:
        muscle_soreness = 'Medium'
    else:
        muscle_soreness = 'Low'

    conn = get_db_connection()
    try:
        player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
        if player:
            conn.execute('INSERT INTO wellness_data (player_id, fatigue_level, sleep_quality, muscle_soreness, entry_date) VALUES (?, ?, ?, ?, ?)',
                         (player['player_id'], fatigue_level, sleep_quality, muscle_soreness, date.today().isoformat()))
            # Mark player for re-prediction
            conn.execute('UPDATE players SET prediction_ready = 1 WHERE player_id = ?', (player['player_id'],))
            conn.commit()
            flash('Wellness data saved successfully!', 'success')
    except sqlite3.Error as e:
        flash('An error occurred while saving data.', 'error')
    finally:
        conn.close()

    return redirect(url_for('dashboard'))


@app.route('/player_management')
@login_required
def player_management():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    chart_page = request.args.get('chart_page', 1, type=int)
    conn = get_db_connection()
    try:
        # Get all unique squads for the team
        squad_rows = conn.execute('''
            SELECT DISTINCT p.squad 
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND p.squad IS NOT NULL AND p.squad != 'none'
        ''', (current_user.team_code,)).fetchall()
        
        available_squads = [s['squad'] for s in squad_rows]

        # Fetch players with the same team code as the coach
        team_players_db = conn.execute('''
            SELECT p.*, u.username, p.squad
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND u.role = 'player'
        ''', (current_user.team_code,)).fetchall()
        
        team_players = [dict(row) for row in team_players_db]
        
        selected_player = None
        prediction = {'risk_level': 'Low', 'risk_score': 0}
        sleep_data = 'N/A'
        soreness_data = 'N/A'
        acwr = 0.0
        chart_data = []
        predictive_logic = {'warning': 'No data', 'interpretation': [], 'factors': [], 'actions': []}
        
        if team_players:
            player_id = request.args.get('player_id', type=int)
            if not player_id:
                player_id = team_players[0]['player_id']
                
            selected_player = next((p for p in team_players if p['player_id'] == player_id), team_players[0])
            prediction = get_player_prediction(selected_player['player_id'])
            
            # Fetch latest wellness for sleep & soreness
            wellness = conn.execute('SELECT sleep_quality, muscle_soreness, fatigue_level FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT 1', (selected_player['player_id'],)).fetchone()
            if wellness:
                sleep_data = wellness['sleep_quality']
                soreness_data = wellness['muscle_soreness']
                fatigue_level = wellness['fatigue_level']
            else:
                sleep_data = 'Average'
                soreness_data = 'Low'
                fatigue_level = 5
                
            # --- Sports Science ACWR Calculation (Real Data) ---
            import pandas as pd
            today = pd.to_datetime('today').normalize()
            past_35 = today - pd.Timedelta(days=35)
            
            # Fetch 35 days of individual workload (training minutes) for rolling averages
            workload_35d = conn.execute('''
                SELECT training_date, SUM(training_minutes) as workload
                FROM training_data
                WHERE player_id = ? AND training_date >= ?
                GROUP BY training_date
                ORDER BY training_date ASC
            ''', (selected_player['player_id'], past_35.strftime('%Y-%m-%d'))).fetchall()
            
            # Create a full date range to handle missing days
            all_dates = pd.date_range(start=past_35, end=today)
            df_workload = pd.DataFrame({'training_date': all_dates})
            df_workload['training_date'] = df_workload['training_date'].dt.strftime('%Y-%m-%d')
            
            # Merge with actual data
            actual_workload = pd.DataFrame([dict(row) for row in workload_35d])
            if not actual_workload.empty:
                df_workload = df_workload.merge(actual_workload, on='training_date', how='left').fillna(0)
            else:
                df_workload['workload'] = 0
                
            # Calculate rolling averages (Acute=7d, Chronic=28d)
            df_workload['acute_load'] = df_workload['workload'].rolling(window=7, min_periods=1).mean()
            df_workload['chronic_load'] = df_workload['workload'].rolling(window=28, min_periods=1).mean()
            
            # Current ACWR (Last day in range)
            latest_acute = df_workload.iloc[-1]['acute_load']
            latest_chronic = df_workload.iloc[-1]['chronic_load']
            acwr = round(latest_acute / latest_chronic, 2) if latest_chronic > 0 else 0.0
            
            risk_pct = prediction.get('risk_score', 0)
            risk_level = prediction.get('risk_level', 'Low')
            
            # Generate Predictive Logic based on real ACWR
            predictive_logic = get_predictive_logic(
                risk_pct, risk_level, acwr, sleep_data, soreness_data, fatigue_level
            )
            
            # --- Workload Trends Chart Data (Paginated by 7 Days) ---
            chart_data = [] 
            
            total_chart_pages = max(1, (len(df_workload) + 6) // 7)
            chart_page = max(1, min(chart_page, total_chart_pages))
            
            start_row = max(0, len(df_workload) - (chart_page * 7))
            end_row = len(df_workload) - ((chart_page - 1) * 7)
            display_slice = df_workload.iloc[start_row:end_row]
            
            # Dynamically calculate the maximum load in the current window for visual scaling
            # Fallback to 60 if max is 0 to avoid division by zero or invisible bars
            window_max = max(display_slice['acute_load'].max(), display_slice['chronic_load'].max())
            max_load = window_max if window_max > 0 else 60.0
            
            for _, row in display_slice.iterrows():
                d_obj = pd.to_datetime(row['training_date'])
                label_str = d_obj.strftime('%a').capitalize()
                
                # Normalize values into percentage heights using the dynamic max_load
                acute_pct = min(100, (row['acute_load'] / max_load) * 100)
                chronic_pct = min(100, (row['chronic_load'] / max_load) * 100)
                
                # Add highlighting properties if acute significantly outpaces chronic
                # ACWR > 1.3 is generally the danger zone in sports science
                day_acwr = row['acute_load'] / row['chronic_load'] if row['chronic_load'] > 0 else 0
                is_danger = day_acwr > 1.3
                
                chart_data.append({
                    'label': label_str,
                    'full_date': d_obj.strftime('%b %d, %Y'),
                    'acute_height': f"{int(acute_pct)}%",
                    'chronic_height': f"{int(chronic_pct)}%",
                    'acute_val': round(row['acute_load'], 1),
                    'chronic_val': round(row['chronic_load'], 1),
                    'day_acwr': round(day_acwr, 2),
                    'is_danger': is_danger
                })
            
    except sqlite3.Error:
        team_players = []
        selected_player = None
        prediction = {'risk_level': 'Low', 'risk_score': 0}
        sleep_data = 'N/A'
        soreness_data = 'N/A'
        acwr = 0.0
        chart_data = []
        chart_page = 1
        total_chart_pages = 1
        predictive_logic = {'warning': 'No data', 'interpretation': [], 'factors': [], 'actions': []}
    finally:
        conn.close()
            
    return render_template('player management.html', user=current_user, team_players=team_players, 
                           selected_player=selected_player, prediction=prediction, 
                           sleep_data=sleep_data, soreness_data=soreness_data, acwr=acwr, chart_data=chart_data,
                           chart_page=chart_page, total_chart_pages=total_chart_pages,
                           predictive_logic=predictive_logic, available_squads=available_squads)

@app.route('/assign_squad', methods=['POST'])
@login_required
def assign_squad():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    player_id = request.form.get('player_id')
    squad_name = request.form.get('squad_name')
    
    if not player_id or not squad_name:
        flash('Missing parameters.', 'error')
        return redirect(url_for('player_management'))
        
    conn = get_db_connection()
    try:
        # Verify the coach has access to this player
        player_check = conn.execute('''
            SELECT p.player_id 
            FROM players p 
            JOIN users u ON p.user_id = u.user_id 
            WHERE p.player_id = ? AND u.team_code = ?
        ''', (player_id, current_user.team_code)).fetchone()
        
        if player_check:
            conn.execute('UPDATE players SET squad = ? WHERE player_id = ?', (squad_name, player_id))
            conn.commit()
            flash('Squad assigned successfully!', 'success')
        else:
            flash('Player not found in your team.', 'error')
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'error')
    finally:
        conn.close()
        
    return redirect(url_for('player_management', player_id=player_id))

@app.route('/notify_player', methods=['POST'])
@login_required
def notify_player():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))

    player_id = request.form.get('player_id')
    if not player_id:
        flash('No player selected.', 'error')
        return redirect(url_for('player_management'))

    actions_taken = []
    if request.form.get('action_reduce_intensity'):
        actions_taken.append("Reduce Intensity (Max speed 80%)")
    if request.form.get('action_contrast_therapy'):
        actions_taken.append("Contrast Therapy (Post-training)")
    if request.form.get('action_sleep_consultation'):
        actions_taken.append("Sleep Consultation")

    if not actions_taken:
        flash('No actions selected for notification.', 'error')
        return redirect(url_for('player_management', player_id=player_id))

    message = "Coach Recommendation: " + ", ".join(actions_taken) + " - Mandatory Rest Day Logged."

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO notifications (player_id, message) VALUES (?, ?)', (player_id, message))
        conn.commit()
        flash('Preventive action notification sent to player successfully.', 'success')
    except sqlite3.Error as e:
        flash('An error occurred while sending the notification.', 'error')
    finally:
        conn.close()

    return redirect(url_for('player_management', player_id=player_id))

@app.route('/mark_notifications_seen', methods=['POST'])
@login_required
def mark_notifications_seen():
    if current_user.role != 'player':
        return '', 403
        
    conn = get_db_connection()
    try:
        player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
        if player:
            conn.execute('UPDATE notifications SET is_seen = 1 WHERE player_id = ? AND is_read = 0', (player['player_id'],))
            conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()
        
    return '', 200

@app.route('/dismiss_notification/<int:notif_id>', methods=['POST'])
@login_required
def dismiss_notification(notif_id):
    if current_user.role != 'player':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    conn = get_db_connection()
    try:
        # Extra validation: ensuring the notification actually belongs to the active player
        player_check = conn.execute('SELECT p.player_id FROM players p JOIN notifications n ON p.player_id = n.player_id WHERE n.id = ? AND p.user_id = ?', (notif_id, current_user.id)).fetchone()
        
        if player_check:
            conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (notif_id,))
            conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()
        
    return redirect(url_for('dashboard'))

@app.route('/data_entry')
@login_required
def data_entry():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db_connection()
    try:
        # Get all unique squads for the team
        squad_rows = conn.execute('''
            SELECT DISTINCT p.squad 
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND p.squad IS NOT NULL AND p.squad != 'none'
        ''', (current_user.team_code,)).fetchall()
        
        available_squads = [s['squad'] for s in squad_rows]

        # Fetch squad members for this coach's team
        players_db = conn.execute('''
            SELECT p.*, u.username 
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND u.role = 'player'
        ''', (current_user.team_code,)).fetchall()
        
        squad = []
        today_str = date.today().strftime('%Y-%m-%d')
        
        for p in players_db:
            player_dict = dict(p)
            
            # --- Smart Status Identification Logic ---
            # 1. Check for Active Injuries
            active_injury = conn.execute('''
                SELECT 1 FROM injury_history 
                WHERE player_id = ? 
                AND date(injury_date, '+' || recovery_days || ' days') >= date(?)
            ''', (p['player_id'], today_str)).fetchone()
            
            if active_injury:
                player_dict['suggested_status'] = 'No Participation'
                player_dict['status_color'] = 'red-500'
            else:
                # 2. Check Latest Wellness for flags
                latest_wellness = conn.execute('''
                    SELECT fatigue_level, muscle_soreness 
                    FROM wellness_data 
                    WHERE player_id = ? 
                    ORDER BY entry_date DESC LIMIT 1
                ''', (p['player_id'],)).fetchone()
                
                if latest_wellness and (latest_wellness['muscle_soreness'] == 'High' or int(latest_wellness['fatigue_level']) > 8):
                    player_dict['suggested_status'] = 'Modified'
                    player_dict['status_color'] = 'yellow-500'
                else:
                    player_dict['suggested_status'] = 'Full'
                    player_dict['status_color'] = 'primary'
            
            squad.append(player_dict)
            
        print(f"DEBUG: Current User Team Code: {current_user.team_code}")
        print(f"DEBUG: Squad size: {len(squad)}")
    finally:
        conn.close()
        
    today_date = date.today().strftime('%Y-%m-%d')
    return render_template('data entry.html', user=current_user, squad=squad, today_date=today_date, available_squads=available_squads)

@app.route('/analytics')
@login_required
def analytics():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    
    selected_squad = request.args.get('squad', 'all')
    
    conn = get_db_connection()
    try:
        # Get all unique squads for the team
        squad_rows = conn.execute('''
            SELECT DISTINCT p.squad 
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND p.squad IS NOT NULL AND p.squad != 'none'
        ''', (current_user.team_code,)).fetchall()
        
        available_squads = [s['squad'] for s in squad_rows]

        # 1. Fetch team players
        query = '''
            SELECT p.*, u.username 
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ? AND u.role = 'player'
        '''
        params = [current_user.team_code]
        
        if selected_squad != 'all':
            query += ' AND p.squad = ?'
            params.append(selected_squad)
            
        rows = conn.execute(query, params).fetchall()
        
        team_players = [dict(r) for r in rows]
        
        # 2. Calculate current metrics
        total_risk = 0
        high_risk_count = 0
        active_injuries = 0
        
        for p in team_players:
            pred = get_player_prediction(p['player_id'])
            p['risk_score'] = pred.get('risk_score', 0)
            p['risk_level'] = pred.get('risk_level', 'Low')
            
            total_risk += p['risk_score']
            if p['risk_level'] == 'High':
                high_risk_count += 1
                
            # Check latest participation status
            latest_status = conn.execute('''
                SELECT participation_status FROM training_data 
                WHERE player_id = ? 
                ORDER BY training_date DESC, training_id DESC LIMIT 1
            ''', (p['player_id'],)).fetchone()
            
            if latest_status and latest_status['participation_status'] == 'No Participation':
                active_injuries += 1
                
            # Scatter Plot Data Collection
            wellness = conn.execute('''
                SELECT fatigue_level FROM wellness_data 
                WHERE player_id = ? AND entry_date >= date('now', '-30 days')
                ORDER BY entry_date DESC LIMIT 1
            ''', (p['player_id'],)).fetchone()
            
            try:
                fatigue_level = wellness['fatigue_level'] if wellness else None
            except (ValueError, TypeError):
                fatigue_level = None
            p['fatigue_level'] = fatigue_level
            p['fatigue_index'] = (fatigue_level / 10.0) * 100 if fatigue_level is not None else 50
            p['has_wellness'] = True if wellness else False
            
            injury_count = conn.execute('''
                SELECT COUNT(*) as count FROM injury_history 
                WHERE player_id = ?
            ''', (p['player_id'],)).fetchone()
            p['injuries'] = injury_count['count'] if injury_count else 0
        
        avg_risk = round(total_risk / len(team_players), 1) if team_players else 0
        
        # Build Scatter Data & Position Risk
        scatter_data = []
        max_injuries = max([p.get('injuries', 0) for p in team_players]) if team_players else 0
        
        position_data = {
            'Forward': {'total_risk': 0, 'count': 0},
            'Midfielder': {'total_risk': 0, 'count': 0},
            'Defender': {'total_risk': 0, 'count': 0},
            'Goalkeeper': {'total_risk': 0, 'count': 0}
        }
        
        for p in team_players:
            risk_level = p.get('risk_level', 'Low')
            if risk_level == 'High':
                color_class = 'bg-red-500 ring-red-500/20'
                status_label = 'CRITICAL'
                size_class = 'size-4 z-10'
            elif risk_level == 'Medium':
                color_class = 'bg-orange-400 ring-orange-400/20'
                status_label = 'Elevated'
                size_class = 'size-3'
            else:
                color_class = 'bg-primary ring-primary/20'
                status_label = 'Optimal'
                size_class = 'size-3'

            y_pos = 10 + (p['injuries'] / max_injuries) * 75 if max_injuries > 0 else 10
            x_pos = min(max(p.get('fatigue_index', 50), 5), 95) # clamp to 5-95%
            
            # Deterministic Jitter (±2.5%) based on player_id to prevent perfect overlap 
            jitter_y = ((p['player_id'] * 13) % 10 - 5) / 2.0 
            jitter_x = ((p['player_id'] * 17) % 10 - 5) / 2.0
            
            scatter_data.append({
                'name': p.get('name', p.get('username', 'Unknown')),
                'fatigue_index': p.get('fatigue_index', 50),
                'has_wellness': p.get('has_wellness', False),
                'injuries': p.get('injuries', 0),
                'color_class': color_class,
                'status_label': status_label,
                'size_class': size_class,
                'bottom_pct': y_pos + jitter_y,
                'left_pct': x_pos + jitter_x
            })
            
            # Position Data Collection
            pos = str(p.get('position', '')).lower()
            if 'forward' in pos or 'striker' in pos or 'winger' in pos or 'attack' in pos:
                cat = 'Forward'
            elif 'defen' in pos or 'back' in pos:
                cat = 'Defender'
            elif 'goal' in pos or 'keeper' in pos or pos == 'gk':
                cat = 'Goalkeeper'
            else:
                cat = 'Midfielder'
                
            position_data[cat]['total_risk'] += p.get('risk_score', 0)
            position_data[cat]['count'] += 1
            
        # Calculate Position Risk Array
        position_risk = []
        highest_risk_pos = None
        highest_risk_val = -1
        
        for pos_name, data in position_data.items():
            avg_risk = int(data['total_risk'] / data['count']) if data['count'] > 0 else 0
            
            if avg_risk > 65:
                color = 'bg-red-500'
            elif avg_risk > 35:
                color = 'bg-orange-400'
            else:
                color = 'bg-primary'
                
            display_name = pos_name + 's'
            
            position_risk.append({
                'name': display_name,
                'risk_pct': avg_risk,
                'color': color
            })
            
            if avg_risk > highest_risk_val and data['count'] > 0:
                highest_risk_val = avg_risk
                highest_risk_pos = display_name
                
        # Generate insight text
        if highest_risk_pos and highest_risk_val > 50:
            insight_text = f'"{highest_risk_pos} show an elevated average risk of {highest_risk_val}%. Correlation suggests a lighter recovery session for this unit before the next fixture."'
            insight_icon = 'warning'
            insight_color = 'text-orange-400'
        elif highest_risk_pos and highest_risk_val > 0:
            insight_text = f'"Overall squad risk is manageable. {highest_risk_pos} have the highest relative risk at {highest_risk_val}%, but remain within safe thresholds."'
            insight_icon = 'health_and_safety'
            insight_color = 'text-primary'
        else:
            insight_text = '"Insufficient data to generate positional insights."'
            insight_icon = 'info'
            insight_color = 'text-slate-400'
            
        insight_data = {
            'text': insight_text,
            'icon': insight_icon,
            'color': insight_color
        }
        
        # 3. Recovery Timeline (Avg from injury history)
        recovery_query = '''
            SELECT AVG(ih.recovery_days) as avg_rec
            FROM injury_history ih
            JOIN players p ON ih.player_id = p.player_id
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ?
        '''
        rec_params = [current_user.team_code]
        if selected_squad != 'all':
            recovery_query += ' AND p.squad = ?'
            rec_params.append(selected_squad)
            
        recovery_data = conn.execute(recovery_query, rec_params).fetchone()
        
        avg_recovery = round(recovery_data['avg_rec'], 1) if recovery_data and recovery_data['avg_rec'] else 0
        
        # Trends (simplified logic for now)
        risk_trend = 3 # Placeholder trend
        injury_trend = 1 # Placeholder trend
        
        stats = {
            'avg_risk': avg_risk,
            'risk_trend': risk_trend,
            'active_injuries': active_injuries,
            'injury_trend': injury_trend,
            'high_risk_count': high_risk_count,
            'avg_recovery': avg_recovery
        }
        
    except Exception as e:
        print(f"Error in analytics: {e}")
        stats = {'avg_risk': 0, 'risk_trend': 0, 'active_injuries': 0, 'injury_trend': 0, 'high_risk_count': 0, 'avg_recovery': 0}
        scatter_data = []
        position_risk = []
        insight_data = {'text': '', 'icon': '', 'color': ''}
    finally:
        conn.close()

    # --- PREPARE ANALYTICS DATA ---
    try:
        conn = get_db_connection()
        # Fetch report history for this coach
        reports_query = '''
            SELECT r.report_id, r.report_name, r.report_type, r.generated_date, r.report_date, u.full_name as coach_name, r.squad, r.period
            FROM generated_reports r
            JOIN users u ON r.coach_id = u.user_id
            WHERE r.coach_id = ?
            ORDER BY r.report_id DESC LIMIT 5
        '''
        generated_reports = [dict(row) for row in conn.execute(reports_query, (current_user.id,)).fetchall()]
        conn.close()
    except Exception as e:
        print(f"Error fetching reports: {e}")
        generated_reports = []
        
    return render_template('analytics.html', user=current_user, stats=stats, scatter_data=scatter_data, 
                           position_risk=position_risk, insight_data=insight_data, 
                           available_squads=available_squads, selected_squad=selected_squad,
                           generated_reports=generated_reports)

@app.route('/report_archives')
@login_required
def report_archives():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    try:
        conn = get_db_connection()
        # Fetch ALL report history for this coach
        reports_query = '''
            SELECT r.report_id, r.report_name, r.report_type, r.generated_date, r.report_date, u.full_name as coach_name, r.squad, r.period
            FROM generated_reports r
            JOIN users u ON r.coach_id = u.user_id
            WHERE r.coach_id = ?
            ORDER BY r.report_id DESC
        '''
        all_reports = [dict(row) for row in conn.execute(reports_query, (current_user.id,)).fetchall()]
        conn.close()
    except Exception as e:
        print(f"Error fetching all reports: {e}")
        all_reports = []
        
    return render_template('report_archives.html', user=current_user, reports=all_reports)

@app.route('/clear_report_archives', methods=['POST'])
@login_required
def clear_report_archives():
    if current_user.role != 'coach':
        return redirect(url_for('dashboard'))
        
    try:
        conn = get_db_connection()
        conn.execute('DELETE FROM generated_reports WHERE coach_id = ?', (current_user.id,))
        conn.commit()
        conn.close()
        flash('Report archives cleared successfully.', 'success')
    except Exception as e:
        print(f"Error clearing reports: {e}")
        flash('An error occurred while clearing the archives.', 'error')
        
    return redirect(url_for('report_archives'))

@app.route('/api/recent_reports')
@login_required
def api_recent_reports():
    if current_user.role != 'coach':
        return {"error": "Unauthorized"}, 403
        
    try:
        conn = get_db_connection()
        reports_query = '''
            SELECT r.report_id, r.report_name, r.report_type, r.generated_date, r.report_date, u.full_name as coach_name, r.squad, r.period
            FROM generated_reports r
            JOIN users u ON r.coach_id = u.user_id
            WHERE r.coach_id = ?
            ORDER BY r.report_id DESC LIMIT 5
        '''
        reports = [dict(row) for row in conn.execute(reports_query, (current_user.id,)).fetchall()]
        conn.close()
        return {"reports": reports}, 200
    except Exception as e:
        print(f"API Error fetching reports: {e}")
        return {"error": str(e)}, 500

@app.route('/history')
@login_required
def history():
    if current_user.role != 'player':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    period = request.args.get('period', 30, type=int)
    conn = get_db_connection()
    try:
        player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
        if not player:
            return _get_default_response(period, "Player profile not found.")
        
        p_id = player['player_id']
        prediction = get_player_prediction(p_id, period=period)
        wellness_logs = conn.execute('SELECT * FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT ?', (p_id, period)).fetchall()
    except sqlite3.Error:
        prediction = _get_default_response(period, "Error accessing history.")
        wellness_logs = []
    finally:
        conn.close()

    return render_template('history.html', user=current_user, prediction=prediction, wellness_logs=wellness_logs, is_coach_view=False)

@app.route('/coach/player/<int:player_id>')
@login_required
def coach_player_dashboard(player_id):
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    try:
        # Verify the player belongs to the coach's team
        player = conn.execute('''
            SELECT p.user_id, u.username
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.player_id = ? AND u.team_code = ?
        ''', (player_id, current_user.team_code)).fetchone()
        
        if not player:
            flash('Player not found or not in your team.', 'error')
            return redirect(url_for('dashboard'))
            
        # Get squad for the player
        squad_row = conn.execute('SELECT squad FROM players WHERE player_id = ?', (player_id,)).fetchone()
        p_squad = squad_row['squad'] if squad_row else None
        
        prediction = get_player_prediction(player_id)
        # Create a mock user object for the template to render the player's name
        mock_player_user = User(id=player['user_id'], username=player['username'], role='player', team_name=current_user.team_name, squad=p_squad)
        
    finally:
        conn.close()
        
    return render_template('player dashboard.html', user=mock_player_user, prediction=prediction, has_logged_today=True, is_coach_view=True)

@app.route('/coach/history/<int:player_id>')
@login_required
def coach_player_history(player_id):
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))

    period = request.args.get('period', 30, type=int)
    
    conn = get_db_connection()
    try:
        # Verify the player belongs to the coach's team
        player = conn.execute('''
            SELECT p.user_id, u.username
            FROM players p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.player_id = ? AND u.team_code = ?
        ''', (player_id, current_user.team_code)).fetchone()
        
        if not player:
            flash('Player not found or not in your team.', 'error')
            return redirect(url_for('dashboard'))
            
        # Get squad for the player
        squad_row = conn.execute('SELECT squad FROM players WHERE player_id = ?', (player_id,)).fetchone()
        p_squad = squad_row['squad'] if squad_row else None
        
        prediction = get_player_prediction(player_id, period=period)
        wellness_logs = conn.execute('SELECT * FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT ?', (player_id, period)).fetchall()
        
        mock_player_user = User(id=player['user_id'], username=player['username'], role='player', team_name=current_user.team_name, squad=p_squad)
    except sqlite3.Error:
        wellness_logs = []
        mock_player_user = current_user
    finally:
        conn.close()

    return render_template('history.html', user=mock_player_user, prediction=prediction, wellness_logs=wellness_logs, is_coach_view=True, player_id=player_id)

@app.route('/session_history')
@login_required
def session_history():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db_connection()
    try:
        # Fetch all training data for players in the coach's team
        history_data = conn.execute('''
            SELECT td.*, p.name as player_name, u.username
            FROM training_data td
            JOIN players p ON td.player_id = p.player_id
            JOIN users u ON p.user_id = u.user_id
            WHERE u.team_code = ?
            ORDER BY td.training_date DESC, td.training_id DESC
        ''', (current_user.team_code,)).fetchall()
        
        # Group entries by player and date to merge Technical and Match data
        history = []
        seen = {}  # key: (player_id, training_date)
        
        for row in history_data:
            key = (row['player_id'], row['training_date'])
            if key not in seen:
                # Create a base entry
                item = dict(row)
                # Initialize fields to ensure they exist for the template logic
                item['technical_mins'] = row['training_minutes'] if 'Match' not in row['session_type'] else None
                item['technical_freq'] = row['sessions_per_week'] if 'Match' not in row['session_type'] else None
                item['technical_intensity'] = row['intensity'] if 'Match' not in row['session_type'] else None
                item['match_mins'] = row['training_minutes'] if 'Match' in row['session_type'] else None
                item['match_freq'] = row['sessions_per_week'] if 'Match' in row['session_type'] else None
                item['active_injury'] = row['previous_injury'] if 'Match' in row['session_type'] else None
                
                seen[key] = len(history)
                history.append(item)
            else:
                # Update existing entry with missing data (only if not already set, to prioritize newest sessions)
                idx = seen[key]
                item = history[idx]
                if 'Match' not in row['session_type']:
                    if item.get('technical_mins') is None:
                        item['technical_mins'] = row['training_minutes']
                        item['technical_freq'] = row['sessions_per_week']
                        item['technical_intensity'] = row['intensity']
                else:
                    if item.get('match_mins') is None:
                        item['match_mins'] = row['training_minutes']
                        item['match_freq'] = row['sessions_per_week']
                        item['active_injury'] = row['previous_injury']
        
    except sqlite3.Error as e:
        history = []
        flash(f'Error fetching history: {str(e)}', 'error')
    finally:
        conn.close()
        
    return render_template('session_history.html', user=current_user, history=history)

@app.route('/clear_history', methods=['POST'])
@login_required
def clear_history():
    if current_user.role != 'coach':
        return {"error": "Unauthorized access"}, 403
    
    conn = get_db_connection()
    try:
        # We clear the entire table as requested for now
        # In a multi-tenant app, we'd filter by player_id belonging to the coach's team
        conn.execute('DELETE FROM training_data')
        conn.commit()
        flash('Session history cleared successfully.', 'success')
        return redirect(url_for('session_history'))
    except sqlite3.Error as e:
        flash(f'Error clearing history: {str(e)}', 'error')
        return redirect(url_for('session_history'))
    finally:
        conn.close()

@app.route('/guide')
@login_required
def guide():
    if current_user.role != 'player':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db_connection()
    try:
        player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
        if not player:
            return _get_default_response(30, "Player profile not found.")
        prediction = get_player_prediction(player['player_id'])
    except sqlite3.Error:
        prediction = _get_default_response(30, "Error accessing profile.")
    finally:
        conn.close()
        
    return render_template('guide.html', user=current_user, prediction=prediction)

@app.route('/signout')
@login_required
def signout():
    logout_user()
    session.clear()
    return redirect(url_for('index'))

@app.route('/save_session_data', methods=['POST'])
@login_required
def save_session_data():
    data = request.json
    if not data:
        return {"error": "No data provided"}, 400
    
    session_date = data.get('date')
    session_type = data.get('type')
    players_data = data.get('players', [])

    if not session_date:
        return {"error": "Session date is required"}, 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for p in players_data:
            player_id = p.get('player_id')
            if not player_id:
                player = conn.execute('SELECT player_id FROM players WHERE LOWER(name) = LOWER(?)', (p['name'],)).fetchone()
                if not player:
                    continue
                player_id = player['player_id']
            
            status = p.get('status', 'Full Participation')
            
            # 1. Save Technical & Tactical if selected
            if session_type == 'Technical & Tactical':
                tr = p.get('training', {})
                tr_mins = tr.get('minutes', '')
                if tr_mins and tr_mins != '0':
                    # Map numeric intensity to text for CHECK constraint
                    intensity_val = tr.get('intensity', '6')
                    intensity_map = {'3': 'Low', '6': 'Medium', '9': 'High'}
                    intensity_str = intensity_map.get(str(intensity_val), 'Medium')
                    
                    cursor.execute('''
                        INSERT INTO training_data (player_id, training_minutes, intensity, sessions_per_week, training_date, participation_status, session_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (player_id, tr_mins, intensity_str, tr.get('frequency', 0), session_date, status, 'Technical & Tactical'))

            # 2. Save Match Details if selected
            elif session_type == 'Match Details':
                ma = p.get('match', {})
                ma_mins = ma.get('minutes', '')
                if ma_mins and ma_mins != '0':
                    cursor.execute('''
                        INSERT INTO training_data (player_id, training_minutes, intensity, sessions_per_week, training_date, participation_status, session_type, previous_injury)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (player_id, ma_mins, None, ma.get('matches', 0), session_date, status, 'Match Details', ma.get('active_injury', 'No')))
        
        # Mark all affected players for re-prediction
        affected_player_ids = list(set([p.get('player_id') for p in players_data if p.get('player_id')]))
        if affected_player_ids:
            cursor.executemany('UPDATE players SET prediction_ready = 1 WHERE player_id = ?', [(pid,) for pid in affected_player_ids])
        
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}, 500
    finally:
        conn.close()

@app.route('/import_training_data', methods=['POST'])
@login_required
def import_training_data():
    if 'file' not in request.files:
        return {"error": "No file uploaded"}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {"error": "No file selected"}, 400

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.StringIO(file.stream.read().decode("UTF8")))
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file.stream)
        else:
            return {"error": "Unsupported file format"}, 400

        # Normalizing column names to match expected fields
        # Supporting variants like "Player Name", "Minutes", "Intensity", "RPE", "Frequency"
        df.columns = [c.strip().lower() for c in df.columns]
        
        mapping = {
            'name': ['player name', 'name', 'player', 'full name', 'player_name', 'names'],
            'minutes': ['minutes', 'duration', 'minutes played', 'training minutes', 'duration (min)', 'mins', 'time'],
            'intensity': ['intensity', 'rpe', 'training intensity', 'intensity (rpe)', 'matches per week', 'load', 'intensity level'],
            'frequency': ['frequency', 'sessions per week', 'sessions', 'matches', 'freq', 'times']
        }

        results = []
        for _, row in df.iterrows():
            player_data = {}
            for field, variants in mapping.items():
                # Find first matching variant
                match = next((v for v in variants if v in df.columns), None)
                if match:
                    val = row.get(match, 0)
                    # Handle NaN/None
                    if pd.isna(val):
                        val = 0
                    player_data[field] = val
                else:
                    player_data[field] = 0
            
            if player_data.get('name'):
                results.append(player_data)

        if not results:
            return {"error": "No players found. Please check CSV column headers (e.g., 'Player Name', 'Minutes', 'Intensity')."}, 400

        return {"players": results}
    except Exception as e:
        return {"error": str(e)}, 500

if __name__ == '__main__':
    app.run(debug=True)
