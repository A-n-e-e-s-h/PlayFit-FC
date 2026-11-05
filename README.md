# 🏃 PlayFit FC – Athlete Performance & Injury Risk Prediction System

A Python-based web application that combines backend development, database management, data processing and machine learning to analyze athlete performance and estimate potential injury risk.

## 📌 Project Overview

PlayFit FC is an end-to-end sports performance monitoring application designed to help coaches track athlete workload, wellness, recovery and potential injury risk indicators.

The application processes athlete activity data, stores structured records in a SQLite database, applies data processing and machine learning workflows and presents insights through interactive dashboards and automated PDF reports.

The project focuses on building an integrated software solution that connects backend application logic, database operations, analytical processing, predictive modeling and reporting functionality.

## 🎯 Key Features

- **Athlete Management:** Organizes athlete information and related performance records.
- **Data Processing:** Cleans, validates, transforms and prepares athlete activity and wellness data.
- **Performance Monitoring:** Analyzes training workload, match activity, fatigue and recovery indicators.
- **Injury Risk Estimation:** Integrates machine learning to generate injury risk scores and classifications.
- **Interactive Dashboards:** Provides team-level and individual athlete performance insights.
- **Database Management:** Uses SQLite to store and retrieve structured athlete and analytical records.
- **Automated PDF Reporting:** Generates reports containing performance summaries, wellness indicators and risk estimates.
- **Time-Series Analysis:** Tracks workload and recovery patterns over time.

## 🏗️ Application Architecture & Workflow

The application follows an integrated workflow connecting data ingestion, backend processing, database management, predictive modeling and reporting.

```text
       User Interaction
              |
              ▼
       Flask Application
              |
              ▼
      Application Logic
              |
       ┌──────┴──────┐
       ▼             ▼
  SQLite Database  Data Processing
       |             |
       ▼             ▼
 Data Retrieval   Feature Engineering
                     |
                     ▼
              ML Model Integration
                     |
                     ▼
               Risk Scoring
                     |
              ┌──────┴──────┐
              ▼             ▼
         Dashboards     PDF Reports
```

## ⚙️ Backend Development

The application uses Python and Flask to implement the web application logic and coordinate its core functionalities.

Key implementation areas include:

- Developing application workflows using Python.
- Integrating data processing and machine learning components.
- Handling athlete performance and wellness information.
- Connecting application functionality with SQLite.
- Processing analytical results for dashboard presentation.
- Integrating automated report generation.

## 🗄️ Database Design & Management

SQLite is used as the relational database for storing and managing structured application data.

The database covers the following logical entities:

| Entity | Purpose |
|---|---|
| Players | Athlete information |
| Wellness Data | Daily wellness and recovery metrics |
| Training Data | Training workload records |
| Match Data | Match-related statistics |
| Risk Predictions | Generated injury risk estimates |
| Notifications | Alert and notification history |

SQL operations support structured data storage, retrieval and management across the application.

## 🔄 Data Processing & Machine Learning Integration

The application incorporates a data processing pipeline to prepare athlete records for analysis and predictive modeling.

**Processing workflow:**

1. Data cleaning and validation.
2. Handling missing values.
3. Data transformation and normalization.
4. Feature engineering.
5. Time-series organization.
6. Feature scaling and model preparation.
7. Machine learning model execution.
8. Injury risk score generation.

**Derived features include:**

- Acute:Chronic Workload Ratio (ACWR).
- Rolling workload averages.
- Recovery indicators.
- Workload trends.
- Risk-related metrics.

The machine learning component uses historical athlete data and engineered features to estimate potential injury risk.

Risk classifications include:

- 🟢 Low Risk
- 🟡 Medium Risk
- 🔴 High Risk

*Note: The project uses a simulated dataset representing 120 days of athlete activity and wellness information. Predictions are experimental estimates, not medically validated assessments.*

## 📊 Dashboard & Reporting

The application provides dashboard functionality for monitoring athlete performance and analyzing team-level patterns.

**Coach Dashboard**
- Team-wide injury risk overview.
- Athlete risk indicators.
- Workload and recovery trends.
- Fatigue analysis.
- Injury distribution.

**Player Dashboard**
- Individual wellness tracking.
- Injury risk estimates.
- Workload trends.
- Recovery insights.
- Historical activity summaries.

**Automated PDF Reports**

Integrated PDF generation using ReportLab to produce structured reports containing:

- Athlete performance summaries.
- Individual risk assessments.
- Workload analysis.
- Wellness and recovery trends.
- Predictive analysis summaries.

## 🛠️ Technology Stack

| Category | Technologies |
|---|---|
| Programming Language | Python |
| Backend Framework | Flask |
| Database | SQLite, SQL |
| Data Processing | Pandas, NumPy |
| Machine Learning | Scikit-learn |
| Data Visualization | Matplotlib |
| Report Generation | ReportLab |
| Version Control | Git, GitHub |

## 💻 Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/A-n-e-e-s-h/PlayFit-FC.git
```

### 2. Navigate to the project directory

```bash
cd PlayFit-FC
```

### 3. Create a virtual environment

```bash
python -m venv venv
```

### 4. Activate the virtual environment

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

## 🎓 Technical Skills Demonstrated

- Python Application Development
- Flask Web Development
- Backend Application Logic
- SQL & Relational Database Management
- SQLite Integration
- Data Processing & Validation
- Machine Learning Integration
- Feature Engineering
- Data Visualization
- Automated PDF Generation
- Git & Version Control
- End-to-End Application Development

## 👨‍💻 Author

**Mohammed Aneesh**

- GitHub: [A-n-e-e-s-h](https://github.com/A-n-e-e-s-h)
- LinkedIn: [Mohammed Aneesh](https://www.linkedin.com/in/mohammed-aneesh)

---

⭐ If you find this project interesting, feel free to explore the repository!
