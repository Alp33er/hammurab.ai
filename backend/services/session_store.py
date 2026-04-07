"""
Session Store — Redis tabanlı, in-memory fallback.
Chat geçmişi ve dosya verilerini yönetir.

KVKK Uyumu:
- Session'lar TTL ile otomatik silinir (varsayılan: 24 saat)
- Dosya verileri diske yazılmaz
- Session verileri şifrelenebilir (production'da)
"""

import json
import os
from typing import Optional

# Redis opsiyonel
try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

# Konfigürasyon
REDIS_URL = os.environ.get("HUKUK_REDIS_URL", "redis://localhost:6379/0")
SESSION_TTL = int(os.environ.get("HUKUK_SESSION_TTL", "86400"))  # 24 saat (saniye)
MAX_HISTORY_PAIRS = 10  # Son 10 mesaj çifti (20 mesaj)

_redis_client: Optional["redis.Redis"] = None
_memory_store: dict[str, dict] = {}  # Fallback


def _get_redis() -> Optional["redis.Redis"]:
    """Redis bağlantısını lazy al."""
    global _redis_client
    if not HAS_REDIS:
        return None
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client


def _is_redis_available() -> bool:
    return _get_redis() is not None


# ─── CHAT SESSION ────────────────────────────────────

def get_chat_history(session_id: str) -> list[dict]:
    """Session'ın chat geçmişini getir."""
    r = _get_redis()
    if r:
        key = f"hukuk:chat:{session_id}"
        data = r.get(key)
        if data:
            return json.loads(data)
        return []
    else:
        return _memory_store.get(f"chat:{session_id}", {}).get("history", [])


def save_chat_history(session_id: str, history: list[dict]):
    """Chat geçmişini kaydet (son N mesaj çifti)."""
    # Sadece son MAX_HISTORY_PAIRS çifti tut
    trimmed = history[-(MAX_HISTORY_PAIRS * 2):]

    r = _get_redis()
    if r:
        key = f"hukuk:chat:{session_id}"
        r.setex(key, SESSION_TTL, json.dumps(trimmed, ensure_ascii=False))
    else:
        _memory_store[f"chat:{session_id}"] = {"history": trimmed}


def delete_chat_session(session_id: str):
    """Chat session'ı sil (KVKK: unutulma hakkı)."""
    r = _get_redis()
    if r:
        r.delete(f"hukuk:chat:{session_id}")
    else:
        _memory_store.pop(f"chat:{session_id}", None)


# ─── DOSYA SESSION ───────────────────────────────────

MAX_FILES_PER_SESSION = 10


def get_session_files(session_id: str) -> dict[str, dict]:
    """Session'a ait dosyaları getir."""
    r = _get_redis()
    if r:
        key = f"hukuk:files:{session_id}"
        data = r.get(key)
        if data:
            return json.loads(data)
        return {}
    else:
        return _memory_store.get(f"files:{session_id}", {}).get("files", {})


def save_file(session_id: str, file_id: str, file_data: dict) -> bool:
    """Dosyayı session'a kaydet. False dönerse limit aşılmış."""
    files = get_session_files(session_id)
    if len(files) >= MAX_FILES_PER_SESSION:
        return False

    files[file_id] = file_data

    r = _get_redis()
    if r:
        key = f"hukuk:files:{session_id}"
        r.setex(key, SESSION_TTL, json.dumps(files, ensure_ascii=False))
    else:
        _memory_store[f"files:{session_id}"] = {"files": files}

    return True


def delete_file(session_id: str, file_id: str) -> bool:
    """Session'dan dosya sil."""
    files = get_session_files(session_id)
    if file_id not in files:
        return False

    del files[file_id]

    r = _get_redis()
    if r:
        key = f"hukuk:files:{session_id}"
        if files:
            r.setex(key, SESSION_TTL, json.dumps(files, ensure_ascii=False))
        else:
            r.delete(key)
    else:
        if files:
            _memory_store[f"files:{session_id}"] = {"files": files}
        else:
            _memory_store.pop(f"files:{session_id}", None)

    return True


def delete_all_session_data(session_id: str):
    """Session'ın tüm verilerini sil (KVKK: unutulma hakkı)."""
    r = _get_redis()
    if r:
        r.delete(f"hukuk:chat:{session_id}", f"hukuk:files:{session_id}")
    else:
        _memory_store.pop(f"chat:{session_id}", None)
        _memory_store.pop(f"files:{session_id}", None)


def get_files_context(session_id: str) -> str:
    """Session'daki dosyaları Claude context'i olarak formatla."""
    files = get_session_files(session_id)
    if not files:
        return ""

    lines = ["# YÜKLENEN DOSYALAR\n"]
    for fid, f in files.items():
        desc = f" — {f['description']}" if f.get("description") else ""
        lines.append(f"## [{f['name']}{desc}]")
        text = f["text"][:8000]
        if len(f["text"]) > 8000:
            text += f"\n\n[... dosyanın geri kalanı kesildi ({len(f['text'])} karakter toplam)]"
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


# ─── DURUM ───────────────────────────────────────────

def get_store_info() -> dict:
    """Session store durumunu döndür."""
    r = _get_redis()
    if r:
        try:
            info = r.info("keyspace")
            return {
                "backend": "redis",
                "url": REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL,
                "ttl_seconds": SESSION_TTL,
                "info": info,
            }
        except Exception as e:
            return {"backend": "redis", "error": str(e)}
    else:
        return {
            "backend": "memory",
            "session_count": len(_memory_store),
            "ttl_seconds": SESSION_TTL,
            "note": "Redis bağlantısı yok, in-memory fallback aktif",
        }
