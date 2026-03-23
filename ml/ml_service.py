import sqlite3
import pandas as pd
import numpy as np
import joblib
import os

# Using the correct model path based on where train_model.py saved it
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'injury_risk_model.pkl')
DB_PATH = os.path.join(os.path.dirname(__file__), '../playfit.db')

def get_player_prediction(player_id, period=30):
    """Fetches the latest data for a player and predicts their injury risk."""
    
    if not os.path.exists(MODEL_PATH):
        # Model not trained yet
        return {
            "risk_score": 0, 
            "risk_level": "Unknown", 
            "recommendation": "Model needs training.",
            "days_injury_free": "Days",
            "avg_sleep": "",
            "avg_soreness": "0.0/10",
            "history_svg_path": "M0,100 L400,100",
            "history_labels": [""] * 5,
            "history_labels": [""] * 5,
            "period": period,
            "history_risk_map": {},
            "insight_message": "Not enough data to form an insight yet.",
            "history_points": []
        }
    
    model = joblib.load(MODEL_PATH)
    conn = sqlite3.connect(DB_PATH)
    
    # Get latest wellness entry
    wellness_df = pd.read_sql_query(
        "SELECT * FROM wellness_data WHERE player_id = ? ORDER BY entry_date DESC LIMIT 1", 
        conn, params=(player_id,)
    )
    
    if len(wellness_df) == 0:
        conn.close()
        return {
            "risk_score": 0, 
            "risk_level": "Low", 
            "recommendation": "Not enough check-in data. Please complete a daily check-in.",
            "days_injury_free": "Days",
            "avg_sleep": "",
            "avg_soreness": "0.0/10",
            "history_svg_path": "M0,100 L400,100",
            "history_labels": [""] * 5,
            "period": period,
            "history_risk_map": {},
            "insight_message": "Not enough data to form an insight yet.",
            "history_points": []
        }
        
    # Fetch player's age
    player_df = pd.read_sql_query("SELECT age FROM players WHERE player_id = ?", conn, params=(player_id,))
    player_age = player_df.iloc[0]['age'] if not player_df.empty else 25 # Default 25
    if pd.isna(player_age) or player_age is None:
        player_age = 25

    latest_date = pd.to_datetime(wellness_df.iloc[0]['entry_date'])
    
    # Get last 28 days of training load relative to that wellness entry
    past_28_days = latest_date - pd.Timedelta(days=28)
    training_df = pd.read_sql_query(
        "SELECT * FROM training_data WHERE player_id = ? AND training_date >= ? AND training_date <= ?",
        conn, params=(player_id, past_28_days.strftime('%Y-%m-%d'), latest_date.strftime('%Y-%m-%d'))
    )
    
    # Match Data
    past_7_days = latest_date - pd.Timedelta(days=7)
    match_df = pd.read_sql_query(
        "SELECT * FROM match_data WHERE player_id = ? AND match_date >= ? AND match_date <= ?",
        conn, params=(player_id, past_7_days.strftime('%Y-%m-%d'), latest_date.strftime('%Y-%m-%d'))
    )
    
    # Formatting features
    sleep_map = {'Poor': 3, 'Average': 6, 'Good': 9}
    soreness_map = {'Low': 2, 'Medium': 5, 'High': 8}
    intensity_map = {'Low': 1, 'Medium': 2, 'High': 3}
    
    sleep_score = sleep_map.get(wellness_df.iloc[0]['sleep_quality'], 6)
    soreness_score = soreness_map.get(wellness_df.iloc[0]['muscle_soreness'], 5)
    try:
        fatigue_level = int(wellness_df.iloc[0]['fatigue_level'])
    except (ValueError, TypeError):
        fatigue_level = 5
    
    # Match features
    matches_per_week = 0
    minutes_played = 0
    if not match_df.empty:
        matches_per_week = len(match_df)
        minutes_played = match_df['minutes_played'].sum()

    # Training features
    sessions_per_week = 0
    training_minutes = 0
    training_intensity = 2.0
    if not training_df.empty:
        training_df['training_date'] = pd.to_datetime(training_df['training_date'])
        training_df['intensity_score'] = training_df['intensity'].map(intensity_map).fillna(2)
        
        acute_df = training_df[training_df['training_date'] >= past_7_days]
        sessions_per_week = len(acute_df)
        if sessions_per_week > 0:
            training_minutes = acute_df['training_minutes'].sum()
            training_intensity = acute_df['intensity_score'].mean()

    # Create feature vector corresponding to injury_risk_dataset_300_rows.csv
    feature_vec = {
        'minutes_played': [minutes_played],
        'matches_per_week': [matches_per_week],
        'training_minutes': [training_minutes],
        'training_intensity': [training_intensity],
        'sessions_per_week': [sessions_per_week],
        'fatigue_level': [fatigue_level],
        'muscle_soreness': [soreness_score],
        'sleep_quality': [sleep_score]
    }
    
    X_input = pd.DataFrame(feature_vec)

    # Predict Probability of Injury Classes [0=Low, 1=Medium, 2=High]
    probabilities = model.predict_proba(X_input)[0]
    
    # Calculate a composite scalar risk (0-100) weighting High vs Medium
    if len(probabilities) == 3:
        risk_probability = probabilities[1] * 0.5 + probabilities[2] * 1.0
    elif len(probabilities) == 2:
        risk_probability = probabilities[1]
    else:
        risk_probability = 1.0 if model.classes_[0] in [1, 2] else 0.0
        
    risk_score = min(int(risk_probability * 100), 100)
    
    # Determine level and recommendation
    if risk_score < 35:
        risk_level = "Low"
        rec = "You are in good form. Continue normal training load."
    elif risk_score < 65:
        risk_level = "Medium"
        rec = "Moderate risk. Consider reducing intensity and focusing on recovery."
    else:
        risk_level = "High"
        rec = "High injury risk detected! Rest highly recommended. Skip intense training."
        
    # Calculate Days Injury Free
    conn = sqlite3.connect(DB_PATH)
    injury_df = pd.read_sql_query(
        "SELECT injury_date FROM injury_history WHERE player_id = ? ORDER BY injury_date DESC LIMIT 1", 
        conn, params=(player_id,)
    )
    
    today_date = pd.to_datetime('today').normalize()
    if not injury_df.empty:
        last_injury_date = pd.to_datetime(injury_df.iloc[0]['injury_date']).normalize()
        days_injury_free = (today_date - last_injury_date).days
        if days_injury_free < 0:
             days_injury_free = 0 # in case of future dated test data
    else:
        # If no injuries logged, we could use the account creation date, 
        # but for now we'll just set a high default or 90 to look good
        days_injury_free = 90
        
    # Calculate Average Sleep/Soreness over selected period relative to current wellness 
    past_days_str = (today_date - pd.Timedelta(days=period)).strftime('%Y-%m-%d')
    recent_wellness_df = pd.read_sql_query(
        "SELECT * FROM wellness_data WHERE player_id = ? AND entry_date >= ?", 
        conn, params=(player_id, past_days_str)
    )
    conn.close()

    avg_sleep_str = "0h 0m"
    if not recent_wellness_df.empty:
        # Approximate mappings based on categories
        sleep_hours_map = {'Poor': 4.5, 'Average': 6.5, 'Good': 8.5}
        recent_wellness_df['hours'] = recent_wellness_df['sleep_quality'].map(sleep_hours_map).fillna(6.5)
        avg_hours = recent_wellness_df['hours'].mean()
        
        # Convert decimal hours to hours and minutes
        h = int(avg_hours)
        m = int((avg_hours - h) * 60)
        avg_sleep_str = f"{h}h {m}m"

        soreness_map = {'Low': 2.0, 'Medium': 5.0, 'High': 8.0}
        recent_wellness_df['soreness_num'] = recent_wellness_df['muscle_soreness'].map(soreness_map).fillna(2.0)
        avg_soreness = recent_wellness_df['soreness_num'].mean()
        avg_soreness_str = f"{avg_soreness:.1f}/10"
    else:
        avg_soreness_str = "0.0/10"

    # --- SVG Chart History (Last period Days) ---
    svg_path, svg_labels, risk_map, points = _calculate_risk_history_svg(conn_reopen=True, player_id=player_id, model=model, days=period)

    # Generate Dynamic Insight
    insight_msg = _generate_analysis_insight(recent_wellness_df, risk_map)

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recommendation": rec,
        "days_injury_free": days_injury_free,
        "avg_sleep": avg_sleep_str,
        "avg_soreness": avg_soreness_str,
        "history_svg_path": svg_path,
        "history_labels": svg_labels,
        "period": period,
        "history_risk_map": risk_map,
        "insight_message": insight_msg,
        "history_points": points
    }

def _calculate_risk_history_svg(conn_reopen, player_id, model, days=30):
    conn = sqlite3.connect(DB_PATH)
    
    player_df = pd.read_sql_query("SELECT age FROM players WHERE player_id = ?", conn, params=(player_id,))
    player_age = player_df.iloc[0]['age'] if not player_df.empty else 25
    if pd.isna(player_age) or player_age is None: player_age = 25

    today = pd.to_datetime('today').normalize()
    start_date = today - pd.Timedelta(days=days)
    
    wellness_df = pd.read_sql_query(
        "SELECT * FROM wellness_data WHERE player_id = ? AND entry_date >= ? ORDER BY entry_date ASC",
        conn, params=(player_id, start_date.strftime('%Y-%m-%d'))
    )
    
    training_start = start_date - pd.Timedelta(days=28)
    training_df = pd.read_sql_query(
        "SELECT * FROM training_data WHERE player_id = ? AND training_date >= ?",
        conn, params=(player_id, training_start.strftime('%Y-%m-%d'))
    )
    match_df = pd.read_sql_query(
        "SELECT * FROM match_data WHERE player_id = ? AND match_date >= ?",
        conn, params=(player_id, training_start.strftime('%Y-%m-%d'))
    )
    conn.close()
    
    if wellness_df.empty:
        return "M0,100 L400,100", [""] * 5, {}, []
        
    training_df['training_date'] = pd.to_datetime(training_df['training_date'])
    if not match_df.empty:
        match_df['match_date'] = pd.to_datetime(match_df['match_date'])

    intensity_map = {'Low': 1, 'Medium': 2, 'High': 3}
    if not training_df.empty:
        training_df['intensity_score'] = training_df['intensity'].map(intensity_map).fillna(2)
        
    sleep_map = {'Poor': 3, 'Average': 6, 'Good': 9}
    soreness_map = {'Low': 2, 'Medium': 5, 'High': 8}
    
    risk_scores = []
    dates = []
    risk_map = {}
    
    for _, row in wellness_df.iterrows():
        current_date = pd.to_datetime(row['entry_date'])
        dates.append(current_date)
        
        sleep_score = sleep_map.get(row['sleep_quality'], 6)
        soreness_score = soreness_map.get(row['muscle_soreness'], 5)
        try:
            fatigue_level = int(row['fatigue_level'])
        except (ValueError, TypeError):
            fatigue_level = 5
        
        past_7 = current_date - pd.Timedelta(days=7)
        
        sessions_per_week = 0
        training_minutes = 0
        training_intensity = 2.0
        
        if not training_df.empty:
            recent_7_train = training_df[(training_df['training_date'] < current_date) & (training_df['training_date'] >= past_7)]
            sessions_per_week = len(recent_7_train)
            if sessions_per_week > 0:
                training_minutes = recent_7_train['training_minutes'].sum()
                training_intensity = recent_7_train['intensity_score'].mean()
                
        matches_per_week = 0
        minutes_played = 0
        
        if not match_df.empty:
            recent_7_match = match_df[(match_df['match_date'] < current_date) & (match_df['match_date'] >= past_7)]
            matches_per_week = len(recent_7_match)
            if matches_per_week > 0:
                minutes_played = recent_7_match['minutes_played'].sum()
                
        feature_vec = {
            'minutes_played': [minutes_played],
            'matches_per_week': [matches_per_week],
            'training_minutes': [training_minutes],
            'training_intensity': [training_intensity],
            'sessions_per_week': [sessions_per_week],
            'fatigue_level': [fatigue_level],
            'muscle_soreness': [soreness_score],
            'sleep_quality': [sleep_score]
        }
        
        X_input = pd.DataFrame(feature_vec)
        
        probabilities = model.predict_proba(X_input)[0]
        if len(probabilities) == 3:
            risk_probability = probabilities[1] * 0.5 + probabilities[2] * 1.0
        elif len(probabilities) == 2:
            risk_probability = probabilities[1]
        else:
            risk_probability = 1.0 if model.classes_[0] in [1, 2] else 0.0
            
        risk_score = min(int(risk_probability * 100), 100)
        risk_scores.append(risk_score)
        risk_map[row['entry_date']] = risk_score

    points = []
    if len(risk_scores) == 1:
        y = 100 - risk_scores[0]
        path_str = f"M0,{y} L400,{y}"
        points = [{'x': 0, 'y': y, 'risk': risk_scores[0]}, {'x': 400, 'y': y, 'risk': risk_scores[0]}]
    else:
        path_str = ""
        for i, score in enumerate(risk_scores):
            x = (i / (len(risk_scores) - 1)) * 400
            y = 100 - score
            path_str += f"{'M' if i==0 else 'L'}{x:.1f},{y:.1f} "
            points.append({'x': x, 'y': y, 'risk': score})
                
    if len(dates) == 0:
        labels = [""] * 5
    elif len(dates) == 1:
        labels = ["", "", dates[0].strftime('%b %d'), "", ""]
    else:
        start_d, end_d = dates[0], dates[-1]
        delta = (end_d - start_d) / 4
        labels = []
        last_d = ""
        for i in range(5):
            d_str = (start_d + delta * i).strftime('%b %d')
            if d_str == last_d:
                labels.append("")
            else:
                labels.append(d_str)
                last_d = d_str
        if end_d.normalize() == today:
            labels[-1] = "Today"

    return path_str.strip(), labels, risk_map, points

def _generate_analysis_insight(wellness_df, risk_map):
    """Generates a dynamic narrative correlating high risk days with their underlying wellness metrics."""
    if wellness_df.empty or not risk_map:
        return "Keep logging your daily wellness check-ins to build enough data for analytical insights."
        
    # Find the day with the highest risk in the current map
    max_risk_date_str = max(risk_map, key=risk_map.get)
    max_risk = risk_map[max_risk_date_str]
    
    if max_risk < 20:
        return "Your readiness scores have been optimal across the selected period. Recovery is tracking perfectly with no significant physiological red flags. Maintain current load progression."
    
    # Locate the row for that specific day
    spike_row = wellness_df[wellness_df['entry_date'] == max_risk_date_str]
    if spike_row.empty:
        # Fallback if somehow date mismatch
        return f"A spike in injury risk ({max_risk}%) was detected around {max_risk_date_str}. Ensure adequate rest and monitor your training loads closely."
        
    spike_row = spike_row.iloc[0]
    date_obj = pd.to_datetime(max_risk_date_str)
    date_formatted = date_obj.strftime("%b %d")
    
    # Identify contributing factors
    factors: list[str] = []
    if spike_row['sleep_quality'] == 'Poor':
        factors.append("a significant drop in sleep quality")
    elif spike_row['sleep_quality'] == 'Average' and max_risk > 35:
         factors.append("sub-optimal sleep")
         
    if spike_row['muscle_soreness'] == 'High':
        factors.append("peak muscle soreness")
        
    if spike_row['fatigue_level'] >= 7:
        factors.append(f"accumulated fatigue levels ({spike_row['fatigue_level']}/10)")
        
    # Construct the sentence
    if not factors:
        message = f"The recent risk spike on <span class='text-primary font-bold'>{date_formatted}</span> ({max_risk}%) was primarily driven by cumulative training load dynamics. "
    else:
        factors_str = " and ".join(factors)
        message = f"The recent spike on <span class='text-primary font-bold'>{date_formatted}</span> correlates with {factors_str}. "
        
    # Add actionable advice based on severity
    if max_risk >= 70:
        message += f"Ensure recovery protocols are strictly followed indefinitely to mitigate this critical {max_risk}% calculated risk level."
    elif max_risk >= 35:
        message += f"Please monitor your training intensities for the next 48 hours to mitigate the {max_risk}% calculated risk."
    else:
        message += f"Small preventative measures like extra stretching will help completely clear the minor {max_risk}% risk."
        
    return message

def get_predictive_logic(risk_score, risk_level, acwr, sleep_quality, muscle_soreness, fatigue_level):
    """
    Generates structured logic for the Player Management dashboard.
    Returns a dictionary with 'warning', 'interpretation', 'factors', and 'actions'.
    """
    # 1. Warning & Interpretation
    try:
        fatigue_num = int(fatigue_level)
    except (ValueError, TypeError):
        fatigue_num = 5

    warning = f"High Acute-to-Chronic ratio ({acwr:.2f})"
    if sleep_quality == 'Poor' or fatigue_num > 7:
        warning += " + Poor recovery metrics"
    
    warning += f" → Elevated {risk_level} risk"
    
    interpretation = []
    if acwr > 1.3:
        interpretation.append("Training load increased quickly")
    if sleep_quality == 'Poor' or fatigue_num > 7:
        interpretation.append("Player recovery is poor")
    if risk_score > 50:
        interpretation.append("Significant physiological red flags detected")
    else:
        interpretation.append("General baseline indicators are stable")

    # 2. Contributing Factors
    factors = []
    if acwr > 1.3:
        factors.append({
            'label': 'Training Load Spike',
            'desc': f'Workload ratio of {acwr:.2f} (optimal is 0.8-1.3).',
            'risk': 'Muscle overload and soft tissue strain.',
            'icon': 'arrow_upward',
            'color': 'rose-500'
        })
    
    if sleep_quality == 'Poor' or fatigue_num > 7:
        factors.append({
            'label': 'Low Recovery Score',
            'desc': f'Sleep is {sleep_quality} and fatigue is {fatigue_num}/10.',
            'risk': 'Reduced muscle repair and cognitive focus.',
            'icon': 'arrow_downward',
            'color': 'rose-500'
        })
    
    if risk_score > 60:
        factors.append({
            'label': 'Predicted Risk Spike',
            'desc': f'ML model detects {risk_score}% injury probability.',
            'risk': 'Imminent risk of non-contact injury.',
            'icon': 'report',
            'color': 'amber-500'
        })
    elif not factors:
        factors.append({
            'label': 'Stable Baseline',
            'desc': 'All metrics are within expected ranges.',
            'risk': 'Low probability of recurring issues.',
            'icon': 'check_circle',
            'color': 'primary'
        })

    # 3. Actions
    actions = []
    if acwr > 1.5 or risk_score > 70:
        actions = ["Mandatory Rest Day", "Immediate Physio Assessment", "Limit Speed to 60%", "Avoid Sprint Drills"]
    elif acwr > 1.3 or risk_score > 40:
        actions = ["Reduce training intensity", "Contrast therapy (Ice/Heat)", "Monitor recovery tonight", "No high-speed sprints"]
    else:
        actions = ["Standard training load", "Post-session maintenance", "Quality sleep focus", "Routine hydration"]

    return {
        'warning': warning,
        'interpretation': interpretation,
        'factors': factors,
        'actions': actions
    }
