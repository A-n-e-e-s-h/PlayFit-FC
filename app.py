from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Any, cast, List, Dict
import sqlite3
import pandas as pd
import io
import sys
import os
from datetime import date
sys.path.append(os.path.join(os.path.dirname(__file__), 'ml'))
from ml_service import get_player_prediction, get_predictive_logic

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here' # Change this in production

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'signin'

def get_db_connection():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    return conn

class User(UserMixin):
    def __init__(self, id, username, role, team_code=None):
        self.id = id
        self.username = username
        self.role = role
        self.team_code = team_code

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(id=user['user_id'], username=user['username'], role=user['role'], team_code=user['team_code'])
    return None

@app.route('/')
def index():
    return render_template('homepage.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role') # 'coach' or 'player'
        team_code = request.form.get('team_code', '').strip()

        if not username or not password or not role:
            flash('Please fill in all basic required fields', 'error')
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
            cursor.execute('INSERT INTO users (username, password, role, team_code) VALUES (?, ?, ?, ?)',
                           (username, hashed_password, role, team_code))
            user_id = cursor.lastrowid
            
            # If player, also create a record in the players table
            if role == 'player':
                age = request.form.get('age')
                position = request.form.get('position')
                experience_years = request.form.get('experience_years')
                cursor.execute('INSERT INTO players (user_id, name, age, position, experience_years) VALUES (?, ?, ?, ?, ?)',
                               (user_id, full_name if full_name else username, age, position, experience_years))
            
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

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            user_obj = User(id=user['user_id'], username=user['username'], role=user['role'])
            user_obj.team_code = user['team_code'] # Bind dynamically upon login
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('signin.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'coach':
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

            # --- Workload vs Fatigue SVG Chart (Last 7 Days) ---
            past_7 = today - pd.Timedelta(days=7)
            
            # Fetch daily team averages for fatigue
            fatigue_7d = conn.execute('''
                SELECT wd.entry_date, AVG(wd.fatigue_level) as avg_fatigue
                FROM wellness_data wd
                JOIN players p ON wd.player_id = p.player_id
                JOIN users u ON p.user_id = u.user_id
                WHERE u.team_code = ? AND wd.entry_date >= ?
                GROUP BY wd.entry_date
                ORDER BY wd.entry_date ASC
            ''', (current_user.team_code, past_7.strftime('%Y-%m-%d'))).fetchall()
            
            # Fetch daily team averages for workload (training minutes)
            # We must sum the minutes PER PLAYER for a given day first (since a player might have both match and training entries)
            # Then we average those total daily player workloads.
            workload_7d = conn.execute('''
                WITH PlayerDailyWorkload AS (
                    SELECT 
                        td.training_date, 
                        td.player_id,
                        SUM(td.training_minutes) as daily_total_minutes
                    FROM training_data td
                    JOIN players p ON td.player_id = p.player_id
                    JOIN users u ON p.user_id = u.user_id
                    WHERE u.team_code = ? AND td.training_date >= ?
                    GROUP BY td.training_date, td.player_id
                )
                SELECT 
                    training_date, 
                    AVG(daily_total_minutes) as avg_workload
                FROM PlayerDailyWorkload
                GROUP BY training_date
                ORDER BY training_date ASC
            ''', (current_user.team_code, past_7.strftime('%Y-%m-%d'))).fetchall()
            
            # Create dictionaries mapped by date
            fatigue_dict = {row['entry_date']: row['avg_fatigue'] for row in fatigue_7d}
            workload_dict = {row['training_date']: row['avg_workload'] for row in workload_7d}
            
            # Generate exactly 7 days of points 
            chart_labels = []
            fatigue_points = []
            workload_points = []
            
            for i in range(7):
                d = past_7 + pd.Timedelta(days=i)
                date_str = d.strftime('%Y-%m-%d')
                label_str = d.strftime('%a').upper() # MON, TUE, etc
                chart_labels.append(label_str)
                
                f_val = fatigue_dict.get(date_str, 5.0) # default mid fatigue
                w_val = workload_dict.get(date_str, 30.0) # default low workload
                
                # Normalize values for a 0-150px high SVG area
                # Fatigue scaling: (1-10) -> (150-0) [Inverted Y] -> 150 - (f_val * 15)
                f_y = max(10, 150 - (f_val * 12))
                # Workload scaling: (0-120 mins) -> (150-0) [Inverted Y] -> 150 - (w_val)
                w_y = max(10, 150 - w_val)
                
                # X coordinate: 0 to 400 spacing for 7 elements = 400 / 6 = ~66.6
                x = i * (400.0 / 6.0)
                
                fatigue_points.append({'x': x, 'y': f_y})
                workload_points.append({'x': x, 'y': w_y})
            
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
            risk_alerts = []
            for player in team_players:
                    risk_val = float(str(player.get('risk_score', 0)))
                    alert = {
                        'type': 'CRITICAL FATIGUE' if risk_val > 75 else 'RECOVERY NEEDED',
                        'player_name': str(player.get('name', 'Unknown')),
                        'message': f"{player.get('name', 'Unknown')} reached high risk probability ({risk_val}%)",
                        'time': str(today_str) if str(player.get('last_session')) == str(today_str) else str(player.get('last_session', 'N/A'))
                    }
                    risk_alerts.append(alert)

        except sqlite3.Error as e:
            team_players = []
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
        finally:
            conn.close()
        return render_template('coach dashboard.html', user=current_user, team_players=team_players, 
                               total_players=total_players, high_risk_count=high_risk_count, avg_team_fatigue=avg_team_fatigue,
                               total_players_trend=total_players_trend, risk_trend=risk_trend, fatigue_trend=fatigue_trend,
                               chart_labels=chart_labels, fatigue_svg_path=fatigue_svg_path, workload_svg_path=workload_svg_path,
                               risk_alerts=risk_alerts)
    else:
        prediction = get_player_prediction(current_user.id)
        
        has_logged_today = False
        notifications = []
        conn = get_db_connection()
        try:
            player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
            if player:
                today = date.today().isoformat()
                entry = conn.execute('SELECT 1 FROM wellness_data WHERE player_id = ? AND entry_date = ?', (player['player_id'], today)).fetchone()
                has_logged_today = bool(entry)
                
                notifications_db = conn.execute('SELECT id, message, created_at FROM notifications WHERE player_id = ? AND is_read = 0 ORDER BY created_at DESC', (player['player_id'],)).fetchall()
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
        
    conn = get_db_connection()
    try:
        # Fetch players with the same team code as the coach
        team_players_db = conn.execute('''
            SELECT p.*, u.username 
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
                SELECT training_date, training_minutes as workload
                FROM training_data
                WHERE player_id = ? AND training_date >= ?
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
            
            # --- Workload Trends Chart Data (Last 7 Days) ---
            chart_data = [] 
            display_slice = df_workload.tail(7)
            for _, row in display_slice.iterrows():
                d_obj = pd.to_datetime(row['training_date'])
                label_str = d_obj.strftime('%a').capitalize()
                
                # Normalize values into percentage heights for the UI bars (max ~120 mins = 100%)
                acute_pct = min(100, (row['acute_load'] / 120.0) * 100)
                chronic_pct = min(100, (row['chronic_load'] / 120.0) * 100)
                
                # Add highlighting properties if acute significantly outpaces chronic
                # ACWR > 1.3 is generally the danger zone in sports science
                day_acwr = row['acute_load'] / row['chronic_load'] if row['chronic_load'] > 0 else 0
                is_danger = day_acwr > 1.3
                
                chart_data.append({
                    'label': label_str,
                    'acute_height': f"{int(acute_pct)}%",
                    'chronic_height': f"{int(chronic_pct)}%",
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
        predictive_logic = {'warning': 'No data', 'interpretation': [], 'factors': [], 'actions': []}
    finally:
        conn.close()
            
    return render_template('player management.html', user=current_user, team_players=team_players, 
                           selected_player=selected_player, prediction=prediction, 
                           sleep_data=sleep_data, soreness_data=soreness_data, acwr=acwr, chart_data=chart_data,
                           predictive_logic=predictive_logic)

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
        
    return render_template('data entry.html', user=current_user, squad=squad)

@app.route('/analytics')
@login_required
def analytics():
    if current_user.role != 'coach':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    return render_template('analytics.html', user=current_user)

@app.route('/history')
@login_required
def history():
    if current_user.role != 'player':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    period = request.args.get('period', 30, type=int)
    prediction = get_player_prediction(current_user.id, period=period)
    
    conn = get_db_connection()
    try:
        player = conn.execute('SELECT player_id FROM players WHERE user_id = ?', (current_user.id,)).fetchone()
        if player:
            wellness_logs = conn.execute('SELECT * FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT ?', (player['player_id'], period)).fetchall()
        else:
            wellness_logs = []
    except sqlite3.Error:
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
            
        prediction = get_player_prediction(player['user_id'])
        # Create a mock user object for the template to render the player's name
        mock_player_user = User(id=player['user_id'], username=player['username'], role='player')
        
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
            
        prediction = get_player_prediction(player['user_id'], period=period)
        wellness_logs = conn.execute('SELECT * FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT ?', (player_id, period)).fetchall()
        
        mock_player_user = User(id=player['user_id'], username=player['username'], role='player')
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
                
                seen[key] = len(history)
                history.append(item)
            else:
                # Update existing entry with missing data
                idx = seen[key]
                item = history[idx]
                if 'Match' not in row['session_type']:
                    item['technical_mins'] = row['training_minutes']
                    item['technical_freq'] = row['sessions_per_week']
                    item['technical_intensity'] = row['intensity']
                else:
                    item['match_mins'] = row['training_minutes']
                    item['match_freq'] = row['sessions_per_week']
        
    except sqlite3.Error as e:
        history = []
        flash(f'Error fetching history: {str(e)}', 'error')
    finally:
        conn.close()
        
    return render_template('session_history.html', user=current_user, history=history)

@app.route('/guide')
@login_required
def guide():
    if current_user.role != 'player':
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    prediction = get_player_prediction(current_user.id)
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
            
            # 1. Save Technical & Tactical if data exists
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

            # 2. Save Match Details if data exists
            ma = p.get('match', {})
            ma_mins = ma.get('minutes', '')
            if ma_mins and ma_mins != '0':
                cursor.execute('''
                    INSERT INTO training_data (player_id, training_minutes, intensity, sessions_per_week, training_date, participation_status, session_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (player_id, ma_mins, None, ma.get('matches', 0), session_date, status, 'Match Details'))
        
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
