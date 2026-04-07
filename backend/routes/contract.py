"""
Sozlesme inceleme endpoint'i.
Yuklenen sozlesmeyi madde bazli analiz eder, risk bayraklari verir.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.claude_service import generate_response, generate_response_stream

router = APIRouter(tags=["contract"])


CONTRACT_REVIEW_PROMPT = """Sen bir sozlesme inceleme uzmanisin. Asagidaki sozlesmeyi madde madde analiz et.

Her madde icin su formati kullan:

## Madde [numara]: [madde basligi]
**Risk Seviyesi**: DUSUK / ORTA / YUKSEK
**Analiz**: [Bu maddenin hukuki degerlendirmesi]
**Oneri**: [Varsa degisiklik onerisi]

---

Analiz sonunda bir OZET RAPOR ekle:

# OZET RAPOR
- **Toplam Madde**: X
- **Dusuk Risk**: X madde
- **Orta Risk**: X madde
- **Yuksek Risk**: X madde
- **Genel Degerlendirme**: [1-2 cumle genel yorum]
- **Kritik Uyarilar**: [Varsa acil dikkat gerektiren maddeler]

DIKKAT:
- Turk hukuku (TBK, TTK, KVKK) perspektifinden degerlendir
- Belirsiz ifadeleri, tek tarafli fesih haklarini, sorumluluk sinirlamalarini ve cezai sart maddelerini ozellikle isaretle
- KVKK kapsaminda kisisel veri isleme maddelerini kontrol et
- Uyusmazlik cozum yontemi (tahkim/mahkeme) ve yetkili mahkeme maddesini degerlendir
"""


class ContractReviewRequest(BaseModel):
    contract_text: str
    contract_type: Optional[str] = None
    focus_areas: Optional[list[str]] = None
    session_id: Optional[str] = None


@router.post("/contract/review")
async def review_contract(req: ContractReviewRequest):
    """Sozlesmeyi madde bazli analiz et, risk raporu uret."""

    if not req.contract_text.strip():
        raise HTTPException(status_code=400, detail="Sozlesme metni bos olamaz")

    if len(req.contract_text) > 100_000:
        raise HTTPException(status_code=400, detail="Sozlesme metni cok uzun (max 100.000 karakter)")

    user_prompt = CONTRACT_REVIEW_PROMPT

    if req.contract_type:
        user_prompt += "\n\nSOZLESME TURU: " + req.contract_type

    if req.focus_areas:
        areas_text = ", ".join(req.focus_areas)
        user_prompt += "\n\nOZELLIKLE DIKKAT EDILECEK ALANLAR: " + areas_text

    user_prompt += "\n\n# SOZLESME METNI\n\n" + req.contract_text

    try:
        analysis = generate_response(
            query=user_prompt,
            rag_context="",
            session_history=None,
            files_context="",
            model="claude-sonnet-4-20250514",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analiz hatasi: {e}")

    risk_counts = {
        "dusuk": analysis.count("\U0001f7e2"),
        "orta": analysis.count("\U0001f7e1"),
        "yuksek": analysis.count("\U0001f534"),
    }

    return {
        "analysis": analysis,
        "risk_summary": risk_counts,
        "contract_length": len(req.contract_text),
    }


class ContractCompareRequest(BaseModel):
    original_text: str
    revised_text: str


@router.post("/contract/compare")
async def compare_contracts(req: ContractCompareRequest):
    """Iki sozlesme versiyonunu karsilastir."""

    if not req.original_text.strip() or not req.revised_text.strip():
        raise HTTPException(status_code=400, detail="Her iki metin de gerekli")

    compare_prompt = (
        "Iki sozlesme versiyonunu karsilastir. Degisiklikleri madde bazli listele.\n\n"
        "# ORIJINAL SOZLESME\n" + req.original_text + "\n\n"
        "# REVIZE SOZLESME\n" + req.revised_text
    )

    try:
        analysis = generate_response(
            query=compare_prompt,
            rag_context="",
            session_history=None,
            files_context="",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Karsilastirma hatasi: {e}")

    return {
        "analysis": analysis,
        "original_length": len(req.original_text),
        "revised_length": len(req.revised_text),
    }


class ContractReviewStreamRequest(BaseModel):
    contract_text: str
    contract_type: Optional[str] = None
    focus_areas: Optional[list[str]] = None


@router.post("/contract/review/stream")
async def review_contract_stream(req: ContractReviewStreamRequest):
    """Sozlesmeyi stream ederek analiz et (SSE)."""

    if not req.contract_text.strip():
        raise HTTPException(status_code=400, detail="Sozlesme metni bos olamaz")

    if len(req.contract_text) > 100_000:
        raise HTTPException(status_code=400, detail="Sozlesme metni cok uzun")

    user_prompt = CONTRACT_REVIEW_PROMPT
    if req.contract_type:
        user_prompt += "\n\nSOZLESME TURU: " + req.contract_type
    if req.focus_areas:
        user_prompt += "\n\nOZELLIKLE DIKKAT: " + ", ".join(req.focus_areas)
    user_prompt += "\n\n# SOZLESME METNI\n\n" + req.contract_text

    async def event_stream():
        full_text = ""
        async for chunk in generate_response_stream(
            query=user_prompt,
            rag_context="",
            session_history=None,
            files_context="",
        ):
            full_text += chunk
            data = json.dumps({"type": "text", "text": chunk}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        risk_counts = {
            "dusuk": full_text.count("\U0001f7e2"),
            "orta": full_text.count("\U0001f7e1"),
            "yuksek": full_text.count("\U0001f534"),
        }
        data = json.dumps({"type": "done", "risk_summary": risk_counts}, ensure_ascii=False)
        yield f"data: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
