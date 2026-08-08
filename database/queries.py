# pyrefly: ignore [missing-import]
import numpy as np
from database.connection import get_db_connection

def insert_person(vector_array):
    """
        Add a vector 512- dimensions into database, ID will be auto-generated
    """

    conn = get_db_connection()
    cursor = conn.cursor()

    # transfer vector into BLOB form
    vector_blob = vector_array.astype(np.float32).tobytes()

    cursor.execute("""
        INSERT INTO persons (feature_vector) VALUES (?)
    """, (vector_blob,))

    # get ID 
    generated_id = cursor.lastrowid

    conn.commit()
    conn.close()

    print(f"Insert person success with ID : {generated_id}")

    return generated_id

def load_gallery_features():
    """
        load all feature vectors from database
    """

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, feature_vector FROM persons
    """)

    rows = cursor.fetchall()

    conn.close()

    gallery = []
    for row in rows:
        vector = np.frombuffer(row['feature_vector'], dtype=np.float32)
        gallery.append({
            "id" : row['id'],
            "vector" : vector,
        })
    return gallery

def insert_violation(person_id, no_helmet=0, no_glasses=0, no_gloves=0, no_vest=0, image_path=None):
    """
        Insert a PPE violation event into the database
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ppe_violations (person_id, no_helmet, no_glasses, no_gloves, no_vest, image_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (person_id, no_helmet, no_glasses, no_gloves, no_vest, image_path))

    generated_id = cursor.lastrowid
    conn.commit()
    conn.close()

    print(f"Logged PPE violation with ID {generated_id} for Person {person_id}")
    return generated_id

def get_violations_by_person(person_id):
    """
        Load all PPE violations for a specific person_id
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM ppe_violations WHERE person_id = ? ORDER BY violation_time DESC
    """, (person_id,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]