import sqlite3

def migrate():
    conn = sqlite3.connect('playfit.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE training_data ADD COLUMN session_type TEXT DEFAULT 'Technical & Tactical'")
        print("Added session_type column to training_data")
    except sqlite3.OperationalError as e:
        print(f"Column might already exist: {e}")
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate()
