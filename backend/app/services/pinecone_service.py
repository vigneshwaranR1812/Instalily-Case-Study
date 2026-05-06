from openai import OpenAI
from pinecone import Pinecone

from app.config import (
    OPENAI_API_KEY,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    EMBEDDING_MODEL,
)

openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)


def embed_query(text: str):
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def search_namespace(query: str, namespace: str, top_k: int = 3):
    vector = embed_query(query)

    results = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )

    matches = results.get("matches", [])

    return [
        {
            "score": match.get("score"),
            "content": match.get("metadata", {}).get("text", ""),
            "metadata": match.get("metadata", {}),
        }
        for match in matches
    ]


def search_repair_docs(query: str):
    repair_docs = search_namespace(query, "repair_guides", 3)
    blog_docs = search_namespace(query, "blog_articles", 2)
    product_docs = search_namespace(query, "product_docs", 2)

    return repair_docs + blog_docs + product_docs