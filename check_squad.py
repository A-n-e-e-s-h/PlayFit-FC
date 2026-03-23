import sqlite3

def check_players():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check coach's team code
    coach = cursor.execute("SELECT * FROM users WHERE username = 'coach1@gmail.com'").fetchone()
    if not coach:
        print("Coach coach1@gmail.com not found.")
        return
    
    team_code = coach['team_code']
    print(f"Coach Team Code: {team_code}")
    
    # Check players in that team
    players = cursor.execute("""
        SELECT p.* FROM players p
        JOIN users u ON p.user_id = u.user_id
        WHERE u.team_code = ?
    """, (team_code,)).fetchall()
    
    print(f"Players found: {len(players)}")
    for p in players:
        print(f"ID: {p['player_id']}, Name: {p['name']}")

    conn.close()

if __name__ == '__main__':
    check_players()
