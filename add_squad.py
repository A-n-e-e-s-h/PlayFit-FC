import sqlite3
from werkzeug.security import generate_password_hash

def add_test_players():
    conn = sqlite3.connect('playfit.db')
    cursor = conn.cursor()
    
    # 1. Get coach's team_code
    coach = cursor.execute("SELECT * FROM users WHERE username = 'coach1@gmail.com'").fetchone()
    if not coach:
        print("Coach coach1@gmail.com not found.")
        return
    
    team_code = coach[4] # user_id, username, password, role, team_code
    print(f"Adding players to team {team_code}")
    
    # 2. Add players
    test_players = ["Fix Tester", "Unified Analyst", "Squad Member"]
    for i, name in enumerate(test_players):
        # Create a user record first
        email = f"player{i}@playfit.com"
        cursor.execute("INSERT OR IGNORE INTO users (username, password, role, team_code) VALUES (?, ?, ?, ?)",
                       (email, generate_password_hash('password123'), 'player', team_code))
        user_id = cursor.execute("SELECT user_id FROM users WHERE username = ?", (email,)).fetchone()[0]
        
        # Create player record
        cursor.execute("INSERT OR IGNORE INTO players (user_id, name, age, position, experience_years) VALUES (?, ?, ?, ?, ?)",
                       (user_id, name, 20 + i, 'Forward', 5))
        
    conn.commit()
    print("Test players added.")
    conn.close()

if __name__ == '__main__':
    add_test_players()
