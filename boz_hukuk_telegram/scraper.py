#!/usr/bin/env python3
"""
Boz Hukuk — Mersin İmar & Kamulaştırma Scraper
Günde 2x çalışır (09:00 + 18:00), yeni ilan bulursa Telegram'a gönderir.
"""

import json
import os
import re
import sys
import hashlib
from datetime import datetime, date
from urllib.parse import urljoin

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup

# Aynı dizindeki modüller
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    SOURCES, KEYWORDS_IMAR, KEYWORDS_KAMULASTIRMA,
    MERSIN_ILCELER, ILCE_TOPIC_MAP, DB_FILE
)
from telegram_bot import send_message, format_imar_message, format_kamulastirma_message

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) BozHukukBot/1.0"
}


# ─── Veritabanı (duplicate kontrolü) ───

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sent": {}, "stats": {"total_imar": 0, "total_kamulastirma": 0}}


def save_db(db: dict):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def item_hash(url: str, title: str) -> str:
    """URL + başlık'tan benzersiz hash üretir."""
    raw = f"{url}|{title}".lower().strip()
    return hashlib.md5(raw.encode()).hexdigest()


def is_sent(db: dict, h: str) -> bool:
    return h in db["sent"]


def mark_sent(db: dict, h: str, item: dict):
    db["sent"][h] = {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "date_sent": datetime.now().isoformat(),
        "type": item.get("type", "imar"),
    }


# ─── Yardımcı fonksiyonlar ───

def contains_keywords(text: str, keywords: list) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def detect_ilce(text: str) -> str | None:
    """Metinden ilçe adı çıkarır."""
    text_lower = text.lower()
    for ilce, topic_key in ILCE_TOPIC_MAP.items():
        if ilce in text_lower:
            return topic_key
    return None


def fetch_page(url: str, timeout: int = 60) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"[UYARI] {url} çekilemedi: {e}")
        return None


# ─── Kaynak-spesifik scraper'lar ───

def scrape_buyuksehir() -> list:
    """mersin.bel.tr/ilanlar sayfasından imar ilanlarını çeker."""
    items = []
    soup = fetch_page("https://www.mersin.bel.tr/ilanlar")
    if not soup:
        return items

    # İlan linkleri genelde <a> taglarında /ilan/ path'iyle
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/ilan/" not in href:
            continue

        title = link.get_text(strip=True)
        if not title:
            continue

        full_url = urljoin("https://www.mersin.bel.tr", href)

        # İmar veya kamulaştırma mı?
        combined = f"{title} {href}".lower()
        is_imar = contains_keywords(combined, KEYWORDS_IMAR)
        is_kamulastirma = contains_keywords(combined, KEYWORDS_KAMULASTIRMA)

        if not is_imar and not is_kamulastirma:
            continue

        ilce_topic = detect_ilce(combined)

        item = {
            "title": title,
            "url": full_url,
            "source": "buyuksehir",
            "source_name": "Mersin Büyükşehir Belediyesi",
            "type": "kamulastirma" if is_kamulastirma else "imar",
            "ilce": ilce_topic,
        }
        items.append(item)

    print(f"[Büyükşehir] {len(items)} ilan bulundu")
    return items


def scrape_yenisehir() -> list:
    """yenisehir.bel.tr plan askı tutanakları."""
    items = []
    soup = fetch_page("https://www.yenisehir.bel.tr/tr/plan-aski-tutanaklari")
    if not soup:
        return items

    # Tablo veya kartlardan veri çek
    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        combined = f"{title} {href}".lower()
        if contains_keywords(combined, KEYWORDS_IMAR):
            full_url = urljoin("https://www.yenisehir.bel.tr", href)
            items.append({
                "title": title,
                "url": full_url,
                "source": "yenisehir",
                "source_name": "Yenişehir Belediyesi",
                "type": "imar",
                "ilce": "yenisehir",
            })

    print(f"[Yenişehir] {len(items)} ilan bulundu")
    return items


def scrape_mezitli() -> list:
    """mezitli.bel.tr imar duyuruları."""
    items = []
    soup = fetch_page("https://mezitli.bel.tr/imar-ve-sehircilik-mudurlugu/")
    if not soup:
        return items

    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        combined = f"{title} {href}".lower()
        if contains_keywords(combined, KEYWORDS_IMAR + KEYWORDS_KAMULASTIRMA):
            full_url = urljoin("https://mezitli.bel.tr", href)
            items.append({
                "title": title,
                "url": full_url,
                "source": "mezitli",
                "source_name": "Mezitli Belediyesi",
                "type": "imar",
                "ilce": "mezitli",
            })

    print(f"[Mezitli] {len(items)} ilan bulundu")
    return items


def scrape_toroslar() -> list:
    """toroslar-bld.gov.tr duyurular."""
    items = []
    soup = fetch_page("https://toroslar-bld.gov.tr/duyurular")
    if not soup:
        return items

    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        combined = f"{title} {href}".lower()
        if contains_keywords(combined, KEYWORDS_IMAR + KEYWORDS_KAMULASTIRMA):
            full_url = urljoin("https://toroslar-bld.gov.tr", href)
            items.append({
                "title": title,
                "url": full_url,
                "source": "toroslar",
                "source_name": "Toroslar Belediyesi",
                "type": "imar",
                "ilce": "toroslar",
            })

    print(f"[Toroslar] {len(items)} ilan bulundu")
    return items


def scrape_erdemli() -> list:
    """erdemli.bel.tr imar duyuruları."""
    items = []
    for url in [
        "https://www.erdemli.bel.tr/duyuru/aski-ilani-imar-ve-sehircilik-mudurlugu.html",
        "https://www.erdemli.bel.tr/duyuru/imar-plan-degisikligi-ilani.html",
    ]:
        soup = fetch_page(url)
        if not soup:
            continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            combined = f"{title} {href}".lower()
            if contains_keywords(combined, KEYWORDS_IMAR + KEYWORDS_KAMULASTIRMA):
                full_url = urljoin("https://www.erdemli.bel.tr", href)
                items.append({
                    "title": title,
                    "url": full_url,
                    "source": "erdemli",
                    "source_name": "Erdemli Belediyesi",
                    "type": "imar",
                    "ilce": "erdemli",
                })

    print(f"[Erdemli] {len(items)} ilan bulundu")
    return items


def scrape_anamur() -> list:
    """anamur.bel.tr duyurular."""
    items = []
    soup = fetch_page("https://anamur.bel.tr/category/haberler/duyurular/")
    if not soup:
        return items

    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        combined = f"{title} {href}".lower()
        if contains_keywords(combined, KEYWORDS_IMAR + KEYWORDS_KAMULASTIRMA):
            full_url = urljoin("https://anamur.bel.tr", href)
            items.append({
                "title": title,
                "url": full_url,
                "source": "anamur",
                "source_name": "Anamur Belediyesi",
                "type": "imar",
                "ilce": "anamur",
            })

    print(f"[Anamur] {len(items)} ilan bulundu")
    return items


def scrape_mut() -> list:
    """mut.bel.tr duyurular."""
    items = []
    soup = fetch_page("https://mut.bel.tr/duyurular")
    if not soup:
        return items

    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        combined = f"{title} {href}".lower()
        if contains_keywords(combined, KEYWORDS_IMAR + KEYWORDS_KAMULASTIRMA):
            full_url = urljoin("https://mut.bel.tr", href)
            items.append({
                "title": title,
                "url": full_url,
                "source": "mut",
                "source_name": "Mut Belediyesi",
                "type": "imar",
                "ilce": "mut",
            })

    print(f"[Mut] {len(items)} ilan bulundu")
    return items


def scrape_resmi_gazete() -> list:
    """Resmi Gazete'den bugünkü Mersin kamulaştırma kararlarını kontrol eder."""
    items = []
    today = date.today()
    url = f"https://www.resmigazete.gov.tr/eskiler/{today.year}/{today.month:02d}/{today.strftime('%Y%m%d')}.htm"

    soup = fetch_page(url)
    if not soup:
        return items

    page_text = soup.get_text().lower()

    # Mersin ile ilgili kamulaştırma var mı?
    has_mersin = any(ilce in page_text for ilce in MERSIN_ILCELER)
    has_kamulastirma = contains_keywords(page_text, KEYWORDS_KAMULASTIRMA)

    if has_mersin and has_kamulastirma:
        items.append({
            "title": f"Resmi Gazete {today.strftime('%d.%m.%Y')} — Mersin Kamulaştırma Kararı",
            "url": url,
            "source": "resmi_gazete",
            "source_name": "Resmi Gazete",
            "type": "kamulastirma",
            "tarih": today.strftime("%d.%m.%Y"),
            "description": "Bugünkü Resmi Gazete'de Mersin ili ile ilgili kamulaştırma kararı tespit edildi. Detaylar için linke tıklayın.",
        })

    # İmar ile ilgili de kontrol
    has_imar = contains_keywords(page_text, KEYWORDS_IMAR)
    if has_mersin and has_imar:
        items.append({
            "title": f"Resmi Gazete {today.strftime('%d.%m.%Y')} — Mersin İmar Kararı",
            "url": url,
            "source": "resmi_gazete",
            "source_name": "Resmi Gazete",
            "type": "imar",
            "tarih": today.strftime("%d.%m.%Y"),
            "description": "Bugünkü Resmi Gazete'de Mersin ili ile ilgili imar kararı tespit edildi.",
        })

    print(f"[Resmi Gazete] {len(items)} Mersin kararı bulundu")
    return items


def scrape_csb_mersin() -> list:
    """Çevre Bakanlığı Mersin İl Müdürlüğü duyuruları."""
    items = []
    soup = fetch_page("https://mersin.csb.gov.tr")
    if not soup:
        return items

    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        combined = f"{title} {href}".lower()
        if contains_keywords(combined, KEYWORDS_IMAR + KEYWORDS_KAMULASTIRMA):
            full_url = urljoin("https://mersin.csb.gov.tr", href)
            ilce = detect_ilce(combined)
            items.append({
                "title": title,
                "url": full_url,
                "source": "csb_mersin",
                "source_name": "Çevre Bakanlığı Mersin İl Müdürlüğü",
                "type": "imar",
                "ilce": ilce,
            })

    print(f"[ÇSB Mersin] {len(items)} duyuru bulundu")
    return items


# ─── Ana çalışma fonksiyonu ───

def run_scraper():
    """Tüm kaynakları tarar, yeni ilanları Telegram'a gönderir."""
    print(f"\n{'='*60}")
    print(f"Boz Hukuk — Mersin İmar Taraması")
    print(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*60}\n")

    db = load_db()
    new_imar = 0
    new_kamulastirma = 0

    # Tüm scraper'ları çalıştır
    scrapers = [
        scrape_buyuksehir,
        scrape_yenisehir,
        scrape_mezitli,
        scrape_toroslar,
        scrape_erdemli,
        scrape_anamur,
        scrape_mut,
        scrape_resmi_gazete,
        scrape_csb_mersin,
    ]

    all_items = []
    for scraper_func in scrapers:
        try:
            items = scraper_func()
            all_items.extend(items)
        except Exception as e:
            print(f"[HATA] {scraper_func.__name__}: {e}")

    print(f"\nToplam {len(all_items)} ilan bulundu.")

    # Yeni olanları filtrele ve gönder
    for item in all_items:
        h = item_hash(item.get("url", ""), item.get("title", ""))

        if is_sent(db, h):
            continue

        # Topic belirle
        if item["type"] == "kamulastirma":
            topic_key = "kamulastirma"
            msg = format_kamulastirma_message(item)
            new_kamulastirma += 1
        else:
            topic_key = item.get("ilce") or "genel"
            msg = format_imar_message(item)
            new_imar += 1

        # Gönder
        success = send_message(topic_key, msg)
        if success:
            mark_sent(db, h, item)

    # İstatistikleri güncelle
    db["stats"]["total_imar"] = db["stats"].get("total_imar", 0) + new_imar
    db["stats"]["total_kamulastirma"] = db["stats"].get("total_kamulastirma", 0) + new_kamulastirma
    db["stats"]["last_run"] = datetime.now().isoformat()

    save_db(db)

    print(f"\n{'='*60}")
    print(f"Sonuç: {new_imar} yeni imar, {new_kamulastirma} yeni kamulaştırma gönderildi.")
    print(f"Toplam gönderilmiş: {len(db['sent'])} ilan")
    print(f"{'='*60}\n")

    return new_imar, new_kamulastirma


if __name__ == "__main__":
    run_scraper()
