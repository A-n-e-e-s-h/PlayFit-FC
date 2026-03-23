import pandas as pd
import numpy as np
import os
import joblib
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score, classification_report

CSV_PATH = '../injury_risk_dataset_300_rows.csv'
MODEL_PATH = 'injury_risk_model.pkl'

def train_and_evaluate():
    # Adjust path if run from root
    csv_file = CSV_PATH
    if not os.path.exists(csv_file):
        csv_file = 'injury_risk_dataset_300_rows.csv'
        global MODEL_PATH
        MODEL_PATH = 'ml/injury_risk_model.pkl'

    print(f"Loading dataset from {csv_file}...")
    df = pd.read_csv(csv_file)

    # Preprocessing
    # Map categorical features
    intensity_map = {'low': 1, 'medium': 2, 'high': 3}
    if 'training_intensity' in df.columns:
        df['training_intensity'] = df['training_intensity'].map(intensity_map)

    # Map target variable
    risk_map = {'low': 0, 'medium': 1, 'high': 2}
    if 'injury_risk' in df.columns:
        df['injury_risk'] = df['injury_risk'].map(risk_map)

    # Features and Target
    X = df.drop(columns=['injury_risk'])
    y = df['injury_risk']

    print(f"Data shape: {X.shape}")
    print(f"Class distribution:\n{y.value_counts()}")

    # Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    print("\n" + "="*50)
    print("Training Logistic Regression Model")
    print("="*50)
    
    # Logistic Regression
    lr_params = {
        'C': [0.01, 0.1, 1, 10, 100],
        'solver': ['lbfgs', 'newton-cg'],
        'max_iter': [2000]
    }
    
    lr_grid = GridSearchCV(
        LogisticRegression(class_weight='balanced', random_state=42),
        lr_params,
        cv=5,
        scoring='accuracy'
    )
    lr_grid.fit(X_train, y_train)
    lr_model = lr_grid.best_estimator_
    
    print("Best LR Parameters:", lr_grid.best_params_)
    lr_preds = lr_model.predict(X_test)
    print("LR Accuracy:", accuracy_score(y_test, lr_preds))
    print("LR Classification Report:")
    print(classification_report(y_test, lr_preds, target_names=['Low', 'Medium', 'High']))

    print("\n" + "="*50)
    print("Training Decision Tree Model")
    print("="*50)

    # Decision Tree
    dt_params = {
        'max_depth': [3, 5, 7, 10, None],
        'min_samples_split': [2, 5, 10],
        'criterion': ['gini', 'entropy']
    }
    
    dt_grid = GridSearchCV(
        DecisionTreeClassifier(class_weight='balanced', random_state=42),
        dt_params,
        cv=5,
        scoring='accuracy'
    )
    dt_grid.fit(X_train, y_train)
    dt_model = dt_grid.best_estimator_
    
    print("Best DT Parameters:", dt_grid.best_params_)
    dt_preds = dt_model.predict(X_test)
    print("DT Accuracy:", accuracy_score(y_test, dt_preds))
    print("DT Classification Report:")
    print(classification_report(y_test, dt_preds, target_names=['Low', 'Medium', 'High']))

    print("\nDT Feature Importances:")
    importances = dt_model.feature_importances_
    for feature, imp in zip(X.columns, importances):
        print(f" - {feature}: {imp:.4f}")

    # Export Logistic Regression as it usually generalizes better and provides smooth probabilities
    print(f"\nExporting Logistic Regression as the production model to {MODEL_PATH}...")
    joblib.dump(lr_model, MODEL_PATH)
    print("Done!")

if __name__ == "__main__":
    train_and_evaluate()
