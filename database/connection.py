import sqlite3
import os
import sys

# Add parent directory to sys.path to allow config import when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

def get_db_connection(db_path = DB_PATH):
    """
        initialize database connection SQLite
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row 
    return conn

def initialize_database(db_path = DB_PATH):
    """
        intialize database table 
    """

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # create table 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS persons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_vector BLOB NOT NULL 
        )""")

    # create ppe_violations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ppe_violations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL,
            no_helmet INTEGER DEFAULT 0,
            no_glasses INTEGER DEFAULT 0,
            no_gloves INTEGER DEFAULT 0,
            no_vest INTEGER DEFAULT 0,
            violation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            image_path TEXT,
            FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE
        )""")

    conn.commit()
    conn.close()
    print("Initialize database successfully")

if __name__ == "__main__":
    initialize_database()
        
        