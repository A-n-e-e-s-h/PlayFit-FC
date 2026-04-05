import sqlite3
import pandas as pd
import numpy as np
import joblib
import os
import shap
import xgboost
from datetime import date, datetime, timedelta

# Paths
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'injury_risk_model.pkl')
SCALER_PATH = os.path.join(os.path.dirname(__file__), 'scaler.pkl')
DB_PATH = os.path.join(os.path.dirname(__file__), '../playfit.db')

def get_player_prediction(player_id, period=30):
    """Fetches the latest data for a player and predicts their injury risk using unified sources."""
    if not os.path.exists(MODEL_PATH) or not os.path.exists(SCALER_PATH):
        return _get_default_response(period, "Model needs training.")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        today = pd.to_datetime('today').normalize()
        # Compute features for Today
        risk_data = _compute_risk_features(conn, player_id, today)
        
        if not risk_data['has_wellness'] and not risk_data['has_workload']:
            return _get_default_response(period, "Insufficient data for prediction. Please complete your daily wellness check-in and log your recent sessions.")
        
        # Load Model & Predict
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        X_input = pd.DataFrame(risk_data['feature_vec'])
        X_scaled = scaler.transform(X_input)
        probabilities = model.predict_proba(X_scaled)[0]
        
        # Risk Score Calculation (0-100)
        if len(probabilities) == 3:
            risk_probability_score = (probabilities[1] * 0.4 + probabilities[2] * 1.0)
        else:
            risk_probability_score = probabilities[1] if len(probabilities) > 1 else 0.0
        
        risk_score = min(int(risk_probability_score * 100), 100)
        
        # Determine Risk Level
        if risk_score > 65: risk_level = "High"
        elif risk_score > 35: risk_level = "Medium"
        else: risk_level = "Low"
        
        # Hard overrides for cross-validation safety
        if risk_data.get('acwr_val', 0) > 1.3 or risk_data.get('fatigue_level', 0) >= 8:
            if risk_level == "Low":
                risk_level = "Medium"
                risk_score = max(risk_score, 40)
        
        # Confidence warning based on data availability
        confidence_suffix = ""
        if not risk_data['has_workload']: confidence_suffix = " (Wellness-only)"
        elif not risk_data['has_wellness']: confidence_suffix = " (Workload-only)"
        
        risk_level_display = risk_level + confidence_suffix

        # Explainability (SHAP)
        top_factors, explanation = _generate_shap_explanation(model, X_scaled, X_input.columns)
        
        # Alert Engine (Checks and Triggers)
        _check_and_trigger_alerts(conn, player_id, risk_score, risk_data)
        
        # Return full payload
        return _build_prediction_payload(conn, player_id, risk_score, risk_level, risk_level_display, period, model, scaler, risk_data, top_factors, explanation)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Prediction Error for player {player_id}: {e}")
        return _get_default_response(period, f"Prediction error: {str(e)}")
    finally:
        conn.close()

def _compute_risk_features(conn, player_id, target_date):
    """Unified helper to calculate the 17-feature vector for a specific date (Expanded to 19+)."""
    target_date = pd.to_datetime(target_date).normalize()
    past_7 = target_date - pd.Timedelta(days=7)
    past_14 = target_date - pd.Timedelta(days=14)
    past_28 = target_date - pd.Timedelta(days=28)
    
    # 0. Fetch Player Profile
    player_df = pd.read_sql_query(
        "SELECT age, position, experience_years FROM players WHERE player_id = ?",
        conn, params=(player_id,)
    )
    age = player_df.iloc[0]['age'] if not player_df.empty else 25
    exp = player_df.iloc[0]['experience_years'] if not player_df.empty else 5
    pos_raw = player_df.iloc[0]['position'] if not player_df.empty else 'Midfielder'
    
    # Simple encoding for position (could be one-hot, but for now we'll map to numeric 1-4)
    pos_map = {'Forward': 4, 'Midfielder': 3, 'Defender': 2, 'Goalkeeper': 1}
    position_encoded = pos_map.get(pos_raw, 3)

    # 1. Fetch Latest Wellness & Trends
    wellness_df = pd.read_sql_query(
        "SELECT * FROM wellness_data WHERE player_id = ? AND entry_date <= ? ORDER BY entry_date DESC LIMIT 1", 
        conn, params=(player_id, target_date.strftime('%Y-%m-%d'))
    )
    has_wellness = not wellness_df.empty
    
    # Trends (7-day moving averages)
    wellness_7d = pd.read_sql_query(
        "SELECT fatigue_level, sleep_quality, muscle_soreness FROM wellness_data WHERE player_id = ? AND entry_date >= ? AND entry_date <= ?",
        conn, params=(player_id, past_7.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
    )
    
    # 2. Fetch Workload (Technical & Tactical)
    workload_df = pd.read_sql_query(
        "SELECT * FROM training_data WHERE player_id = ? AND session_type = 'Technical & Tactical' AND training_date >= ? AND training_date <= ?",
        conn, params=(player_id, past_28.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
    )
    
    # 3. Fetch Match Details
    match_df = pd.read_sql_query(
        "SELECT * FROM training_data WHERE player_id = ? AND session_type = 'Match Details' AND training_date >= ? AND training_date <= ?",
        conn, params=(player_id, past_7.strftime('%Y-%m-%d'), target_date.strftime('%Y-%m-%d'))
    )
    
    # Data presence indicator
    has_workload = (not workload_df.empty and workload_df[workload_df['training_date'] >= past_7.strftime('%Y-%m-%d')]['training_minutes'].sum() > 0) or \
                   (not match_df.empty and match_df['training_minutes'].sum() > 0)
    
    # Feature Mappings
    sleep_map = {'Poor': 3, 'Average': 6, 'Good': 9}
    soreness_map = {'Low': 2, 'Medium': 5, 'High': 8}
    intensity_map = {'Low': 1, 'Medium': 2, 'High': 3}
    
    # Current wellness
    if has_wellness:
        sleep_score = sleep_map.get(wellness_df.iloc[0]['sleep_quality'], 6)
        soreness_score = soreness_map.get(wellness_df.iloc[0]['muscle_soreness'], 5)
        try: fatigue_level = int(wellness_df.iloc[0]['fatigue_level'])
        except: fatigue_level = 5
    else:
        sleep_score, soreness_score, fatigue_level = 6, 5, 5 # Defaults

    # Trend calculation
    fatigue_trend = float(wellness_7d['fatigue_level'].astype(float).mean()) if not wellness_7d.empty else 5.0
    sleep_trend = float(wellness_7d['sleep_quality'].map(sleep_map).mean()) if not wellness_7d.empty else 6.0
    soreness_trend = float(wellness_7d['muscle_soreness'].map(soreness_map).mean()) if not wellness_7d.empty else 5.0

    # Workload Aggregates (Acute=7d)
    tech_7 = workload_df[workload_df['training_date'] >= past_7.strftime('%Y-%m-%d')] if not workload_df.empty else pd.DataFrame()
    training_minutes = int(tech_7['training_minutes'].sum()) if not tech_7.empty else 0
    sessions_per_week = len(tech_7)
    
    intensity_scores = tech_7['intensity'].map(intensity_map).fillna(2) if not tech_7.empty else pd.Series([2.0])
    training_intensity = float(intensity_scores.mean()) if not tech_7.empty else 2.0
    
    minutes_played = int(match_df['training_minutes'].sum()) if not match_df.empty else 0
    matches_per_week = len(match_df)
    
    # Previous week workload for spike detection
    prev_week_df = workload_df[(workload_df['training_date'] >= past_14.strftime('%Y-%m-%d')) & (workload_df['training_date'] < past_7.strftime('%Y-%m-%d'))]
    prev_week_load = prev_week_df['training_minutes'].sum() if not prev_week_df.empty else 1.0
    workload_spike = (training_minutes + 1) / (prev_week_load + 1)

    # 4. Injury Features (Expanded)
    injury_hist_df = pd.read_sql_query(
        "SELECT * FROM injury_history WHERE player_id = ? AND injury_date <= ? ORDER BY injury_date DESC", 
        conn, params=(player_id, target_date.strftime('%Y-%m-%d'))
    )
    
    previous_injury_count = len(injury_hist_df)
    avg_recovery_days = float(injury_hist_df['recovery_days'].mean()) if not injury_hist_df.empty else 0.0
    
    latest_inj_dt = None
    recovery_days = 0
    if not injury_hist_df.empty:
        latest_inj_dt = pd.to_datetime(injury_hist_df.iloc[0]['injury_date'])
        recovery_days = int(injury_hist_df.iloc[0].get('recovery_days', 14))
        
    days_since_last_injury = 365
    previous_injury = 0
    if latest_inj_dt is not None:
        days_since_last_injury = (target_date - latest_inj_dt).days
        previous_injury = 1 if days_since_last_injury < 60 else 0

    # Recency features
    training_recency = 7
    if not workload_df.empty:
        training_recency = (target_date - pd.to_datetime(workload_df['training_date'].max())).days
        
    match_load_frequency = 14
    if not match_df.empty:
        match_load_frequency = (target_date - pd.to_datetime(match_df['training_date'].max())).days

    # Advanced Calculations
    acute_load = training_minutes + minutes_played
    total_chronic_minutes = workload_df['training_minutes'].sum() if not workload_df.empty else 160.0
    chronic_load = max(total_chronic_minutes / 4.0, 1.0) # baseline of weekly load
    acwr_val = acute_load / chronic_load
    
    recovery_score = sleep_score - soreness_score
    load_ratio = training_minutes / (minutes_played + 1.0)
    injury_risk_factor = previous_injury * recovery_days

    # EXPANDED Feature Vector CONSTRUCTION (25 features)
    feature_vec = {
        'age': [age],
        'position_encoded': [position_encoded],
        'experience_years': [exp],
        'minutes_played': [minutes_played],
        'matches_per_week': [matches_per_week],
        'training_minutes': [training_minutes],
        'training_intensity': [training_intensity],
        'sessions_per_week': [sessions_per_week],
        'fatigue_level': [fatigue_level],
        'muscle_soreness': [soreness_score],
        'sleep_quality': [sleep_score],
        'fatigue_trend': [fatigue_trend],
        'sleep_trend': [sleep_trend],
        'soreness_trend': [soreness_trend],
        'workload_spike': [workload_spike],
        'previous_injury_count': [previous_injury_count],
        'avg_recovery_days': [avg_recovery_days],
        'previous_injury': [previous_injury],
        'recovery_days': [recovery_days],
        'days_since_last_injury': [days_since_last_injury],
        'training_recency': [training_recency],
        'match_load_frequency': [match_load_frequency],
        'ACWR': [acwr_val],
        'recovery_score': [recovery_score],
        'load_ratio': [load_ratio],
        'injury_risk_factor': [injury_risk_factor]
    }
    
    return {
        'feature_vec': feature_vec,
        'has_wellness': has_wellness,
        'has_workload': has_workload,
        'wellness_df': wellness_df,
        'sleep_score': sleep_score,
        'soreness_score': soreness_score,
        'fatigue_level': fatigue_level,
        'acwr_val': acwr_val,
        'days_since_last_injury': days_since_last_injury
    }

def _build_prediction_payload(conn, player_id, risk_score, risk_level, risk_level_display, period, model, scaler, risk_data, top_factors=[], explanation=""):
    # Dynamic Recommendations based on risk status
    recommendation_list = []
    if risk_level == "High":
        rec = explanation if explanation else "Rest recommended. High combined injury risk detected based on load and recovery metrics."
        recommendation_list.append({'title': 'High Priority', 'description': 'Complete rest or low-impact active recovery session.', 'icon': 'warning', 'bg_class': 'bg-orange-500/10 border-orange-500/20', 'text_class': 'text-orange-500'})
    elif risk_level == "Medium":
        rec = explanation if explanation else "Monitor load. Focus on active recovery and reduce training intensity by 30%."
        recommendation_list.append({'title': 'Moderate Risk', 'description': 'Limit high-speed drills and impact today.', 'icon': 'warning', 'bg_class': 'bg-orange-500/10 border-orange-500/20', 'text_class': 'text-orange-500'})
    else:
        rec = "Optimal condition. Cleared for full participation in match and technical drills."
        recommendation_list.append({'title': 'Optimal Status', 'description': 'Ready for peak intensity loading.', 'icon': 'check_circle', 'bg_class': 'bg-primary/10 border-primary/20', 'text_class': 'text-primary'})

    # Secondary health-based recommendations
    if risk_data['soreness_score'] >= 7 or risk_data['fatigue_level'] >= 7:
        recommendation_list.append({'title': 'Mobility Focus', 'description': '15m foam rolling and dynamic joint prep required.', 'icon': 'fitness_center', 'bg_class': 'bg-primary/10 border-primary/20', 'text_class': 'text-primary'})
    else:
        recommendation_list.append({'title': 'Maintenance', 'description': 'Continue standard hydration and stretching protocol.', 'icon': 'fitness_center', 'bg_class': 'bg-primary/10 border-primary/20', 'text_class': 'text-primary'})

    # Chart History Integration
    svg_path, svg_labels, risk_map, points = _calculate_risk_history_svg(conn, player_id, model, scaler, days=period)
    insight_msg = _generate_analysis_insight(risk_data['wellness_df'], risk_map)
    
    # Averages formatting
    avg_sleep_h = 7.0 if risk_data['wellness_df'].empty else {'Poor': 5, 'Average': 7, 'Good': 8.5}.get(risk_data['wellness_df'].iloc[0]['sleep_quality'], 7)
    avg_sleep_str = f"{int(avg_sleep_h)}h {int((avg_sleep_h%1)*60)}m"
    avg_soreness_str = f"{risk_data['soreness_score']:.1f}/10"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level_display,
        "recommendation": rec,
        "top_factors": top_factors,
        "explanation": explanation,
        "days_injury_free": f"{risk_data['days_since_last_injury']} Days" if risk_data['days_since_last_injury'] < 365 else "No Injuries Recorded",
        "avg_sleep": avg_sleep_str,
        "avg_soreness": avg_soreness_str,
        "history_svg_path": svg_path,
        "history_labels": svg_labels,
        "period": period,
        "history_risk_map": risk_map,
        "insight_message": insight_msg,
        "history_points": points,
        "recommendation_list": recommendation_list
    }

def _generate_shap_explanation(model, X_scaled, feature_names):
    """Calculates SHAP values to identify top contributors to risk."""
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
            'feature': name.replace('_', ' ').title(),
            'impact': impact
        })
        
    # Sort by absolute impact (the magnitude of influence)
    sorted_factors = sorted(feature_impacts, key=lambda x: abs(x['impact']), reverse=True)
    top_3 = sorted_factors[:3]
    
    # Generate human readable description
    high_impact_factors = [f for f in top_3 if f['impact'] > 0.05]
    if not high_impact_factors:
        explanation = "Metrics are within safe ranges. No single acute risk factor dominant."
    else:
        reasons = [f"{f['feature']}" for f in high_impact_factors]
        explanation = f"Injury risk is elevated primarily due to {', '.join(reasons)}."
        
    # Format impact values for display
    for f in top_3:
        f['impact_str'] = f"{'+' if f['impact'] > 0 else ''}{f['impact']:.2f}"
        # Calculate visual bar width (max 100%)
        f['width_pct'] = min(int(abs(f['impact']) * 200), 100)
        
    return top_3, explanation

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
    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    
    for alert in active_alerts:
        existing = conn.execute('''
            SELECT id FROM notifications 
            WHERE player_id = ? AND message LIKE ? AND created_at > ?
            LIMIT 1
        ''', (player_id, f'%{alert["type"]}%', cutoff)).fetchone()
        
        if not existing:
            # Insert new notification
            full_msg = f"[{alert['prio']} Alert] {alert['msg']}"
            conn.execute('''
                INSERT INTO notifications (player_id, message, is_read, created_at)
                VALUES (?, ?, 0, datetime('now'))
            ''', (player_id, full_msg))
            conn.commit()

def _calculate_risk_history_svg(conn, player_id, model, scaler, days=30):
    """Generates the history graph by sampling risk points over the recent period."""
    today = pd.to_datetime('today').normalize()
    # Sample points to balance performance with visual detail (e.g., every 5 days for a 30-day chart)
    sample_interval = max(1, days // 6)
    dates = [today - pd.Timedelta(days=i) for i in range(days, -1, -sample_interval)]
    dates.sort()
    
    risk_scores = []
    risk_map = {}
    
    for d in dates:
        d_risk = _compute_risk_features(conn, player_id, d)
        X_input = pd.DataFrame(d_risk['feature_vec'])
        X_scaled = scaler.transform(X_input)
        probs = model.predict_proba(X_scaled)[0]
        
        if len(probs) == 3:
            score = min(int((probs[1] * 0.4 + probs[2] * 1.0) * 100), 100)
        else:
            score = int(probs[1]*100) if len(probs)>1 else 0
            
        risk_scores.append(score)
        risk_map[d.strftime('%Y-%m-%d')] = score

    # SVG geometry
    points = []
    path_str = ""
    for i, s in enumerate(risk_scores):
        x = (i / (len(risk_scores)-1)) * 400 if len(risk_scores) > 1 else 200
        y = 100 - s
        path_str += f"{'M' if i==0 else 'L'}{x:.1f},{y:.1f} "
        points.append({'x': x, 'y': y, 'risk': s})
    
    # Labels (Start, Middle, End)
    labels = [""] * 5
    if len(dates) >= 1:
        labels[0] = dates[0].strftime('%b %d')
        labels[2] = dates[len(dates)//2].strftime('%b %d')
        labels[4] = "Today"
    
    return path_str.strip(), labels, risk_map, points

def _generate_analysis_insight(wellness_df, risk_map):
    """Insight narrative summarizing trends."""
    if not risk_map: return "No historical data available for insight."
    
    max_date = max(risk_map, key=risk_map.get)
    max_val = risk_map[max_date]
    
    if max_val < 30:
        return "Team readiness metrics are stable. Recovery protocol is effectively managing current training loads."
    return f"A peak injury risk of {max_val}% was detected on {max_date}. Physiological indicators suggest recent workload spikes may requiring monitoring."

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
