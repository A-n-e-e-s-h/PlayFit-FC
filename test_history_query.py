import sqlite3

def test_query():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    coach = cursor.execute("SELECT * FROM users WHERE username = 'coach1@gmail.com'").fetchone()
    if not coach:
        print("Coach not found.")
        return
    
    team_code = coach['team_code']
    print(f"Testing query for team_code: '{team_code}'")
    
    history_data = cursor.execute('''
        SELECT td.*, p.name as player_name, u.username
        FROM training_data td
        JOIN players p ON td.player_id = p.player_id
        JOIN users u ON p.user_id = u.user_id
        WHERE u.team_code = ?
        ORDER BY td.training_date DESC, td.training_id DESC
    ''', (team_code,)).fetchall()
    
    print(f"Results found: {len(history_data)}")
    for row in history_data:
        print(dict(row))
        
    conn.close()

if __name__ == '__main__':
    test_query()
