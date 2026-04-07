"""
Claude API servisi — Hukuk AI yanıtları üretir.
RAG context'ini alır, system prompt ile birleştirir, streaming yanıt döner.
"""

import os
from pathlib import Path
from typing import AsyncGenerator

import anthropic

# System prompt'u dosyadan oku
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "HUKUK_SYSTEM.md"

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable gerekli")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "Sen Türk hukuku konusunda uzman bir hukuk araştırma asistanısın."


def _build_user_content(query: str, rag_context: str, files_context: str = "") -> str:
    """Kullanıcı mesajını RAG ve dosya context'i ile birleştir."""
    parts = [f"# KULLANICI SORUSU\n{query}"]

    if files_context:
        parts.append(f"""# YÜKLENEN DOSYALAR
Aşağıda kullanıcının yüklediği dosyaların içerikleri yer almaktadır.
Bu dosyaları analiz ederken ilgili mevzuat maddelerine referans ver.

{files_context}""")

    parts.append(f"""# MEVZUAT BAĞLAMI (RAG)
Aşağıda sorguyla en alakalı kanun maddeleri yer almaktadır. Yanıtında SADECE bu kaynaklara referans ver.
Burada olmayan maddeleri veya kararları UYDURMA.

{rag_context}""")

    return "\n\n".join(parts)


def generate_response(
    query: str,
    rag_context: str,
    session_history: list[dict] | None = None,
    files_context: str = "",
    model: str = "claude-opus-4-20250514",
) -> str:
    """Tek seferde tam yanıt üret (non-streaming)."""
    client = _get_client()
    system = _load_system_prompt()

    messages = []

    # Önceki konuşma geçmişi
    if session_history:
        messages.extend(session_history)

    user_content = _build_user_content(query, rag_context, files_context)
    messages.append({"role": "user", "content": user_content})

    # Opus modeli non-streaming 10dk timeout aşıyor, streaming ile toplama yapıyoruz
    full_text = ""
    with client.messages.stream(
        model=model,
        max_tokens=32000,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            full_text += text

    return full_text


async def generate_response_stream(
    query: str,
    rag_context: str,
    session_history: list[dict] | None = None,
    files_context: str = "",
    model: str = "claude-opus-4-20250514",
) -> AsyncGenerator[str, None]:
    """Streaming yanıt üret (SSE için)."""
    client = _get_client()
    system = _load_system_prompt()

    messages = []

    if session_history:
        messages.extend(session_history)

    user_content = _build_user_content(query, rag_context, files_context)
    messages.append({"role": "user", "content": user_content})

    with client.messages.stream(
        model=model,
        max_tokens=32000,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
