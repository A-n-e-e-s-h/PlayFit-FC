import sqlite3
import os

def test_insert():
    conn = sqlite3.connect('playfit.db')
    cursor = conn.cursor()
    try:
        # Test numeric insert into intensity
        cursor.execute('''
            INSERT INTO training_data (player_id, training_minutes, intensity, sessions_per_week, training_date, participation_status, session_type)
            VALUES (1, 30, '6', 2, '2026-03-18', 'Full Participation', 'Technical & Tactical')
        ''')
        print("Success: Numeric string '6' inserted into intensity.")
        conn.rollback() # Don't commit
    except sqlite3.IntegrityError as e:
        print(f"FAILED (IntegrityError): {e}")
    except sqlite3.OperationalError as e:
        print(f"FAILED (OperationalError): {e}")
    except Exception as e:
        print(f"FAILED (General Error): {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    test_insert()
