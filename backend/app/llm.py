from openai import OpenAI
from app.config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)


def call_llm(prompt: str) -> str:
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    return response.output_text