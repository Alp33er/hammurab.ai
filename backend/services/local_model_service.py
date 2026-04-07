"""
Lokal Model servisi — Fine-tuned Turkish GPT-2 ile yanıt üretir.
Claude API yerine tamamen lokal çalışır.
"""

from pathlib import Path
from typing import AsyncGenerator

from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

# System prompt'u dosyadan oku
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "HUKUK_SYSTEM.md"

# Fine-tuned model dizini (fine-tuning sonrası buraya kaydedilecek)
MODEL_DIR = Path(__file__).parent.parent.parent / "model"
# Eğer fine-tuned model yoksa HuggingFace'den base model kullan
BASE_MODEL_NAME = "ytu-ce-cosmos/turkish-gpt2"

_model = None
_tokenizer = None


def _load_model():
    """Model ve tokenizer'ı yükle (lazy loading)."""
    global _model, _tokenizer

    if _model is not None:
        return

    # Fine-tuned model varsa onu kullan, yoksa base model
    model_path = str(MODEL_DIR) if MODEL_DIR.exists() else BASE_MODEL_NAME

    print(f"Model yükleniyor: {model_path}")
    _tokenizer = AutoTokenizer.from_pretrained(model_path)
    _model = AutoModelForCausalLM.from_pretrained(model_path)

    # Padding token ayarla (GPT-2'de yoktur)
    if _tokenizer.pad_token is None:
        _tokenizer.pad_token = _tokenizer.eos_token

    _model.eval()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    _model.to(device)
    print(f"Model yüklendi: {model_path} ({device})")


def _load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "Sen Türk hukuku konusunda uzman bir hukuk araştırma asistanısın."


def _build_prompt(query: str, rag_context: str, files_context: str = "",
                  session_history: list[dict] | None = None) -> str:
    """
    GPT-2 için prompt oluştur.
    Fine-tuning sırasında kullanılan format ile aynı olmalı.
    """
    system = _load_system_prompt()

    parts = []

    # System prompt (kısaltılmış — GPT-2 context window küçük)
    parts.append(f"### Sistem:\n{system[:500]}")

    # Önceki konuşma (sadece son 2 tur)
    if session_history:
        for msg in session_history[-4:]:
            role = "Kullanıcı" if msg["role"] == "user" else "Asistan"
            parts.append(f"### {role}:\n{msg['content'][:300]}")

    # RAG context
    if rag_context:
        parts.append(f"### Mevzuat:\n{rag_context[:2000]}")

    # Dosya context
    if files_context:
        parts.append(f"### Dosyalar:\n{files_context[:1000]}")

    # Kullanıcı sorusu
    parts.append(f"### Kullanıcı:\n{query}")

    # Yanıt başlangıcı
    parts.append("### Asistan:\n")

    return "\n\n".join(parts)


def generate_response(
    query: str,
    rag_context: str,
    session_history: list[dict] | None = None,
    files_context: str = "",
    model: str = "",  # uyumluluk için, kullanılmıyor
) -> str:
    """Lokal model ile tam yanıt üret."""
    _load_model()

    prompt = _build_prompt(query, rag_context, files_context, session_history)

    device = next(_model.parameters()).device
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = _model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            top_k=50,
            repetition_penalty=1.2,
            pad_token_id=_tokenizer.eos_token_id,
        )

    # Sadece üretilen kısmı al (prompt hariç)
    generated = outputs[0][inputs["input_ids"].shape[1]:]
    response = _tokenizer.decode(generated, skip_special_tokens=True)

    # "### Kullanıcı" veya "### Sistem" görünce kes (model bazen devam eder)
    for stop in ["### Kullanıcı", "### Sistem", "### Mevzuat", "<|endoftext|>"]:
        if stop in response:
            response = response[:response.index(stop)]

    return response.strip()


async def generate_response_stream(
    query: str,
    rag_context: str,
    session_history: list[dict] | None = None,
    files_context: str = "",
    model: str = "",
) -> AsyncGenerator[str, None]:
    """
    Streaming yanıt üret.
    GPT-2 native streaming desteklemez, bu yüzden tam yanıtı
    parçalara bölerek simüle ediyoruz.
    """
    full_response = generate_response(
        query=query,
        rag_context=rag_context,
        session_history=session_history,
        files_context=files_context,
    )

    # Kelime kelime stream et
    words = full_response.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == 0 else " " + word
        yield chunk
