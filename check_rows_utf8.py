import sqlite3
import io

def check_rows():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    rows = cursor.execute("""
        SELECT training_id, training_minutes, intensity, sessions_per_week, participation_status, session_type 
        FROM training_data 
        ORDER BY training_id DESC LIMIT 10
    """).fetchall()
    
    with io.open('row_check_utf8.txt', 'w', encoding='utf-8') as f:
        for r in rows:
            line = f"ID: {r['training_id']}, Mins: {r['training_minutes']}, Int: {r['intensity']}, Freq: {r['sessions_per_week']}, Status: {r['participation_status']}, Type: {r['session_type']}\n"
            f.write(line)
        
    conn.close()

if __name__ == '__main__':
    check_rows()
