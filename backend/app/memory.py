session_memory = {}

def get_memory(session_id: str):
    if session_id not in session_memory:
        session_memory[session_id] = {
            "last_part_number": None,
            "last_model_number": None
        }
    return session_memory[session_id]


def update_memory(session_id: str, part_number=None, model_number=None):
    memory = get_memory(session_id)

    if part_number:
        memory["last_part_number"] = part_number

    if model_number:
        memory["last_model_number"] = model_number