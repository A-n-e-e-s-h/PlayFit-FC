# 🏃‍♂️ PLAYFIT FC

### AI-Powered Injury Risk Prediction & Athlete Performance Platform

## 🚀 What is PLAYFIT FC?

**PLAYFIT FC** is an AI-driven sports analytics platform designed to help teams **predict and prevent athlete injuries** using real-time data and machine learning.

It combines:

* 📊 Performance analytics
* 🧠 Machine learning predictions
* ⚠️ Smart alerts
* 📄 Professional reporting

👉 Built to simulate **real-world sports science systems used by elite teams**

---

## ✨ Core Features

### 🧠 Injury Risk Prediction Engine

* Predicts:

  * **Risk Score (0–100%)**
  * **Risk Level (Low / Medium / High)**
* Uses:

  * Fatigue
  * Sleep quality
  * Muscle soreness
  * Workload
  * ACWR

---

### 📊 Coach Intelligence Dashboard

* Team-wide risk overview
* High-risk player detection
* Fatigue & workload trends
* Smart alerts & recommendations

---

### 👤 Player Performance Dashboard

* Daily wellness tracking
* Personal injury risk score
* Trend visualization
* Recovery insights

---

### ⚠️ Real-Time Alert System

* Triggers when:

  * Risk score exceeds threshold
  * Fatigue is high
  * ACWR is unsafe (>1.3)
* Helps coaches act **before injury occurs**

---

### 📄 Automated PDF Reports

* Download professional reports including:

  * Team overview
  * Player risk breakdown
  * Trend analysis
  * ACWR insights
  * Actionable recommendations

---

### 🧬 Realistic Data Simulation Engine

* 120-day historical dataset per player
* Non-consecutive, time-series data
* Includes:

  * Training cycles
  * Match load
  * Recovery phases
  * Active injury states

---

## 🧠 How It Works

```text
Player Wellness + Training Data
            ↓
     Feature Engineering
            ↓
      ML Prediction Model
            ↓
 Risk Score + Risk Level
            ↓
 Dashboards + Alerts + Reports
```

---

## 🏗️ System Architecture

```text
Frontend (HTML + Tailwind)
        ↓
Flask Backend (API + Logic)
        ↓
SQLite Database
        ↓
ML Model (.pkl + scaler)
        ↓
Analytics + Alerts + PDF Reports
```

---

## 🗄️ Database Design

| Table           | Purpose                  |
| --------------- | ------------------------ |
| users           | Authentication & roles   |
| players         | Player profiles          |
| training_data   | Workload tracking        |
| wellness_data   | Fatigue, sleep, soreness |
| match_data      | Match performance        |
| notifications   | Alert system             |
| risk_prediction | ML outputs               |

---

## ⚙️ Tech Stack

| Layer    | Technology          |
| -------- | ------------------- |
| Backend  | Flask (Python)      |
| Frontend | HTML + Tailwind CSS |
| Database | SQLite              |
| ML       | Scikit-learn        |
| Data     | Pandas, NumPy       |
| Reports  | ReportLab           |

---

## 📦 Installation

```bash
git clone https://github.com/your-username/playfit-fc.git
cd playfit-fc
pip install -r requirements.txt
```

---

## ▶️ Run the Application

```bash
python app.py
```

Open in browser:

```
http://127.0.0.1:5000/
```

---

## 👥 User Roles

### 👨‍🏫 Coach

* Manage players
* Input training data
* Analyze team performance
* Download reports

### 🧑‍💻 Player

* Submit wellness data
* View risk score
* Track performance trends

---

## 📊 Key Concepts Used

* **ACWR (Acute:Chronic Workload Ratio)**
* Time-series analysis
* Feature engineering
* Predictive modeling
* Sports science principles

---

## 🔥 What Makes This Project Special?

✅ Full-stack AI system
✅ Real-world sports science logic
✅ Multi-user ecosystem (Coach + Player)
✅ Data-driven decision support
✅ Professional analytics & reporting

👉 This is not just a project — it's a **sports analytics platform prototype**


## 🚀 Future Roadmap

* 🔄 Continuous ML retraining
* 🧠 Explainable AI (SHAP)
* 📱 Mobile app
* 📡 Real-time notifications
* 🛰️ GPS & wearable integration
