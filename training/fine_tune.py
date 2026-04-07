#!/usr/bin/env python3
"""
Turkish GPT-2 Fine-Tuning — Hukuk Q&A

Kullanım:
  1. Önce veri seti oluştur:  python training/prepare_dataset.py
  2. Fine-tune başlat:        python training/fine_tune.py

Google Colab'da çalışır (T4 GPU yeterli).
"""

import json
import math
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader, random_split
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    get_linear_schedule_with_warmup,
)

# ─── KONFİGÜRASYON ─────────────────────────────────

BASE_MODEL = "ytu-ce-cosmos/turkish-gpt2"
DATA_PATH = Path(__file__).parent / "data" / "hukuk_qa.jsonl"
OUTPUT_DIR = Path(__file__).parent.parent / "model"

# Eğitim parametreleri
EPOCHS = 3
BATCH_SIZE = 4
LEARNING_RATE = 5e-5
MAX_LENGTH = 512
WARMUP_RATIO = 0.1
VAL_SPLIT = 0.1
GRADIENT_ACCUMULATION_STEPS = 4


# ─── DATASET ────────────────────────────────────────

class HukukQADataset(Dataset):
    """Hukuk Q&A veri seti — prompt + completion birleşik."""

    def __init__(self, data_path: Path, tokenizer, max_length: int):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.examples = []

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                # Prompt + completion birleştir
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

        # Labels = input_ids (causal LM), padding tokenlarını -100 yap
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
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        print("Device: Apple MPS")
    else:
        device = torch.device("cpu")
        print("Device: CPU (yavaş olacak!)")

    # Model ve tokenizer
    print(f"\nModel yükleniyor: {BASE_MODEL}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        model.config.pad_token_id = tokenizer.pad_token_id

    model.to(device)
    print(f"Parametre sayısı: {sum(p.numel() for p in model.parameters()):,}")

    # Veri seti
    if not DATA_PATH.exists():
        print(f"\nHATA: Veri seti bulunamadı: {DATA_PATH}")
        print("Önce çalıştır: python training/prepare_dataset.py")
        return

    dataset = HukukQADataset(DATA_PATH, tokenizer, MAX_LENGTH)

    # Train/val split
    val_size = int(len(dataset) * VAL_SPLIT)
    train_size = len(dataset) - val_size
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size])
    print(f"Train: {train_size} | Val: {val_size}")

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE)

    # Optimizer & scheduler
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
    total_steps = len(train_loader) * EPOCHS // GRADIENT_ACCUMULATION_STEPS
    warmup_steps = int(total_steps * WARMUP_RATIO)
    scheduler = get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)

    print(f"\n{'='*50}")
    print(f"Eğitim başlıyor")
    print(f"  Epochs: {EPOCHS}")
    print(f"  Batch size: {BATCH_SIZE} (x{GRADIENT_ACCUMULATION_STEPS} accumulation)")
    print(f"  Effective batch: {BATCH_SIZE * GRADIENT_ACCUMULATION_STEPS}")
    print(f"  Learning rate: {LEARNING_RATE}")
    print(f"  Total steps: {total_steps}")
    print(f"  Warmup steps: {warmup_steps}")
    print(f"{'='*50}\n")

    best_val_loss = float("inf")

    for epoch in range(EPOCHS):
        # ── Train ──
        model.train()
        total_loss = 0
        optimizer.zero_grad()

        for step, batch in enumerate(train_loader):
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
                batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(**batch)
                val_loss += outputs.loss.item()

        avg_val_loss = val_loss / len(val_loader) if val_loader else 0
        train_ppl = math.exp(min(avg_train_loss, 10))
        val_ppl = math.exp(min(avg_val_loss, 10))

        print(f"\nEpoch {epoch+1}/{EPOCHS}")
        print(f"  Train Loss: {avg_train_loss:.4f} | Train PPL: {train_ppl:.2f}")
        print(f"  Val Loss:   {avg_val_loss:.4f} | Val PPL:   {val_ppl:.2f}")

        # En iyi modeli kaydet
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(OUTPUT_DIR)
            tokenizer.save_pretrained(OUTPUT_DIR)
            print(f"  ✓ En iyi model kaydedildi → {OUTPUT_DIR}")
        print()

    print(f"{'='*50}")
    print(f"Eğitim tamamlandı!")
    print(f"En iyi val loss: {best_val_loss:.4f}")
    print(f"Model: {OUTPUT_DIR}")
    print(f"{'='*50}")


if __name__ == "__main__":
    train()
