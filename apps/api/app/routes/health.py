from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict:
    return {
        "service": "Earnings Intelligence API",
        "version": "0.1.0",
        "endpoints": {
            "health": "GET /health",
            "chat": "POST /chat",
            "docs": "GET /docs",
        },
    }


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "qdrant_url": settings.qdrant_url,
        "watchlist": settings.default_watchlist,
    }
