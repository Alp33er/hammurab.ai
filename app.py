#!/usr/bin/env python3
"""
Hammurab.AI — Türk Hukuk Chatbot (Gradio UI)
Qwen2.5-7B-Instruct (+ opsiyonel QLoRA adapter) + RAG ile hukuki soru-cevap.

ENV override:
  HAMMURAB_MODEL_DIR=/path/to/lora    (varsayılan: ./model)
  HAMMURAB_SHARE=1                     (Gradio public URL — Colab için)
  HAMMURAB_NO_LORA=1                   (LoRA adapter'ı yükleme — sadece base model)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import torch
import gradio as gr
from transformers import AutoTokenizer, AutoModelForCausalLM

# ─── MODEL YÜKLEME ─────────────────────────────────

MODEL_DIR = Path(os.environ.get(
    "HAMMURAB_MODEL_DIR",
    str(Path(__file__).parent / "model"),
))
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# Colab'da otomatik public URL aç
IN_COLAB = "COLAB_GPU" in os.environ or "COLAB_RELEASE_TAG" in os.environ
SHARE = IN_COLAB or os.environ.get("HAMMURAB_SHARE", "").lower() in ("1", "true", "yes")

device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Device: {device}")
print(f"Base model: {BASE_MODEL}")

if device == "cuda":
    # GPU varsa 4-bit quantize ile yükle (T4/L4/A100 hepsinde sığar)
    from transformers import BitsAndBytesConfig
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
else:
    # GPU yok — fp16 (Mac MPS için ~14 GB RAM gerekir)
    print("⚠️  CUDA yok, fp16 yükleniyor (yavaş + bellek yoğun olabilir).")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    if device == "mps":
        model = model.to("mps")

# Tokenizer — model/ varsa fine-tune sonrası kaydedilen tokenizer'ı kullan
tokenizer_path = str(MODEL_DIR) if (MODEL_DIR / "tokenizer.json").exists() else BASE_MODEL
tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# LoRA adapter yükle (varsa ve devre dışı bırakılmadıysa)
adapter_loaded = False
no_lora = os.environ.get("HAMMURAB_NO_LORA", "").lower() in ("1", "true", "yes")
if no_lora:
    print("⏭  HAMMURAB_NO_LORA=1 → adapter yüklenmiyor, sadece base model.")
elif (MODEL_DIR / "adapter_config.json").exists():
    from peft import PeftModel
    print(f"LoRA adapter yükleniyor: {MODEL_DIR}")
    model = PeftModel.from_pretrained(model, str(MODEL_DIR))
    adapter_loaded = True
else:
    print(f"⚠️  LoRA adapter bulunamadı ({MODEL_DIR}). Base model kullanılıyor.")

model.eval()
print(f"Model hazır ({device}) | LoRA: {'aktif' if adapter_loaded else 'devre dışı'}")


# ─── RAG (opsiyonel) ───────────────────────────────

rag_available = False
try:
    from rag.retriever import hybrid_retrieve, format_context
    rag_available = True
    print("RAG aktif (ChromaDB + BM25)")
except Exception:
    print("RAG devre dışı (ChromaDB/BM25 index bulunamadı)")


# ─── YANIT ÜRETME ──────────────────────────────────

SYSTEM_PROMPT = (
    "Sen Türk hukuku konusunda uzman bir hukuk araştırma asistanısın. "
    "Soruları verilen mevzuat metinlerine dayanarak yanıtla, "
    "ilgili kanun maddesini ve referansını mutlaka göster, "
    "context'te olmayan bilgiyi uydurma."
)


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

    user_content = soru
    if mevzuat:
        user_content += f"\n\n[İlgili Mevzuat]\n{mevzuat[:3000]}"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        for user_msg, bot_msg in history[-2:]:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": bot_msg})
    messages.append({"role": "user", "content": user_content})

    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
        truncation=True,
        max_length=2048,
    )
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    input_len = inputs["input_ids"].shape[1]

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=int(max_tokens),
            do_sample=True,
            temperature=float(temperature),
            top_p=0.9,
            top_k=50,
            repetition_penalty=1.1,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = outputs[0][input_len:]
    response = tokenizer.decode(generated, skip_special_tokens=True).strip()

    if kaynaklar:
        response += f"\n\n---\n**Kaynaklar:**\n{kaynaklar}"

    history.append((soru, response))
    return history, ""


# ─── GRADIO ARAYÜZÜ ────────────────────────────────

with gr.Blocks(title="Hammurab.AI") as demo:

    gr.Markdown("""
    # Hammurab.AI — Türk Hukuk Chatbot
    **Fine-tuned Qwen2.5-7B-Instruct (QLoRA)** modeli ile hukuki sorularınıza yanıt alın.

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
                minimum=64, maximum=1024, value=512, step=32,
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

    gr.Markdown(
        f"**Base:** `{BASE_MODEL}` | **Device:** `{device}` | "
        f"**LoRA:** `{'aktif' if adapter_loaded else 'yok'}` | "
        f"**RAG:** `{'aktif' if rag_available else 'yok'}`"
    )

    msg.submit(generate, [msg, chatbot, rag_toggle, max_tokens, temperature], [chatbot, msg])
    send_btn.click(generate, [msg, chatbot, rag_toggle, max_tokens, temperature], [chatbot, msg])
    clear_btn.click(lambda: [], outputs=[chatbot])


if __name__ == "__main__":
    if SHARE:
        # Colab veya HAMMURAB_SHARE=1 → Gradio public URL (gradio.live)
        demo.launch(share=True)
    else:
        demo.launch(server_name="127.0.0.1", server_port=7860)
