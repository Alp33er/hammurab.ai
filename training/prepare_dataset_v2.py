#!/usr/bin/env python3
"""
prepare_dataset_v2.py — Claude API ile yüksek kaliteli Türk hukuk Q&A üretimi.

Her madde için Claude Haiku 4.5'tan 3 kaliteli Q&A çifti üretir:
  1. Direkt soru (madde içeriği)
  2. Kavramsal soru (maddenin düzenlediği konu)
  3. Senaryo sorusu (pratik durum)

Çıktı: training/data/hukuk_qa_v2.jsonl  (messages formatında, fine_tune.py uyumlu)

Maliyet tahmini (Haiku 4.5 ile):
  - 5000 madde × ~$0.0028 = ~$14
  - 8000 madde × ~$0.0028 = ~$22
  - 18000 madde × ~$0.0028 = ~$50

Süre tahmini:
  - 5 worker × ~2 sn/madde = ~30-40 dk (5000 madde için)

Kullanım:
  export ANTHROPIC_API_KEY=sk-ant-...
  python training/prepare_dataset_v2.py

ENV override:
  HAMMURAB_MAX_ARTICLES=5000  # subsample (default: 5000, 0=hepsi)
  HAMMURAB_WORKERS=5          # paralel worker sayısı
  HAMMURAB_RESUME=1           # eksik kalan yerden devam et
  HAMMURAB_MODEL=claude-haiku-4-5  # model override
"""

import json
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

import anthropic
from pydantic import BaseModel, Field

# ─── KONFİGÜRASYON ─────────────────────────────────

JSON_DIR = Path(__file__).parent.parent / "scraper" / "data" / "json"
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "hukuk_qa_v2.jsonl"

MODEL = os.environ.get("HAMMURAB_MODEL", "claude-haiku-4-5")
MAX_ARTICLES = int(os.environ.get("HAMMURAB_MAX_ARTICLES", "5000"))  # 0 = tümü
WORKERS = int(os.environ.get("HAMMURAB_WORKERS", "5"))
RESUME = os.environ.get("HAMMURAB_RESUME", "").lower() in ("1", "true", "yes")
SEED = 42

# Eğitimde kullanılacak sistem mesajı (HUKUK_SYSTEM.md ilkeleriyle uyumlu)
TRAINING_SYSTEM_PROMPT = (
    "Sen Türk hukuku konusunda uzman bir hukuk araştırma asistanısın. "
    "Soruları verilen mevzuat metinlerine dayanarak yanıtla, "
    "ilgili kanun maddesini ve referansını mutlaka göster, "
    "context'te olmayan bilgiyi uydurma."
)

# Q&A üretici için Claude'a verilecek talimatlar
GENERATOR_SYSTEM = """Sen Türk hukuku için fine-tuning datasetı üreten uzman bir asistansın.

Görevin: Verilen kanun maddesinden, bir LLM'in eğitiminde kullanılacak 3 yüksek kaliteli soru-cevap çifti üretmek.

ZORUNLU KURALLAR:

1. **Sadakat**: Her cevap, verilen MADDE METNİNE %100 sadık olmalı. Madde dışı bilgi UYDURMA. Maddede olmayan kavram, sayı, tarih, oran KULLANMA.

2. **Kaynak gösterme**: Her cevap madde referansıyla başlamalı. Format:
   "[Kanun no] s. [Kısaltma] m.[Numara] hükmüne göre: ..."
   Örnek: "6098 s. TBK m.49 hükmüne göre: ..."

3. **Cevap uzunluğu**: 80-200 kelime arası. Akıcı, net Türkçe. Cümleler tam bitmeli.

4. **Soru çeşitliliği**: 3 farklı tipte olmalı:
   - **direkt**: Maddenin içeriğini doğrudan soran. Örn: "TBK m.49 ne diyor?"
   - **kavramsal**: Maddenin düzenlediği KONU/KAVRAM hakkında. Örn: "Haksız fiil sorumluluğu nasıl belirlenir?"
   - **senaryo**: Pratik bir hukuki durum. Örn: "Birinin kusuruyla zarar gören kişi ne yapabilir?"

5. **Tutarlılık**: Soru ile cevap KESİN eşleşmeli. Kavramsal/senaryo sorusunun cevabı verilen maddeyi tartışmalı, başka madde uyduramazsın.

6. **Dilbilgisi**: Türkçe imla, ek uyumu, harf hataları olmamalı. Cümle yarıda kesilmemeli.

ÖZEL DURUMLAR:

- Madde "Mülga" ise → qa_pairs: [] (boş liste)
- Madde 50 karakterden kısaysa → qa_pairs: []
- Madde sadece tanım veya başlık ise → qa_pairs: []
- Madde yorumlanamayacak kadar belirsizse → qa_pairs: []

ÖRNEK İYİ Q&A:

Girdi: "6098 s. TBK m.49: Kusurlu ve hukuka aykırı bir fiille başkasına zarar veren, bu zararı gidermekle yükümlüdür..."

Çıktı:
{
  "qa_pairs": [
    {
      "type": "direkt",
      "question": "Türk Borçlar Kanunu madde 49 ne diyor?",
      "answer": "6098 s. TBK m.49 hükmüne göre: Kusurlu ve hukuka aykırı bir fiille başkasına zarar veren, bu zararı gidermekle yükümlüdür. Zarar verici fiili yasaklayan bir hukuk kuralı bulunmasa bile, ahlaka aykırı bir fiille başkasına kasten zarar veren de zararı gidermekle yükümlüdür."
    },
    {
      "type": "kavramsal",
      "question": "Haksız fiil sorumluluğunun temel şartları nelerdir?",
      "answer": "6098 s. TBK m.49 hükmüne göre haksız fiil sorumluluğu için kusur, hukuka aykırılık, zarar ve illiyet bağı şartları aranır. Kusurlu ve hukuka aykırı bir fiille başkasına zarar veren, bu zararı gidermekle yükümlüdür. Ayrıca ahlaka aykırı bir fiille kasten zarar veren de aynı şekilde sorumludur — zarar verici fiili yasaklayan bir hukuk kuralı bulunmasa bile."
    },
    {
      "type": "senaryo",
      "question": "Bir kimsenin dikkatsizliği yüzünden malım hasara uğradı. Ne yapabilirim?",
      "answer": "6098 s. TBK m.49 hükmüne göre, kusurlu ve hukuka aykırı bir fiille zarar veren kişi, verdiği zararı gidermekle yükümlüdür. Dikkatsizlik (taksir) bir kusur halidir; dolayısıyla dikkatsiz davranışıyla malınıza zarar veren kişiden tazminat talep edebilirsiniz. Davayı zarar verenin yerleşim yeri mahkemesinde veya zararın doğduğu yer mahkemesinde açabilirsiniz."
    }
  ]
}

ÖRNEK KÖTÜ (BUNDAN KAÇIN):

❌ Soru "Kıdem tazminatı nasıl hesaplanır?" + Madde 4857 İK m.5 (eşit davranma ilkesi)
   → Madde içeriği soruyla EŞLEŞMİYOR, m.5 kıdem tazminatı düzenlemiyor.

❌ Cevap: "İş kazası durumunda işçi tazminat alır..." + maddede "iş kazası" geçmiyor
   → UYDURMA. Cevap madde metniyle desteklenmiyor.

❌ Cümle yarıda kesik: "İşçi haklarını talep edebilir, ancak"
   → Cümle tamamlanmamış.

JSON dışında HİÇBİR ŞEY yazma. Açıklama, başlık, prefix yok."""


# ─── SCHEMA ────────────────────────────────────────

class QAPair(BaseModel):
    type: str = Field(description="Soru tipi: 'direkt', 'kavramsal' veya 'senaryo'")
    question: str = Field(description="Türkçe soru")
    answer: str = Field(description="Madde referansıyla başlayan, madde metnine sadık cevap")


class QABatch(BaseModel):
    qa_pairs: List[QAPair] = Field(description="3 Q&A çifti, ya da Mülga/anlamsız madde için boş liste")


# ─── GLOBAL STATE ──────────────────────────────────

client = None  # main()'de oluşturulur
write_lock = threading.Lock()
stats = {"processed": 0, "generated": 0, "skipped": 0, "errors": 0}


# ─── YARDIMCI FONKSİYONLAR ─────────────────────────

def already_processed_keys() -> set:
    """Resume: zaten işlenmiş madde anahtarlarını yükle."""
    if not RESUME or not OUTPUT_FILE.exists():
        return set()
    keys = set()
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
                if "_source_key" in item:
                    keys.add(item["_source_key"])
            except Exception:
                pass
    if keys:
        print(f"Resume: {len(keys)} madde zaten işlenmiş, atlanıyor.\n")
    return keys


def make_training_example(qa: QAPair, mevzuat: str, source_key: str) -> dict:
    """Q&A pair'ini fine_tune.py uyumlu messages formatına çevir."""
    user_content = qa.question
    if mevzuat:
        user_content += f"\n\n[İlgili Mevzuat]\n{mevzuat[:1500]}"
    return {
        "messages": [
            {"role": "system", "content": TRAINING_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": qa.answer},
        ],
        "_source_key": source_key,
    }


def generate_qa_for_madde(kanun_ad: str, madde: dict) -> List[dict]:
    """Bir madde için Claude API'den Q&A çiftleri al."""
    text = madde.get("text", "")
    ref = madde.get("ref", "")
    source_key = f"{kanun_ad}::{ref}"

    if len(text) < 50 or "Mülga" in text[:30]:
        stats["skipped"] += 1
        return []

    user_msg = (
        f"KANUN: {kanun_ad}\n"
        f"MADDE REFERANS: {ref}\n"
        f"MADDE METNİ:\n{text[:2500]}"
    )

    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2000,
            system=GENERATOR_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            output_format=QABatch,
        )

        batch = response.parsed_output
        if not batch or not batch.qa_pairs:
            stats["skipped"] += 1
            return []

        examples = [
            make_training_example(qa, text, source_key)
            for qa in batch.qa_pairs
        ]
        stats["generated"] += len(examples)
        return examples

    except anthropic.RateLimitError:
        stats["errors"] += 1
        print(f"  ⏸  Rate limit: {ref}", file=sys.stderr)
        return []
    except Exception as e:
        stats["errors"] += 1
        print(f"  ❌ {ref}: {type(e).__name__}: {e}", file=sys.stderr)
        return []


def write_examples(examples: List[dict]):
    """Thread-safe JSONL append."""
    with write_lock:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")


def load_all_articles() -> list:
    """Tüm kanun maddelerini topla → [(kanun_ad, madde_dict), ...]"""
    index_path = JSON_DIR / "index.json"
    if not index_path.exists():
        print(f"HATA: {index_path} bulunamadı.", file=sys.stderr)
        sys.exit(1)

    index = json.loads(index_path.read_text(encoding="utf-8"))
    articles = []
    for kanun_info in index["kanunlar"]:
        json_path = JSON_DIR / kanun_info["dosya"]
        if not json_path.exists():
            continue
        kanun_data = json.loads(json_path.read_text(encoding="utf-8"))
        kanun_ad = kanun_data.get("kanun_ad", kanun_info["tam_ad"])
        for madde in kanun_data["maddeler"]:
            articles.append((kanun_ad, madde))
    return articles


# ─── MAIN ──────────────────────────────────────────

def main():
    global client

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("HATA: ANTHROPIC_API_KEY environment variable set değil.", file=sys.stderr)
        print("Şunu çalıştır: export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    print(f"Model: {MODEL}")
    print(f"Workers: {WORKERS}")
    print(f"Output: {OUTPUT_FILE}")
    print()

    articles = load_all_articles()
    print(f"Toplam madde sayısı: {len(articles)}")

    # Subsample (cost control)
    if MAX_ARTICLES > 0 and len(articles) > MAX_ARTICLES:
        random.seed(SEED)
        articles = random.sample(articles, MAX_ARTICLES)
        print(f"Subsampled: {len(articles)} madde (HAMMURAB_MAX_ARTICLES={MAX_ARTICLES})")

    # Resume — zaten işlenmiş olanları skip
    seen_keys = already_processed_keys()
    if seen_keys:
        articles = [
            (k, m) for k, m in articles
            if f"{k}::{m.get('ref', '')}" not in seen_keys
        ]
        print(f"Resume sonrası kalan: {len(articles)} madde")
    else:
        if OUTPUT_FILE.exists():
            print(f"Mevcut {OUTPUT_FILE.name} siliniyor (HAMMURAB_RESUME=1 yapmadın).")
            OUTPUT_FILE.unlink()

    # Maliyet tahmini
    est_cost = len(articles) * 0.0028
    print(f"Tahmini maliyet (Haiku 4.5): ~${est_cost:.2f}")
    print(f"\nİşleniyor...\n")

    if not articles:
        print("İşlenecek madde yok. Çıkılıyor.")
        return

    completed = 0
    total = len(articles)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(generate_qa_for_madde, kanun_ad, madde): (kanun_ad, madde)
            for kanun_ad, madde in articles
        }
        for future in as_completed(futures):
            examples = future.result()
            if examples:
                write_examples(examples)
            completed += 1
            stats["processed"] = completed
            if completed % 25 == 0 or completed == total:
                pct = 100 * completed / total
                print(
                    f"  [{completed}/{total} {pct:.0f}%] "
                    f"Q&A: {stats['generated']} | "
                    f"atlanan: {stats['skipped']} | "
                    f"hata: {stats['errors']}"
                )

    print(f"\n{'='*50}")
    print(f"✅ Tamamlandı.")
    print(f"   İşlenen madde: {stats['processed']}")
    print(f"   Üretilen Q&A: {stats['generated']}")
    print(f"   Atlanan (mülga/kısa/anlamsız): {stats['skipped']}")
    print(f"   Hata: {stats['errors']}")
    print(f"   Çıktı: {OUTPUT_FILE}")
    print(f"{'='*50}")
    print(f"\nFine-tune için kullanmak istersen:")
    print(f"  cp {OUTPUT_FILE} {OUTPUT_FILE.parent / 'hukuk_qa.jsonl'}")
    print(f"  # veya environment variable ile:")
    print(f"  HAMMURAB_DATA_PATH={OUTPUT_FILE} python training/fine_tune.py")


if __name__ == "__main__":
    main()
