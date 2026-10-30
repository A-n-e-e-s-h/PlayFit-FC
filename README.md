# 🏃‍♂️ PLAYFIT FC – Athlete Performance & Injury Risk Prediction System

## 📌 Project Overview

PLAYFIT FC is a sports analytics and machine learning application designed to analyze athlete workload, wellness and recovery data to identify potential injury risk patterns.

The system processes athlete activity data, performs exploratory data analysis, applies feature engineering techniques and uses machine learning to estimate injury risk.

It also provides interactive dashboards and automated PDF reports to help coaches monitor athlete performance, understand workload trends and make data-informed decisions.

The project demonstrates an end-to-end workflow involving data processing, statistical analysis, predictive modeling, database management, visualization and reporting.

## 🎯 Business Problem

Athlete injuries can negatively impact team performance, player availability and competitive outcomes.

Traditional injury monitoring often relies on manual observations, making it difficult to identify workload imbalances and potential injury warning signs.

PLAYFIT FC aims to address this challenge by:

- Identifying workload and wellness patterns associated with injury risk.
- Estimating injury probability using machine learning.
- Monitoring athlete workload and recovery trends.
- Identifying athletes with elevated risk indicators.
- Generating analytical reports for coaches.
- Supporting evidence-based sports performance decisions.

## 📊 Dataset

The project uses a simulated time-series dataset representing 120 days of athlete activity and wellness information.

**Key dataset attributes:**

| Feature | Description |
|---|---|
| Training Workload | Daily training activity load |
| Match Workload | Workload associated with matches |
| Sleep Quality | Athlete sleep and recovery indicator |
| Fatigue Level | Reported fatigue measurement |
| Muscle Soreness | Muscle soreness indicator |
| ACWR | Acute:Chronic Workload Ratio |
| Injury Status | Historical injury indicator |

The simulated dataset is designed to represent athlete monitoring data commonly used in sports performance analysis.

## 🧹 Data Preparation & Feature Engineering

The data preparation workflow includes:

- Data cleaning and validation.
- Handling missing values.
- Data transformation and normalization.
- Feature engineering.
- Time-series organization.
- Feature scaling.
- Preparation of model-ready datasets.

**Derived features include:**

- Acute:Chronic Workload Ratio (ACWR).
- Recovery indicators.
- Rolling workload averages.
- Workload trends.
- Risk-related metrics.

## 📈 Exploratory Data Analysis (EDA)

The project analyzes athlete data to identify meaningful patterns and relationships.

**Key analyses include:**

- Player workload trends.
- Fatigue level distribution.
- Sleep quality analysis.
- Injury occurrence patterns.
- ACWR trend analysis.
- Wellness score comparisons.
- High-risk athlete identification.

These analyses help understand how workload and wellness indicators vary across athletes and over time.

## 🤖 Machine Learning & Predictive Analytics

A machine learning model is developed using athlete workload and wellness indicators to estimate potential injury risk.

**Model outputs include:**

- Injury Risk Score (0–100%).
- Risk Classification.
  - 🟢 Low Risk
  - 🟡 Medium Risk
  - 🔴 High Risk

The model uses historical athlete data and engineered features to generate risk estimates based on identified patterns.

## 📊 Dashboard & Visualization

PLAYFIT FC provides interactive dashboards designed for coaches and athletes.

**Coach Dashboard**

- Team-wide injury risk overview.
- High-risk athlete identification.
- Workload monitoring.
- Fatigue and recovery trends.
- Injury distribution analysis.
- Risk-related recommendations.

**Player Dashboard**

- Individual wellness tracking.
- Injury risk score.
- Workload and performance trends.
- Recovery insights.
- Historical activity summaries.

## 📄 Automated Reporting

The application generates PDF reports containing:

- Team performance summaries.
- Individual athlete risk assessments.
- Workload analysis.
- Wellness and recovery trends.
- Risk prediction summaries.
- Analytical recommendations.

These reports help coaches review athlete data and monitor performance indicators over time.

## 🗄 Database Design

SQLite is used to store and manage structured athlete and analytical data.

| Table | Purpose |
|---|---|
| Players | Stores athlete information |
| Wellness Data | Maintains daily wellness metrics |
| Training Data | Stores training workload records |
| Match Data | Maintains match statistics |
| Risk Predictions | Stores machine learning prediction results |
| Notifications | Maintains alert history |

## 🔄 Analytics & Machine Learning Workflow

```text
       Athlete Activity Data
                 |
                 ▼
           Data Cleaning
                 |
                 ▼
        Feature Engineering
                 |
                 ▼
     Exploratory Data Analysis
                 |
                 ▼
       Feature Preparation
                 |
                 ▼
       Machine Learning Model
                 |
                 ▼
        Injury Risk Scoring
                 |
                 ▼
       Risk Categorization
                 |
                 ▼
       Interactive Dashboards
                 |
                 ▼
       Automated PDF Reports
```

## 💡 Key Outcomes

- Identified workload and wellness patterns associated with potential injury risk.
- Developed machine learning-based injury risk estimation.
- Analyzed athlete performance and recovery trends.
- Created dashboards for individual and team-level monitoring.
- Automated analytical reporting.
- Demonstrated an end-to-end sports analytics and machine learning workflow.

## 🛠️ Technologies & Tools

| Category | Technologies |
|---|---|
| Programming Language | Python |
| Data Analysis | Pandas, NumPy |
| Machine Learning | Scikit-learn |
| Database | SQLite, SQL |
| Data Visualization | Matplotlib |
| Backend Development | Flask |
| Reporting | ReportLab |
| Development Tools | Git, GitHub |

## 🚀 Skills Demonstrated

- Python Programming
- SQL & Database Management
- Data Cleaning & Preprocessing
- Exploratory Data Analysis (EDA)
- Statistical Analysis
- Feature Engineering
- Time-Series Analysis
- Machine Learning
- Predictive Analytics
- Data Visualization
- Dashboard Development
- Automated Report Generation

## ⚙️ Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/A-n-e-e-s-h/PlayFit-FC.git
```

### 2. Navigate to the project directory

```bash
cd PlayFit-FC
```

### 3. Create a virtual environment (recommended)

```bash
python -m venv venv
```

### 4. Activate the environment

**Windows:**
```bash
venv\Scripts\activate
```

**Linux / macOS:**
```bash
source venv/bin/activate
```

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the application

```bash
python app.py
```

Open the local application URL displayed in the terminal.

## 👨‍💻 Author

**Mohammed Aneesh**

**Technical Skills:** Python • SQL • SQLite • Pandas • NumPy • Scikit-learn • Machine Learning • Data Analysis • Data Visualization
