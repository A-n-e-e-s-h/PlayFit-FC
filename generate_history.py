import sqlite3
import random
import pandas as pd
from datetime import datetime, timedelta

DB_PATH = 'playfit.db'

def generate_history():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Clear existing data as requested
    print("Clearing existing training, wellness, and match records...")
    cursor.execute("DELETE FROM training_data")
    cursor.execute("DELETE FROM wellness_data")
    cursor.execute("DELETE FROM match_data")
    conn.commit()

    # 2. Get active players
    players = cursor.execute("SELECT player_id, name FROM players").fetchall()
    print(f"Generating 120 days of data for {len(players)} players...")

    today = datetime.now().date()
    # 180 day window
    all_possible_dates = [today - timedelta(days=i) for i in range(2, 182)]
    
    for player in players:
        pid = player['player_id']
        pname = player['name']
        print(f"Processing {pname} (ID: {pid})...")
        
        # 120 unique, non-consecutive dates
        sample_dates = sorted(random.sample(all_possible_dates, 120))
        
        # State
        fatigue = 5
        soreness = 'Low'
        sleep = 'Good'
        injury_days_left = 0
        
        for date_obj in sample_dates:
            date_str = date_obj.strftime('%Y-%m-%d')
            
            # --- Logic: Injury Recovery ---
            if injury_days_left > 0:
                is_injured = 'Yes'
                # Gradual return
                minutes = random.randint(0, 30)
                intensity = 'Low'
                sessions = random.randint(1, 2)
                type = 'recovery'
                match_mins = 0
                fatigue = max(2, fatigue - 1)
                soreness = 'Low'
                injury_days_left -= 1
            else:
                # Occasional Injury trigger (2% chance)
                if random.random() < 0.02:
                    injury_days_left = random.randint(4, 10)
                    is_injured = 'Yes'
                    minutes = 0
                    intensity = 'Low'
                    sessions = 0
                    type = 'recovery'
                    match_mins = 0
                    fatigue = fatigue + 2
                else:
                    is_injured = 'No'
                    # Normal or Match day?
                    if random.random() < 0.15: # ~1 match per week approx
                        type = 'Match Details'
                        minutes = random.randint(30, 45) # Training part
                        intensity = 'High'
                        match_mins = random.randint(60, 90)
                        fatigue = min(10, fatigue + 4)
                        soreness = 'High'
                    else:
                        type = 'Technical & Tactical'
                        minutes = random.randint(60, 110)
                        intensity = random.choice(['Medium', 'High'])
                        match_mins = 0
                        fatigue = max(3, min(9, fatigue + random.randint(-1, 1)))
                        soreness = random.choice(['Low', 'Medium'])
            
            # --- Logic: Sleep Impact ---
            if sleep == 'Poor':
                fatigue = fatigue + 2
            
            # Final clamp to DB constraint
            fatigue = max(1, min(10, fatigue))

            # Next day's sleep
            sleep = random.choices(['Poor', 'Average', 'Good'], weights=[10, 30, 60])[0]

            # Wellness
            cursor.execute('''
                INSERT INTO wellness_data (player_id, fatigue_level, sleep_quality, muscle_soreness, entry_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (pid, int(fatigue), sleep, soreness, date_str))

            # Training
            sessions = random.randint(1, 6)
            cursor.execute('''
                INSERT INTO training_data (player_id, training_minutes, intensity, sessions_per_week, training_date, participation_status, session_type, previous_injury)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (pid, minutes, intensity, sessions, date_str, 'Completed', type, is_injured))

            # Match Data
            if match_mins > 0:
                cursor.execute('''
                    INSERT INTO match_data (player_id, minutes_played, matches_per_week, match_date)
                    VALUES (?, ?, ?, ?)
                ''', (pid, match_mins, 1, date_str))

        print(f"  Finished {pname}.")
        conn.commit()

    conn.close()
    print("Data generation complete.")

if __name__ == "__main__":
    generate_history()
