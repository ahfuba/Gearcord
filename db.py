import sqlite3
import os

DB_PATH = 'shame.db'

def setup_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table to store configurations
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    # Table to track messages that made it to the wall of shame
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shame_messages (
        og_message_id INTEGER PRIMARY KEY,
        og_channel_id INTEGER,
        webhook_message_id INTEGER,
        shame_user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Table to track unique votes (deduplication)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shame_votes (
        og_message_id INTEGER,
        voter_id INTEGER,
        PRIMARY KEY (og_message_id, voter_id),
        FOREIGN KEY (og_message_id) REFERENCES shame_messages(og_message_id)
    )
    ''')

    conn.commit()
    conn.close()

def get_config(key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_config(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

# Initialize DB when this module is imported
setup_db()
