import sqlite3
from app.config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_product_by_part_number(part_number: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM products
        WHERE partselect_number = ?
        OR manufacturer_part_number = ?
        LIMIT 1
    """, (part_number, part_number))

    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None


def check_compatibility(part_number: str, model_number: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM compatible_models
        WHERE partselect_number = ?
        AND model_number = ?
        LIMIT 1
    """, (part_number, model_number))

    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None

def get_compatible_models_for_part(part_number: str, limit: int = 20):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT brand, model_number, model_url, description
        FROM compatible_models
        WHERE partselect_number = ?
        LIMIT ?
    """, (part_number, limit))

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]