"""Sağlık kontrolü endpoint'leri."""

from fastapi import APIRouter

from services.session_store import get_store_info

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "berry-hukuk-ai",
        "version": "0.2.0",
        "session_store": get_store_info(),
    }
