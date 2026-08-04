# 🏃‍♂️ PLAYFIT FC – Athlete Injury Risk Analytics System

## 📌 Project Overview

PLAYFIT FC is a sports analytics project that analyzes athlete wellness and workload data to identify injury risk trends using data analysis and machine learning.

The project demonstrates an end-to-end analytics workflow including data collection, preprocessing, feature engineering, predictive modeling, dashboard creation, and automated reporting to support data-driven decision making in sports performance.

---

# 🎯 Business Problem

Athlete injuries negatively affect team performance, player availability, and overall competitive success.

Traditional injury monitoring often relies on manual observations, making it difficult to detect early warning signs.

This project uses historical player data to:

- Identify injury risk factors
- Predict injury probability
- Monitor workload trends
- Generate actionable insights for coaches
- Support evidence-based decision making

---

# 📊 Dataset

The project uses simulated time-series athlete data representing 120 days of player activity.

### Data includes:

- Training workload
- Match workload
- Sleep quality
- Fatigue level
- Muscle soreness
- Acute:Chronic Workload Ratio (ACWR)
- Injury status

The simulated dataset was designed to mimic real-world athlete monitoring systems.

---

# 🧹 Data Preparation

The analytical workflow includes:

- Data Cleaning
- Handling missing values
- Feature Engineering
- Data Transformation
- Time-series organization
- Feature Scaling

Derived features include:

- ACWR
- Recovery indicators
- Rolling workload averages
- Risk-related metrics

---

# 📈 Exploratory Data Analysis

Key analyses performed include:

- Player workload trends
- Fatigue distribution
- Sleep quality analysis
- Injury occurrence patterns
- ACWR trend analysis
- Wellness score comparisons
- High-risk player identification

---

# 🤖 Predictive Analytics

A Machine Learning model was developed to predict athlete injury risk.

### Model Output

- Injury Risk Score (0–100%)
- Risk Category
  - Low
  - Medium
  - High

The model combines workload and wellness indicators to estimate injury probability.

---

# 📊 Dashboard & Visualizations

The project includes interactive dashboards for both coaches and players.

### Coach Dashboard

- Team risk overview
- High-risk athlete identification
- Workload monitoring
- Fatigue trends
- Injury distribution
- Smart recommendations

### Player Dashboard

- Individual wellness tracking
- Injury risk score
- Performance trends
- Recovery insights

---

# 📄 Automated Reporting

Professional PDF reports summarize:

- Team performance
- Player injury risk
- Workload analysis
- Trend summaries
- Actionable recommendations

---

# 🗄 Database Design

The project stores structured analytical data using SQLite.

| Table | Purpose |
|--------|----------|
| Players | Player information |
| Wellness Data | Daily wellness metrics |
| Training Data | Training workload |
| Match Data | Match statistics |
| Risk Predictions | ML prediction results |
| Notifications | Alert history |

---

# 🛠 Tools & Technologies

### Programming

- Python

### Data Analysis

- Pandas
- NumPy

### Machine Learning

- Scikit-learn

### Database

- SQLite
- SQL

### Visualization

- Matplotlib
- Dashboard Interface

### Reporting

- ReportLab

### Web Framework

- Flask

---

# 📊 Analytics Workflow

```
Data Collection
        │
        ▼
Data Cleaning
        │
        ▼
Feature Engineering
        │
        ▼
Exploratory Data Analysis
        │
        ▼
Machine Learning Model
        │
        ▼
Risk Prediction
        │
        ▼
Dashboards & Reports
```

---

# 📌 Key Outcomes

- Identified workload patterns associated with increased injury risk.
- Predicted athlete injury probability using machine learning.
- Generated dashboards for monitoring player wellness.
- Automated analytical reports to support coaching decisions.
- Demonstrated an end-to-end sports analytics workflow.

---

# 🚀 Skills Demonstrated

- Data Cleaning
- Data Analysis
- Exploratory Data Analysis (EDA)
- Feature Engineering
- SQL
- SQLite
- Python
- Pandas
- NumPy
- Machine Learning
- Dashboard Development
- Data Visualization
- Predictive Analytics
- Report Automation

---

# ▶️ Installation

```bash
git clone https://github.com/A-n-e-e-s-h/PlayFit-FC.git
cd PlayFit-FC
pip install -r requirements.txt
python app.py
```

---

# 📷 Project Preview

*Add screenshots of:*

- Coach Dashboard
- Player Dashboard
- Risk Prediction Results
- Trend Visualizations
- PDF Reports

---

# 👤 Author

**Mohammed Aneesh**

Aspiring Data Analyst

**Skills:** Python • SQL • SQLite • Pandas • NumPy • Tableau • Excel • Machine Learning
