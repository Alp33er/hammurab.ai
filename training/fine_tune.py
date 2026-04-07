#!/usr/bin/env python3
"""
Qwen2.5-1.5B LoRA Fine-Tuning — Hukuk Q&A

Kullanım:
  1. Önce veri seti oluştur:  python training/prepare_dataset.py
  2. Fine-tune başlat:        python training/fine_tune.py

Google Colab T4 GPU'da ~30-45 dk sürer.
"""

import json
import math
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader, random_split
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    get_linear_schedule_with_warmup,
)
from peft import LoraConfig, get_peft_model, TaskType

# ─── KONFİGÜRASYON ─────────────────────────────────

BASE_MODEL = "Qwen/Qwen2.5-1.5B"
DATA_PATH = Path(__file__).parent / "data" / "hukuk_qa.jsonl"
OUTPUT_DIR = Path(__file__).parent.parent / "model"

# Eğitim parametreleri
EPOCHS = 3
BATCH_SIZE = 4
LEARNING_RATE = 2e-4
MAX_LENGTH = 512
WARMUP_RATIO = 0.1
VAL_SPLIT = 0.1
GRADIENT_ACCUMULATION_STEPS = 4

# LoRA parametreleri
LORA_R = 16          # LoRA rank
LORA_ALPHA = 32      # LoRA alpha
LORA_DROPOUT = 0.05  # LoRA dropout


# ─── DATASET ────────────────────────────────────────

class HukukQADataset(Dataset):
    """Hukuk Q&A veri seti — ChatML formatında."""

    def __init__(self, data_path: Path, tokenizer, max_length: int):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.examples = []

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                full_text = item["prompt"] + item["completion"] + tokenizer.eos_token
                self.examples.append(full_text)

        print(f"Veri seti yüklendi: {len(self.examples)} örnek")

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        text = self.examples[idx]
        encoding = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )
        input_ids = encoding["input_ids"].squeeze()
        attention_mask = encoding["attention_mask"].squeeze()

        labels = input_ids.clone()
        labels[attention_mask == 0] = -100

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
        }


# ─── EĞİTİM ────────────────────────────────────────

def train():
    # Device
    if torch.cuda.is_available():
        device = torch.device("cuda")
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        print("Device: Apple MPS")
    else:
        device = torch.device("cpu")
        print("Device: CPU (yavaş olacak!)")

    # Tokenizer
    print(f"\nModel yükleniyor: {BASE_MODEL}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Model — 4-bit quantization (GPU bellek tasarrufu)
    if torch.cuda.is_available():
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
        # MPS veya CPU — quantization olmadan
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=torch.float32,
            trust_remote_code=True,
        )
        model.to(device)

    model.config.pad_token_id = tokenizer.pad_token_id

    # LoRA ayarları
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
    )

    model = get_peft_model(model, lora_config)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Toplam parametre: {total:,}")
    print(f"Eğitilen parametre (LoRA): {trainable:,} ({100 * trainable / total:.2f}%)")

    # Veri seti
    if not DATA_PATH.exists():
        print(f"\nHATA: Veri seti bulunamadı: {DATA_PATH}")
        print("Önce çalıştır: python training/prepare_dataset.py")
        return

    dataset = HukukQADataset(DATA_PATH, tokenizer, MAX_LENGTH)

    val_size = int(len(dataset) * VAL_SPLIT)
    train_size = len(dataset) - val_size
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size])
    print(f"Train: {train_size} | Val: {val_size}")

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE)

    # Optimizer & scheduler
    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=LEARNING_RATE,
        weight_decay=0.01,
    )
    total_steps = len(train_loader) * EPOCHS // GRADIENT_ACCUMULATION_STEPS
    warmup_steps = int(total_steps * WARMUP_RATIO)
    scheduler = get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)

    print(f"\n{'='*50}")
    print(f"Eğitim başlıyor — Qwen2.5-1.5B + LoRA")
    print(f"  Epochs: {EPOCHS}")
    print(f"  Batch size: {BATCH_SIZE} (x{GRADIENT_ACCUMULATION_STEPS} accumulation)")
    print(f"  Effective batch: {BATCH_SIZE * GRADIENT_ACCUMULATION_STEPS}")
    print(f"  Learning rate: {LEARNING_RATE}")
    print(f"  LoRA r={LORA_R}, alpha={LORA_ALPHA}")
    print(f"  Total steps: {total_steps}")
    print(f"{'='*50}\n")

    best_val_loss = float("inf")

    for epoch in range(EPOCHS):
        # ── Train ──
        model.train()
        total_loss = 0
        optimizer.zero_grad()

        for step, batch in enumerate(train_loader):
            if torch.cuda.is_available():
                batch = {k: v.to("cuda") for k, v in batch.items()}
            else:
                batch = {k: v.to(device) for k, v in batch.items()}

            outputs = model(**batch)
            loss = outputs.loss / GRADIENT_ACCUMULATION_STEPS
            loss.backward()

            if (step + 1) % GRADIENT_ACCUMULATION_STEPS == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            total_loss += outputs.loss.item()

            if (step + 1) % 50 == 0:
                avg = total_loss / (step + 1)
                ppl = math.exp(min(avg, 10))
                print(f"  Epoch {epoch+1} | Step {step+1}/{len(train_loader)} | Loss: {avg:.4f} | PPL: {ppl:.2f}")

        avg_train_loss = total_loss / len(train_loader)

        # ── Validation ──
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for batch in val_loader:
                if torch.cuda.is_available():
                    batch = {k: v.to("cuda") for k, v in batch.items()}
                else:
                    batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(**batch)
                val_loss += outputs.loss.item()

        avg_val_loss = val_loss / len(val_loader) if val_loader else 0
        train_ppl = math.exp(min(avg_train_loss, 10))
        val_ppl = math.exp(min(avg_val_loss, 10))

        print(f"\nEpoch {epoch+1}/{EPOCHS}")
        print(f"  Train Loss: {avg_train_loss:.4f} | Train PPL: {train_ppl:.2f}")
        print(f"  Val Loss:   {avg_val_loss:.4f} | Val PPL:   {val_ppl:.2f}")

        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            # LoRA adaptörlerini birleştir ve tam model olarak kaydet
            print(f"  Model birleştiriliyor (merge)...")
            merged = model.merge_and_unload()
            merged.save_pretrained(OUTPUT_DIR)
            tokenizer.save_pretrained(OUTPUT_DIR)
            print(f"  ✓ En iyi model kaydedildi → {OUTPUT_DIR}")

            # Tekrar LoRA model'e dön (eğitime devam etmek için)
            if epoch < EPOCHS - 1:
                model = get_peft_model(merged, lora_config)
                optimizer = torch.optim.AdamW(
                    filter(lambda p: p.requires_grad, model.parameters()),
                    lr=LEARNING_RATE, weight_decay=0.01,
                )
        print()

    print(f"{'='*50}")
    print(f"Eğitim tamamlandı!")
    print(f"En iyi val loss: {best_val_loss:.4f}")
    print(f"Model: {OUTPUT_DIR}")
    print(f"{'='*50}")


if __name__ == "__main__":
    train()
