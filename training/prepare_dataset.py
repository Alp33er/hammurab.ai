#!/usr/bin/env python3
"""
Hukuk Q&A veri seti oluşturucu.
Mevcut kanun JSON'larından Qwen ChatML formatında Q&A çiftleri üretir.

Çıktı: training/data/hukuk_qa.jsonl
Format: {"messages": [{"role": "system|user|assistant", "content": "..."}]}
"""

import json
import re
import random
from pathlib import Path

JSON_DIR = Path(__file__).parent.parent / "scraper" / "data" / "json"
YARGITAY_DIR = Path(__file__).parent.parent / "scraper" / "data" / "yargitay" / "json"
OUTPUT_DIR = Path(__file__).parent / "data"

SYSTEM_PROMPT = (
    "Sen Türk hukuku konusunda uzman bir hukuk araştırma asistanısın. "
    "Soruları verilen mevzuat metinlerine dayanarak yanıtla, "
    "ilgili kanun maddesini ve referansını mutlaka göster, "
    "context'te olmayan bilgiyi uydurma."
)

# Soru şablonları
SORU_SABLONLARI = [
    "{kanun_ad} madde {madde_no} ne diyor?",
    "{kanun_ad} {madde_no}. madde neyi düzenliyor?",
    "{kanun_ad} m.{madde_no} hükmü nedir?",
    "{kanun_ad} {madde_no}. maddeye göre hukuki durum nedir?",
    "{ref} hükmünü açıkla.",
    "{kanun_ad} kapsamında {madde_no}. maddenin içeriği nedir?",
]

# Konu bazlı sorular
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
    clean_text = re.sub(r'^Madde\s+\d+[A-Z]?\s*[-–—]\s*', '', text).strip()
    return f"{ref} hükmüne göre: {clean_text}"


def make_example(question: str, answer: str, mevzuat: str = "") -> dict:
    """ChatML mesaj formatında bir eğitim örneği üret."""
    user_content = question
    if mevzuat:
        user_content += f"\n\n[İlgili Mevzuat]\n{mevzuat}"
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": answer},
        ]
    }


def create_qa_from_madde(madde: dict, kanun_ad: str) -> list:
    """Bir kanun maddesinden Q&A çiftleri oluştur."""
    pairs = []
    text = madde["text"]
    ref = madde["ref"]
    madde_no = madde["madde_no"]

    if len(text) < 50 or "Mülga" in text[:30]:
        return []

    answer = generate_answer(madde)

    # Şablon sorular (rastgele 2 tane)
    templates = random.sample(SORU_SABLONLARI, min(2, len(SORU_SABLONLARI)))
    for template in templates:
        question = template.format(
            kanun_ad=kanun_ad,
            madde_no=madde_no,
            ref=ref,
        )
        pairs.append(make_example(question, answer, text[:1500]))

    # Konu bazlı sorular
    text_lower = text.lower()
    for keyword, questions in KONU_SORULARI.items():
        if keyword in text_lower:
            q = random.choice(questions)
            pairs.append(make_example(q, answer, text[:1500]))
            break

    return pairs


def create_qa_from_yargitay(karar: dict) -> list:
    """Yargıtay kararından Q&A çifti oluştur."""
    tam_metin = karar.get("tam_metin", "")
    if len(tam_metin) < 100:
        return []

    daire = karar.get("daire", "")
    esas_no = karar.get("esas_no", "")
    karar_no = karar.get("karar_no", "")

    question = f"Yargıtay {daire} {esas_no} E. {karar_no} K. sayılı karar ne hakkında?"
    answer = f"Yargıtay {daire}, {esas_no} E., {karar_no} K. sayılı kararında: {tam_metin[:500].strip()}"

    return [make_example(question, answer, tam_metin[:1500])]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "hukuk_qa.jsonl"

    all_pairs = []

    index_path = JSON_DIR / "index.json"
    if not index_path.exists():
        print("HATA: index.json bulunamadı!")
        return

    index = json.loads(index_path.read_text())
    print(f"Kanun sayısı: {len(index['kanunlar'])}")

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

    random.shuffle(all_pairs)

    with open(output_path, "w", encoding="utf-8") as f:
        for pair in all_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    print(f"\nToplam: {len(all_pairs)} Q&A çifti → {output_path}")

    val_size = int(len(all_pairs) * 0.1)
    print(f"Önerilen split: {len(all_pairs) - val_size} train / {val_size} val")


if __name__ == "__main__":
    main()
