"""
Dosya yükleme endpoint'leri.
Güvenlik: Memory-only, session izolasyonu, boyut/tür kısıtlama.
"""

import re
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from services.file_parser import (
    MAX_FILE_SIZE,
    FileParseError,
    parse_file,
    validate_file,
)
from services.session_store import (
    get_session_files,
    save_file,
    delete_file as store_delete_file,
)

router = APIRouter(tags=["upload"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    description: str = Form(""),
):
    """Dosya yükle, parse et, session'a kaydet."""

    # Boyut ön kontrolü (header'dan)
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük: {file.size / 1024 / 1024:.1f} MB (max 10 MB)",
        )

    # Dosya verisini oku (memory-only)
    data = await file.read()

    # Boyut kontrolü (gerçek veri)
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük: {len(data) / 1024 / 1024:.1f} MB (max 10 MB)",
        )

    # Tür doğrulama
    try:
        file_type = validate_file(
            filename=file.filename or "unknown",
            content_type=file.content_type or "",
            size=len(data),
        )
    except FileParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Parse et
    try:
        text = parse_file(data, file_type)
    except FileParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Güvenlik: Dosya adı sanitize (path traversal koruması)
    safe_filename = re.sub(r'[^\w\s\-\.]', '', file.filename or "unknown")
    safe_filename = safe_filename[:100]

    # Session'a kaydet (Redis veya memory)
    file_id = str(uuid.uuid4())[:8]
    file_data = {
        "name": safe_filename,
        "description": description.strip()[:500],
        "type": file_type,
        "text": text,
        "size": len(data),
        "char_count": len(text),
    }

    if not save_file(session_id, file_id, file_data):
        raise HTTPException(
            status_code=400,
            detail="Session başına en fazla 10 dosya yüklenebilir",
        )

    return {
        "file_id": file_id,
        "name": safe_filename,
        "type": file_type,
        "size": len(data),
        "char_count": len(text),
        "description": description.strip()[:500],
        "preview": text[:300] + ("..." if len(text) > 300 else ""),
    }


@router.delete("/upload/{session_id}/{file_id}")
async def delete_file_endpoint(session_id: str, file_id: str):
    """Session'dan dosya sil."""
    if not store_delete_file(session_id, file_id):
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return {"ok": True}


@router.get("/upload/{session_id}")
async def list_files(session_id: str):
    """Session'daki dosyaları listele."""
    files = get_session_files(session_id)
    return {
        "files": [
            {
                "file_id": fid,
                "name": f["name"],
                "type": f["type"],
                "size": f["size"],
                "char_count": f["char_count"],
                "description": f["description"],
            }
            for fid, f in files.items()
        ]
    }
