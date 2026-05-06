import re
from openai import OpenAI
from app.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def extract_entities_with_llm(message: str):
    prompt = f"""
Extract the following from the user query:

1. PartSelect part number, it can also be referred to as part number (format: PS12345678)
2. Appliance model number, it can also be referred to as model, model number

Return ONLY valid JSON like:
{{
  "part_number": "...",
  "model_number": "..."
}}

If not found, return null.

User query:
{message}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    content = response.choices[0].message.content.strip()

    try:
        import json
        data = json.loads(content)
        print(data)
        return data.get("part_number"), data.get("model_number")
    except:
        return None, None


def extract_part_number(text: str):
    match = re.search(r"\bPS\d+\b", text.upper())
    return match.group(0) if match else None


def extract_model_number(text: str):
    # Example: WDT780SAEM1
    match = re.search(r"\b[A-Z0-9]{6,15}\b", text.upper())
    if match and not match.group(0).startswith("PS"):
        return match.group(0)
    return None


def classify_intent(message: str):
    msg = message.lower()

    if any(x in msg for x in ["compatible", "fit", "fits", "work with my model"]):
        return "compatibility"

    if any(x in msg for x in ["install", "installation", "replace", "how to change"]):
        return "installation"

    if any(x in msg for x in ["not working", "broken", "leaking", "not draining", "not cooling", "ice maker"]):
        return "troubleshooting"

    if re.search(r"\bPS\d+\b", message.upper()):
        return "product_lookup"

    return "out_of_scope"