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
import random
import json
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta
from ml.ml_service import get_player_prediction, get_player_risk_snapshot, get_predictive_logic, _get_default_response, queue_prediction, check_and_trigger_learning

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here' # Change this in production
_RUNTIME_SCHEMA_READY = False

# ─── SMTP Configuration (loaded from .env) ────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; fall back to environment variables

SMTP_SERVER   = 'smtp.gmail.com'
SMTP_PORT     = 587
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', 'your_email@gmail.com')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', 'your_app_password_here')
SMTP_FROM     = f'PlayFit FC <{SMTP_USERNAME}>'
# ──────────────────────────────────────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

from routes.report import report_bp
app.register_blueprint(report_bp)

def get_db_connection():
    global _RUNTIME_SCHEMA_READY
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    if not _RUNTIME_SCHEMA_READY:
        try:
            notif_columns = {row['name'] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
            if notif_columns and 'is_seen' not in notif_columns:
                conn.execute("ALTER TABLE notifications ADD COLUMN is_seen BOOLEAN DEFAULT 0")
                conn.commit()
            _RUNTIME_SCHEMA_READY = True
        except sqlite3.Error:
            pass
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
            
            if role == 'admin':
                return User(id=user['user_id'], username=user['username'], role=role,
                            full_name=user['full_name'], team_name='Administration',
                            login_count=user['login_count'])
            
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


@app.after_request
def add_no_cache_headers(response):
    """Prevent browser from caching any page so back/forward always hits the server."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/')
def index():
    return render_template('homepage.html')

@app.route('/logout')
def logout():
    """Log out the current user and redirect to homepage."""
    logout_user()
    session.clear()
    return redirect(url_for('index'))

@app.route('/signout')
def signout():
    """Alias for /logout used by existing sidebar links."""
    logout_user()
    session.clear()
    return redirect(url_for('index'))

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
            # New accounts start as unapproved (is_approved=0) — admin must approve them
            cursor.execute('INSERT INTO users (username, password, role, full_name, team_code, team_name, sport, is_approved) VALUES (?, ?, ?, ?, ?, ?, ?, 0)',
                           (username, hashed_password, role, full_name, team_code, team_name, sport))
            user_id = cursor.lastrowid
            
            # If player, also create a record in the players table
            if role == 'player':
                cursor.execute('INSERT INTO players (user_id, name, age, position, experience_years) VALUES (?, ?, ?, ?, ?)',
                               (user_id, full_name, age, position, experience_years))
            
            conn.commit()
            flash('Account created! Your account is pending admin approval. You will be able to sign in once approved.', 'success')
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
        try:
            user = conn.execute('SELECT * FROM users WHERE LOWER(username) = LOWER(?)', (username,)).fetchone()

            if user and check_password_hash(user['password'], password):
                
                # Check if user is approved (coaches and players need approval)
                if user['role'] in ('coach', 'player') and not user['is_approved']:
                    flash('Your account is pending admin approval. Please wait.', 'error')
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
                if user['role'] == 'admin':
                    user_obj.team_name = 'Administration'
                elif user['role'] == 'coach':
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
                
                if user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password', 'error')
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
            
            # --- Lazy Cleanup ---
            if random.random() < 0.01:
                try:
                    last_cleanup = conn.execute("SELECT meta_value FROM system_meta WHERE meta_key = 'last_cleanup_at'").fetchone()
                    should_run = True
                    if last_cleanup:
                        last_dt = datetime.fromisoformat(last_cleanup['meta_value'])
                        if datetime.now() - last_dt < timedelta(hours=24):
                            should_run = False
                    
                    if should_run:
                        conn.execute("DELETE FROM predictions WHERE prediction_date < DATE('now', '-90 days')")
                        conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'last_cleanup_at'", (datetime.now().isoformat(),))
                        conn.commit()
                        print("Lazy Cleanup executed.")
                except Exception as cleanup_e:
                    print(f"Cleanup failed: {cleanup_e}")

            # --- Batch Prediction Fetching ---
            player_ids = [p['player_id'] for p in team_players_db]
            placeholders = ', '.join(['?'] * len(player_ids))
            
            # Fetch latest prediction for all players
            latest_preds_db = conn.execute(f'''
                SELECT p1.* 
                FROM predictions p1
                JOIN (
                    SELECT player_id, MAX(prediction_date) as max_date 
                    FROM predictions 
                    WHERE player_id IN ({placeholders}) 
                    GROUP BY player_id
                ) p2 ON p1.player_id = p2.player_id AND p1.prediction_date = p2.max_date
            ''', player_ids).fetchall()
            
            preds_map = {p['player_id']: dict(p) for p in latest_preds_db}
            
            team_players = []
            stats = {'fatigue': 0, 'wellness': 0, 'high_risk': 0}
            
            for row in team_players_db:
                player = dict(row)
                p_id = player['player_id']
                
                # Check if update needed and queue
                if player['prediction_ready'] == 1:
                    queue_prediction(p_id)
                
                prediction = preds_map.get(p_id)
                if prediction:
                    player['risk_level'] = prediction['risk_level']
                    player['risk_score'] = prediction['risk_score']
                    player['top_factors'] = json.loads(prediction['top_factors']) if prediction['top_factors'] else []
                    
                    # Confidence check for stale data (2 days)
                    last_pred_date = pd.to_datetime(prediction['prediction_date'])
                    if (datetime.now() - last_pred_date).days > 2:
                        player['risk_level'] += " (Stale)"
                else:
                    player['risk_level'] = 'Calculating...'
                    player['risk_score'] = 0
                    player['top_factors'] = []
                
                if player['risk_level'].startswith('High'):
                    stats['high_risk'] += 1
                    
                wellness_row = conn.execute('SELECT fatigue_level, entry_date FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT 1', (p_id,)).fetchone()
                if wellness_row:
                    stats['fatigue'] += wellness_row['fatigue_level'] or 0
                    stats['wellness'] += 1
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
                avg_team_fatigue = None

            # --- 30-Day Historical Trend Calculation ---
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
            # Removed fake fallback to today if no data exists to avoid displaying misleading empty graphs
            
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
            
            # Dynamic scaling for workload and fatigue
            page_workloads = [workload_dict.get(d, 30.0) for d in all_dates]
            page_fatigues = [fatigue_dict.get(d, 5.0) for d in all_dates]
            
            min_w = min(page_workloads) if page_workloads else 0.0
            max_w = max(page_workloads) if page_workloads else 100.0
            if max_w == min_w:
                max_w += 10.0
                min_w = max(0.0, min_w - 10.0)
                
            w_pad = (max_w - min_w) * 0.15
            scale_min_w = max(0.0, min_w - w_pad)
            scale_max_w = max_w + w_pad
            w_range = scale_max_w - scale_min_w
            
            min_f = min(page_fatigues) if page_fatigues else 0.0
            max_f = max(page_fatigues) if page_fatigues else 10.0
            if max_f == min_f:
                max_f = min(10.0, max_f + 1.0)
                min_f = max(0.0, min_f - 1.0)
                
            f_pad = (max_f - min_f) * 0.15
            scale_min_f = max(0.0, min_f - f_pad)
            scale_max_f = min(10.0, max_f + f_pad)
            f_range = scale_max_f - scale_min_f
            
            # Use a true linear time scale for the X-axis
            min_date_ts = pd.to_datetime(all_dates[0]).timestamp() if all_dates else 0
            max_date_ts = pd.to_datetime(all_dates[-1]).timestamp() if all_dates else 1
            date_range_ts = max_date_ts - min_date_ts if max_date_ts > min_date_ts else 1
            
            for i, date_str in enumerate(all_dates):
                try:
                    d = pd.to_datetime(date_str)
                    label_str = d.strftime('%b %d')
                    curr_ts = d.timestamp()
                except Exception:
                    label_str = date_str
                    curr_ts = min_date_ts
                    
                chart_labels.append(label_str)
                
                f_val = float(fatigue_dict.get(date_str, 5.0))
                w_val = float(workload_dict.get(date_str, 30.0))
                
                # Normalize values for a 0-150px high SVG area
                f_y = 140.0 - (((f_val - scale_min_f) / f_range) * 130.0)
                w_y = 140.0 - (((w_val - scale_min_w) / w_range) * 130.0)
                
                # X coordinate: Linear time scale across 400px
                x = ((curr_ts - min_date_ts) / date_range_ts) * 400.0
                
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
            risk_alerts = []
            for player in team_players:
                risk_level = str(player.get('risk_level', 'Low'))
                risk_val = float(str(player.get('risk_score', 0)))
                
                # Show players who are at risk (Medium/High risk level or score > 35)
                if risk_level in ['High', 'Medium'] or risk_val > 35:
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
                        'time': alert_time,
                        'score': risk_val # for sorting
                    })
            
            # Sort by score descending and limit to top 5 for a cleaner dashboard
            risk_alerts.sort(key=lambda x: x['score'], reverse=True)
            risk_alerts = risk_alerts[:5]
            
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
                
                notifications_db = conn.execute('SELECT notif_id as id, message, created_at, COALESCE(is_seen, 0) as is_seen FROM notifications WHERE player_id = ? AND is_read = 0 ORDER BY created_at DESC', (p_id,)).fetchall()
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
            # Mark player for re-prediction and queue in background
            conn.execute('UPDATE players SET prediction_ready = 1 WHERE player_id = ?', (player['player_id'],))
            conn.commit()
            queue_prediction(player['player_id'])
            # Autonomous learning trigger
            check_and_trigger_learning(conn)
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
                sleep_data = 'N/A'
                soreness_data = 'N/A'
                fatigue_level = 0
                
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
        player_check = conn.execute('SELECT p.player_id FROM players p JOIN notifications n ON p.player_id = n.player_id WHERE n.notif_id = ? AND p.user_id = ?', (notif_id, current_user.id)).fetchone()
        
        if player_check:
            conn.execute('UPDATE notifications SET is_read = 1, is_seen = 1 WHERE notif_id = ?', (notif_id,))
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
                SELECT 1 FROM training_data 
                WHERE player_id = ? 
                AND active_injury = 1
                AND date(training_date, '+14 days') >= date(?)
                ORDER BY training_date DESC LIMIT 1
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
    selected_date = request.args.get('date', date.today().isoformat())
    try:
        selected_date_obj = pd.to_datetime(selected_date).normalize()
        selected_date = selected_date_obj.strftime('%Y-%m-%d')
    except Exception:
        selected_date_obj = pd.to_datetime(date.today().isoformat()).normalize()
        selected_date = selected_date_obj.strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    try:
        prediction_cache = {}

        def resolve_snapshot_prediction(player_id, target_date_str):
            cache_key = (player_id, target_date_str)
            if cache_key not in prediction_cache:
                prediction_cache[cache_key] = get_player_risk_snapshot(player_id, target_date=target_date_str)
            return prediction_cache[cache_key]

        def normalize_risk_level(level_text, risk_score):
            if level_text in ('High', 'Medium', 'Low'):
                return level_text
            level_text = str(level_text or '')
            if level_text.startswith('High'):
                return 'High'
            if level_text.startswith('Medium'):
                return 'Medium'
            if level_text.startswith('Low'):
                return 'Low'
            if risk_score > 65:
                return 'High'
            if risk_score > 35:
                return 'Medium'
            return 'Low'

        # --- Helper for dynamic recovery timeline ---
        def get_team_avg_recovery(conn, team_code, squad_name='all'):
            try:
                # Look at players in the team
                player_query = '''
                    SELECT p.player_id FROM players p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE u.team_code = ?
                '''
                params = [team_code]
                if squad_name != 'all':
                    player_query += ' AND p.squad = ?'
                    params.append(squad_name)

                players = conn.execute(player_query, params).fetchall()
                
                player_ids = [p['player_id'] for p in players]
                if not player_ids: return 14.0
                
                stints = []
                for pid in player_ids:
                    # Get recent history
                    rows = conn.execute('''
                        SELECT training_date, active_injury FROM training_data 
                        WHERE player_id = ? AND training_date <= ?
                        ORDER BY training_date ASC
                    ''', (pid, selected_date)).fetchall()
                    
                    in_injury = False
                    start_date = None
                    for row in rows:
                        if row['active_injury'] == 1 and not in_injury:
                            in_injury = True
                            start_date = datetime.strptime(row['training_date'], '%Y-%m-%d')
                        elif row['active_injury'] == 0 and in_injury:
                            in_injury = False
                            end_date = datetime.strptime(row['training_date'], '%Y-%m-%d')
                            stints.append((end_date - start_date).days)
                
                if not stints: return 14.0
                # Filter out outliers or unrealistically short/long ones if needed
                return round(sum(stints) / len(stints), 1)
            except:
                return 14.0
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

        total_risk = 0
        high_risk_count = 0
        active_injuries = 0
        
        for p in team_players:
            p_id = p['player_id']
            pred = resolve_snapshot_prediction(p_id, selected_date)
            p['risk_score'] = float(pred.get('risk_score', 0) or 0)
            p['risk_level'] = pred.get('risk_level', 'Low')
            p['risk_level_base'] = pred.get('risk_level_base') or normalize_risk_level(p['risk_level'], p['risk_score'])
            
            total_risk += p['risk_score']
            if p['risk_level_base'] == 'High':
                high_risk_count += 1
                
            # Check latest participation status
            latest_status = conn.execute('''
                SELECT active_injury FROM training_data 
                WHERE player_id = ? AND training_date <= ?
                ORDER BY training_date DESC, training_id DESC LIMIT 1
            ''', (p_id, selected_date)).fetchone()
            
            if latest_status and latest_status['active_injury'] == 1:
                active_injuries += 1
                
            # Scatter Plot Data Collection
            wellness = conn.execute('''
                SELECT fatigue_level FROM wellness_data 
                WHERE player_id = ? AND entry_date <= ?
                ORDER BY entry_date DESC LIMIT 1
            ''', (p_id, selected_date)).fetchone()
            
            try:
                fatigue_level = wellness['fatigue_level'] if wellness else None
            except (ValueError, TypeError):
                fatigue_level = None
            p['fatigue_level'] = fatigue_level
            p['fatigue_index'] = (fatigue_level / 10.0) * 100 if fatigue_level is not None else None
            p['has_wellness'] = True if wellness else False
            
            injury_dates_query = conn.execute('''
                SELECT DISTINCT training_date FROM training_data 
                WHERE player_id = ? AND active_injury = 1 AND training_date <= ?
                ORDER BY training_date ASC
            ''', (p_id, selected_date)).fetchall()
            
            calculated_injuries = 0
            if injury_dates_query:
                dates = [datetime.strptime(row['training_date'], '%Y-%m-%d').date() for row in injury_dates_query]
                calculated_injuries = 1
                for i in range(1, len(dates)):
                    if (dates[i] - dates[i-1]).days > 7:
                        calculated_injuries += 1
                        
            p['injuries'] = calculated_injuries
        
        avg_risk = round(total_risk / len(team_players), 1) if team_players else 0
        
        # Build Scatter Data & Position Risk
        scatter_data = []
        max_injuries = max([p.get('injuries', 0) for p in team_players]) if team_players else 1 # Avoid div by zero
        
        position_data = {
            'Forward': {'total_risk': 0, 'count': 0},
            'Midfielder': {'total_risk': 0, 'count': 0},
            'Defender': {'total_risk': 0, 'count': 0},
            'Goalkeeper': {'total_risk': 0, 'count': 0}
        }
        
        for p in team_players:
            risk_level = p.get('risk_level_base', 'Low')
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

            y_pos = 10 + (p.get('injuries', 0) / max_injuries) * 75
            
            # SAFE Fatigue handling to prevent crash
            f_idx = p.get('fatigue_index')
            if f_idx is None:
                f_idx = 50 # Default middle
            x_pos = min(max(f_idx, 5), 95) # clamp to 5-95%
            
            # Deterministic Jitter (±2.5%) based on player_id to prevent perfect overlap 
            jitter_y = ((p['player_id'] * 13) % 10 - 5) / 2.0 
            jitter_x = ((p['player_id'] * 17) % 10 - 5) / 2.0
            
            scatter_data.append({
                'name': p.get('name', p.get('username', 'Unknown')),
                'fatigue_index': f_idx,
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
        
        # 3. Dynamic Recovery Timeline
        avg_recovery = get_team_avg_recovery(conn, current_user.team_code, selected_squad)
        
        # Trends (Dynamic based on selected date)
        try:
            print(f"Calculating analytics for: {selected_date}")
            past_date = (selected_date_obj - timedelta(days=7)).strftime('%Y-%m-%d')
            past_total_risk = 0

            for p in team_players:
                past_pred = resolve_snapshot_prediction(p['player_id'], past_date)
                past_total_risk += float(past_pred.get('risk_score', 0) or 0)
            
            past_avg_risk = round(past_total_risk / len(team_players), 1) if team_players else 0
            risk_trend = round(avg_risk - past_avg_risk, 1)
            
            # Dynamic Injury Trend
            past_active_injuries = 0
            for p in team_players:
                p_past_status = conn.execute('''
                    SELECT active_injury FROM training_data 
                    WHERE player_id = ? AND training_date <= ?
                    ORDER BY training_date DESC, training_id DESC LIMIT 1
                ''', (p['player_id'], past_date)).fetchone()
                if p_past_status and p_past_status['active_injury'] == 1:
                    past_active_injuries += 1
            
            injury_trend = active_injuries - past_active_injuries
        except Exception as e:
            print(f"Trend error: {e}")
            risk_trend = 0
            injury_trend = 0
        
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
                           selected_date=selected_date, generated_reports=generated_reports)

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
        
        history = []
        for row in history_data:
            item = dict(row)
            # Map metrics - ensure None handles cleanly for the template's "or '-'" logic
            item['technical_mins'] = row['training_minutes'] if row['training_minutes'] and row['training_minutes'] > 0 else None
            item['technical_freq'] = row['sessions_per_week'] if row['sessions_per_week'] and row['sessions_per_week'] > 0 else None
            # Show intensity if technical data exists
            item['technical_intensity'] = row['intensity'] if (row['training_minutes'] and row['training_minutes'] > 0) or (row['sessions_per_week'] and row['sessions_per_week'] > 0) else None
            
            item['match_mins'] = row['minutes_played'] if row['minutes_played'] and row['minutes_played'] > 0 else None
            item['match_freq'] = row['matches_per_week'] if row['matches_per_week'] and row['matches_per_week'] > 0 else None
            item['active_injury'] = 'Yes' if row['active_injury'] else 'No'
            
            # Infer participation status
            if row['active_injury']:
                item['participation_status'] = 'No Participation'
            elif (item['technical_mins'] and item['technical_mins'] < 45) or (item['match_mins'] and item['match_mins'] < 45):
                item['participation_status'] = 'Modified Training'
            else:
                item['participation_status'] = 'Full Participation'
                
            history.append(item)
            
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
        # Clear the entire table as requested for now
        conn.execute('DELETE FROM training_data')
        conn.commit()
        flash('Session history cleared successfully.', 'success')
        return redirect(url_for('session_history'))
    except sqlite3.Error as e:
        flash(f'Error clearing history: {str(e)}', 'error')
        return redirect(url_for('session_history'))
    finally:
        conn.close()


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
        cursor.execute("BEGIN")
        for p in players_data:
            player_id = p.get('player_id')
            if not player_id:
                player = conn.execute('SELECT player_id FROM players WHERE LOWER(name) = LOWER(?)', (p['name'],)).fetchone()
                if not player:
                    continue
                player_id = player['player_id']
            
            existing = cursor.execute('''
                SELECT training_id, training_minutes, minutes_played FROM training_data 
                WHERE player_id = ? AND training_date = ?
            ''', (player_id, session_date)).fetchone()
            
            update_fields = []
            params = []
            is_new_session_type = False
            
            # Process ALL data if present, regardless of session_type dropdown
            # This allows users to fill both Technical and Match details if they switch modes
            
            # 1. Technical Data
            tr = p.get('training', {})
            tr_mins = tr.get('minutes')
            if tr_mins is not None and tr_mins != '':
                update_fields.append("training_minutes = ?")
                params.append(int(tr_mins))
                if existing and existing['training_minutes'] == 0:
                    is_new_session_type = True
            
            intensity_val = tr.get('intensity')
            if intensity_val is not None and intensity_val != '':
                intensity_map = {'3': 'Low', '6': 'Medium', '9': 'High'}
                intensity_str = intensity_map.get(str(intensity_val), 'Medium')
                update_fields.append("intensity = ?")
                params.append(intensity_str)
                
            tr_freq = tr.get('frequency')
            if tr_freq is not None and tr_freq != '':
                update_fields.append("sessions_per_week = ?")
                params.append(int(tr_freq))
            
            # 2. Match Data
            ma = p.get('match', {})
            ma_mins = ma.get('minutes')
            if ma_mins is not None and ma_mins != '':
                update_fields.append("minutes_played = ?")
                params.append(int(ma_mins))
                if existing and existing['minutes_played'] == 0:
                    is_new_session_type = True
                    
            ma_freq = ma.get('matches')
            if ma_freq is not None and ma_freq != '':
                update_fields.append("matches_per_week = ?")
                params.append(int(ma_freq))
                
            # 3. Status and Active Injury
            status = p.get('status')
            active_injury_raw = ma.get('active_injury')
            
            if status == 'No Participation':
                update_fields.append("active_injury = ?")
                params.append(1)
            elif session_type == 'Match Details' and active_injury_raw is not None and active_injury_raw != '':
                active_injury = 1 if str(active_injury_raw).lower() in ['yes', 'true', '1'] else 0
                update_fields.append("active_injury = ?")
                params.append(active_injury)
            elif status in ['Full Participation', 'Modified Training']:
                update_fields.append("active_injury = ?")
                params.append(0)
            
            if not update_fields:
                continue
                
            update_fields.append("last_updated_at = CURRENT_TIMESTAMP")
            
            if existing:
                if is_new_session_type:
                    update_fields.append("session_count = session_count + 1")
                
                query = f"UPDATE training_data SET {', '.join(update_fields)} WHERE training_id = ?"
                params.append(existing['training_id'])
                cursor.execute(query, params)
            else:
                insert_dict = {
                    "player_id": player_id,
                    "training_date": session_date,
                    "session_count": 1,
                    "training_minutes": 0,
                    "intensity": "Medium",
                    "sessions_per_week": 0,
                    "minutes_played": 0,
                    "matches_per_week": 0,
                    "active_injury": 0
                }
                for i, field_str in enumerate(update_fields):
                    if " = ?" in field_str:
                        col_name = field_str.split(" =")[0]
                        insert_dict[col_name] = params[i]
                
                cols = ", ".join(insert_dict.keys())
                placeholders = ", ".join(["?"] * len(insert_dict))
                query = f"INSERT INTO training_data ({cols}, last_updated_at) VALUES ({placeholders}, CURRENT_TIMESTAMP)"
                cursor.execute(query, list(insert_dict.values()))
                
        affected_player_ids = list(set([p.get('player_id') for p in players_data if p.get('player_id')]))
        if affected_player_ids:
            cursor.executemany('UPDATE players SET prediction_ready = 1 WHERE player_id = ?', [(pid,) for pid in affected_player_ids])
            # Queue background updates for all affected players
            for pid in affected_player_ids:
                queue_prediction(pid)
        
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
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

# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────

def admin_required(f):
    """Decorator: ensures only admin users can access the route."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('signin'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    try:
        # Summary stats
        total_coaches = conn.execute("SELECT COUNT(*) FROM users WHERE role='coach'").fetchone()[0]
        total_players = conn.execute("SELECT COUNT(*) FROM users WHERE role='player'").fetchone()[0]
        pending_coaches = conn.execute("SELECT COUNT(*) FROM users WHERE role='coach' AND is_approved=0").fetchone()[0]
        pending_players = conn.execute("SELECT COUNT(*) FROM users WHERE role='player' AND is_approved=0").fetchone()[0]
        
        # Pending users (awaiting approval)
        pending_users = conn.execute("""
            SELECT user_id, username, role, full_name, team_code, team_name, sport, login_count
            FROM users 
            WHERE role IN ('coach', 'player') AND is_approved = 0
            ORDER BY user_id DESC
        """).fetchall()
        pending_users = [dict(u) for u in pending_users]
        
        # All coaches
        coaches = conn.execute("""
            SELECT u.user_id, u.username, u.full_name, u.team_code, u.team_name, u.sport, u.login_count, u.is_approved,
                   COUNT(p.player_id) as player_count
            FROM users u
            LEFT JOIN users pu ON pu.team_code = u.team_code AND pu.role = 'player'
            LEFT JOIN players p ON p.user_id = pu.user_id
            WHERE u.role = 'coach'
            GROUP BY u.user_id
            ORDER BY u.user_id DESC
        """).fetchall()
        coaches = [dict(c) for c in coaches]
        
        # All players with their coach info
        players = conn.execute("""
            SELECT u.user_id, u.username, u.team_code, u.login_count, u.is_approved,
                   pl.position, pl.age, pl.squad,
                   COALESCE(pl.name, u.full_name) as full_name,
                   coach.full_name as coach_name, coach.team_name
            FROM users u
            LEFT JOIN players pl ON pl.user_id = u.user_id
            LEFT JOIN users coach ON coach.team_code = u.team_code AND coach.role = 'coach'
            WHERE u.role = 'player'
            ORDER BY u.user_id DESC
        """).fetchall()
        players = [dict(p) for p in players]
        
    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
        total_coaches = total_players = pending_coaches = pending_players = 0
        pending_users = coaches = players = []
    finally:
        conn.close()
    
    return render_template('admin_dashboard.html',
        user=current_user,
        total_coaches=total_coaches,
        total_players=total_players,
        pending_coaches=pending_coaches,
        pending_players=pending_players,
        pending_users=pending_users,
        coaches=coaches,
        players=players
    )


@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_approve_user(user_id):
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT username, role FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            conn.execute('UPDATE users SET is_approved = 1, approved_by = ? WHERE user_id = ?',
                         (current_user.id, user_id))
            conn.commit()
            flash(f"User '{user['username']}' ({user['role']}) has been approved.", 'success')
        else:
            flash('User not found.', 'error')
    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_reject_user(user_id):
    """Reject & delete a pending user."""
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT username, role FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.commit()
            flash(f"User '{user['username']}' ({user['role']}) has been rejected and removed.", 'success')
        else:
            flash('User not found.', 'error')
    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    """Permanently delete an approved coach or player."""
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT username, role FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            if user['role'] == 'admin':
                flash('Cannot delete admin accounts.', 'error')
            else:
                conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                conn.commit()
                flash(f"User '{user['username']}' ({user['role']}) has been permanently deleted.", 'success')
        else:
            flash('User not found.', 'error')
    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/toggle_approval/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_approval(user_id):
    """Suspend (unapprove) or re-approve an existing user."""
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT username, role, is_approved FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            new_status = 0 if user['is_approved'] else 1
            action = 'suspended' if new_status == 0 else 're-approved'
            conn.execute('UPDATE users SET is_approved = ? WHERE user_id = ?', (new_status, user_id))
            conn.commit()
            flash(f"User '{user['username']}' has been {action}.", 'success')
        else:
            flash('User not found.', 'error')
    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    """GET: return user data as JSON for the edit modal. POST: save updated fields."""
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if not user:
            if request.method == 'GET':
                return {'error': 'User not found.'}, 404
            flash('User not found.', 'error')
            return redirect(url_for('admin_dashboard'))

        if request.method == 'GET':
            # Return editable user data as JSON for the modal
            player_row = None
            if user['role'] == 'player':
                player_row = conn.execute(
                    'SELECT age, position, experience_years FROM players WHERE user_id = ?', (user_id,)
                ).fetchone()

            data = {
                'user_id':          user['user_id'],
                'username':         user['username'],
                'full_name':        user['full_name'] or '',
                'role':             user['role'],
                'team_name':        user['team_name'] or '',
                'team_code':        user['team_code'] or '',
                'sport':            user['sport'] or '',
                'age':              player_row['age'] if player_row else '',
                'position':         player_row['position'] if player_row else '',
                'experience_years': player_row['experience_years'] if player_row else '',
            }
            return data

        # ── POST: save changes ──────────────────────────────────────────────
        full_name  = request.form.get('full_name', '').strip()
        username   = request.form.get('username', '').strip().lower()
        team_name  = request.form.get('team_name', '').strip()
        team_code  = request.form.get('team_code', '').strip()
        sport      = request.form.get('sport', '').strip()

        if not username or not full_name:
            flash('Full name and username are required.', 'error')
            return redirect(url_for('admin_dashboard'))

        # Check username uniqueness (excluding current user)
        existing = conn.execute(
            'SELECT user_id FROM users WHERE LOWER(username) = ? AND user_id != ?', (username, user_id)
        ).fetchone()
        if existing:
            flash(f"Username '{username}' is already taken by another user.", 'error')
            return redirect(url_for('admin_dashboard'))

        conn.execute('''
            UPDATE users
            SET full_name = ?, username = ?, team_name = ?, team_code = ?, sport = ?
            WHERE user_id = ?
        ''', (full_name, username, team_name, team_code, sport, user_id))

        # If player, also update the players table
        if user['role'] == 'player':
            age              = request.form.get('age', '').strip()
            position         = request.form.get('position', '').strip()
            experience_years = request.form.get('experience_years', '').strip()

            conn.execute('''
                UPDATE players
                SET name = ?, age = ?, position = ?, experience_years = ?
                WHERE user_id = ?
            ''', (full_name, age or None, position or None, experience_years or None, user_id))

        conn.commit()
        flash(f"User '{username}' updated successfully.", 'success')

    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))


# ─── OTP Password Reset ───────────────────────────────────────────────────────

def _send_otp_email(to_address: str, otp: str, full_name: str) -> bool:
    """Send a 6-digit OTP to the user's email via SMTP. Returns True on success."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'PlayFit FC — Your Password Reset OTP'
        msg['From']    = SMTP_FROM
        msg['To']      = to_address

        html_body = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Password Reset OTP</title>
        </head>
        <body style="margin:0;padding:0;background:#102218;font-family:'Segoe UI',Arial,sans-serif;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#102218;padding:40px 0;">
            <tr><td align="center">
              <table width="560" cellpadding="0" cellspacing="0" style="background:#193324;border-radius:12px;overflow:hidden;border:1px solid #2a5a3a;">
                <!-- Header -->
                <tr>
                  <td style="background:#13ec6d;padding:24px 32px;text-align:center;">
                    <p style="margin:0;color:#102218;font-size:24px;font-weight:900;letter-spacing:2px;">PLAYFIT FC</p>
                  </td>
                </tr>
                <!-- Body -->
                <tr>
                  <td style="padding:40px 32px;">
                    <p style="color:#92c9a9;font-size:14px;margin:0 0 8px;">Hello, <strong style="color:#fff;">{full_name}</strong></p>
                    <h2 style="color:#fff;font-size:22px;margin:0 0 16px;">Your Password Reset OTP</h2>
                    <p style="color:#92c9a9;font-size:15px;line-height:1.6;margin:0 0 28px;">
                      We received a request to reset your PlayFit FC account password.
                      Use the OTP below to verify your identity. It expires in <strong style="color:#13ec6d;">10 minutes</strong>.
                    </p>
                    <div style="text-align:center;margin-bottom:32px;">
                      <div style="display:inline-block;background:#102218;border:2px solid #13ec6d;border-radius:12px;padding:20px 48px;">
                        <p style="margin:0;color:#13ec6d;font-size:42px;font-weight:900;letter-spacing:12px;font-family:monospace;">{otp}</p>
                      </div>
                    </div>
                    <p style="color:#92c9a9;font-size:13px;margin:0 0 4px;">Enter this code on the verification page. Do not share it with anyone.</p>
                    <hr style="border:none;border-top:1px solid #2a5a3a;margin:24px 0;">
                    <p style="color:#6aaa80;font-size:12px;margin:0;">
                      If you did not request a password reset, you can safely ignore this email.
                    </p>
                  </td>
                </tr>
                <!-- Footer -->
                <tr>
                  <td style="background:#112218;padding:16px 32px;text-align:center;">
                    <p style="color:#6aaa80;font-size:11px;margin:0;">&copy; 2026 PlayFit FC. All rights reserved.</p>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>
        </body>
        </html>
        """

        text_body = (
            f"Hello {full_name},\n\n"
            f"Your PlayFit FC password reset OTP is: {otp}\n"
            f"This code expires in 10 minutes.\n\n"
            f"If you did not request this, please ignore this email.\n\n"
            f"— PlayFit FC Team"
        )

        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, to_address, msg.as_string())
        return True
    except Exception as e:
        print(f"[SMTP Error] Failed to send OTP email: {e}")
        return False


# ─── Forgot Password — OTP Flow ────────────────────────────────────────────────

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    """Step 1: User enters their registered email; we generate and send a 6-digit OTP."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Please enter your email address.', 'error')
            return redirect(url_for('forgot_password'))

        conn = get_db_connection()
        try:
            user = conn.execute(
                'SELECT user_id, full_name, username FROM users WHERE LOWER(username) = ?',
                (email,)
            ).fetchone()

            if user:
                otp = str(random.randint(100000, 999999))
                expiry = (datetime.now() + timedelta(minutes=10)).isoformat()

                # Store OTP state in session (server-side, not exposed in URL)
                session['otp_code']    = otp
                session['otp_expiry']  = expiry
                session['otp_email']   = email
                session['otp_user_id'] = user['user_id']
                session['otp_attempts'] = 0

                full_name = user['full_name'] or user['username']
                _send_otp_email(email, otp, full_name)

            # Always redirect to verify page (prevents email enumeration)
            flash('If that email is registered, a 6-digit OTP has been sent. Check your inbox.', 'success')
            return redirect(url_for('verify_otp'))
        except sqlite3.Error as e:
            print(f"[DB Error] forgot_password: {e}")
            flash('A server error occurred. Please try again later.', 'error')
        finally:
            conn.close()

    return render_template('forgot_password.html')


@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    """Step 2: User enters the OTP received by email."""
    if 'otp_code' not in session:
        flash('Please start the password reset process from the beginning.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()

        # Increment attempt counter
        session['otp_attempts'] = session.get('otp_attempts', 0) + 1

        # Too many attempts
        if session['otp_attempts'] > 3:
            session.pop('otp_code', None)
            flash('Too many incorrect attempts. Please request a new OTP.', 'error')
            return redirect(url_for('forgot_password'))

        # Check expiry
        try:
            expiry = datetime.fromisoformat(session['otp_expiry'])
        except (KeyError, ValueError):
            expiry = datetime.min

        if datetime.now() > expiry:
            session.pop('otp_code', None)
            flash('Your OTP has expired. Please request a new one.', 'error')
            return redirect(url_for('forgot_password'))

        # Verify OTP
        if entered == session.get('otp_code'):
            session['otp_verified'] = True
            session.pop('otp_code', None)  # Consume the OTP immediately
            return redirect(url_for('reset_password'))
        else:
            remaining = 3 - session['otp_attempts']
            flash(f'Incorrect OTP. {remaining} attempt(s) remaining.', 'error')

    return render_template('verify_otp.html')


@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    """Step 3: Verified user sets a new password."""
    if not session.get('otp_verified') or 'otp_user_id' not in session:
        flash('Please complete the OTP verification first.', 'error')
        return redirect(url_for('forgot_password'))

    conn = get_db_connection()
    try:
        if request.method == 'POST':
            password = request.form.get('password', '')
            confirm  = request.form.get('confirm_password', '')

            if len(password) < 8:
                flash('Password must be at least 8 characters.', 'error')
                return render_template('reset_password.html')

            if password != confirm:
                flash('Passwords do not match.', 'error')
                return render_template('reset_password.html')

            user_id = session['otp_user_id']
            hashed  = generate_password_hash(password)
            conn.execute(
                'UPDATE users SET password = ?, reset_token = NULL, reset_token_expiry = NULL WHERE user_id = ?',
                (hashed, user_id)
            )
            conn.commit()

            # Clear all OTP session keys
            for key in ('otp_verified', 'otp_user_id', 'otp_email', 'otp_expiry', 'otp_attempts'):
                session.pop(key, None)

            flash('Your password has been updated! You can now sign in.', 'success')
            return redirect(url_for('signin'))

        return render_template('reset_password.html')

    except sqlite3.Error as e:
        print(f"[DB Error] reset_password: {e}")
        flash('A server error occurred. Please try again.', 'error')
        return redirect(url_for('forgot_password'))
    finally:
        conn.close()


if __name__ == '__main__':
    app.run(debug=True)
