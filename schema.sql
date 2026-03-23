DROP TABLE IF EXISTS prevention_recommendation;
DROP TABLE IF EXISTS risk_prediction;
DROP TABLE IF EXISTS injury_history;
DROP TABLE IF EXISTS wellness_data;
DROP TABLE IF EXISTS match_data;
DROP TABLE IF EXISTS training_data;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role TEXT CHECK(role IN ('coach', 'player')) NOT NULL
);

CREATE TABLE players (
    player_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    age INTEGER,
    position VARCHAR(50),
    experience_years INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE TABLE training_data (
    training_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    training_minutes INTEGER,
    intensity TEXT CHECK(intensity IN ('Low', 'Medium', 'High')),
    sessions_per_week INTEGER,
    training_date DATE,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);

CREATE TABLE match_data (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    minutes_played INTEGER,
    matches_per_week INTEGER,
    match_date DATE,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);

CREATE TABLE wellness_data (
    wellness_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    fatigue_level INTEGER CHECK(fatigue_level BETWEEN 1 AND 10),
    sleep_quality TEXT CHECK(sleep_quality IN ('Poor', 'Average', 'Good')),
    muscle_soreness TEXT CHECK(muscle_soreness IN ('Low', 'Medium', 'High')),
    entry_date DATE,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);

CREATE TABLE injury_history (
    injury_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    injury_type VARCHAR(100),
    severity TEXT CHECK(severity IN ('Minor', 'Moderate', 'Severe')),
    recovery_days INTEGER,
    injury_date DATE,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);

CREATE TABLE risk_prediction (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    risk_score FLOAT,
    risk_level TEXT CHECK(risk_level IN ('Low', 'Medium', 'High')),
    prediction_date DATE,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);

CREATE TABLE prevention_recommendation (
    recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL,
    recommendation TEXT,
    created_date DATE,
    FOREIGN KEY (prediction_id) REFERENCES risk_prediction (prediction_id) ON DELETE CASCADE
);
