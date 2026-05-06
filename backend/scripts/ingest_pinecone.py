import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from tqdm import tqdm

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]

REPAIR_FILE = BASE_DIR / "data" / "repair_data" / "repairs.jsonl"
BLOG_FILE = BASE_DIR / "data" / "blog_data" / "filtered_articles.jsonl"
PRODUCT_FILE = BASE_DIR / "data" / "parts1" / "enriched" / "product_details_with_main_image_and_crossref.jsonl"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "partselect-agent")

EMBED_MODEL = "text-embedding-3-small"
DIMENSION = 1536
BATCH_SIZE = 50

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY missing")

if not PINECONE_API_KEY:
    raise ValueError("PINECONE_API_KEY missing")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)


def ensure_index():
    existing = [idx["name"] for idx in pc.list_indexes()]

    if INDEX_NAME not in existing:
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud="aws",
                region="us-east-1"
            )
        )

        print("Creating Pinecone index...")
        time.sleep(20)

    return pc.Index(INDEX_NAME)


index = ensure_index()


def embed_texts(texts):
    response = openai_client.embeddings.create(
        model=EMBED_MODEL,
        input=texts
    )
    return [item.embedding for item in response.data]


def safe_text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value)


def upsert_docs(records, namespace):
    for start in range(0, len(records), BATCH_SIZE):
        end = min(start + BATCH_SIZE, len(records))
        batch = records[start:end]

        texts = [r["text"] for r in batch]
        embeddings = embed_texts(texts)

        vectors = []
        for r, emb in zip(batch, embeddings):
            vectors.append({
                "id": r["id"],
                "values": emb,
                "metadata": {
                    **r["metadata"],
                    "text": r["text"][:3500]
                }
            })

        index.upsert(vectors=vectors, namespace=namespace)
        print(f"Upserted {namespace} {start}-{end}/{len(records)}", flush=True)
        time.sleep(0.2)


def ingest_repairs():
    records = []

    if not REPAIR_FILE.exists():
        print("Repair file not found")
        return

    with open(REPAIR_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(tqdm(f, desc="Repair docs")):
            if not line.strip():
                continue

            item = json.loads(line)

            text = f"""
Appliance: {item.get("item")}
Symptom: {item.get("symptom")}
Part: {item.get("part")}

Repair guidance:
{item.get("text")}
""".strip()

            records.append({
                "id": f"repair-{idx}",
                "text": text,
                "metadata": {
                    "source": "repair",
                    "appliance": item.get("item") or "",
                    "symptom": item.get("symptom") or "",
                    "part": item.get("part") or "",
                }
            })

    upsert_docs(records, namespace="repair_guides")


def ingest_blogs():
    records = []

    if not BLOG_FILE.exists():
        print("Blog file not found")
        return

    with open(BLOG_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(tqdm(f, desc="Blog docs")):
            if not line.strip():
                continue

            item = json.loads(line)
            title = item.get("title") or ""
            url = item.get("url") or ""

            for s_idx, section in enumerate(item.get("sections") or []):
                heading = section.get("heading") or "Section"
                text_body = section.get("text") or ""

                if not text_body.strip():
                    continue

                text = f"""
Title: {title}
Section: {heading}

{text_body}
""".strip()

                records.append({
                    "id": f"blog-{idx}-{s_idx}",
                    "text": text,
                    "metadata": {
                        "source": "blog",
                        "title": title,
                        "heading": heading,
                        "url": url,
                        "video": section.get("video") or "",
                    }
                })

    upsert_docs(records, namespace="blog_articles")


def ingest_product_docs():
    records = []

    if not PRODUCT_FILE.exists():
        print("Product file not found")
        return

    with open(PRODUCT_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(tqdm(f, desc="Product docs")):
            if not line.strip():
                continue

            item = json.loads(line)
            part = item.get("partselect_number")

            if not part:
                continue

            text = f"""
Part Number: {part}
Name: {item.get("name")}
Manufacturer Part Number: {item.get("manufacturer_part_number")}
Manufacturer: {item.get("manufacturer")}
Description: {item.get("description")}
Symptoms fixed: {safe_text(item.get("symptoms"))}
Installation complexity: {item.get("installation_complexity")}
Installation time: {item.get("installation_time")}
Video URL: {item.get("video_url")}
""".strip()

            records.append({
                "id": f"product-{part}",
                "text": text,
                "metadata": {
                    "source": "product",
                    "partselect_number": part,
                    "name": item.get("name") or "",
                    "manufacturer": item.get("manufacturer") or "",
                    "product_url": item.get("product_url") or "",
                    "video_url": item.get("video_url") or "",
                }
            })

    upsert_docs(records, namespace="product_docs")


def main():
    print("Starting Pinecone ingestion...")
    ingest_repairs()
    ingest_blogs()
    ingest_product_docs()
    print("Done.")


if __name__ == "__main__":
    main()