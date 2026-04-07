#!/usr/bin/env python3
"""
Berry Hukuk AI — FastAPI Backend
RAG + Lokal Turkish GPT-2 ile hukuk araştırma servisi.
"""

import os
import sys
from pathlib import Path

# RAG modülünü import edebilmek için (backend/ ve proje kökü)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.chat import router as chat_router
from routes.contract import router as contract_router
from routes.health import router as health_router
from routes.templates import router as templates_router
from routes.upload import router as upload_router

app = FastAPI(
    title="Berry Hukuk AI",
    description="Türk avukatları için AI destekli hukuk araştırma API'si",
    version="0.2.0",
    docs_url=None if os.environ.get("HUKUK_ENV") == "production" else "/docs",
    redoc_url=None if os.environ.get("HUKUK_ENV") == "production" else "/redoc",
)

# ─── GÜVENLİK MİDDLEWARE ────────────────────────────

# CORS — production'da sıkılaştırılmış
ALLOWED_ORIGINS = os.environ.get(
    "HUKUK_CORS_ORIGINS",
    "http://localhost:3000,https://www.playberrygames.com"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


# Rate limiting middleware (basit, IP bazlı)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import time

_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_RPM = int(os.environ.get("HUKUK_RATE_LIMIT_RPM", "30"))  # req/min


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Health check'i muaf tut
        if request.url.path == "/api/health":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Eski kayıtları temizle
        if client_ip in _rate_limit_store:
            _rate_limit_store[client_ip] = [
                t for t in _rate_limit_store[client_ip] if now - t < 60
            ]
        else:
            _rate_limit_store[client_ip] = []

        if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_RPM:
            return JSONResponse(
                status_code=429,
                content={"detail": "Çok fazla istek. Lütfen biraz bekleyin."},
            )

        _rate_limit_store[client_ip].append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# Güvenlik header'ları
from starlette.middleware.base import BaseHTTPMiddleware as _BHM


class SecurityHeadersMiddleware(_BHM):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # KVKK: Veri işleme bildirimi
        response.headers["X-Data-Processing"] = "KVKK-compliant; no-persistent-storage"
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.include_router(health_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(contract_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8100, reload=True)
