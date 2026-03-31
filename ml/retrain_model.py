import sqlite3
import pandas as pd
import numpy as np
import joblib
import os
import shap
from datetime import datetime, timedelta
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
import ml_service

# Configuration
DB_PATH = os.path.join(os.path.dirname(__file__), '../playfit.db')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

def extract_and_prepare_data():
    """
    Scans the database for historical (player, date) samples to create an ML dataset.
    Target (y): 1 if an injury was recorded within the following 7 days.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 1. Identity all unique (player, date) pairs with at least some activity
    samples = conn.execute('''
        SELECT player_id, entry_date as sample_date FROM wellness_data
        UNION
        SELECT player_id, training_date as sample_date FROM training_data
    ''').fetchall()
    
    X_list = []
    y_list = []
    
    print(f"Total historical samples found: {len(samples)}")
    
    for i, row in enumerate(samples):
        pid = row['player_id']
        s_date = row['sample_date']
        dt_obj = pd.to_datetime(s_date)
        
        # Calculate features using the unified logic in ml_service
        try:
            risk_data = ml_service._compute_risk_features(conn, pid, dt_obj)
            feature_row = pd.DataFrame(risk_data['feature_vec'])
            
            # Determine Label: Was there an injury in [T, T+7] days?
            label_query = '''
                SELECT injury_id FROM injury_history 
                WHERE player_id = ? AND injury_date > ? AND injury_date <= ?
                LIMIT 1
            '''
            injury_event = conn.execute(label_query, (pid, s_date, (dt_obj + timedelta(days=7)).strftime('%Y-%m-%d'))).fetchone()
            
            X_list.append(feature_row)
            y_list.append(1 if injury_event else 0)
            
            if i % 100 == 0:
                print(f"Processed {i} samples...")
                
        except Exception as e:
            print(f"Skip sample {pid}/{s_date}: {e}")
            continue
            
    conn.close()
    
    if not X_list:
        return None, None
        
    X_full = pd.concat(X_list, ignore_index=True)
    y_full = np.array(y_list)
    
    return X_full, y_full

def train_new_model(X, y):
    """Trains an XGBoost model and saves both the model and the scaler."""
    if X is None or len(X) < 10:
        print("Not enough data to train. Need at least 10 samples.")
        return False
        
    print(f"Starting training with {len(X)} samples. Injury rate: {np.mean(y):.2%}")
    
    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # XGBoost
    model = XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
        use_label_encoder=False,
        eval_metric='logloss'
    )
    
    model.fit(X_scaled, y)
    
    # Versioning
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    model_ver_path = os.path.join(MODEL_DIR, f"injury_model_{timestamp}.pkl")
    scaler_ver_path = os.path.join(MODEL_DIR, f"scaler_{timestamp}.pkl")
    
    # Global Paths (active model)
    active_model_path = os.path.join(os.path.dirname(__file__), 'injury_risk_model.pkl')
    active_scaler_path = os.path.join(os.path.dirname(__file__), 'scaler.pkl')
    
    # Save versioned
    joblib.dump(model, model_ver_path)
    joblib.dump(scaler, scaler_ver_path)
    
    # Save active
    joblib.dump(model, active_model_path)
    joblib.dump(scaler, active_scaler_path)
    
    print(f"Model successfully retrained and updated. Version: {timestamp}")
    return True

if __name__ == "__main__":
    print("--- Injury Risk Model Retraining Pipeline ---")
    X, y = extract_and_prepare_data()
    if X is not None:
        success = train_new_model(X, y)
        if success:
            print("Retraining completed successfully.")
        else:
            print("Retraining failed.")
    else:
        print("No data extracted.")
