import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

DB_PATH = BASE_DIR / "data" / "storage" / "partselect.db"
PRODUCT_FILE = BASE_DIR / "data" / "parts1" / "enriched" / "product_details_with_main_image_and_crossref.jsonl"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def create_tables(conn):
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partselect_number TEXT UNIQUE,
        manufacturer_part_number TEXT,
        name TEXT,
        price TEXT,
        availability TEXT,
        manufacturer TEXT,
        manufactured_for TEXT,
        description TEXT,
        product_url TEXT,
        main_image TEXT,
        video_url TEXT,
        installation_complexity TEXT,
        installation_time TEXT,
        rating_value REAL,
        rating_count INTEGER,
        symptoms TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS compatible_models (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partselect_number TEXT,
        brand TEXT,
        model_number TEXT,
        model_url TEXT,
        description TEXT,
        FOREIGN KEY(partselect_number) REFERENCES products(partselect_number)
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_part ON products(partselect_number);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_models_part ON compatible_models(partselect_number);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_models_model ON compatible_models(model_number);")

    conn.commit()


def ingest_products(conn):
    cur = conn.cursor()
    inserted = 0
    models_inserted = 0

    with open(PRODUCT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            item = json.loads(line)

            partselect_number = item.get("partselect_number")
            if not partselect_number:
                continue

            cur.execute("""
            INSERT OR REPLACE INTO products (
                partselect_number,
                manufacturer_part_number,
                name,
                price,
                availability,
                manufacturer,
                manufactured_for,
                description,
                product_url,
                main_image,
                video_url,
                installation_complexity,
                installation_time,
                rating_value,
                rating_count,
                symptoms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                partselect_number,
                item.get("manufacturer_part_number"),
                item.get("name"),
                item.get("price"),
                item.get("availability"),
                item.get("manufacturer"),
                item.get("manufactured_for"),
                item.get("description"),
                item.get("product_url"),
                item.get("main_image"),
                item.get("video_url"),
                item.get("installation_complexity"),
                item.get("installation_time"),
                item.get("rating_value"),
                item.get("rating_count"),
                json.dumps(item.get("symptoms") or []) 
            ))

            inserted += 1

            cross_refs = item.get("model_cross_reference") or []
            for ref in cross_refs:
                model_number = ref.get("model_number")
                if not model_number:
                    continue

                cur.execute("""
                INSERT INTO compatible_models (
                    partselect_number,
                    brand,
                    model_number,
                    model_url,
                    description
                )
                VALUES (?, ?, ?, ?, ?)
                """, (
                    partselect_number,
                    ref.get("brand"),
                    model_number,
                    ref.get("model_url"),
                    ref.get("description"),
                ))

                models_inserted += 1

    conn.commit()
    print(f"Inserted products: {inserted}")
    print(f"Inserted compatible models: {models_inserted}")


def main():
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    ingest_products(conn)
    conn.close()
    print(f"SQLite DB created at: {DB_PATH}")


if __name__ == "__main__":
    main()