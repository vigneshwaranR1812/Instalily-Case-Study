import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

db = BASE_DIR / "data" / "storage" / "partselect.db"
chroma = BASE_DIR / "data" / "storage" / "chroma"

if db.exists():
    db.unlink()
    print("Deleted SQLite DB")

if chroma.exists():
    shutil.rmtree(chroma)
    print("Deleted Chroma DB")