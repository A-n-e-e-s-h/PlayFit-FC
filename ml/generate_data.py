import sqlite3
import random
import uuid
from datetime import datetime, timedelta

def generate_synthetic_data(db_path='playfit.db', num_players=10, days=60):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create users & players
    player_ids = []
    for i in range(1, num_players + 1):
        suffix = str(random.randint(1000, 9999))
        username = f'player{i}_{suffix}@example.com'
        # Default user with role player
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, 'password123', 'player')", (username,))
        user_id = cursor.lastrowid
        
        cursor.execute("INSERT INTO players (user_id, name, age, position, experience_years) VALUES (?, ?, ?, ?, ?)",
                       (user_id, f'Synthetic Player {i}', random.randint(18, 35), random.choice(['Forward', 'Midfielder', 'Defender', 'Goalkeeper']), random.randint(0, 15)))
        player_ids.append(cursor.lastrowid)
    
    start_date = datetime.now() - timedelta(days=days)
    
    # Generate data day by day
    for day in range(days):
        current_date = (start_date + timedelta(days=day)).strftime('%Y-%m-%d')
        
        for pid in player_ids:
            # Wellness Data
            fatigue = random.randint(1, 10)
            sleep = random.choice(['Poor', 'Average', 'Good'])
            soreness = random.choice(['Low', 'Medium', 'High'])
            
            cursor.execute("INSERT INTO wellness_data (player_id, fatigue_level, sleep_quality, muscle_soreness, entry_date) VALUES (?, ?, ?, ?, ?)",
                           (pid, fatigue, sleep, soreness, current_date))
            
            # Training Data (approx. 4 days a week)
            if random.random() < 0.6:
                minutes = random.randint(30, 120)
                intensity = random.choice(['Low', 'Medium', 'High'])
                cursor.execute("INSERT INTO training_data (player_id, training_minutes, intensity, sessions_per_week, training_date) VALUES (?, ?, ?, ?, ?)",
                               (pid, minutes, intensity, 4, current_date))
            
            # Simulate Injury (Risk increases with high fatigue, poor sleep, high soreness)
            risk_factor = 0
            if fatigue > 7: risk_factor += 0.3
            if sleep == 'Poor': risk_factor += 0.4
            if soreness == 'High': risk_factor += 0.3
            
            # Base risk is low, but spikes on bad days
            if random.random() < (0.01 + (risk_factor * 0.1)):
                injury_type = random.choice(['Muscle Strain', 'Ankle Sprain', 'Knee Ligament', 'Hamstring'])
                severity = random.choice(['Minor', 'Moderate', 'Severe'])
                recovery = random.randint(3, 30)
                cursor.execute("INSERT INTO injury_history (player_id, injury_type, severity, recovery_days, injury_date) VALUES (?, ?, ?, ?, ?)",
                               (pid, injury_type, severity, recovery, current_date))

    conn.commit()
    conn.close()
    print(f"Generated data for {num_players} players over {days} days.")

if __name__ == "__main__":
    generate_synthetic_data()
