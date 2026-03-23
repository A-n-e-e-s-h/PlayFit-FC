import sqlite3

conn = sqlite3.connect('playfit.db')
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

for table in tables:
    table_name = table[0]
    if table_name != 'sqlite_sequence':
        cursor.execute(f"DELETE FROM {table_name}")

cursor.execute("DELETE FROM sqlite_sequence")
conn.commit()
conn.close()

print('Database cleared.')
