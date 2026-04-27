import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
import joblib
import os

# --- Parameters ---
DATASET_PATH = r"c:\Project\PlayFit FC\injury_risk_full_dataset_1000.csv"
MODEL_OUTPUT = r"c:\Project\PlayFit FC\ml\injury_risk_model.pkl"
SCALER_OUTPUT = r"c:\Project\PlayFit FC\ml\scaler.pkl"

def load_and_preprocess(filepath):
    print("Loading dataset:", filepath)
    df = pd.read_csv(filepath)
    
    # Fill missing numerics
    df['previous_injury'] = df['previous_injury'].fillna(0)
    df['recovery_days'] = df['recovery_days'].fillna(0)
    
    # --- Feature Engineering ---
    # Convert dates safely
    date_cols = ['injury_date', 'training_date', 'match_date', 'entry_date']
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors='coerce')
        
    # Calculate days since last injury (default to 365 if no prior injury or missing)
    df['days_since_last_injury'] = (df['entry_date'] - df['injury_date']).dt.days
    df['days_since_last_injury'] = df['days_since_last_injury'].fillna(365).clip(lower=0)
    
    df['training_recency'] = (df['entry_date'] - df['training_date']).dt.days
    df['training_recency'] = df['training_recency'].fillna(7).clip(lower=0)
    
    df['match_load_frequency'] = (df['entry_date'] - df['match_date']).dt.days
    df['match_load_frequency'] = df['match_load_frequency'].fillna(14).clip(lower=0)
    
    # Derived metrics
    # ACWR proxy: assume chronic load is around 300 minutes based on simple constant or average
    df['ACWR'] = df['training_minutes'] / 300.0
    
    df['recovery_score'] = df['sleep_quality'] - df['muscle_soreness']
    df['load_ratio'] = df['training_minutes'] / (df['minutes_played'] + 1.0)
    df['injury_risk_factor'] = df['previous_injury'] * df['recovery_days']
    
    # Select final features
    feature_cols = [
        'minutes_played', 'matches_per_week', 'training_minutes', 
        'training_intensity', 'sessions_per_week', 'fatigue_level', 
        'muscle_soreness', 'sleep_quality', 'previous_injury', 'recovery_days',
        'days_since_last_injury', 'training_recency', 'match_load_frequency',
        'ACWR', 'recovery_score', 'load_ratio', 'injury_risk_factor'
    ]
    
    X = df[feature_cols]
    y = df['injury_risk']
    
    # Shuffle dataset
    # X, y = X.sample(frac=1, random_state=42).reset_index(drop=True), y.sample(frac=1, random_state=42).reset_index(drop=True)
    
    return X, y, feature_cols

def train_and_evaluate():
    X, y, feature_cols = load_and_preprocess(DATASET_PATH)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # Scale Features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    print("-" * 50)
    print("Baseline Models")
    print("-" * 50)
    
    # 1. Logistic Regression
    lr = LogisticRegression(max_iter=1000)
    lr.fit(X_train_scaled, y_train)
    print(f"Logistic Regression Accuracy: {accuracy_score(y_test, lr.predict(X_test_scaled)):.4f}")
    
    # 2. Decision Tree
    dt = DecisionTreeClassifier(random_state=42)
    dt.fit(X_train_scaled, y_train)
    print(f"Decision Tree Accuracy: {accuracy_score(y_test, dt.predict(X_test_scaled)):.4f}")
    
    print("\n" + "-" * 50)
    print("Hyperparameter Tuning (GridSearchCV)")
    print("-" * 50)
    
    # 3. Random Forest Tuning
    rf_params = {
        'n_estimators': [50, 100, 200],
        'max_depth': [None, 10, 20],
        'min_samples_split': [2, 5, 10]
    }
    rf = RandomForestClassifier(random_state=42)
    rf_grid = GridSearchCV(rf, rf_params, cv=5, scoring='accuracy', n_jobs=-1)
    rf_grid.fit(X_train_scaled, y_train)
    best_rf = rf_grid.best_estimator_
    print(f"Best Random Forest CV Accuracy: {rf_grid.best_score_:.4f}")
    print(f"Test Accuracy: {accuracy_score(y_test, best_rf.predict(X_test_scaled)):.4f}")
    
    # 4. Gradient Boosting Tuning
    gb_params = {
        'learning_rate': [0.01, 0.1, 0.2],
        'n_estimators': [50, 100, 200],
        'max_depth': [3, 5, 7]
    }
    gb = GradientBoostingClassifier(random_state=42)
    gb_grid = GridSearchCV(gb, gb_params, cv=5, scoring='accuracy', n_jobs=-1)
    gb_grid.fit(X_train_scaled, y_train)
    best_gb = gb_grid.best_estimator_
    print(f"\nBest Gradient Boosting CV Accuracy: {gb_grid.best_score_:.4f}")
    print(f"Test Accuracy: {accuracy_score(y_test, best_gb.predict(X_test_scaled)):.4f}")
    
    # Selection
    if gb_grid.best_score_ >= rf_grid.best_score_:
        best_model = best_gb
        model_name = "Gradient Boosting"
    else:
        best_model = best_rf
        model_name = "Random Forest"
        
    print(f"\n>>> Selected Best Model: {model_name} <<<")
    
    # Final Evaluation
    y_pred = best_model.predict(X_test_scaled)
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    print("Confusion Matrix:")
    print(confusion_matrix(y_test, y_pred))
    
    # Feature Importances
    importances = best_model.feature_importances_
    feature_imp_df = pd.DataFrame({'Feature': feature_cols, 'Importance': importances}).sort_values(by='Importance', ascending=False)
    print("\nTop 5 Feature Importances:")
    print(feature_imp_df.head(5))
    
    # Export
    os.makedirs(os.path.dirname(MODEL_OUTPUT), exist_ok=True)
    joblib.dump(best_model, MODEL_OUTPUT)
    joblib.dump(scaler, SCALER_OUTPUT)
    print(f"\nModels successfully exported to {os.path.dirname(MODEL_OUTPUT)}")
    
if __name__ == "__main__":
    train_and_evaluate()
