import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "storage" / "partselect.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

part = "PS11752778"

cur.execute("SELECT * FROM products WHERE partselect_number = ?", (part,))
product = cur.fetchone()

print(dict(product) if product else "Product not found")

cur.execute("""
SELECT * FROM compatible_models
WHERE partselect_number = ?
LIMIT 5
""", (part,))

for row in cur.fetchall():
    print(dict(row))

conn.close()