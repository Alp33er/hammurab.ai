#!/usr/bin/env python3
"""
Yargıtay Karar Arama Scraper
karararama.yargitay.gov.tr'den emsal kararları çeker.

Kullanım:
    python3 yargitay_scraper.py                    # Tüm anahtar kelimeleri tara
    python3 yargitay_scraper.py "kira sözleşmesi"  # Tek anahtar kelime
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests gerekli: pip3 install requests")
    sys.exit(1)

# ─── KONFİGÜRASYON ─────────────────────────────────

DATA_DIR = Path(__file__).parent / "data" / "yargitay"
JSON_DIR = DATA_DIR / "json"

BASE_URL = "https://karararama.yargitay.gov.tr"

# Rate limiting — devlet sitesi, nazik ol
REQUEST_DELAY = 3  # saniye
PAGE_SIZE = 10
MAX_PAGES_PER_QUERY = 20  # max 200 karar per query

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}

# Hukuk alanlarına göre arama terimleri
ARAMA_TERIMLERI = [
    # Borçlar Hukuku
    "kira sözleşmesi fesih",
    "kira tahliye",
    "kira bedeli tespit",
    "tazminat davası",
    "haksız fiil tazminat",
    "sözleşme ihlali",
    "alacak davası",
    "itirazın iptali",
    "menfi tespit",
    "istirdat davası",
    # İş Hukuku
    "işçi alacak ihbar kıdem",
    "iş kazası tazminat",
    "işe iade davası",
    "fazla mesai ücreti",
    "mobbing manevi tazminat",
    # Aile Hukuku
    "boşanma davası",
    "nafaka artırım",
    "velayet değişikliği",
    "tenkis davası miras",
    "mal rejimi tasfiye",
    # Ceza Hukuku
    "hırsızlık ceza",
    "dolandırıcılık ceza",
    "yaralama ceza",
    "hakaret ceza",
    "uyuşturucu ceza",
    "cinsel istismar ceza",
    # Ticaret Hukuku
    "iflas erteleme",
    "çek iptali",
    "şirket ortaklık",
    "haksız rekabet",
    # Taşınmaz Hukuku
    "tapu iptali tescil",
    "kamulaştırma bedel",
    "kat mülkiyeti",
    "ecrimisil tazminat",
    "ortaklığın giderilmesi",
    # İdare Hukuku
    "idari işlem iptali",
    "tam yargı davası",
    # Tüketici Hukuku
    "tüketici ayıplı mal",
    "tüketici kredi",
    # İcra İflas
    "itirazın kaldırılması",
    "istihkak davası",
    "sıra cetveli",
    # Ceza Hukuku
    "kasten yaralama ceza",
    "hırsızlık cezası",
    "dolandırıcılık",
    "adam öldürme kasten",
    "uyuşturucu ticareti",
    "cinsel istismar",
    "tehdit suçu",
    "hakaret suçu",
    # İş Hukuku (ek)
    "kıdem tazminatı hesaplama",
    "ihbar tazminatı",
    "fazla mesai ücreti",
    "iş kazası tazminat",
    "işe iade davası",
    "mobbing iş",
    # Tüketici (ek)
    "ayıplı mal iade",
    "tüketici hakem heyeti",
]


def search_yargitay(keyword: str, page: int = 1) -> list[dict]:
    """Yargıtay karar arama API'sine istek gönder. Sonuç listesi döndürür."""
    payload = {
        "data": {
            "arananKelime": keyword,
            "pageSize": PAGE_SIZE,
            "pageNumber": page,
        }
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/aramalist",
            json=payload,
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        # Nested yapı: {data: {data: [...], recordsFiltered: N}}
        inner = result.get("data", {})
        if isinstance(inner, dict):
            items = inner.get("data", [])
            total = inner.get("recordsFiltered", 0)
            return items, total
        return [], 0
    except requests.exceptions.RequestException as e:
        print(f"  ✗ API hatası: {e}")
        return [], 0


def get_karar_detay(karar_id: str) -> str:
    """Tek bir kararın tam metnini çek. HTML string döndürür."""
    try:
        resp = requests.get(
            f"{BASE_URL}/getDokuman",
            params={"id": karar_id},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        # data doğrudan HTML string
        return result.get("data", "")
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Detay hatası (id={karar_id}): {e}")
        return ""


def clean_karar_text(html_text: str) -> str:
    """HTML etiketlerini temizle, düz metin döndür."""
    import re
    # HTML taglarını kaldır
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    # Fazla boşlukları temizle
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def scrape_keyword(keyword: str, existing_ids: set) -> list[dict]:
    """Bir anahtar kelime için tüm kararları çek."""
    print(f"\n[ARAMA] '{keyword}'")

    kararlar = []
    page = 1

    while page <= MAX_PAGES_PER_QUERY:
        items, total_count = search_yargitay(keyword, page)
        time.sleep(REQUEST_DELAY)

        if not items:
            if page == 1:
                print(f"  Sonuç bulunamadı")
            break

        for item in items:
            karar_id = str(item.get("id", ""))
            if not karar_id or karar_id in existing_ids:
                continue

            # Özet bilgiler
            karar = {
                "id": karar_id,
                "daire": item.get("daire", ""),
                "esas_no": item.get("esasNo", ""),
                "karar_no": item.get("kararNo", ""),
                "tarih": item.get("kararTarihi", ""),
                "anahtar_kelime": keyword,
            }

            # Tam metni çek (HTML)
            html = get_karar_detay(karar_id)
            time.sleep(REQUEST_DELAY)

            if html:
                karar["tam_metin"] = clean_karar_text(html)
            else:
                continue  # Metin yoksa atla

            # Çok kısa kararları atla
            if len(karar["tam_metin"]) < 100:
                continue

            kararlar.append(karar)
            existing_ids.add(karar_id)

            if len(kararlar) % 5 == 0:
                print(f"  {len(kararlar)} karar çekildi...")

        # Sonraki sayfa var mı?
        if page * PAGE_SIZE >= total_count:
            break

        page += 1

    print(f"  ✓ {len(kararlar)} yeni karar")
    return kararlar


def scrape_all(keywords: list[str] = None):
    """Tüm anahtar kelimeler için kararları çek."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    if keywords is None:
        keywords = ARAMA_TERIMLERI

    print("=" * 60)
    print("YARGITAY KARAR SCRAPER — Berry Hukuk AI")
    print(f"Anahtar kelime sayısı: {len(keywords)}")
    print(f"Max karar/kelime: {MAX_PAGES_PER_QUERY * PAGE_SIZE}")
    print("=" * 60)

    # Mevcut kararları yükle (duplicate önleme)
    all_kararlar_path = JSON_DIR / "yargitay_kararlar.json"
    existing_kararlar = []
    existing_ids = set()

    if all_kararlar_path.exists():
        existing_kararlar = json.loads(all_kararlar_path.read_text())
        existing_ids = {k["id"] for k in existing_kararlar}
        print(f"Mevcut karar sayısı: {len(existing_kararlar)}")

    new_total = 0
    for i, keyword in enumerate(keywords, 1):
        print(f"\n--- [{i}/{len(keywords)}] ---")
        new_kararlar = scrape_keyword(keyword, existing_ids)
        existing_kararlar.extend(new_kararlar)
        new_total += len(new_kararlar)

        # Her 5 kelimede ara kaydet
        if i % 5 == 0 and new_total > 0:
            with open(all_kararlar_path, "w", encoding="utf-8") as f:
                json.dump(existing_kararlar, f, ensure_ascii=False, indent=2)
            print(f"\n  [KAYIT] {len(existing_kararlar)} karar kaydedildi")

    # Final kaydet
    with open(all_kararlar_path, "w", encoding="utf-8") as f:
        json.dump(existing_kararlar, f, ensure_ascii=False, indent=2)

    # Index oluştur
    index = {
        "toplam_karar": len(existing_kararlar),
        "yeni_karar": new_total,
        "anahtar_kelimeler": keywords,
        "scrape_date": time.strftime("%Y-%m-%d"),
    }
    with open(JSON_DIR / "yargitay_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print(f"TAMAMLANDI")
    print(f"Toplam karar: {len(existing_kararlar)}")
    print(f"Yeni eklenen: {new_total}")
    print(f"Dosya: {all_kararlar_path}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        keyword = " ".join(sys.argv[1:])
        scrape_all([keyword])
    else:
        scrape_all()
