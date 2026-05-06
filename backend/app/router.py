import re
import json
from openai import OpenAI
from app.config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)


def extract_entities_with_llm(message: str):
    prompt = f"""
Extract the following from the user query:

1. PartSelect part number, it can also be referred to as part number (format: PS12345678)
2. Appliance model number, it can also be referred to as model, model number get the number properly.

Return ONLY valid JSON like:
{{
  "part_number": "...",
  "model_number": "..."
}}

If not found, return null.

User query:
{message}
"""
    print(message)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    content = response.choices[0].message.content.strip()

    # remove markdown fences
    content = content.replace("```json", "").replace("```", "").strip()

    print("RAW LLM OUTPUT:", content)

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


VALID_INTENTS = {
    "product_lookup",
    "compatibility",
    "installation",
    "troubleshooting",
    "out_of_scope",
}


def classify_intent(message: str) -> str:
    prompt = f"""
You are an intent classifier for a PartSelect assistant.

The assistant ONLY supports refrigerator and dishwasher use cases.

Classify the user message into exactly one intent:

1. product_lookup
- User asks about a specific part number or product details.
- Example: "Show me part PS11752778"

2. compatibility
- User asks whether a part fits or works with an appliance model.
- Example: "Is PS11752778 compatible with WDT780SAEM1?"

3. installation
- User asks how to install, replace, remove, or change a part.
- Example: "How do I install PS11752778?"

4. troubleshooting
- User describes an appliance problem, symptom, or broken behaviour.
- Includes dishwasher/refrigerator rack, door, leaking, smell, noise, cooling, draining, cleaning, ice maker, water, sliding, stuck, broken, not working issues.
- Example: "Dishwasher rack not sliding properly"
- Example: "My Whirlpool fridge ice maker is not working"

5. out_of_scope
- Anything not related to refrigerator/dishwasher parts, repair, troubleshooting, installation, or compatibility.

Return ONLY valid JSON:
{{
  "intent": "one_of_the_intents"
}}

User message:
{message}
"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        content = response.choices[0].message.content.strip()
        data = json.loads(content)

        intent = data.get("intent", "out_of_scope")

        if intent in VALID_INTENTS:
            return intent

        return "out_of_scope"

    except Exception as e:
        print("LLM intent classification failed:", e)

        # fallback regex
        msg = message.lower()

        if any(x in msg for x in ["compatible", "fit", "fits", "work with my model"]):
            return "compatibility"

        if any(x in msg for x in ["install", "installation", "replace", "how to change"]):
            return "installation"

        if any(x in msg for x in [
            "not working", "broken", "leaking", "not draining", "not cooling",
            "ice maker", "rack", "slide", "stuck", "door", "noise", "smell"
        ]):
            return "troubleshooting"

        if re.search(r"\bPS\d+\b", message.upper()):
            return "product_lookup"

        return "out_of_scope"