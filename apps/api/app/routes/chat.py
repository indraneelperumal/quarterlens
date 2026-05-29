from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    ticker: str | None = Field(None, description="Optional ticker hint, e.g. AAPL")


class ChatResponse(BaseModel):
    reply: str
    sources: list[dict] = Field(default_factory=list)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Placeholder — Phase 3 wires Claude + MCP + Qdrant retrieval."""
    ticker = request.ticker or "your watchlist"
    return ChatResponse(
        reply=(
            f"Agent loop not wired yet (Phase 3). You asked: {request.message!r}. "
            f"Ticker hint: {ticker}. Connect API keys in .env and continue with Phase 1 (SEC ingest)."
        ),
        sources=[],
    )
