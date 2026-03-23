import sqlite3
import os

def check_schema():
    db_path = 'playfit.db'
    if not os.path.exists(db_path):
        with open('schema_info.txt', 'w') as f:
            f.write(f"Database {db_path} not found.\n")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(training_data);")
        columns = cursor.fetchall()
        with open('schema_info.txt', 'w') as f:
            if not columns:
                f.write("Table 'training_data' not found or has no columns.\n")
            for col in columns:
                f.write(f"{col}\n")
    except Exception as e:
        with open('schema_info.txt', 'w') as f:
            f.write(f"Error: {str(e)}\n")
    finally:
        conn.close()

if __name__ == '__main__':
    check_schema()
