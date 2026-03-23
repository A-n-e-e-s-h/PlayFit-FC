import sqlite3
import os

def create_database():
    db_path = 'playfit.db'
    schema_path = 'schema.sql'
    
    if not os.path.exists(schema_path):
        print(f"Error: Schema file '{schema_path}' not found.")
        return

    # Connect to SQLite (creates the file if it doesn't exist)
    print(f"Connecting to database '{db_path}'...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Read the schema
    with open(schema_path, 'r') as f:
        schema_script = f.read()

    # Create tables
    try:
        cursor.executescript(schema_script)
        conn.commit()
        print(f"Database '{db_path}' created and schema applied successfully.")
    except sqlite3.Error as e:
        print(f"An SQLite error occurred: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    create_database()
