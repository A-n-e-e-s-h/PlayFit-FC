import sqlite3
import pandas as pd
import numpy as np
import joblib
import os
import shap
import xgboost
import time
import json
import logging
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paths
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'injury_risk_model.pkl')
SCALER_PATH = os.path.join(os.path.dirname(__file__), 'scaler.pkl')
DB_PATH = os.path.join(os.path.dirname(__file__), '../playfit.db')

# Versions (Static defaults, will be overridden by DB)
MODEL_VERSION = "v1.0.0"
FEATURE_VERSION = "v1.0.0"

# Module-level singletons
_MODEL = None
_SCALER = None
_ACTIVE_VERSION = None
_PREDICTION_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_TRAINING_EXECUTOR = ThreadPoolExecutor(max_workers=1) # Prevent CPU starvation

def _load_model_assets():
    global _MODEL, _SCALER, _ACTIVE_VERSION, MODEL_VERSION
    
    conn = sqlite3.connect(DB_PATH)
    try:
        ver_row = conn.execute("SELECT meta_value FROM system_meta WHERE meta_key = 'active_model_version'").fetchone()
        current_db_ver = ver_row['meta_value'] if ver_row else "v1.0.0"
    except:
        current_db_ver = "v1.0.0"
    finally:
        conn.close()

    # Reload if first time or version changed
    if _MODEL is None or _SCALER is None or _ACTIVE_VERSION != current_db_ver:
        if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
            # Use joblib.load directly to ensure fresh load
            _MODEL = joblib.load(MODEL_PATH)
            _SCALER = joblib.load(SCALER_PATH)
            _ACTIVE_VERSION = current_db_ver
            MODEL_VERSION = current_db_ver
            logger.info(f"ML Model ({current_db_ver}) and Scaler loaded into memory.")
        else:
            logger.warning("Model or Scaler files missing.")
    return _MODEL, _SCALER

def _score_prediction(probabilities, risk_data):
    """Apply the same score and level rules everywhere we surface injury risk."""
    if len(probabilities) == 3:
        risk_probability_score = (probabilities[1] * 0.4 + probabilities[2] * 1.0)
    else:
        risk_probability_score = probabilities[1] if len(probabilities) > 1 else 0.0

    risk_score = min(int(risk_probability_score * 100), 100)

    if risk_score > 65:
        risk_level = "High"
    elif risk_score > 35:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    acwr_val = float(risk_data.get('acwr_val', 0) or 0)
    fatigue_val = int(risk_data.get('fatigue_level', 0) or 0)
    if acwr_val > 1.3 or fatigue_val >= 8:
        if risk_level == "Low":
            risk_level = "Medium"
            acwr_bonus = max(0, (acwr_val - 1.3) * 15)
            fatigue_bonus = max(0, (fatigue_val - 8) * 4)
            risk_score = max(risk_score, int(36 + acwr_bonus + fatigue_bonus))
            risk_score = min(risk_score, 64)

    return risk_score, risk_level

def _build_prediction_summary(risk_score, risk_level, risk_data, target_date_obj):
    """Build a lightweight prediction summary without SHAP or history generation."""
    confidence_suffix = ""
    last_date = pd.to_datetime(risk_data.get('wellness_df').iloc[0]['entry_date']) if not risk_data['wellness_df'].empty else None
    if last_date and (target_date_obj - last_date).days > 2:
        confidence_suffix = " (Low Confidence - Stale Data)"
    elif not risk_data['has_workload']:
        confidence_suffix = " (Wellness-only)"
    elif not risk_data['has_wellness']:
        confidence_suffix = " (Workload-only)"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level + confidence_suffix,
        "risk_level_base": risk_level,
        "has_wellness": risk_data.get('has_wellness', False),
        "has_workload": risk_data.get('has_workload', False)
    }

def get_player_risk_snapshot(player_id, target_date=None):
    """Fast risk lookup for team analytics/report pages without history or explanation payloads."""
    model, scaler = _load_model_assets()
    if not model or not scaler:
        return {
            "risk_score": 0,
            "risk_level": "Model needs training.",
            "risk_level_base": "Low",
            "has_wellness": False,
            "has_workload": False
        }

    today_obj = pd.to_datetime('today').normalize()
    if target_date is None:
        target_date_obj = today_obj
    else:
        target_date_obj = pd.to_datetime(target_date).normalize()

    target_date_str = target_date_obj.strftime('%Y-%m-%d')

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        player = conn.execute('SELECT * FROM players WHERE player_id = ?', (player_id,)).fetchone()
        if not player:
            return {
                "risk_score": 0,
                "risk_level": "Player not found.",
                "risk_level_base": "Low",
                "has_wellness": False,
                "has_workload": False
            }

        if target_date_obj == today_obj and player['prediction_ready'] == 0:
            cache = conn.execute('''
                SELECT * FROM predictions
                WHERE player_id = ? AND DATE(prediction_date) = DATE(?)
                AND model_version = ? AND feature_version = ?
                ORDER BY prediction_date DESC LIMIT 1
            ''', (player_id, target_date_str, MODEL_VERSION, FEATURE_VERSION)).fetchone()
            if cache:
                risk_data = _compute_risk_features(conn, player_id, target_date_obj)
                return _build_prediction_summary(
                    float(cache['risk_score']),
                    cache['risk_level'],
                    risk_data,
                    target_date_obj
                )

        risk_data = _compute_risk_features(conn, player_id, target_date_obj)
        if not risk_data['has_wellness'] and not risk_data['has_workload']:
            return {
                "risk_score": 0,
                "risk_level": "Insufficient Data",
                "risk_level_base": "Low",
                "has_wellness": False,
                "has_workload": False
            }

        X_input = pd.DataFrame(risk_data['feature_vec'])
        X_scaled = scaler.transform(X_input)
        probabilities = model.predict_proba(X_scaled)[0]
        risk_score, risk_level = _score_prediction(probabilities, risk_data)
        return _build_prediction_summary(risk_score, risk_level, risk_data, target_date_obj)
    except Exception as e:
        logger.error(f"Risk snapshot error for player {player_id}: {e}")
        return {
            "risk_score": 0,
            "risk_level": "Prediction Error",
            "risk_level_base": "Low",
            "has_wellness": False,
            "has_workload": False
        }
    finally:
        conn.close()

def get_player_prediction(player_id, period=30, target_date=None, force_refresh=False):
    """Fetches the latest data for a player and predicts their injury risk with caching and retry logic."""
    start_time = time.time()
    model, scaler = _load_model_assets()
    if not model or not scaler:
        return _get_default_response(period, "Model needs training.")
    
    today_obj = pd.to_datetime('today').normalize()
    if target_date is None:
        target_date_obj = today_obj
    else:
        target_date_obj = pd.to_datetime(target_date).normalize()
    snapshot_mode = target_date_obj != today_obj
    
    target_date_str = target_date_obj.strftime('%Y-%m-%d')
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 1. Check Cache Validity
        player = conn.execute('SELECT * FROM players WHERE player_id = ?', (player_id,)).fetchone()
        if not player:
            return _get_default_response(period, "Player not found.")

        if snapshot_mode:
            risk_data = _compute_risk_features(conn, player_id, target_date_obj)

            if not risk_data['has_wellness'] and not risk_data['has_workload']:
                return _get_default_response(period, "Insufficient data for prediction. Please complete your daily wellness check-in.")

            X_input = pd.DataFrame(risk_data['feature_vec'])
            X_scaled = scaler.transform(X_input)
            probabilities = model.predict_proba(X_scaled)[0]
            risk_score, risk_level = _score_prediction(probabilities, risk_data)

            confidence_suffix = ""
            last_date = pd.to_datetime(risk_data.get('wellness_df').iloc[0]['entry_date']) if not risk_data['wellness_df'].empty else None
            if last_date and (target_date_obj - last_date).days > 2:
                confidence_suffix = " (Low Confidence - Stale Data)"
            elif not risk_data['has_workload']:
                confidence_suffix = " (Wellness-only)"
            elif not risk_data['has_wellness']:
                confidence_suffix = " (Workload-only)"

            risk_level_display = risk_level + confidence_suffix
            top_factors, explanation = _generate_shap_explanation(model, X_scaled, X_input.columns, risk_data)

            duration = (time.time() - start_time) * 1000
            logger.info(json.dumps({
                "event": "prediction_snapshot",
                "player_id": player_id,
                "target_date": target_date_str,
                "duration_ms": round(duration, 2)
            }))

            return _build_prediction_payload(
                conn, player_id, risk_score, risk_level, risk_level_display,
                period, model, scaler, risk_data, top_factors, explanation
            )
        
        # Deadlock Recovery: If stuck in "In-Progress" (2) for > 2 mins, reset
        if player['prediction_ready'] == 2:
            last_attempt = player['last_prediction_attempt']
            if last_attempt:
                attempt_dt = datetime.fromisoformat(last_attempt)
                if datetime.now() - attempt_dt > timedelta(minutes=2):
                    logger.warning(f"Deadlock detected for player {player_id}. Resetting status.")
                    conn.execute('UPDATE players SET prediction_ready = 1 WHERE player_id = ?', (player_id,))
                    conn.commit()
                    player = conn.execute('SELECT * FROM players WHERE player_id = ?', (player_id,)).fetchone()

        if not force_refresh and player['prediction_ready'] == 0:
            # Check for existing prediction today with correct versions
            cache = conn.execute('''
                SELECT * FROM predictions 
                WHERE player_id = ? AND DATE(prediction_date) = DATE(?) 
                AND model_version = ? AND feature_version = ?
                ORDER BY prediction_date DESC LIMIT 1
            ''', (player_id, target_date_str, MODEL_VERSION, FEATURE_VERSION)).fetchone()
            
            if cache:
                # Check for staleness (if last wellness log is > 2 days ago)
                last_wellness = conn.execute('SELECT MAX(entry_date) as last_date FROM wellness_data WHERE player_id = ?', (player_id,)).fetchone()
                is_stale = False
                confidence_msg = ""
                if last_wellness and last_wellness['last_date']:
                    last_date = pd.to_datetime(last_wellness['last_date'])
                    if (target_date_obj - last_date).days > 2:
                        is_stale = True
                        confidence_msg = " (Stale Data)"
                
                # Reconstruct payload from cache
                duration = (time.time() - start_time) * 1000
                logger.info(json.dumps({
                    "event": "prediction_cache_hit",
                    "player_id": player_id,
                    "duration_ms": round(duration, 2),
                    "cache": "HIT",
                    "stale": is_stale
                }))
                
                top_factors = json.loads(cache['top_factors']) if cache['top_factors'] else []
                risk_level_display = cache['risk_level'] + confidence_msg
                
                # Note: We still need some risk_data for the payload building, but we can do a lighter version
                # or just return the essentials. For full dashboard we need the SVG history too.
                # To keep it fast, if it's a cache hit we might still need to build the SVG if not cached.
                # But for now let's assume we need to re-run the full logic to get the SVG history segments.
                # Optimization: Cache the full payload or at least the history points.
                pass 
        
        # 2. Atomic Lock for Calculation
        # Only proceed if update Needed (1) or Force Refresh
        lock_won = False
        if force_refresh or player['prediction_ready'] == 1:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE players 
                SET prediction_ready = 2, last_prediction_attempt = ?, prediction_retry_count = prediction_retry_count + 1
                WHERE player_id = ? AND (prediction_ready = 1 OR ? = 1)
            ''', (datetime.now().isoformat(), player_id, 1 if force_refresh else 0))
            if cursor.rowcount > 0:
                lock_won = True
                conn.commit()

        if not lock_won and not force_refresh:
            # If someone else is calculating, or it's already ready, just fetch latest
            # (Similar to cache hit logic above)
            cache = conn.execute('''
                SELECT * FROM predictions WHERE player_id = ? 
                ORDER BY prediction_date DESC LIMIT 1
            ''', (player_id,)).fetchone()
            if cache:
                # Return existing while waiting or if ready
                return _build_prediction_payload(conn, player_id, cache['risk_score'], cache['risk_level'], cache['risk_level'], period, model, scaler, _compute_risk_features(conn, player_id, target_date_obj), json.loads(cache['top_factors']), cache['recommendation'])

        # 3. Perform Prediction
        try:
            # Compute features for Target Date
            risk_data = _compute_risk_features(conn, player_id, target_date_obj)
            
            if not risk_data['has_wellness'] and not risk_data['has_workload']:
                return _get_default_response(period, "Insufficient data for prediction. Please complete your daily wellness check-in.")
            
            X_input = pd.DataFrame(risk_data['feature_vec'])
            X_scaled = scaler.transform(X_input)
            probabilities = model.predict_proba(X_scaled)[0]
            
            # Risk Score Calculation (0-100)
            risk_score, risk_level = _score_prediction(probabilities, risk_data)
            
            # Confidence handling
            confidence_suffix = ""
            last_date = pd.to_datetime(risk_data.get('wellness_df').iloc[0]['entry_date']) if not risk_data['wellness_df'].empty else None
            if last_date and (target_date_obj - last_date).days > 2:
                confidence_suffix = " (Low Confidence - Stale Data)"
            elif not risk_data['has_workload']: confidence_suffix = " (Wellness-only)"
            elif not risk_data['has_wellness']: confidence_suffix = " (Workload-only)"
            
            risk_level_display = risk_level + confidence_suffix

            # Explainability
            top_factors, explanation = _generate_shap_explanation(model, X_scaled, X_input.columns, risk_data)
            
            # Alert Engine
            _check_and_trigger_alerts(conn, player_id, risk_score, risk_data)
            
            # 4. Save and Release Lock
            json_safe_factors = [
                {k: (float(v) if isinstance(v, (np.float32, np.float64, np.float16)) else v) for k, v in factor.items()}
                for factor in top_factors
            ]
            
            _save_prediction_to_db(conn, player_id, risk_score, risk_level, explanation, json.dumps(json_safe_factors))
            
            # Reset retry count and set ready
            conn.execute('UPDATE players SET prediction_ready = 0, prediction_retry_count = 0 WHERE player_id = ?', (player_id,))
            conn.commit()
            
            duration = (time.time() - start_time) * 1000
            logger.info(json.dumps({
                "event": "prediction_complete",
                "player_id": player_id,
                "duration_ms": round(duration, 2),
                "cache": "MISS",
                "retries": player['prediction_retry_count']
            }))
            
            return _build_prediction_payload(conn, player_id, risk_score, risk_level, risk_level_display, period, model, scaler, risk_data, top_factors, explanation)

        except Exception as calc_e:
            # Retry logic with exponential backoff if it's a background/auto attempt
            retry_count = player['prediction_retry_count']
            if retry_count < 3:
                # We don't sleep here if it's a web request, but we mark for retry
                conn.execute('UPDATE players SET prediction_ready = 1 WHERE player_id = ?', (player_id,))
                conn.commit()
                # Exponential backoff would be handled by the background worker sleeping before the next attempt
            else:
                # Permanent fallback
                conn.execute('UPDATE players SET prediction_ready = 0 WHERE player_id = ?', (player_id,))
                conn.commit()
            raise calc_e

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Prediction Error for player {player_id}: {e}")
        return _get_default_response(period, f"Prediction error: {str(e)}")
    finally:
        conn.close()

def _save_prediction_to_db(conn, player_id, risk_score, risk_level, recommendation, top_factors=None):
    """Saves the prediction to the database with versioning."""
    try:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO predictions (player_id, risk_score, risk_level, recommendation, prediction_date, top_factors, model_version, feature_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (player_id, float(risk_score), risk_level, recommendation, now, top_factors, MODEL_VERSION, FEATURE_VERSION))
        
        conn.execute('''
            UPDATE players 
            SET last_prediction_at = ?
            WHERE player_id = ?
        ''', (now, player_id))
    except Exception as e:
        logger.error(f"Error saving prediction to DB: {e}")

def run_prediction_background(player_id):
    """Entry point for background thread pool execution."""
    # Exponential backoff check
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        player = conn.execute('SELECT prediction_retry_count FROM players WHERE player_id = ?', (player_id,)).fetchone()
        if player and player['prediction_retry_count'] > 0:
            delay = 2 ** player['prediction_retry_count']
            logger.info(f"Retrying prediction for player {player_id} with delay {delay}s")
            time.sleep(delay)
    finally:
        conn.close()
        
    get_player_prediction(player_id, force_refresh=True)

def queue_prediction(player_id):
    """Queues a prediction to be calculated in the background executor."""
    _PREDICTION_EXECUTOR.submit(run_prediction_background, player_id)

def check_and_trigger_learning(conn=None):
    """
    Evaluates if autonomous retraining is needed based on thresholds, 
    cooldowns, and concurrency locks.
    """
    should_close = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        should_close = True
        
    try:
        # 1. Fetch system meta
        meta = {}
        rows = conn.execute("SELECT meta_key, meta_value, last_updated FROM system_meta").fetchall()
        for r in rows:
            meta[r['meta_key']] = {'val': r['meta_value'], 'updated': r['last_updated']}
            
        status = meta.get('retraining_status', {}).get('val', 'idle')
        last_trained = meta.get('last_retrained_at', {}).get('val', '2000-01-01 00:00:00')
        last_samples = int(meta.get('sample_count_at_last_training', {}).get('val', '0'))
        retry_count = int(meta.get('retraining_retry_count', {}).get('val', '0'))
        last_updated_str = meta.get('retraining_status', {}).get('updated')
        
        # 2. Concurrency & Timeout Recovery
        if status == 'running' and last_updated_str:
            last_upd = datetime.fromisoformat(last_updated_str.replace(' ', 'T'))
            if datetime.now() - last_upd > timedelta(hours=1):
                logger.warning("Stuck training lock detected. Resetting to failed.")
                conn.execute("UPDATE system_meta SET meta_value = 'failed', last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_status'")
                conn.commit()
                status = 'failed'
                
        if status == 'running':
            return False
            
        # 3. Failure Backoff
        if status == 'failed':
            delay_hours = min(2 ** retry_count, 24)
            last_upd = datetime.fromisoformat(last_updated_str.replace(' ', 'T'))
            if datetime.now() - last_upd < timedelta(hours=delay_hours):
                return False
                
        # 4. Threshold Checks
        # Cooldown check (12h)
        last_trained_dt = datetime.fromisoformat(last_trained.replace(' ', 'T'))
        if datetime.now() - last_trained_dt < timedelta(hours=12):
            return False
            
        # Data volume check
        wellness_cnt = conn.execute("SELECT COUNT(*) FROM wellness_data").fetchone()[0]
        training_cnt = conn.execute("SELECT COUNT(*) FROM training_data").fetchone()[0]
        total_samples = wellness_cnt + training_cnt
        
        MIN_NEW_SAMPLES = 50
        MIN_TOTAL_SAMPLES = 200
        
        if total_samples < MIN_TOTAL_SAMPLES:
            return False
            
        if (total_samples - last_samples) < MIN_NEW_SAMPLES:
            return False
            
        # 5. Atomic Lock Acquisition
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE system_meta 
            SET meta_value = 'running', last_updated = CURRENT_TIMESTAMP 
            WHERE meta_key = 'retraining_status' AND meta_value != 'running'
        """)
        if cursor.rowcount == 0:
            return False # Someone else got the lock
            
        conn.commit()
        logger.info(f"Autonomous learning triggered. Current samples: {total_samples}")
        
        # Trigger background training
        _TRAINING_EXECUTOR.submit(trigger_autonomous_learning)
        return True
        
    except Exception as e:
        logger.error(f"Error in check_and_trigger_learning: {e}")
        return False
    finally:
        if should_close:
            conn.close()

def trigger_autonomous_learning():
    """Wrapper to run the retraining pipeline in the background."""
    try:
        from ml.retrain_model import run_retraining_pipeline
        run_retraining_pipeline()
    except Exception as e:
        logger.error(f"Background training failed: {e}")
        # Status update is handled inside run_retraining_pipeline

def _compute_risk_features(conn, player_id, target_date, wellness_batch=None, workload_batch=None):
    """Unified helper to calculate the 17-feature vector for a specific date (Expanded to 19+).
    Supports batch dataframes to avoid N+1 query overhead.
    """
    target_date = pd.to_datetime(target_date).normalize()
    past_7 = target_date - pd.Timedelta(days=7)
    past_14 = target_date - pd.Timedelta(days=14)
    past_28 = target_date - pd.Timedelta(days=28)
    
    # 0. Fetch Player Profile (cached if in loop, but here we can just query once or pass it)
    player_df = pd.read_sql_query(
        "SELECT age, position, experience_years FROM players WHERE player_id = ?",
        conn, params=(player_id,)
    )
    age = player_df.iloc[0]['age'] if not player_df.empty else 25
    exp = player_df.iloc[0]['experience_years'] if not player_df.empty else 5
    pos_raw = player_df.iloc[0]['position'] if not player_df.empty else 'Midfielder'
    
    pos_map = {'Forward': 4, 'Midfielder': 3, 'Defender': 2, 'Goalkeeper': 1}
    position_encoded = pos_map.get(pos_raw, 3)

    # 1. Fetch Latest Wellness & Trends
    target_date_str = target_date.strftime('%Y-%m-%d')
    if wellness_batch is not None:
        wellness_df = wellness_batch[wellness_batch['entry_date'] <= target_date_str].sort_values('entry_date', ascending=False).head(1)
        wellness_7d = wellness_batch[(wellness_batch['entry_date'] >= past_7.strftime('%Y-%m-%d')) & (wellness_batch['entry_date'] <= target_date_str)]
    else:
        wellness_df = pd.read_sql_query(
            "SELECT * FROM wellness_data WHERE player_id = ? AND entry_date <= ? ORDER BY entry_date DESC LIMIT 1", 
            conn, params=(player_id, target_date_str)
        )
        wellness_7d = pd.read_sql_query(
            "SELECT fatigue_level, sleep_quality, muscle_soreness FROM wellness_data WHERE player_id = ? AND entry_date >= ? AND entry_date <= ?",
            conn, params=(player_id, past_7.strftime('%Y-%m-%d'), target_date_str)
        )
        
    has_wellness = not wellness_df.empty
    
    # 2 & 3. Fetch Workload and Match Details
    if workload_batch is not None:
        workload_df = workload_batch[(workload_batch['training_date'] >= past_28.strftime('%Y-%m-%d')) & (workload_batch['training_date'] <= target_date_str)]
    else:
        workload_df = pd.read_sql_query(
            "SELECT * FROM training_data WHERE player_id = ? AND training_date >= ? AND training_date <= ?",
            conn, params=(player_id, past_28.strftime('%Y-%m-%d'), target_date_str)
        )
    
    tech_df = workload_df[workload_df['training_minutes'] > 0] if not workload_df.empty else pd.DataFrame()
    match_df = workload_df[workload_df['minutes_played'] > 0] if not workload_df.empty else pd.DataFrame()
    
    has_workload = (not workload_df.empty and workload_df[workload_df['training_date'] >= past_7.strftime('%Y-%m-%d')]['training_minutes'].sum() > 0)
    
    sleep_map = {'Poor': 3, 'Average': 6, 'Good': 9}
    soreness_map = {'Low': 2, 'Medium': 5, 'High': 8}
    intensity_map = {'Low': 1, 'Medium': 2, 'High': 3}
    
    if has_wellness:
        sleep_score = sleep_map.get(wellness_df.iloc[0]['sleep_quality'], 6)
        soreness_score = soreness_map.get(wellness_df.iloc[0]['muscle_soreness'], 5)
        try: fatigue_level = int(wellness_df.iloc[0]['fatigue_level'])
        except: fatigue_level = 5
    else:
        sleep_score, soreness_score, fatigue_level = 6, 5, 5

    fatigue_trend = float(wellness_7d['fatigue_level'].astype(float).mean()) if not wellness_7d.empty else 5.0
    sleep_trend = float(wellness_7d['sleep_quality'].map(sleep_map).mean()) if not wellness_7d.empty else 6.0
    soreness_trend = float(wellness_7d['muscle_soreness'].map(soreness_map).mean()) if not wellness_7d.empty else 5.0

    tech_7 = tech_df[tech_df['training_date'] >= past_7.strftime('%Y-%m-%d')] if not tech_df.empty else pd.DataFrame()
    training_minutes = int(tech_7['training_minutes'].sum()) if not tech_7.empty else 0
    sessions_per_week = tech_7['sessions_per_week'].iloc[0] if not tech_7.empty else 0
    
    intensity_scores = tech_7['intensity'].map(intensity_map).fillna(2) if not tech_7.empty else pd.Series([2.0])
    training_intensity = float(intensity_scores.mean()) if not tech_7.empty else 2.0
    
    match_7 = match_df[match_df['training_date'] >= past_7.strftime('%Y-%m-%d')] if not match_df.empty else pd.DataFrame()
    minutes_played = int(match_7['minutes_played'].sum()) if not match_7.empty else 0
    matches_per_week = match_7['matches_per_week'].iloc[0] if not match_7.empty else 0
    
    prev_week_df = workload_df[(workload_df['training_date'] >= past_14.strftime('%Y-%m-%d')) & (workload_df['training_date'] < past_7.strftime('%Y-%m-%d'))]
    prev_week_load = prev_week_df['training_minutes'].sum() if not prev_week_df.empty else 1.0
    workload_spike = (training_minutes + 1) / (prev_week_load + 1)

    # 4. Injury Features (Full History for Recency)
    # This is still a bit expensive if done in loop, but we can pre-fetch last injury date once.
    last_inj_query = pd.read_sql_query(
        "SELECT training_date FROM training_data WHERE player_id = ? AND active_injury = 1 ORDER BY training_date DESC LIMIT 1",
        conn, params=(player_id,)
    )
    
    days_since_last_injury = 365
    if not last_inj_query.empty:
        latest_inj_dt = pd.to_datetime(last_inj_query.iloc[0]['training_date'])
        days_since_last_injury = (target_date - latest_inj_dt).days
    
    past_30 = target_date - pd.Timedelta(days=30)
    injury_30d_df = workload_df[(workload_df['training_date'] >= past_30.strftime('%Y-%m-%d')) & (workload_df['training_date'] < target_date_str)]
    
    injury_days_last_30 = int(injury_30d_df['active_injury'].sum()) if not injury_30d_df.empty else 0
    previous_injury = 1 if days_since_last_injury < 60 else 0
    previous_injury_count = injury_days_last_30 // 14
    avg_recovery_days = 0.0
    recovery_days = 0

    training_recency = 7
    if not workload_df.empty:
        training_recency = (target_date - pd.to_datetime(workload_df['training_date'].max())).days
        
    match_load_frequency = 14
    if not match_df.empty:
        match_load_frequency = (target_date - pd.to_datetime(match_df['training_date'].max())).days

    acute_load = training_minutes + minutes_played
    total_chronic_minutes = workload_df['training_minutes'].sum() if not workload_df.empty else 160.0
    chronic_load = max(total_chronic_minutes / 4.0, 1.0)
    acwr_val = acute_load / chronic_load
    
    recovery_score = sleep_score - soreness_score
    load_ratio = training_minutes / (minutes_played + 1.0)
    injury_risk_factor = previous_injury * recovery_days

    feature_vec = {
        'age': [age], 'position_encoded': [position_encoded], 'experience_years': [exp],
        'minutes_played': [minutes_played], 'matches_per_week': [matches_per_week],
        'training_minutes': [training_minutes], 'training_intensity': [training_intensity],
        'sessions_per_week': [sessions_per_week], 'fatigue_level': [fatigue_level],
        'muscle_soreness': [soreness_score], 'sleep_quality': [sleep_score],
        'fatigue_trend': [fatigue_trend], 'sleep_trend': [sleep_trend],
        'soreness_trend': [soreness_trend], 'workload_spike': [workload_spike],
        'previous_injury_count': [previous_injury_count], 'avg_recovery_days': [avg_recovery_days],
        'previous_injury': [previous_injury], 'recovery_days': [recovery_days],
        'days_since_last_injury': [days_since_last_injury], 'training_recency': [training_recency],
        'match_load_frequency': [match_load_frequency], 'ACWR': [acwr_val],
        'recovery_score': [recovery_score], 'load_ratio': [load_ratio],
        'injury_risk_factor': [injury_risk_factor]
    }
    
    return {
        'feature_vec': feature_vec, 'has_wellness': has_wellness, 'has_workload': has_workload,
        'wellness_df': wellness_df, 'wellness_7d': wellness_7d, 'sleep_score': sleep_score,
        'soreness_score': soreness_score, 'fatigue_level': fatigue_level, 'acwr_val': acwr_val,
        'days_since_last_injury': days_since_last_injury
    }

def calculate_rolling_avg(values):
    """Calculates average and count for a list of values, ignoring None/NaN."""
    valid = [float(v) for v in values if v is not None and str(v).lower() != 'nan']
    if not valid:
        return 0.0, 0
    return sum(valid) / len(valid), len(valid)

def _build_prediction_payload(conn, player_id, risk_score, risk_level, risk_level_display, period, model, scaler, risk_data, top_factors=[], explanation=""):
    # Dynamic Recommendations based on risk status
    recommendation_list = []
    if risk_score > 65: # Sync with thresholds
        rec = explanation if explanation else "Rest recommended. High combined injury risk detected."
        recommendation_list.append({'title': 'High Priority', 'description': 'Complete rest or low-impact active recovery.', 'icon': 'warning', 'bg_class': 'bg-red-500/10 border-red-500/20', 'text_class': 'text-red-500'})
    elif risk_score > 35:
        rec = explanation if explanation else "Monitor load. Focus on active recovery and reduce intensity."
        recommendation_list.append({'title': 'Moderate Risk', 'description': 'Limit high-speed drills and impact today.', 'icon': 'warning', 'bg_class': 'bg-amber-500/10 border-amber-500/20', 'text_class': 'text-amber-500'})
    else:
        rec = "Optimal condition. Cleared for full participation."
        recommendation_list.append({'title': 'Optimal Status', 'description': 'Ready for peak intensity loading.', 'icon': 'check_circle', 'bg_class': 'bg-primary/10 border-primary/20', 'text_class': 'text-primary'})

    # Chart History Integration (Segmented)
    history_segments, svg_labels, risk_map, points = _calculate_risk_history_svg(conn, player_id, model, scaler, days=period)
    insight_msg, insight_status = _generate_analysis_insight(risk_data['wellness_7d'], risk_map)
    
    # 7-Day Rolling Averages
    sleep_map = {'Poor': 3, 'Average': 6, 'Good': 9}
    soreness_map = {'Low': 2, 'Medium': 5, 'High': 8}
    
    raw_sleeps = [sleep_map.get(s, 6) for s in risk_data['wellness_7d']['sleep_quality']] if not risk_data['wellness_7d'].empty else []
    raw_soreness = [soreness_map.get(s, 5) for s in risk_data['wellness_7d']['muscle_soreness']] if not risk_data['wellness_7d'].empty else []
    
    avg_sleep_val, sleep_count = calculate_rolling_avg(raw_sleeps)
    avg_soreness_val, soreness_count = calculate_rolling_avg(raw_soreness)
    
    # Formatting
    # Map back to hours roughly for sleep (3->5h, 6->7h, 9->8.5h)
    avg_sleep_h = 5.0 + ((avg_sleep_val - 3.0) / 6.0) * 3.5 if sleep_count > 0 else 7.0
    avg_sleep_str = f"{int(avg_sleep_h)}h {int((avg_sleep_h%1)*60)}m" if sleep_count > 0 else "No data"
    avg_soreness_str = f"{avg_soreness_val:.1f}/10" if soreness_count > 0 else "No data"

    # Dynamic Injury Logic
    injury_str = "No injuries recorded"
    days_val = risk_data['days_since_last_injury']
    if days_val == 0:
        injury_str = "Injury reported today"
    elif days_val < 365:
        injury_str = f"{days_val} Days"
    else:
        # Fallback to days since first session
        first_session = conn.execute('SELECT MIN(training_date) FROM training_data WHERE player_id = ?', (player_id,)).fetchone()
        if first_session and first_session[0]:
            total_days = (pd.to_datetime('today').normalize() - pd.to_datetime(first_session[0])).days
            injury_str = f"{total_days} Days"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level_display,
        "recommendation": rec,
        "top_factors": top_factors,
        "factors_label": "Factors contributing to your current condition" if risk_score < 10 else "Main Risk Drivers",
        "explanation": explanation,
        "days_injury_free": injury_str,
        "avg_sleep": avg_sleep_str,
        "sleep_limited": sleep_count < 3 and sleep_count > 0,
        "avg_soreness": avg_soreness_str,
        "soreness_limited": soreness_count < 3 and soreness_count > 0,
        "history_segments": history_segments,
        "history_labels": svg_labels,
        "period": period,
        "history_risk_map": risk_map,
        "insight_message": insight_msg,
        "insight_status": insight_status,
        "history_points": points,
        "recommendation_list": recommendation_list
    }

def _generate_shap_explanation(model, X_scaled, feature_names, risk_data):
    """Calculates SHAP values to identify top contributors to risk, with explicit value-based gating."""
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_scaled)
    
    # If ternary classification (0,1,2), shap_values is a list of arrays.
    # Typically we care about the "High Risk" class (index 2) or "Injury" class.
    # In binary, it's just one array. 
    if isinstance(shap_values, list):
        # Taking impact on the highest risk class (2)
        target_shap = shap_values[-1][0]
    else:
        target_shap = shap_values[0]
        
    feature_impacts = []
    for i, name in enumerate(feature_names):
        impact = target_shap[i]
        feature_impacts.append({
            'feature': name,
            'impact': impact
        })
        
    FEATURE_ALIASES = {
        "fatigue": "fatigue_level",
        "sleep": "sleep_quality",
        "soreness": "muscle_soreness",
        "acwr_val": "acwr"
    }
    
    FEATURE_GROUPS = {
        "acwr": "workload",
        "workload_spike": "workload",
        "fatigue_level": "fatigue",
        "sleep_quality": "recovery",
        "muscle_soreness": "soreness",
        "recovery_days": "recovery_time"
    }
    
    GROUP_LABELS = {
        "workload": "Workload Spike"
    }
    
    FEATURE_LABELS = {
        "acwr": "Workload Spike",
        "fatigue_level": "Fatigue",
        "sleep_quality": "Sleep Recovery",
        "muscle_soreness": "Muscle Overload",
        "recovery_days": "Recovery Time",
        "workload_spike": "Acute Workload Spike"
    }
    
    FEATURE_PRIORITY = {
        "acwr": 5,
        "workload_spike": 5,
        "fatigue_level": 4,
        "sleep_quality": 3,
        "muscle_soreness": 2,
        "recovery_days": 1
    }
    
    FEATURE_DIRECTION = {
        "acwr": "high",              # Bad when high
        "fatigue_level": "high",     # Bad when high
        "muscle_soreness": "high",   # Bad when high
        "workload_spike": "high",    # Bad when high
        "sleep_quality": "low",      # Bad when low
        "recovery_days": "low"       # Bad when low
    }

    THRESHOLDS = {
        "acwr": {"critical": 1.5, "moderate": 1.3},
        "workload_spike": {"critical": 1.5, "moderate": 1.3},
        "fatigue_level": {"critical": 8, "moderate": 7},
        "sleep_quality": {"critical": 4, "moderate": 6},
        "muscle_soreness": {"critical": 8, "moderate": 7},
        "recovery_days": {"critical": 1, "moderate": 2}
    }

    capped_impact = lambda v: min(abs(v), 1.0)
    
    valid_factors = []
    for factor in feature_impacts:
        feature = factor["feature"]
        impact = factor["impact"]
        
        # Normalize feature name before fetching value to ensure correct lookup
        feature_clean = feature.strip().lower()
        feature_mapped = FEATURE_ALIASES.get(feature_clean, feature_clean)
        
        if 'feature_vec' in risk_data and feature in risk_data['feature_vec']:
            raw_value = risk_data['feature_vec'][feature][0]
        else:
            raw_value = risk_data.get(feature_mapped)
        
        if raw_value is None:
            continue
            
        try:
            raw_value = float(raw_value)
        except ValueError:
            continue
            
        direction = FEATURE_DIRECTION.get(feature_mapped, "high")
        thresholds = THRESHOLDS.get(feature_mapped, {})
        critical_th = thresholds.get("critical")
        moderate_th = thresholds.get("moderate")
        
        if not thresholds:
            continue # Explicitly skip unmapped features
            
        is_critical = False
        is_moderate = False
        
        if direction == "high":
            if critical_th is not None and raw_value >= critical_th:
                is_critical = True
            elif moderate_th is not None and raw_value >= moderate_th:
                is_moderate = True
        elif direction == "low":
            if critical_th is not None and raw_value <= critical_th:
                is_critical = True
            elif moderate_th is not None and raw_value <= moderate_th:
                is_moderate = True
                
        # Value-based Gating
        if not (is_critical or is_moderate):
            continue 
            
        # Severity Mapping (Purely Threshold-Driven)
        if is_critical:
            severity = "critical"
        else:
            severity = "moderate"
            
        # Natural Phrasing 
        LABEL_PREFIX = {"critical": "High", "moderate": "Moderate"}
        grp = FEATURE_GROUPS.get(feature_mapped, feature_mapped)
        base_label = GROUP_LABELS.get(
            grp, 
            FEATURE_LABELS.get(feature_mapped, feature_mapped.replace("_", " ").title())
        )
        
        label = f"{LABEL_PREFIX[severity]} {base_label}"
        
        # Build and Append Factor Dict
        factor_dict = {
            "raw_feature": feature,
            "feature_mapped": feature_mapped,
            "impact": impact,
            "severity": severity,
            "label": label
        }
        valid_factors.append(factor_dict)

    # Early Return
    if not valid_factors:
        return [{"label": "All key metrics are within safe ranges.", "severity": "info"}], "Maintain current training and recovery patterns."

    # Semantic Deduplication
    SEVERITY_RANK = {"critical": 3, "moderate": 2, "info": 1}
    group_map = {}
    for f in valid_factors:
        f_mapped = f.get("feature_mapped", f["raw_feature"])
        grp = FEATURE_GROUPS.get(f_mapped, f_mapped)
        f_impact = capped_impact(f.get("impact", 0.0))
        
        if grp not in group_map or (
            SEVERITY_RANK[f["severity"]] > SEVERITY_RANK[group_map[grp]["severity"]]
            or (
                SEVERITY_RANK[f["severity"]] == SEVERITY_RANK[group_map[grp]["severity"]]
                and f_impact > capped_impact(group_map[grp].get("impact", 0.0))
            )
        ):
            group_map[grp] = f
            
    deduped_factors = list(group_map.values())
    
    # Advanced Sorting (Fully Stable)
    sorted_factors = sorted(
        deduped_factors,
        key=lambda x: (
            -SEVERITY_RANK[x["severity"]], 
            -capped_impact(x.get("impact", 0.0)),
            -FEATURE_PRIORITY.get(x.get("feature_mapped") or x.get("raw_feature"), 0),
            x.get("feature_mapped") or x.get("raw_feature")
        )
    )

    top_factors = sorted_factors[:min(3, len(sorted_factors))]
    
    # Generate human readable description
    high_critical = [f for f in top_factors if f['severity'] == 'critical']
    if high_critical:
        reasons = [f['label'] for f in high_critical]
        explanation = f"Injury risk is critically elevated due to {', '.join(reasons)}."
    else:
        reasons = [f['label'] for f in top_factors]
        explanation = f"Monitor workload. Elevated risk driven by {', '.join(reasons)}."

    return top_factors, explanation

def _check_and_trigger_alerts(conn, player_id, risk_score, risk_data):
    """Evaluation engine for real-time alerts with 24h duplicate prevention."""
    active_alerts = []
    
    # Threshold checks
    if risk_score > 70:
        active_alerts.append({'type': 'Risk Score', 'prio': 'High', 'msg': f'Critical Injury Risk Level: {risk_score}%'})
    
    if risk_data.get('acwr_val', 0) > 1.3:
        active_alerts.append({'type': 'Workload', 'prio': 'High', 'msg': f'Hazardous Workload Spike detected (ACWR: {risk_data["acwr_val"]:.2f})'})
        
    if risk_data.get('fatigue_level', 0) >= 8:
        active_alerts.append({'type': 'Fatigue', 'prio': 'Medium', 'msg': f'Extreme Fatigue reported ({risk_data["fatigue_level"]}/10)'})
        
    if not risk_data['wellness_df'].empty and risk_data['wellness_df'].iloc[0]['sleep_quality'] == 'Poor':
        active_alerts.append({'type': 'Recovery', 'prio': 'Medium', 'msg': 'Sub-optimal recovery logged: Poor Sleep Quality'})

    if not active_alerts:
        return

    # De-duplication: check if any notification for this player + type exists in last 24h
    for alert in active_alerts:
        existing = conn.execute('''
            SELECT notif_id FROM notifications 
            WHERE player_id = ? AND message LIKE ? AND created_at > datetime('now', '-1 day')
            LIMIT 1
        ''', (player_id, f'%{alert["type"]}%')).fetchone()
        
        if not existing:
            # Insert new notification
            full_msg = f"[{alert['prio']} Alert - {alert['type']}] {alert['msg']}"
            conn.execute('''
                INSERT INTO notifications (player_id, message, is_read, created_at)
                VALUES (?, ?, 0, datetime('now'))
            ''', (player_id, full_msg))
            conn.commit()

def _calculate_risk_history_svg(conn, player_id, model, scaler, days=30):
    """Generates the history graph with optimized batch data fetching."""
    today = pd.to_datetime('today').normalize()
    total_days = max(int(days), 1)
    dates = [today - pd.Timedelta(days=i) for i in range(total_days - 1, -1, -1)]
    dates.sort()
    
    # Batch Fetch Data
    start_history = dates[0] - pd.Timedelta(days=35) # buffer for chronic load
    wellness_batch = pd.read_sql_query(
        "SELECT * FROM wellness_data WHERE player_id = ? AND entry_date >= ?",
        conn, params=(player_id, start_history.strftime('%Y-%m-%d'))
    )
    workload_batch = pd.read_sql_query(
        "SELECT * FROM training_data WHERE player_id = ? AND training_date >= ?",
        conn, params=(player_id, start_history.strftime('%Y-%m-%d'))
    )
    
    wellness_logged_dates = set(wellness_batch['entry_date'].tolist()) if not wellness_batch.empty else set()
    workload_logged_dates = set(workload_batch['training_date'].tolist()) if not workload_batch.empty else set()
    
    history_points = []
    risk_map = {}
    
    for i, d in enumerate(dates):
        d_str = d.strftime('%Y-%m-%d')
        has_data = d_str in wellness_logged_dates or d_str in workload_logged_dates
        
        # Use batch data to compute features
        d_risk = _compute_risk_features(conn, player_id, d, wellness_batch=wellness_batch, workload_batch=workload_batch)
        X_input = pd.DataFrame(d_risk['feature_vec'])
        X_scaled = scaler.transform(X_input)
        probs = model.predict_proba(X_scaled)[0]
        
        score, level = _score_prediction(probs, d_risk)
        
        x = (i / (len(dates) - 1)) * 400 if len(dates) > 1 else 200
        y = 100 - score
        
        drivers = None
        if has_data:
            drivers = {
                "fatigue": int(d_risk.get('fatigue_level', 5)),
                "sleep": int(d_risk.get('sleep_score', 6)),
                "acwr": round(float(d_risk.get('acwr_val', 1.0)), 2)
            }
        
        history_points.append({
            'x': round(x, 1), 'y': round(y, 1), 'risk': score,
            'date': d.strftime('%b %d'), 'full_date': d_str,
            'level': level, 'is_actual': has_data, 'drivers': drivers
        })
        risk_map[d_str] = score

    # Segment construction
    segments = []
    if history_points:
        current_segment = {'type': 'real' if history_points[0]['is_actual'] else 'interpolated', 'points': [history_points[0]]}
        
        gap_count = 0
        for i in range(1, len(history_points)):
            curr = history_points[i]
            
            # Gap detection
            if curr['is_actual']:
                gap_count = 0
            else:
                gap_count += 1
            
            # Determine segment type
            seg_type = 'real'
            if not curr['is_actual']:
                seg_type = 'gap' if gap_count >= 3 else 'interpolated'
            
            if seg_type != current_segment['type']:
                # Close current and start new
                # Add current point to both to ensure continuous lines
                current_segment['points'].append(curr)
                segments.append(current_segment)
                current_segment = {'type': seg_type, 'points': [curr]}
            else:
                current_segment['points'].append(curr)
        
        segments.append(current_segment)

    # Convert segments to SVG paths
    for seg in segments:
        pts = seg['points']
        path = f"M {pts[0]['x']} {pts[0]['y']} "
        for p in pts[1:]:
            path += f"L {p['x']} {p['y']} "
        seg['path'] = path.strip()

    # Labels (Start, Mid, End)
    labels = [""] * 3
    if len(dates) >= 1:
        labels[0] = dates[0].strftime('%b %d')
        labels[1] = dates[len(dates)//2].strftime('%b %d')
        labels[2] = "Today"
    
    return segments, labels, risk_map, history_points

def _generate_analysis_insight(wellness_7d, risk_map):
    """Insight narrative summarizing trends with status coloring."""
    if not risk_map or wellness_7d.empty: 
        return "Insufficient data to generate specific insights.", "gray"
    
    if len(wellness_7d) < 3:
        return "Insight generation limited: Minimum 3 logs required for trend analysis.", "gray"
    
    max_date = max(risk_map, key=risk_map.get)
    max_val = risk_map[max_date]
    
    status = "green"
    if max_val > 65: status = "red"
    elif max_val > 35: status = "yellow"
    
    if max_val < 35:
        msg = "Readiness metrics are stable. Recovery protocol is effectively managing current training loads."
    else:
        msg = f"A peak injury risk of {max_val}% was detected on {pd.to_datetime(max_date).strftime('%b %d')}. Workload spikes may require monitoring."
        
    return msg, status

def _get_default_response(period, msg):
    return {
        "risk_score": 0, "risk_level": "Insufficient Data", "recommendation": msg,
        "days_injury_free": "N/A", "avg_sleep": "0h 0m", "avg_soreness": "0.0/10",
        "history_svg_path": "M0,100 L400,100", "history_labels": [""] * 5,
        "period": period, "history_risk_map": {}, "insight_message": msg,
        "history_points": [], "recommendation_list": []
    }

def get_predictive_logic(risk_score, risk_level, acwr, sleep_quality, muscle_soreness, fatigue_level):
    """Dynamic helper for dashboard info boxes."""
    factors = []
    actions = []
    interpretation = []
    
    # Evaluate ACWR
    if acwr > 1.3:
        factors.append({'label': 'Workload Spike', 'desc': f'ACWR is high ({acwr:.2f}).', 'risk': 'Elevated injury risk.', 'icon': 'trending_up', 'color': 'red-500'})
        actions.append("Reduce training volume by 20-30%.")
    elif 0.3 < acwr < 0.8:
        factors.append({'label': 'Underloading', 'desc': f'ACWR is low ({acwr:.2f}).', 'risk': 'Loss of fitness.', 'icon': 'trending_down', 'color': 'amber-500'})
        actions.append("Gradually increase training load.")
    elif acwr <= 0.3:
        factors.append({'label': 'Off-Load', 'desc': f'ACWR is extremely low ({acwr:.2f}).', 'risk': 'Deconditioning.', 'icon': 'hourglass_empty', 'color': 'slate-500'})
        actions.append("Ensure regular training sessions are actively logged.")
    else:
        factors.append({'label': 'Optimal Load', 'desc': f'ACWR is balanced ({acwr:.2f}).', 'risk': 'Safe zone.', 'icon': 'check_circle', 'color': 'primary'})
        actions.append("Maintain current progression.")
        
    # Evaluate Sleep
    if sleep_quality == 'Poor':
        factors.append({'label': 'Poor Sleep', 'desc': 'Inadequate recovery.', 'risk': 'Impairs recovery.', 'icon': 'bedtime', 'color': 'red-500'})
        actions.append("Prioritize sleep hygiene tonight.")
        
    # Evaluate Fatigue/Soreness
    if fatigue_level >= 8 or muscle_soreness in ['High', 'Severe']:
        factors.append({'label': 'High Fatigue', 'desc': 'Nervous system drained.', 'risk': 'Coordination drops.', 'icon': 'battery_alert', 'color': 'red-500'})
        actions.append("Prioritize active recovery and massage.")
        
    # Interpretation based on risk level
    if risk_level == 'High':
        interpretation.append("Critical risk threshold crossed. Immediate intervention required.")
    elif risk_level == 'Medium':
        if acwr > 1.3 or fatigue_level >= 8:
            interpretation.append("Model indicates moderate risk driven by severe workload spikes or extreme fatigue.")
        else:
            interpretation.append("Moderate risk detected. Monitor load carefully.")
    else:
        interpretation.append("Player is operating in safe parameters.")
            
    if not actions:
        actions.append("Continue daily logging.")

    return {
        'warning': f"Risk Analysis: {risk_level} ({risk_score}%)",
        'interpretation': interpretation,
        'factors': factors,
        'actions': actions
    }
