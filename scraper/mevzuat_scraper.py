#!/usr/bin/env python3
"""
mevzuat.gov.tr Kanun Scraper
Resmi Gazete'den kanun PDF'lerini indirir ve madde bazlı JSON'a çevirir.
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# PyPDF2 gerekli: pip3 install PyPDF2
try:
    from PyPDF2 import PdfReader
except ImportError:
    print("PyPDF2 gerekli: pip3 install PyPDF2")
    sys.exit(1)

# ─── KONFİGÜRASYON ─────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"
PDF_DIR = DATA_DIR / "pdf"
JSON_DIR = DATA_DIR / "json"

# Temel kanunlar listesi
# Format: (kanun_no, tertip, kısa_ad, tam_ad)
KANUNLAR = [
    # ── TEMEL KANUNLAR (20 mevcut) ──
    (2709, 5, "anayasa", "Türkiye Cumhuriyeti Anayasası"),
    (4721, 5, "tmk", "Türk Medeni Kanunu"),
    (6098, 5, "tbk", "Türk Borçlar Kanunu"),
    (6100, 5, "hmk", "Hukuk Muhakemeleri Kanunu"),
    (5237, 5, "tck", "Türk Ceza Kanunu"),
    (5271, 5, "cmk", "Ceza Muhakemesi Kanunu"),
    (4857, 5, "ik", "İş Kanunu"),
    (6102, 5, "ttk", "Türk Ticaret Kanunu"),
    (2577, 5, "iyuk", "İdari Yargılama Usulü Kanunu"),
    (6331, 5, "isg", "İş Sağlığı ve Güvenliği Kanunu"),
    (5510, 5, "sgk", "Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu"),
    (2004, 5, "iik", "İcra ve İflas Kanunu"),
    (6325, 5, "arabuluculuk", "Hukuk Uyuşmazlıklarında Arabuluculuk Kanunu"),
    (6502, 5, "tuketici", "Tüketicinin Korunması Hakkında Kanun"),
    (4734, 5, "ihale", "Kamu İhale Kanunu"),
    (5846, 5, "fsek", "Fikir ve Sanat Eserleri Kanunu"),
    (6769, 5, "sinai", "Sınai Mülkiyet Kanunu"),
    (3065, 5, "kdv", "Katma Değer Vergisi Kanunu"),
    (193,  5, "gvk", "Gelir Vergisi Kanunu"),
    (5520, 5, "kvk", "Kurumlar Vergisi Kanunu"),
    # ── YENİ EKLENEN KANUNLAR (30 ek) ──
    # Kişisel Veri & Bilgi
    (6698, 5, "kvkk", "Kişisel Verilerin Korunması Kanunu"),
    (4982, 5, "bilgi_edinme", "Bilgi Edinme Hakkı Kanunu"),
    # Ceza & İnfaz
    (5326, 5, "kabahatler", "Kabahatler Kanunu"),
    (5275, 5, "infaz", "Ceza ve Güvenlik Tedbirlerinin İnfazı Hakkında Kanun"),
    # Aile & Kişi
    (6284, 5, "ailenin_korunmasi", "Ailenin Korunması ve Kadına Karşı Şiddetin Önlenmesine Dair Kanun"),
    (5901, 5, "vatandaslik", "Türk Vatandaşlık Kanunu"),
    (5490, 5, "nufus", "Nüfus Hizmetleri Kanunu"),
    # Taşınmaz & İmar
    (634,  5, "kat_mulkiyeti", "Kat Mülkiyeti Kanunu"),
    (2644, 5, "tapu", "Tapu Kanunu"),
    (3402, 5, "kadastro", "Kadastro Kanunu"),
    (2942, 5, "kamulastirma", "Kamulaştırma Kanunu"),
    (3194, 5, "imar", "İmar Kanunu"),
    # Vergi & Tahsilat
    (213,  5, "vuk", "Vergi Usul Kanunu"),
    (6183, 5, "aatuhk", "Amme Alacaklarının Tahsili Hakkında Kanun"),
    # Finans & Ticaret
    (5411, 5, "bankacilik", "Bankacılık Kanunu"),
    (6362, 5, "spk", "Sermaye Piyasası Kanunu"),
    (5941, 5, "cek", "Çek Kanunu"),
    # İş & Sendika
    (6356, 5, "sendikalar", "Sendikalar ve Toplu İş Sözleşmesi Kanunu"),
    # Meslek Kanunları
    (1136, 5, "avukatlik", "Avukatlık Kanunu"),
    (1512, 5, "noterlik", "Noterlik Kanunu"),
    # İdare & Yerel Yönetim
    (5393, 5, "belediye", "Belediye Kanunu"),
    (5216, 5, "buyuksehir", "Büyükşehir Belediyesi Kanunu"),
    (2872, 5, "cevre", "Çevre Kanunu"),
    (4735, 5, "ihale_sozlesmeleri", "Kamu İhale Sözleşmeleri Kanunu"),
    # Trafik & Ulaşım
    (2918, 5, "trafik", "Karayolları Trafik Kanunu"),
    # Dernekler & Sivil Toplum
    (5253, 5, "dernekler", "Dernekler Kanunu"),
    # Yargı Teşkilatı
    (6216, 5, "aym", "Anayasa Mahkemesi Kuruluş Kanunu"),
    (2797, 5, "yargitay", "Yargıtay Kanunu"),
    # Miras & Veraset
    (7338, 5, "veraset", "Veraset ve İntikal Vergisi Kanunu"),
    # Tebligat
    (7201, 5, "tebligat", "Tebligat Kanunu"),
]

# ─── PDF İNDİRME ─────────────────────────────────────

def download_pdf(kanun_no: int, tertip: int, kisa_ad: str) -> Path:
    """mevzuat.gov.tr'den kanun PDF'ini indir."""
    pdf_path = PDF_DIR / f"{kisa_ad}_{kanun_no}.pdf"

    if pdf_path.exists():
        print(f"  ✓ PDF zaten var: {pdf_path.name}")
        return pdf_path

    url = f"https://www.mevzuat.gov.tr/MevzuatMetin/1.{tertip}.{kanun_no}.pdf"
    print(f"  ↓ İndiriliyor: {url}")

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Berry Games Hukuk AI Research"
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            pdf_data = response.read()

        pdf_path.write_bytes(pdf_data)
        size_kb = len(pdf_data) / 1024
        print(f"  ✓ İndirildi: {pdf_path.name} ({size_kb:.0f} KB)")
        return pdf_path
    except Exception as e:
        print(f"  ✗ Hata: {e}")
        return None


# ─── PDF PARSE ───────────────────────────────────────

def extract_text_from_pdf(pdf_path: Path) -> str:
    """PDF'den tüm metni çıkar."""
    reader = PdfReader(str(pdf_path))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def parse_maddeler(text: str, kanun_no: int, kisa_ad: str, tam_ad: str) -> dict:
    """Ham metinden maddeleri ayıkla ve yapılandır."""

    # Madde pattern: "Madde 1-" veya "MADDE 1 –" veya "Madde 1 -" vb.
    # Türk mevzuatında madde formatları değişkendir
    madde_pattern = re.compile(
        r'(?:MADDE|Madde)\s+(\d+)\s*[-–—/]',
        re.IGNORECASE
    )

    # Tüm madde başlangıç pozisyonlarını bul
    matches = list(madde_pattern.finditer(text))

    maddeler = []
    for i, match in enumerate(matches):
        madde_no = int(match.group(1))
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        madde_text = text[start:end].strip()

        # Çok kısa maddeleri atla (muhtemelen parse hatası)
        if len(madde_text) < 20:
            continue

        # Madde metnini temizle
        madde_text = re.sub(r'\s+', ' ', madde_text)  # Fazla boşlukları kaldır
        madde_text = madde_text.strip()

        maddeler.append({
            "madde_no": madde_no,
            "text": madde_text,
            "kanun_no": kanun_no,
            "kanun_ad": tam_ad,
            "kanun_kisa": kisa_ad,
            "ref": f"{kanun_no} s. {kisa_ad.upper()} m.{madde_no}",
        })

    # Duplicate madde numaralarını kaldır (son olanı tut)
    seen = {}
    for m in maddeler:
        seen[m["madde_no"]] = m
    maddeler = sorted(seen.values(), key=lambda x: x["madde_no"])

    result = {
        "kanun_no": kanun_no,
        "kanun_ad": tam_ad,
        "kanun_kisa": kisa_ad,
        "toplam_madde": len(maddeler),
        "maddeler": maddeler,
        "scrape_date": time.strftime("%Y-%m-%d"),
    }

    return result


# ─── ANA FONKSİYON ───────────────────────────────────

def scrape_all():
    """Tüm kanunları indir ve parse et."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("MEVZUAT SCRAPER — Berry Hukuk AI")
    print("=" * 60)
    print(f"Toplam kanun: {len(KANUNLAR)}")
    print()

    results = []

    for kanun_no, tertip, kisa_ad, tam_ad in KANUNLAR:
        print(f"[{kisa_ad.upper()}] {tam_ad} (No: {kanun_no})")

        # PDF indir
        pdf_path = download_pdf(kanun_no, tertip, kisa_ad)
        if not pdf_path:
            results.append({"kanun": tam_ad, "status": "HATA", "madde": 0})
            continue

        # PDF'den metin çıkar
        try:
            text = extract_text_from_pdf(pdf_path)
            print(f"  ✓ Metin çıkarıldı: {len(text):,} karakter")
        except Exception as e:
            print(f"  ✗ PDF okuma hatası: {e}")
            results.append({"kanun": tam_ad, "status": "PDF_HATA", "madde": 0})
            continue

        # Maddeleri parse et
        kanun_data = parse_maddeler(text, kanun_no, kisa_ad, tam_ad)

        # JSON kaydet
        json_path = JSON_DIR / f"{kisa_ad}_{kanun_no}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(kanun_data, f, ensure_ascii=False, indent=2)

        print(f"  ✓ {kanun_data['toplam_madde']} madde parse edildi → {json_path.name}")
        results.append({"kanun": tam_ad, "status": "OK", "madde": kanun_data['toplam_madde']})

        # Rate limiting
        time.sleep(1)

    # Özet
    print()
    print("=" * 60)
    print("ÖZET")
    print("=" * 60)
    total_madde = 0
    for r in results:
        status_icon = "✓" if r["status"] == "OK" else "✗"
        print(f"  {status_icon} {r['kanun']}: {r['madde']} madde ({r['status']})")
        total_madde += r["madde"]
    print(f"\nToplam: {total_madde} madde, {len([r for r in results if r['status'] == 'OK'])}/{len(results)} kanun başarılı")

    # Birleşik index dosyası
    index = {
        "kanunlar": [],
        "toplam_madde": total_madde,
        "toplam_kanun": len([r for r in results if r["status"] == "OK"]),
        "scrape_date": time.strftime("%Y-%m-%d"),
    }
    for kanun_no, tertip, kisa_ad, tam_ad in KANUNLAR:
        json_path = JSON_DIR / f"{kisa_ad}_{kanun_no}.json"
        if json_path.exists():
            index["kanunlar"].append({
                "kanun_no": kanun_no,
                "kisa_ad": kisa_ad,
                "tam_ad": tam_ad,
                "dosya": f"{kisa_ad}_{kanun_no}.json",
            })

    index_path = JSON_DIR / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\nIndex dosyası: {index_path}")


if __name__ == "__main__":
    scrape_all()
