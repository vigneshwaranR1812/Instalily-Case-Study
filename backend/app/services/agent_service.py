from app.router import classify_intent, extract_part_number, extract_model_number,extract_entities_with_llm
from app.services.sqlite_service import find_product_by_part_number, check_compatibility, get_compatible_models_for_part
from app.services.pinecone_service import search_repair_docs
from app.llm import call_llm
from app.memory import get_memory, update_memory

SYSTEM_RULES = """
You are a PartSelect assistant.
Only answer questions about Refrigerator and Dishwasher parts, compatibility, installation, troubleshooting, and product support.
If the question is outside this scope, politely refuse.
Do not invent product compatibility, price, stock, or installation details.
Use only the provided context.
"""


def answer_chat(message: str, session_id:str):
    memory = get_memory(session_id)
    intent = classify_intent(message)

    if intent == "product_lookup":
        part = extract_part_number(message)
        if part:
            update_memory(session_id, part_number=part)
        else:
            part = memory["last_part_number"]
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
        if part is None:
            part = memory["last_part_number"]

        if model is None:
            model = memory["last_model_number"]
        update_memory(session_id, part_number=part, model_number=model)
        if part is None or model is None:
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

        product = find_product_by_part_number(part)

        return {
            "answer": answer,
            "intent": intent,
            "products": [product] if product else [],
            "sources": [result] if result else [],
            "suggested_actions": [],
            "needs_model_number": False
        }

    if intent == "compatible_models_lookup":
        part = extract_part_number(message)

        if part is None:
            part = memory["last_part_number"]

        if part is None:
            return {
                "answer": "Please provide the PartSelect part number so I can list compatible models.",
                "intent": intent,
                "products": [],
                "sources": [],
                "suggested_actions": [],
                "needs_model_number": False
            }

        update_memory(session_id, part_number=part)

        models = get_compatible_models_for_part(part)

        if not models:
            return {
                "answer": f"I could not find compatible model data for {part}.",
                "intent": intent,
                "products": [],
                "sources": [],
                "suggested_actions": [],
                "needs_model_number": False
            }

        answer = f"I found {len(models)} compatible models for part {part}. Here are some of them."

        return {
            "answer": answer,
            "intent": intent,
            "products": [],
            "sources": models,
            "suggested_actions": [
                {
                    "type": "check_compatibility",
                    "label": "Check my model number",
                    "part_number": part
                }
            ],
            "needs_model_number": False
        }

    if intent in ["installation", "troubleshooting"]:
        import re

        part_number = extract_part_number(message)
        products = []
        docs = []

        # CASE 1: User mentioned a specific PartSelect part number
        if part_number:
            product = find_product_by_part_number(part_number)

            if not product:
                return {
                    "answer": f"I could not find product data for {part_number}. Please check the part number.",
                    "intent": intent,
                    "products": [],
                    "sources": [],
                    "needs_model_number": False,
                    "suggested_actions": []
                }

            products = [product]

            # Search Pinecone with richer query using product data
            search_query = f"""
            {message}
            Part number: {product.get("partselect_number")}
            Product name: {product.get("name")}
            Description: {product.get("description")}
            Symptoms: {product.get("symptoms")}
            Installation complexity: {product.get("installation_complexity")}
            Installation time: {product.get("installation_time")}
            """

            docs = search_repair_docs(search_query)

            context = "\n\n".join(
                f"Source: {d['metadata']}\nContent: {d['content']}"
                for d in docs
            )

            prompt = f"""
    {SYSTEM_RULES}

    User asked:
    {message}

    The user provided a specific PartSelect part number.

    Verified SQLite product data:
    {product}

    Retrieved PartSelect repair/install context:
    {context}

    Rules:
    - Treat the SQLite product data as the source of truth for the part name, part number, symptoms, installation time, installation complexity, video URL, and product URL.
    - If exact installation instructions are not available in the retrieved context, say that the exact official step-by-step instructions were not found in the available data.
    - You may give general safe guidance only if it is clearly based on the product type and context.
    - Do not invent hidden screws, clips, tools, wiring, or appliance-specific steps unless present in the context.
    - If the user asks troubleshooting, explain likely checks using the product symptoms/description and retrieved context.
    - Keep the answer practical and honest.

    Return a clear customer-facing answer.
    """

            return {
                "answer": call_llm(prompt),
                "intent": intent,
                "products": products,
                "sources": [d["metadata"] for d in docs],
                "needs_model_number": True,
                "suggested_actions": [
                    {
                        "type": "check_compatibility",
                        "label": f"Check if {product['partselect_number']} fits my model",
                        "part_number": product["partselect_number"]
                    }
                ]
            }

        docs = search_repair_docs(message)


        context = "\n\n".join(
            f"Source: {d['metadata']}\nContent: {d['content']}"
            for d in docs
        )

        # Extract related PartSelect part numbers from retrieved repair docs
        import re

        all_doc_text = " ".join(d["content"] for d in docs)

        part_numbers = list(set(
            re.findall(r"PS\d+", all_doc_text, re.IGNORECASE)
        ))

        # Fetch matching product details from SQLite
        products = []

        for part_number in part_numbers[:5]:
            product = find_product_by_part_number(part_number.upper())

            if product:
               products.append(product)

        prompt = f"""
{SYSTEM_RULES}

User asked:
{message}

Retrieved PartSelect context:
{context}

Relevant product data:
{products}

Give a clear, step-by-step answer.

For troubleshooting:
- Explain likely causes
- Give simple checks first
- Recommend replacement parts only if supported by the context/product data

For installation:
- Give safe step-by-step installation guidance
- Mention relevant parts when available

Do not answer outside refrigerator or dishwasher repair.
Use only the provided context and product data.
"""

        return {
            "answer": call_llm(prompt),
            "intent": intent,
            "products": products,
            "sources": [d["metadata"] for d in docs],
            "needs_model_number": True if products else False,
            "suggested_actions": [
                {
                    "type": "check_compatibility",
                    "label": f"Check if {p['partselect_number']} fits my model",
                    "part_number": p["partselect_number"]
                }
                for p in products
            ]
        }

    return {
        "answer": "I can only help with Refrigerator and Dishwasher parts, compatibility, installation, troubleshooting, and product support.",
        "intent": "out_of_scope",
        "products": [],
        "sources": []
    }