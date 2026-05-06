import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("OPENAI_API_KEY")

print("Key exists:", bool(key))
print("Key starts:", key[:8] if key else None)