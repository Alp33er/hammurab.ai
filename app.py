#!/usr/bin/env python3
"""
Hammurab.AI — Türk Hukuk Chatbot (Gradio UI)
Fine-tuned Qwen2.5-1.5B + RAG ile hukuki soru-cevap.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import torch
import gradio as gr
from transformers import AutoTokenizer, AutoModelForCausalLM

# ─── MODEL YÜKLEME ─────────────────────────────────

MODEL_DIR = Path(__file__).parent / "model"
BASE_MODEL = "Qwen/Qwen2.5-7B"

model_path = str(MODEL_DIR) if MODEL_DIR.exists() else BASE_MODEL

print(f"Model yükleniyor: {model_path}")
tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True)

if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model.eval()
device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
print(f"Model hazır ({device})")


# ─── RAG (opsiyonel) ───────────────────────────────

rag_available = False
try:
    from rag.retriever import hybrid_retrieve, format_context
    rag_available = True
    print("RAG aktif (ChromaDB + BM25)")
except Exception:
    print("RAG devre dışı (ChromaDB/BM25 index bulunamadı)")


# ─── YANIT ÜRETME ──────────────────────────────────

def generate(soru, history, rag_kullan, max_tokens, temperature):
    """Kullanıcı sorusuna yanıt üret."""

    mevzuat = ""
    kaynaklar = ""
    if rag_kullan and rag_available:
        results = hybrid_retrieve(query=soru, n_results=5)
        if results:
            mevzuat = format_context(results)
            kaynaklar = "\n".join(
                [f"- {r['ref']} ({r.get('dal_label', '')})" for r in results[:5]]
            )

    # ChatML prompt
    prompt = "<|im_start|>system\nSen Türk hukuku konusunda uzman bir hukuk asistanısın. Soruları ilgili mevzuat maddelerine dayanarak yanıtla.<|im_end|>\n"

    # Önceki konuşma (son 2 tur)
    if history:
        for user_msg, bot_msg in history[-2:]:
            prompt += f"<|im_start|>user\n{user_msg}<|im_end|>\n"
            prompt += f"<|im_start|>assistant\n{bot_msg}<|im_end|>\n"

    # Mevzuat + soru
    user_content = soru
    if mevzuat:
        user_content += f"\n\nİlgili Mevzuat:\n{mevzuat[:3000]}"

    prompt += f"<|im_start|>user\n{user_content}<|im_end|>\n"
    prompt += "<|im_start|>assistant\n"

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048).to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=int(max_tokens),
            do_sample=True,
            temperature=float(temperature),
            top_p=0.9,
            top_k=50,
            repetition_penalty=1.2,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = outputs[0][inputs["input_ids"].shape[1]:]
    response = tokenizer.decode(generated, skip_special_tokens=True)

    # Stop token'larda kes
    for stop in ["<|im_start|>", "<|im_end|>", "<|endoftext|>"]:
        if stop in response:
            response = response[:response.index(stop)]

    response = response.strip()

    if kaynaklar:
        response += f"\n\n---\n**Kaynaklar:**\n{kaynaklar}"

    history.append((soru, response))
    return history, ""


# ─── GRADIO ARAYÜZÜ ────────────────────────────────

with gr.Blocks(title="Hammurab.AI") as demo:

    gr.Markdown("""
    # Hammurab.AI — Türk Hukuk Chatbot
    **Fine-tuned Qwen2.5-1.5B** modeli ile hukuki sorularınıza yanıt alın.

    *CIF425 — Introduction to Large Language Models | Term Project*
    """)

    chatbot = gr.Chatbot(label="Sohbet", height=450)

    with gr.Row():
        msg = gr.Textbox(
            label="Sorunuz",
            placeholder="Örn: Kıdem tazminatı nasıl hesaplanır?",
            scale=4,
        )
        send_btn = gr.Button("Gönder", variant="primary", scale=1)

    with gr.Accordion("Ayarlar", open=False):
        with gr.Row():
            rag_toggle = gr.Checkbox(
                label="RAG (Mevzuat Arama)",
                value=False,
                interactive=rag_available,
            )
            max_tokens = gr.Slider(
                minimum=64, maximum=512, value=256, step=32,
                label="Max Token",
            )
            temperature = gr.Slider(
                minimum=0.1, maximum=1.5, value=0.7, step=0.1,
                label="Temperature",
            )

    clear_btn = gr.Button("Sohbeti Temizle")

    gr.Examples(
        examples=[
            "İş kazası durumunda işçinin hakları nelerdir?",
            "Türk Borçlar Kanunu madde 49 ne diyor?",
            "Boşanma davası nasıl açılır?",
            "Kiracının hakları nelerdir?",
            "KVKK kapsamında kişisel veri ihlali cezası nedir?",
        ],
        inputs=msg,
    )

    gr.Markdown(f"**Model:** `{model_path}` | **Device:** `{device}` | **RAG:** `{'Aktif' if rag_available else 'Devre dışı'}`")

    msg.submit(generate, [msg, chatbot, rag_toggle, max_tokens, temperature], [chatbot, msg])
    send_btn.click(generate, [msg, chatbot, rag_toggle, max_tokens, temperature], [chatbot, msg])
    clear_btn.click(lambda: [], outputs=[chatbot])


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
