import sqlite3

def check_mismatch():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    coach = cursor.execute("SELECT * FROM users WHERE username = 'coach1@gmail.com'").fetchone()
    if not coach:
        print("Coach not found.")
        return
    
    coach_team = coach['team_code']
    print(f"Coach '{coach['username']}' Team Code: '{coach_team}' (Type: {type(coach_team)})")
    
    # Recent training data
    rows = cursor.execute("""
        SELECT td.training_id, td.player_id, td.training_date, p.name, u.team_code as player_team_code
        FROM training_data td
        JOIN players p ON td.player_id = p.player_id
        JOIN users u ON p.user_id = u.user_id
        ORDER BY td.training_id DESC LIMIT 5
    """).fetchall()
    
    print("\nRecent Training Data:")
    for r in rows:
        match = (r['player_team_code'] == coach_team)
        print(f"ID: {r['training_id']}, Player: {r['name']}, Team: '{r['player_team_code']}', Matches Coach: {match}")

    conn.close()

if __name__ == '__main__':
    check_mismatch()
