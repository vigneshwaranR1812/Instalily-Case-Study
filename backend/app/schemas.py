from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    answer: str
    intent: str
    products: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []