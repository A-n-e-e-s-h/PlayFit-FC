import sqlite3

def check_recent_data():
    conn = sqlite3.connect('playfit.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- Recent Training Data (Detailed) ---")
    rows = cursor.execute("""
        SELECT * FROM training_data 
        ORDER BY training_id DESC LIMIT 10
    """).fetchall()
    
    for row in rows:
        print(dict(row))
        
    conn.close()

if __name__ == '__main__':
    check_recent_data()
