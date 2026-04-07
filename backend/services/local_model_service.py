"""
Lokal Model servisi — Fine-tuned Qwen2.5-1.5B ile yanıt üretir.
Tamamen lokal çalışır, API gerekmez.
"""

from pathlib import Path
from typing import AsyncGenerator

from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "HUKUK_SYSTEM.md"
MODEL_DIR = Path(__file__).parent.parent.parent / "model"
BASE_MODEL_NAME = "Qwen/Qwen2.5-7B"

_model = None
_tokenizer = None


def _load_model():
    global _model, _tokenizer

    if _model is not None:
        return

    model_path = str(MODEL_DIR) if MODEL_DIR.exists() else BASE_MODEL_NAME

    print(f"Model yükleniyor: {model_path}")
    _tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    _model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True)

    if _tokenizer.pad_token is None:
        _tokenizer.pad_token = _tokenizer.eos_token

    _model.eval()
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    _model.to(device)
    print(f"Model yüklendi: {model_path} ({device})")


def _load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "Sen Türk hukuku konusunda uzman bir hukuk araştırma asistanısın."


def _build_prompt(query: str, rag_context: str, files_context: str = "",
                  session_history: list[dict] | None = None) -> str:
    system = _load_system_prompt()

    prompt = f"<|im_start|>system\n{system[:1000]}<|im_end|>\n"

    if session_history:
        for msg in session_history[-4:]:
            role = "user" if msg["role"] == "user" else "assistant"
            prompt += f"<|im_start|>{role}\n{msg['content'][:500]}<|im_end|>\n"

    user_content = query
    if rag_context:
        user_content += f"\n\nİlgili Mevzuat:\n{rag_context[:3000]}"
    if files_context:
        user_content += f"\n\nDosyalar:\n{files_context[:1000]}"

    prompt += f"<|im_start|>user\n{user_content}<|im_end|>\n"
    prompt += "<|im_start|>assistant\n"

    return prompt


def generate_response(
    query: str,
    rag_context: str,
    session_history: list[dict] | None = None,
    files_context: str = "",
    model: str = "",
) -> str:
    _load_model()

    prompt = _build_prompt(query, rag_context, files_context, session_history)

    device = next(_model.parameters()).device
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
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

    generated = outputs[0][inputs["input_ids"].shape[1]:]
    response = _tokenizer.decode(generated, skip_special_tokens=True)

    for stop in ["<|im_start|>", "<|im_end|>", "<|endoftext|>"]:
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
    full_response = generate_response(
        query=query,
        rag_context=rag_context,
        session_history=session_history,
        files_context=files_context,
    )

    words = full_response.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == 0 else " " + word
        yield chunk
