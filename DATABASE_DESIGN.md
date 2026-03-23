# PlayFit FC Database Design

This document outlines the database schema for the PlayFit FC project, which tracks player data, training, wellness, match statistics, and machine learning predictions for injury risk.

## Tech Stack
- **Database:** MySQL / SQLite
- **Backend:** Python (Flask) with Flask-Login
- **Frontend:** HTML, CSS, JavaScript, Chart.js
- **Data/ML:** Pandas, NumPy, Scikit-learn

## Database Tables

### 1. `users` Table
Stores user authentication and role information.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `user_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Unique user ID |
| `username` | VARCHAR(50) | Login username |
| `password` | VARCHAR(255) | Encrypted password |
| `role` | ENUM('coach', 'player') | User role |

### 2. `players` Table
Stores personal and professional information about the players.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `player_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Unique player ID |
| `user_id` | INTEGER (Foreign Key) | Linked to `users` table |
| `name` | VARCHAR(100) | Player name |
| `age` | INTEGER | Player age |
| `position` | VARCHAR(50) | Playing position |
| `experience_years` | INTEGER | Years of experience |

### 3. `training_data` Table
Records details about training sessions for each player.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `training_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Training record ID |
| `player_id` | INTEGER (Foreign Key) | Linked to `players` table |
| `training_minutes` | INTEGER | Training duration |
| `intensity` | ENUM('Low', 'Medium', 'High') | Training intensity |
| `sessions_per_week` | INTEGER | Weekly sessions |
| `training_date` | DATE | Training date |

### 4. `match_data` Table
Logs match statistics for players.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `match_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Match record ID |
| `player_id` | INTEGER (Foreign Key) | Linked to `players` table |
| `minutes_played` | INTEGER | Minutes played |
| `matches_per_week` | INTEGER | Match frequency |
| `match_date` | DATE | Match date |

### 5. `wellness_data` Table
Tracks daily wellness metrics reported by the players.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `wellness_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Wellness record ID |
| `player_id` | INTEGER (Foreign Key) | Linked to `players` table |
| `fatigue_level` | INTEGER | Scale (1-10) |
| `sleep_quality` | ENUM('Poor', 'Average', 'Good') | Sleep quality |
| `muscle_soreness` | ENUM('Low', 'Medium', 'High') | Soreness level |
| `entry_date` | DATE | Data entry date |

### 6. `injury_history` Table
Keeps a historical record of player injuries.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `injury_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Injury record ID |
| `player_id` | INTEGER (Foreign Key) | Linked to `players` table |
| `injury_type` | VARCHAR(100) | Injury name |
| `severity` | ENUM('Minor', 'Moderate', 'Severe') | Injury severity |
| `recovery_days` | INTEGER | Recovery duration |
| `injury_date` | DATE | Injury occurrence date |

### 7. `risk_prediction` Table
Stores machine learning predictions regarding a player's risk of injury.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `prediction_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Prediction ID |
| `player_id` | INTEGER (Foreign Key) | Linked to `players` table |
| `risk_score` | FLOAT | Risk percentage (0-100) |
| `risk_level` | ENUM('Low', 'Medium', 'High') | Risk category |
| `prediction_date` | DATE | Prediction date |

### 8. `prevention_recommendation` Table
Provides preventive advice based on risk predictions.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `recommendation_id` | INTEGER (Primary Key, AUTO_INCREMENT) | Recommendation ID |
| `prediction_id` | INTEGER (Foreign Key) | Linked to `risk_prediction` table |
| `recommendation` | TEXT | Preventive advice |
| `created_date` | DATE | Recommendation date |
