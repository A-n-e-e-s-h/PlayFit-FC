-- Finalized 8-Table Design for PlayFit FC
DROP TABLE IF EXISTS reports;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS wellness_data;
DROP TABLE IF EXISTS training_data;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS teams;
DROP TABLE IF EXISTS users;
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(150) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role TEXT CHECK(role IN ('admin', 'coach', 'player')) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    team_code VARCHAR(50),
    team_name VARCHAR(100),
    sport VARCHAR(50),
    login_count INTEGER DEFAULT 0
);
CREATE TABLE teams (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name VARCHAR(100) NOT NULL,
    coach_id INTEGER,
    sport VARCHAR(50),
    FOREIGN KEY (coach_id) REFERENCES users (user_id) ON DELETE
    SET NULL
);
CREATE TABLE players (
    player_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name VARCHAR(150) NOT NULL,
    age INTEGER NOT NULL,
    position VARCHAR(50) NOT NULL,
    experience_years INTEGER,
    squad VARCHAR(50) DEFAULT 'None',
    prediction_ready INTEGER DEFAULT 1,
    -- 0: Ready, 1: Update Needed, 2: In-Progress
    last_prediction_attempt DATETIME,
    prediction_retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);
CREATE TABLE training_data (
    training_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    training_date DATE NOT NULL,
    training_minutes INTEGER NOT NULL,
    training_intensity TEXT CHECK(training_intensity IN ('Low', 'Medium', 'High')),
    sessions_per_week INTEGER NOT NULL,
    minutes_played INTEGER,
    matches_per_week INTEGER,
    active_injury BOOLEAN DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);
CREATE TABLE wellness_data (
    wellness_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    fatigue_level INTEGER CHECK(
        fatigue_level BETWEEN 1 AND 10
    ),
    sleep_quality TEXT CHECK(sleep_quality IN ('Poor', 'Average', 'Good')),
    muscle_soreness TEXT CHECK(muscle_soreness IN ('Low', 'Medium', 'High')),
    entry_date DATE NOT NULL,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);
CREATE TABLE predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    risk_score FLOAT NOT NULL CHECK(
        risk_score BETWEEN 0 AND 100
    ),
    risk_level TEXT CHECK(risk_level IN ('Low', 'Medium', 'High')) NOT NULL,
    recommendation TEXT,
    top_factors TEXT,
    model_version VARCHAR(50),
    feature_version VARCHAR(50),
    prediction_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);
CREATE TABLE notifications (
    notif_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
);
CREATE TABLE reports (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL,
    report_type VARCHAR(50) NOT NULL,
    generated_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    file_path VARCHAR(255),
    FOREIGN KEY (coach_id) REFERENCES users (user_id) ON DELETE CASCADE
);
-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_wellness_player_date ON wellness_data(player_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_training_player_date ON training_data(player_id, training_date);
CREATE INDEX IF NOT EXISTS idx_predictions_player_date ON predictions(player_id, prediction_date);
-- System Meta Tracking
CREATE TABLE IF NOT EXISTS system_meta (
    meta_key VARCHAR(50) PRIMARY KEY,
    meta_value TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('last_cleanup_at', '2000-01-01 00:00:00');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('retraining_status', 'idle');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('last_retrained_at', '2000-01-01 00:00:00');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('sample_count_at_last_training', '0');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('retraining_error', '');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('retraining_retry_count', '0');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('training_stage', 'idle');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('last_training_metrics', '{}');
INSERT
    OR IGNORE INTO system_meta (meta_key, meta_value)
VALUES ('active_model_version', 'v1.0.0');