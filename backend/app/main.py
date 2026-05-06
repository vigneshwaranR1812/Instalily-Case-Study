from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.schemas import ChatRequest, ChatResponse
from app.services.agent_service import answer_chat

app = FastAPI(title="PartSelect Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "service": "PartSelect Agent API"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    result = answer_chat(req.message,req.session_id)
    return result