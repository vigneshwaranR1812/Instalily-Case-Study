## Data Pipeline

The scraper generates three JSONL datasets:

1. `filtered_articles.jsonl` - PartSelect blog articles related to refrigerators and dishwashers.
2. `repairs.jsonl` - symptom-level repair guidance for refrigerator and dishwasher issues.
3. `product_details_with_main_image_and_crossref.jsonl` - structured product information, images, videos, and model compatibility data.

The ingestion layer stores:

- Product, price, image, availability, and compatibility data in SQLite.
- Repair guides, blog articles, and product descriptions in ChromaDB for semantic retrieval.

SQLite is used for deterministic lookup queries such as part number search and model compatibility. ChromaDB is used for troubleshooting and installation-style questions where semantic retrieval is more effective.