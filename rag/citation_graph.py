#!/usr/bin/env python3
"""
Atıf Zinciri / Citation Graph — Kanun maddeleri ve Yargıtay kararları arası ilişkiler.

Özellikler:
- Kanun maddelerindeki çapraz referansları çıkarır (örn: "TMK m.174" → TMK madde 174)
- Yargıtay kararlarının hangi kanun maddelerine atıf yaptığını tespit eder
- Belirli bir maddeye atıf yapan tüm kararları bulabilir
- JSON olarak kaydeder, retriever'da kullanılabilir

Kullanım:
    python3 rag/citation_graph.py          # Graf oluştur
    python3 rag/citation_graph.py "TMK 174" # Maddeye atıf yapan kararları bul
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

JSON_DIR = Path(__file__).parent.parent / "scraper" / "data" / "json"
YARGITAY_DIR = Path(__file__).parent.parent / "scraper" / "data" / "yargitay" / "json"
GRAPH_PATH = Path(__file__).parent / "citation_graph.json"

# Kanun kısa ad → numara eşleştirme
KANUN_MAP = {
    "tmk": 4721, "tbk": 6098, "tck": 5237, "cmk": 5271, "hmk": 6100,
    "ik": 4857, "ttk": 6102, "iyuk": 2577, "isg": 6331, "sgk": 5510,
    "iik": 2004, "kvkk": 6698, "anayasa": 2709, "tuketici": 6502,
    "kabahatler": 5326, "infaz": 5275, "spk": 6362, "avukatlik": 1136,
}

# Madde referansı pattern'leri
PATTERNS = [
    # "TMK m.174", "TBK md.49", "TCK madde 81"
    re.compile(r'\b([A-ZÇĞİÖŞÜ]{2,10})\s+(?:m\.|md\.|madde\s*)(\d+)', re.IGNORECASE),
    # "4721 sayılı Kanun m.174", "6098 s. TBK m.49"
    re.compile(r'(\d{4})\s+(?:sayılı|s\.)\s+\w+\s+(?:m\.|md\.|madde\s*)(\d+)', re.IGNORECASE),
    # "Borçlar Kanunu'nun 49. maddesi"
    re.compile(r'(\d+)\.\s*maddesi', re.IGNORECASE),
]


def extract_citations(text: str) -> list[dict]:
    """Metindeki kanun maddesi atıflarını çıkar."""
    citations = []
    seen = set()

    for pattern in PATTERNS[:2]:  # İlk 2 pattern
        for match in pattern.finditer(text):
            kanun_or_no = match.group(1).lower()
            madde_no = int(match.group(2))

            # Kanun kısaltmasından numara bul
            if kanun_or_no in KANUN_MAP:
                kanun_no = KANUN_MAP[kanun_or_no]
                kanun_kisa = kanun_or_no
            elif kanun_or_no.isdigit():
                kanun_no = int(kanun_or_no)
                kanun_kisa = next((k for k, v in KANUN_MAP.items() if v == kanun_no), "?")
            else:
                continue

            key = f"{kanun_kisa}_{madde_no}"
            if key not in seen:
                seen.add(key)
                citations.append({
                    "kanun_kisa": kanun_kisa,
                    "kanun_no": kanun_no,
                    "madde_no": madde_no,
                    "ref": f"{kanun_no} s. {kanun_kisa.upper()} m.{madde_no}",
                })

    return citations


def build_graph():
    """Tüm veri kaynaklarından atıf grafını oluştur."""
    print("=" * 60)
    print("ATIF GRAFİ — Berry Hukuk AI")
    print("=" * 60)

    # Graf yapısı
    graph = {
        "madde_to_kararlar": defaultdict(list),   # Madde → hangi kararlar atıf yapıyor
        "karar_to_maddeler": defaultdict(list),    # Karar → hangi maddelere atıf yapıyor
        "madde_to_maddeler": defaultdict(list),    # Madde → hangi maddelere çapraz referans
        "stats": {},
    }

    # 1. Yargıtay kararlarındaki atıfları çıkar
    yargitay_path = YARGITAY_DIR / "yargitay_kararlar.json"
    if yargitay_path.exists():
        kararlar = json.loads(yargitay_path.read_text())
        print(f"Yargıtay kararları: {len(kararlar)}")

        for karar in kararlar:
            karar_id = karar.get("id", "")
            tam_metin = karar.get("tam_metin", "")
            daire = karar.get("daire", "?")
            esas = karar.get("esas_no", "?")
            karar_ref = f"Yargıtay {daire} E.{esas}"

            citations = extract_citations(tam_metin)
            for c in citations:
                madde_key = f"{c['kanun_kisa']}_m{c['madde_no']}"
                graph["madde_to_kararlar"][madde_key].append({
                    "karar_id": karar_id,
                    "ref": karar_ref,
                    "daire": daire,
                })
                graph["karar_to_maddeler"][karar_id].append({
                    "ref": c["ref"],
                    "kanun_kisa": c["kanun_kisa"],
                    "madde_no": c["madde_no"],
                })

        print(f"  Atıf yapılan madde sayısı: {len(graph['madde_to_kararlar'])}")
        total_links = sum(len(v) for v in graph["madde_to_kararlar"].values())
        print(f"  Toplam atıf bağlantısı: {total_links}")

    # 2. Kanun maddeleri arası çapraz referanslar
    index_path = JSON_DIR / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        cross_refs = 0

        for kanun_info in index.get("kanunlar", []):
            json_path = JSON_DIR / kanun_info["dosya"]
            if not json_path.exists():
                continue

            kanun_data = json.loads(json_path.read_text())
            kanun_kisa = kanun_data.get("kanun_kisa", "?")

            for madde in kanun_data.get("maddeler", []):
                madde_key = f"{kanun_kisa}_m{madde['madde_no']}"
                citations = extract_citations(madde["text"])

                for c in citations:
                    # Kendi kendine atıf olmasın
                    if c["kanun_kisa"] == kanun_kisa and c["madde_no"] == madde["madde_no"]:
                        continue
                    target_key = f"{c['kanun_kisa']}_m{c['madde_no']}"
                    graph["madde_to_maddeler"][madde_key].append({
                        "ref": c["ref"],
                        "target": target_key,
                    })
                    cross_refs += 1

        print(f"  Çapraz referans: {cross_refs} bağlantı")

    # İstatistikler
    top_cited = sorted(
        graph["madde_to_kararlar"].items(),
        key=lambda x: len(x[1]),
        reverse=True,
    )[:20]

    graph["stats"] = {
        "toplam_karar": len(graph["karar_to_maddeler"]),
        "atif_yapilan_madde": len(graph["madde_to_kararlar"]),
        "toplam_atif": sum(len(v) for v in graph["madde_to_kararlar"].values()),
        "capraz_referans": sum(len(v) for v in graph["madde_to_maddeler"].values()),
        "en_cok_atif_alan": [
            {"madde": k, "atif_sayisi": len(v)} for k, v in top_cited
        ],
    }

    # defaultdict → dict (JSON serializable)
    graph["madde_to_kararlar"] = dict(graph["madde_to_kararlar"])
    graph["karar_to_maddeler"] = dict(graph["karar_to_maddeler"])
    graph["madde_to_maddeler"] = dict(graph["madde_to_maddeler"])

    # Kaydet
    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print(f"\nGraf kaydedildi: {GRAPH_PATH}")
    print(f"Boyut: {GRAPH_PATH.stat().st_size / 1024:.0f} KB")

    # En çok atıf alan maddeler
    print("\nEN ÇOK ATIF ALAN MADDELER:")
    for item in graph["stats"]["en_cok_atif_alan"][:10]:
        print(f"  {item['madde']:25s} → {item['atif_sayisi']} karar")

    print("=" * 60)
    return graph


def query_citations(madde_query: str):
    """Belirli bir maddeye atıf yapan kararları bul."""
    if not GRAPH_PATH.exists():
        print("Graf bulunamadı. Önce: python3 rag/citation_graph.py")
        return

    graph = json.loads(GRAPH_PATH.read_text())

    # Sorguyu normalize et
    q = madde_query.lower().strip()
    q = re.sub(r'\s+', '_', q)
    if not q.startswith("m"):
        # "TMK 174" → "tmk_m174"
        parts = q.split("_")
        if len(parts) >= 2:
            q = f"{parts[0]}_m{parts[1]}"

    kararlar = graph.get("madde_to_kararlar", {}).get(q, [])
    cross_refs = graph.get("madde_to_maddeler", {}).get(q, [])

    print(f"Sorgu: {q}")
    print(f"Bu maddeye atıf yapan {len(kararlar)} Yargıtay kararı:")
    for k in kararlar[:20]:
        print(f"  - {k['ref']}")

    if cross_refs:
        print(f"\nBu maddeden referans verilen {len(cross_refs)} madde:")
        for c in cross_refs[:10]:
            print(f"  → {c['ref']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        query_citations(" ".join(sys.argv[1:]))
    else:
        build_graph()
