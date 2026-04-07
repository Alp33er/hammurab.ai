#!/usr/bin/env python3
"""
Hukuk Q&A veri seti oluşturucu.
Mevcut kanun JSON'larından instruction fine-tuning için Q&A çiftleri üretir.

Çıktı: training/data/hukuk_qa.jsonl
Her satır: {"prompt": "### Kullanıcı:\n...\n\n### Mevzuat:\n...\n\n### Asistan:\n", "completion": "..."}
"""

import json
import random
from pathlib import Path

JSON_DIR = Path(__file__).parent.parent / "scraper" / "data" / "json"
YARGITAY_DIR = Path(__file__).parent.parent / "scraper" / "data" / "yargitay" / "json"
OUTPUT_DIR = Path(__file__).parent / "data"

# Soru şablonları — her kanun maddesi için otomatik Q&A üretimi
SORU_SABLONLARI = [
    "{kanun_ad} madde {madde_no} ne diyor?",
    "{kanun_ad} {madde_no}. madde neyi düzenliyor?",
    "{kanun_ad} m.{madde_no} hükmü nedir?",
    "{kanun_ad} {madde_no}. maddeye göre hukuki durum nedir?",
    "{ref} hükmünü açıkla.",
    "{kanun_ad} kapsamında {madde_no}. maddenin içeriği nedir?",
]

# Daha doğal sorular — konu bazlı (anahtar kelimeye göre)
KONU_SORULARI = {
    "tazminat": [
        "Tazminat hakkında ne gibi düzenlemeler var?",
        "Tazminat nasıl hesaplanır?",
    ],
    "sözleşme": [
        "Sözleşme nasıl kurulur?",
        "Sözleşmenin geçersizlik halleri nelerdir?",
    ],
    "ceza": [
        "Bu suçun cezası nedir?",
        "Cezayı ağırlaştıran haller nelerdir?",
    ],
    "miras": [
        "Miras paylaşımı nasıl yapılır?",
        "Mirasçıların hakları nelerdir?",
    ],
    "boşanma": [
        "Boşanma sebepleri nelerdir?",
        "Boşanma davası nasıl açılır?",
    ],
    "işçi": [
        "İşçinin hakları nelerdir?",
        "İşçi hangi durumlarda tazminat alır?",
    ],
    "kira": [
        "Kiracının hakları nelerdir?",
        "Kira sözleşmesi nasıl sona erer?",
    ],
    "nafaka": [
        "Nafaka nasıl belirlenir?",
        "Nafaka miktarı neye göre hesaplanır?",
    ],
}


def generate_answer(madde: dict) -> str:
    """Madde metninden cevap oluştur."""
    ref = madde["ref"]
    text = madde["text"]

    # "Madde X -" prefix'ini temizle
    import re
    clean_text = re.sub(r'^Madde\s+\d+[A-Z]?\s*[-–—]\s*', '', text).strip()

    return f"{ref} hükmüne göre: {clean_text}"


def create_qa_from_madde(madde: dict, kanun_ad: str) -> list[dict]:
    """Bir kanun maddesinden Q&A çiftleri oluştur."""
    pairs = []
    text = madde["text"]
    ref = madde["ref"]
    madde_no = madde["madde_no"]

    # Çok kısa veya mülga maddeleri atla
    if len(text) < 50 or "Mülga" in text[:30]:
        return []

    answer = generate_answer(madde)

    # 1) Şablon sorular (rastgele 2 tane seç)
    templates = random.sample(SORU_SABLONLARI, min(2, len(SORU_SABLONLARI)))
    for template in templates:
        question = template.format(
            kanun_ad=kanun_ad,
            madde_no=madde_no,
            ref=ref,
        )
        pairs.append({
            "prompt": f"### Kullanıcı:\n{question}\n\n### Mevzuat:\n{text[:1500]}\n\n### Asistan:\n",
            "completion": answer,
        })

    # 2) Konu bazlı sorular (madde metni ilgili anahtar kelimeyi içeriyorsa)
    text_lower = text.lower()
    for keyword, questions in KONU_SORULARI.items():
        if keyword in text_lower:
            q = random.choice(questions)
            pairs.append({
                "prompt": f"### Kullanıcı:\n{q}\n\n### Mevzuat:\n{text[:1500]}\n\n### Asistan:\n",
                "completion": answer,
            })
            break  # Madde başına max 1 konu sorusu

    return pairs


def create_qa_from_yargitay(karar: dict) -> list[dict]:
    """Yargıtay kararından Q&A çifti oluştur."""
    tam_metin = karar.get("tam_metin", "")
    if len(tam_metin) < 100:
        return []

    daire = karar.get("daire", "")
    esas_no = karar.get("esas_no", "")
    karar_no = karar.get("karar_no", "")

    question = f"Yargıtay {daire} {esas_no} E. {karar_no} K. sayılı karar ne hakkında?"
    # Kararın ilk 500 karakterini özet olarak kullan
    answer = f"Yargıtay {daire}, {esas_no} E., {karar_no} K. sayılı kararında: {tam_metin[:500].strip()}"

    return [{
        "prompt": f"### Kullanıcı:\n{question}\n\n### Mevzuat:\n{tam_metin[:1500]}\n\n### Asistan:\n",
        "completion": answer,
    }]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "hukuk_qa.jsonl"

    all_pairs = []

    # Index dosyasını oku
    index_path = JSON_DIR / "index.json"
    if not index_path.exists():
        print("HATA: index.json bulunamadı!")
        return

    index = json.loads(index_path.read_text())
    print(f"Kanun sayısı: {len(index['kanunlar'])}")

    # Her kanundan Q&A üret
    for kanun_info in index["kanunlar"]:
        json_path = JSON_DIR / kanun_info["dosya"]
        if not json_path.exists():
            continue

        kanun_data = json.loads(json_path.read_text())
        kanun_ad = kanun_data.get("kanun_ad", kanun_info["tam_ad"])

        count = 0
        for madde in kanun_data["maddeler"]:
            pairs = create_qa_from_madde(madde, kanun_ad)
            all_pairs.extend(pairs)
            count += len(pairs)

        print(f"  {kanun_info['kisa_ad'].upper():16s} → {count:4d} Q&A çifti")

    # Yargıtay kararları
    yargitay_path = YARGITAY_DIR / "yargitay_kararlar.json"
    if yargitay_path.exists():
        kararlar = json.loads(yargitay_path.read_text())
        yargitay_count = 0
        for karar in kararlar:
            pairs = create_qa_from_yargitay(karar)
            all_pairs.extend(pairs)
            yargitay_count += len(pairs)
        print(f"  {'YARGITAY':16s} → {yargitay_count:4d} Q&A çifti")

    # Karıştır
    random.shuffle(all_pairs)

    # JSONL olarak kaydet
    with open(output_path, "w", encoding="utf-8") as f:
        for pair in all_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    print(f"\nToplam: {len(all_pairs)} Q&A çifti → {output_path}")

    # Train/val split bilgisi
    val_size = int(len(all_pairs) * 0.1)
    print(f"Önerilen split: {len(all_pairs) - val_size} train / {val_size} val")


if __name__ == "__main__":
    main()
