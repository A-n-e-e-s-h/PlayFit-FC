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
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score
import json
try:
    import ml.ml_service as ml_service
except ImportError:
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
            
            # Determine Label: Was there an active injury reported in [T, T+7] days?
            label_query = '''
                SELECT training_id FROM training_data 
                WHERE player_id = ? AND active_injury = 1 AND training_date > ? AND training_date <= ?
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
    
    # Calculate scale_pos_weight for imbalanced classes
    num_neg = np.sum(y == 0)
    num_pos = np.sum(y == 1)
    scale_weight = max(1.0, num_neg / num_pos) if num_pos > 0 else 1.0
    
    # XGBoost
    model = XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
        use_label_encoder=False,
        eval_metric='logloss',
        scale_pos_weight=scale_weight
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

def update_training_stage(conn, stage):
    """Updates the current training stage in system_meta."""
    try:
        conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'training_stage'", (stage,))
        conn.commit()
        print(f"Stage: {stage}")
    except Exception as e:
        print(f"Failed to update stage: {e}")

def validate_training_data(X, y):
    """
    Performs basic data validation and cleaning.
    Drops rows with NaNs and ensures feature ranges are sane.
    """
    if X is None or y is None or len(X) == 0:
        return None, None
        
    # Combine for cleaning
    df = X.copy()
    df['target'] = y
    
    # 1. Drop missing
    initial_len = len(df)
    df = df.dropna()
    
    # 2. Basic Range Validation (e.g., fatigue should be 1-10)
    if 'fatigue_level' in df.columns:
        df = df[(df['fatigue_level'] >= 1) & (df['fatigue_level'] <= 10)]
    
    # 3. Outlier removal (optional, but let's stick to basics for now)
    
    final_len = len(df)
    if final_len < initial_len:
        print(f"Cleaned data: {initial_len - final_len} rows removed.")
        
    if final_len < 10:
        return None, None
        
    return df.drop(columns=['target']), df['target'].values

def run_retraining_pipeline():
    """
    Main entry point for autonomous retraining.
    Executes in stages with quality gates.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        # STAGE 1: DATA EXTRACTION
        update_training_stage(conn, 'DATA_EXTRACTION')
        X, y = extract_and_prepare_data()
        
        # STAGE 2: VALIDATION
        update_training_stage(conn, 'VALIDATION')
        X_clean, y_clean = validate_training_data(X, y)
        if X_clean is None:
            raise ValueError("Data validation failed: insufficient clean samples.")
            
        # STAGE 3: TRAINING
        update_training_stage(conn, 'TRAINING')
        # Split for evaluation
        X_train, X_val, y_train, y_val = train_test_split(X_clean, y_clean, test_size=0.2, random_state=42)
        
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_val_scaled = scaler.transform(X_val)
        
        # Calculate scale_pos_weight
        num_neg = np.sum(y_train == 0)
        num_pos = np.sum(y_train == 1)
        scale_weight = max(1.0, num_neg / num_pos) if num_pos > 0 else 1.0

        model = XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42,
            use_label_encoder=False,
            eval_metric='logloss',
            scale_pos_weight=scale_weight
        )
        model.fit(X_train_scaled, y_train)
        
        # STAGE 4: EVALUATION
        update_training_stage(conn, 'EVALUATION')
        y_pred_proba = model.predict_proba(X_val_scaled)[:, 1]
        new_auc = roc_auc_score(y_val, y_pred_proba)
        new_acc = accuracy_score(y_val, (y_pred_proba > 0.5).astype(int))
        
        print(f"New Model AUC: {new_auc:.4f}, Accuracy: {new_acc:.4f}")
        
        # STAGE 5: ACCEPTANCE
        update_training_stage(conn, 'ACCEPTANCE')
        
        # Fetch previous metrics
        prev_metrics_raw = conn.execute("SELECT meta_value FROM system_meta WHERE meta_key = 'last_training_metrics'").fetchone()
        prev_metrics = json.loads(prev_metrics_raw['meta_value']) if prev_metrics_raw and prev_metrics_raw['meta_value'] else {}
        prev_auc = prev_metrics.get('auc', 0.0)
        
        # QUALITY GATE: Acceptance logic
        # Skip check if validation set is too small (< 20 samples in this case for dev, but plan said 100)
        # For this specific app, we might have fewer players, so let's use a smaller threshold or stick to plan's 100 if data is large.
        # Given our current counts (~2000), 20% validation is 400, so 100 is fine.
        if len(y_val) >= 100:
            if new_auc < (prev_auc - 0.02):
                msg = f"Model REJECTED: New AUC ({new_auc:.3f}) is significantly worse than previous AUC ({prev_auc:.3f})."
                print(msg)
                conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_error'", (msg,))
                return False
        else:
            print(f"Small validation set ({len(y_val)}). Skipping strict acceptance gate.")

        # STAGE 6: SAVE & INTEGRITY CHECK
        update_training_stage(conn, 'SAVE')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        model_ver_path = os.path.join(MODEL_DIR, f"injury_model_{timestamp}.pkl")
        scaler_ver_path = os.path.join(MODEL_DIR, f"scaler_{timestamp}.pkl")
        
        temp_model_path = os.path.join(MODEL_DIR, "temp_model.pkl")
        temp_scaler_path = os.path.join(MODEL_DIR, "temp_scaler.pkl")
        
        # Save to temp first for integrity check
        joblib.dump(model, temp_model_path)
        joblib.dump(scaler, temp_scaler_path)
        
        # INTEGRITY CHECK: Test load
        try:
            test_model = joblib.load(temp_model_path)
            test_scaler = joblib.load(temp_scaler_path)
            print("Integrity check passed.")
        except Exception as integrity_e:
            raise RuntimeError(f"Integrity check failed: {integrity_e}")
            
        # STAGE 7: SWAP
        update_training_stage(conn, 'SWAP')
        
        # Global active paths
        active_model_path = os.path.join(os.path.dirname(__file__), 'injury_risk_model.pkl')
        active_scaler_path = os.path.join(os.path.dirname(__file__), 'scaler.pkl')
        
        # Save versioned
        joblib.dump(model, model_ver_path)
        joblib.dump(scaler, scaler_ver_path)
        
        # Atomic-ish swap (overwrite active)
        joblib.dump(model, active_model_path)
        joblib.dump(scaler, active_scaler_path)
        
        # Cleanup temp
        if os.path.exists(temp_model_path): os.remove(temp_model_path)
        if os.path.exists(temp_scaler_path): os.remove(temp_scaler_path)
        
        # UPDATE METADATA
        metrics_json = json.dumps({'auc': new_auc, 'accuracy': new_acc, 'samples': len(X_clean)})
        now_str = datetime.now().isoformat()
        
        conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'last_training_metrics'", (metrics_json,))
        conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'last_retrained_at'", (now_str,))
        conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'sample_count_at_last_training'", (str(len(X_clean)),))
        conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'active_model_version'", (f"v{timestamp}",))
        conn.execute("UPDATE system_meta SET meta_value = 'idle', last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_status'")
        conn.execute("UPDATE system_meta SET meta_value = '0', last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_retry_count'")
        conn.execute("UPDATE system_meta SET meta_value = '', last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_error'")
        conn.execute("UPDATE system_meta SET meta_value = 'idle', last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'training_stage'")
        
        # Staggered Invalidation (as specified in plan)
        # Note: This might be better handled in ml_service.py after the function returns, 
        # but let's do it here as it's part of the pipeline completion.
        print("Starting staggered player invalidation...")
        players = conn.execute("SELECT player_id FROM players").fetchall()
        for i, p in enumerate(players):
            conn.execute("UPDATE players SET prediction_ready = 1 WHERE player_id = ?", (p['player_id'],))
            if (i + 1) % 20 == 0:
                conn.commit() # Commit in batches
                import time
                time.sleep(0.1)
        
        conn.commit()
        print(f"Retraining successful. [Status: Success | Samples: {len(X_clean)} | AUC: {new_auc:.3f}]")
        return True
        
    except Exception as e:
        print(f"Retraining Pipeline FAILED: {e}")
        import traceback
        traceback.print_exc()
        try:
            conn.execute("UPDATE system_meta SET meta_value = 'failed', last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_status'")
            conn.execute("UPDATE system_meta SET meta_value = ?, last_updated = CURRENT_TIMESTAMP WHERE meta_key = 'retraining_error'", (str(e),))
            conn.commit()
        except:
            pass
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("--- Injury Risk Model Retraining Pipeline ---")
    run_retraining_pipeline()
