import sqlite3

def delete_user(email):
    conn = sqlite3.connect('playfit.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = ?", (email,))
    conn.commit()
    print(f"Rows deleted: {cursor.rowcount}")
    conn.close()

if __name__ == '__main__':
    delete_user('aneesh@gmail.com')
