from fastapi import APIRouter

from app.models.chat import ChatRequest, ChatResponse
from app.services.ai_service import handle_chat

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    return await handle_chat(
        payload.message,
        payload.current_location.latitude,
        payload.current_location.longitude,
    )
