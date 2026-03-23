import sqlite3

def create_table():
    conn = sqlite3.connect('playfit.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (player_id) REFERENCES players (player_id)
        )
    ''')
    conn.commit()
    print("notifications table created successfully.")
    conn.close()

if __name__ == '__main__':
    create_table()
