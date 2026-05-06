import os
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "partselect-agent"))

query = "Whirlpool refrigerator ice maker not working"

embedding = openai_client.embeddings.create(
    model="text-embedding-3-small",
    input=query
).data[0].embedding

results = index.query(
    vector=embedding,
    top_k=3,
    namespace="repair_guides",
    include_metadata=True
)

for match in results["matches"]:
    print("SCORE:", match["score"])
    print("META:", match["metadata"])
    print("TEXT:", match["metadata"].get("text", "")[:500])
    print("-" * 80)