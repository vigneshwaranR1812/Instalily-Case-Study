import sqlite3

conn = sqlite3.connect("../data/storage/partselect.db")
cur = conn.cursor()

cur.execute("""
SELECT * FROM compatible_models
WHERE partselect_number = 'PS11756150'
LIMIT 10
""")

print(cur.fetchall())
conn.close()