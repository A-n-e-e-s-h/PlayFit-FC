import sqlite3

def diag_db():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- Users ---")
    users = cursor.execute("SELECT user_id, username, role, team_code FROM users").fetchall()
    for u in users:
        print(dict(u))
        
    print("\n--- Players ---")
    players = cursor.execute("SELECT player_id, user_id, name FROM players").fetchall()
    for p in players:
        print(dict(p))
        
    print("\n--- Training Data ---")
    training = cursor.execute("SELECT * FROM training_data ORDER BY training_id DESC LIMIT 10").fetchall()
    for t in training:
        print(dict(t))
        
    conn.close()

if __name__ == '__main__':
    diag_db()
