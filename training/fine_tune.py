#!/usr/bin/env python3
"""
Qwen2.5-7B-Instruct + Unsloth + QLoRA Fine-Tuning — Türk Hukuk Q&A.

Hedef ortamlar:
  - Colab Free T4 (16GB)      — varsayılan ayarlar, 1 epoch ~1.5-2 saat
  - Colab Pro+/A100, RunPod   — EPOCHS=3, MAX_SEQ_LENGTH=2048 yapılabilir

Kullanım:
  1. python training/prepare_dataset.py
  2. python training/fine_tune.py

ENV ile override:
  HAMMURAB_OUTPUT_DIR=/content/drive/MyDrive/hammurab_lora python training/fine_tune.py
  HAMMURAB_EPOCHS=3 HAMMURAB_MAX_SEQ=2048 python training/fine_tune.py
  HAMMURAB_RESUME=1 python training/fine_tune.py

NOT: Bu script CUDA GPU + Unsloth gerektirir.
     Kurulum: pip install -r training/requirements.txt
"""

import os
from pathlib import Path

import torch
from datasets import load_dataset

from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
from trl import SFTTrainer, SFTConfig

# ─── KONFİGÜRASYON ─────────────────────────────────

BASE_MODEL = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
DATA_PATH = Path(__file__).parent / "data" / "hukuk_qa.jsonl"

# Çıktı dizini — Colab free için Drive'a yazmak disconnect'e karşı korur
OUTPUT_DIR = Path(os.environ.get(
    "HAMMURAB_OUTPUT_DIR",
    str(Path(__file__).parent.parent / "model"),
))

# Free Colab T4 için güvenli varsayılanlar; A100'de yükseltilebilir
MAX_SEQ_LENGTH = int(os.environ.get("HAMMURAB_MAX_SEQ", "1024"))
EPOCHS = int(os.environ.get("HAMMURAB_EPOCHS", "1"))
RESUME = os.environ.get("HAMMURAB_RESUME", "").lower() in ("1", "true", "yes")

# LoRA
LORA_R = 16
LORA_ALPHA = 16
LORA_DROPOUT = 0.0  # Unsloth optimize: dropout 0 → en hızlı

# Eğitim
BATCH_SIZE = 2          # T4'te kararlı; A100'de 4-8 yapılabilir
GRAD_ACCUM = 4          # Efektif batch = BATCH_SIZE * GRAD_ACCUM
LEARNING_RATE = 2e-4
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
SAVE_STEPS = 200        # Drive'a sık checkpoint — disconnect'te kayıp az olur
SEED = 3407


def main():
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA GPU bulunamadı. Bu script Unsloth ile çalışır → NVIDIA GPU şart.\n"
            "Local Mac için: Colab/RunPod kullan."
        )

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"GPU: {gpu_name}")
    print(f"VRAM: {vram_gb:.1f} GB")
    print(f"BF16 destek: {torch.cuda.is_bf16_supported()}")

    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Veri seti yok: {DATA_PATH}\n"
            f"Önce çalıştır: python training/prepare_dataset.py"
        )

    # ─── Model + Tokenizer ─────────────────────────
    print(f"\nModel yükleniyor: {BASE_MODEL}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,             # auto: T4→fp16, A100→bf16
        load_in_4bit=True,
    )

    # LoRA adapter ekle
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        use_gradient_checkpointing="unsloth",   # %30 daha az VRAM
        random_state=SEED,
        max_seq_length=MAX_SEQ_LENGTH,
    )

    tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")

    # ─── Veri Seti ─────────────────────────────────
    print(f"\nVeri seti: {DATA_PATH}")
    dataset = load_dataset("json", data_files=str(DATA_PATH), split="train")

    def format_messages(batch):
        texts = [
            tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=False
            )
            for msgs in batch["messages"]
        ]
        return {"text": texts}

    dataset = dataset.map(
        format_messages,
        batched=True,
        remove_columns=dataset.column_names,
    )

    split = dataset.train_test_split(test_size=0.1, seed=SEED)
    train_ds, val_ds = split["train"], split["test"]
    print(f"Train: {len(train_ds)} | Val: {len(val_ds)}")

    # ─── Trainer ───────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = OUTPUT_DIR / "checkpoints"

    use_bf16 = torch.cuda.is_bf16_supported()

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LENGTH,
        packing=False,
        args=SFTConfig(
            output_dir=str(checkpoint_dir),
            num_train_epochs=EPOCHS,
            per_device_train_batch_size=BATCH_SIZE,
            per_device_eval_batch_size=BATCH_SIZE,
            gradient_accumulation_steps=GRAD_ACCUM,
            warmup_ratio=WARMUP_RATIO,
            learning_rate=LEARNING_RATE,
            weight_decay=WEIGHT_DECAY,
            lr_scheduler_type="cosine",
            optim="adamw_8bit",
            fp16=not use_bf16,
            bf16=use_bf16,
            logging_steps=10,
            save_strategy="steps",
            save_steps=SAVE_STEPS,
            eval_strategy="steps",
            eval_steps=SAVE_STEPS,
            save_total_limit=2,
            report_to="none",
            seed=SEED,
        ),
    )

    print(f"\n{'='*50}")
    print("Eğitim başlıyor — Qwen2.5-7B QLoRA")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Epochs: {EPOCHS} | Max seq: {MAX_SEQ_LENGTH}")
    print(f"  Batch: {BATCH_SIZE} x {GRAD_ACCUM} grad_accum = {BATCH_SIZE * GRAD_ACCUM} eff. batch")
    print(f"  LR: {LEARNING_RATE} | Precision: {'bf16' if use_bf16 else 'fp16'}")
    print(f"  Checkpoint: her {SAVE_STEPS} adımda → {checkpoint_dir}")
    resume_label = "AÇIK (varsa son checkpoint'ten devam)" if RESUME else "KAPALI"
    print(f"  Resume: {resume_label}")
    print(f"{'='*50}\n")

    resume_arg = True if RESUME and checkpoint_dir.exists() and any(checkpoint_dir.iterdir()) else None
    trainer.train(resume_from_checkpoint=resume_arg)

    # ─── Kaydet ────────────────────────────────────
    print(f"\nLoRA adapter kaydediliyor: {OUTPUT_DIR}")
    model.save_pretrained(str(OUTPUT_DIR))
    tokenizer.save_pretrained(str(OUTPUT_DIR))
    print(f"✓ Tamam.")
    print(
        f"\nÇıkarım için: app.py base modeli (Qwen2.5-7B-Instruct) yükler "
        f"ve {OUTPUT_DIR} altındaki LoRA adapter'ı üzerine bindirir."
    )


if __name__ == "__main__":
    main()
