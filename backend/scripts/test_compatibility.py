import sqlite3

conn = sqlite3.connect("../data/storage/partselect.db")
cur = conn.cursor()

cur.execute("""
SELECT * FROM products
WHERE main_image IS NOT NULL
LIMIT 10
""")

print(cur.fetchall())
conn.close()