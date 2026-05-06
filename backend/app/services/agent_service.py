from app.router import classify_intent, extract_part_number, extract_model_number,extract_entities_with_llm
from app.services.sqlite_service import find_product_by_part_number, check_compatibility
from app.services.pinecone_service import search_repair_docs
from app.llm import call_llm


SYSTEM_RULES = """
You are a PartSelect assistant.
Only answer questions about Refrigerator and Dishwasher parts, compatibility, installation, troubleshooting, and product support.
If the question is outside this scope, politely refuse.
Do not invent product compatibility, price, stock, or installation details.
Use only the provided context.
"""


def answer_chat(message: str):
    intent = classify_intent(message)

    if intent == "product_lookup":
        part = extract_part_number(message)
        product = find_product_by_part_number(part)

        if not product:
            return {
                "answer": f"I could not find product data for {part}.",
                "intent": intent,
                "products": [],
                "sources": []
            }

        prompt = f"""
{SYSTEM_RULES}

User asked:
{message}

Product data:
{product}

Write a helpful product summary.
"""

        return {
            "answer": call_llm(prompt),
            "intent": intent,
            "products": [product],
            "sources": []
        }

    if intent == "compatibility":
        part, model = extract_entities_with_llm(message)
        print(f"Extracted part: {part}, model: {model}")
        if not part or not model:
            return {
                "answer": "Please provide both the PartSelect part number and your appliance model number.",
                "intent": intent,
                "products": [],
                "sources": []
            }

        result = check_compatibility(part, model)

        if result:
            answer = f"Yes, part {part} is compatible with model {model}."
        else:
            answer = f"I could not verify that part {part} is compatible with model {model}."

        return {
            "answer": answer,
            "intent": intent,
            "products": [],
            "sources": [result] if result else []
        }

    if intent in ["installation", "troubleshooting"]:
        docs = search_repair_docs(message)

        context = "\n\n".join(
            f"Source: {d['metadata']}\nContent: {d['content']}"
            for d in docs
        )

        prompt = f"""
{SYSTEM_RULES}

User asked:
{message}

Retrieved PartSelect context:
{context}

Give a clear, step-by-step answer.
Mention relevant parts when available.
Do not answer outside refrigerator or dishwasher repair.
"""

        return {
            "answer": call_llm(prompt),
            "intent": intent,
            "products": [],
            "sources": [d["metadata"] for d in docs]
        }

    return {
        "answer": "I can only help with Refrigerator and Dishwasher parts, compatibility, installation, troubleshooting, and product support.",
        "intent": "out_of_scope",
        "products": [],
        "sources": []
    }