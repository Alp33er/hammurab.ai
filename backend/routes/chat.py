"""
Chat endpoint'leri — Hukuk AI soru-cevap.
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from rag.retriever import retrieve, hybrid_retrieve, format_context
from rag.reranker import rerank
from services.local_model_service import generate_response, generate_response_stream
from services.session_store import (
    get_chat_history,
    save_chat_history,
    get_files_context,
    delete_all_session_data,
)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    kanun_filter: Optional[str] = None
    hukuk_dali_filter: Optional[str] = None
    tip_filter: Optional[str] = None
    n_results: int = 15
    stream: bool = True


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[dict]


@router.post("/chat")
async def chat(req: ChatRequest):
    """Hukuk sorusu sor, RAG + Claude ile yanıt al."""

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Sorgu boş olamaz")

    # Input validation — max sorgu uzunluğu
    if len(req.query) > 10_000:
        raise HTTPException(status_code=400, detail="Sorgu çok uzun (max 10.000 karakter)")

    # Session yönetimi (Redis veya in-memory)
    session_id = req.session_id or str(uuid.uuid4())
    history = get_chat_history(session_id)

    # Dosya context'i
    files_context = get_files_context(session_id)

    # RAG sorgusu — takip sorularında bağlam ekle
    rag_query = req.query
    if len(req.query.split()) <= 5 and history:
        last_user_msgs = [m["content"] for m in history if m["role"] == "user"]
        if last_user_msgs:
            rag_query = f"{last_user_msgs[-1]} {req.query}"

    # RAG — ilgili mevzuatı bul
    rag_results = hybrid_retrieve(
        query=rag_query,
        n_results=req.n_results,
        kanun_filter=req.kanun_filter,
        hukuk_dali_filter=req.hukuk_dali_filter,
        include_live=True,
    )
    # Reranking — Claude ile en alakalı sonuçları seç
    if len(rag_results) > 5:
        rag_results = rerank(req.query, rag_results, top_k=req.n_results)
    
    rag_context = format_context(rag_results)

    # Kaynakları hazırla (frontend'e dönecek)
    sources = [
        {
            "ref": r["ref"],
            "kanun_ad": r["kanun_ad"],
            "madde_no": r["madde_no"],
            "score": r["score"],
            "hukuk_dali": r.get("hukuk_dali", "genel"),
            "dal_label": r.get("dal_label", ""),
            "tip": r.get("tip", "kanun"),
        }
        for r in rag_results
    ]

    if req.stream:
        async def event_stream():
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

            full_response = ""
            async for chunk in generate_response_stream(
                query=req.query,
                rag_context=rag_context,
                session_history=history,
                files_context=files_context,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'text', 'text': chunk}, ensure_ascii=False)}\n\n"

            # Session'a kaydet (Redis veya memory)
            history.append({"role": "user", "content": req.query})
            history.append({"role": "assistant", "content": full_response})
            save_chat_history(session_id, history)

            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    else:
        answer = generate_response(
            query=req.query,
            rag_context=rag_context,
            session_history=history,
            files_context=files_context,
        )

        history.append({"role": "user", "content": req.query})
        history.append({"role": "assistant", "content": answer})
        save_chat_history(session_id, history)

        return ChatResponse(
            session_id=session_id,
            answer=answer,
            sources=sources,
        )


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Session verilerini sil (KVKK: unutulma hakkı)."""
    delete_all_session_data(session_id)
    return {"ok": True, "message": "Session verileri silindi"}


@router.get("/search")
async def search(
    query: str,
    kanun_filter: Optional[str] = None,
    hukuk_dali: Optional[str] = None,
    tip: Optional[str] = None,
    n_results: int = 15,
):
    """Sadece mevzuat araması — Claude kullanmadan."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="Sorgu boş olamaz")

    results = retrieve(
        query=query,
        n_results=n_results,
        kanun_filter=kanun_filter,
        hukuk_dali_filter=hukuk_dali,
        tip_filter=tip,
    )
    return {"query": query, "results": results, "count": len(results)}
