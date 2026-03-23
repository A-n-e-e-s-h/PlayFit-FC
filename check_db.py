import sqlite3
def check_tables():
    conn = sqlite3.connect('playfit.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [x[0] for x in cursor.fetchall()]
    with open('tables.txt', 'w') as f:
        f.write('\n'.join(tables))
    conn.close()

if __name__ == '__main__':
    check_tables()
