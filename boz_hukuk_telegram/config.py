"""
Boz Hukuk — Mersin İmar & Kamulaştırma Takip Sistemi
Konfigürasyon dosyası
"""

TELEGRAM_BOT_TOKEN = "8239533887:AAHrbphk-LWlHeZYBz4Wa4-cEImjkkLhQ3A"
TELEGRAM_CHAT_ID = -1003775246744

# Topic (thread) ID'leri
TOPICS = {
    "genel": 4,
    "kamulastirma": 5,
    "resmi_gazete": 6,
    "yenisehir": 7,
    "mezitli": 8,
    "toroslar": 9,
    "akdeniz": 10,
    "tarsus": 11,
    "erdemli": 12,
    "silifke": 13,
    "anamur": 14,
    "mut": 15,
    "gulnar": 16,
    "camliyayla": 17,
    "bozyazi": 18,
}

# Scrape edilecek kaynaklar
SOURCES = {
    "buyuksehir": {
        "url": "https://www.mersin.bel.tr/ilanlar",
        "topic": "genel",
        "type": "imar",
    },
    "yenisehir": {
        "url": "https://www.yenisehir.bel.tr/tr/plan-aski-tutanaklari",
        "topic": "yenisehir",
        "type": "imar",
    },
    "mezitli": {
        "url": "https://mezitli.bel.tr/imar-ve-sehircilik-mudurlugu/",
        "topic": "mezitli",
        "type": "imar",
    },
    "toroslar": {
        "url": "https://toroslar-bld.gov.tr/duyurular",
        "topic": "toroslar",
        "type": "imar",
    },
    "tarsus": {
        "url": "https://www.tarsus.bel.tr/tr/haberler/duyurular/duyuru-arsivi.aspx",
        "topic": "tarsus",
        "type": "imar",
    },
    "erdemli": {
        "url": "https://www.erdemli.bel.tr/duyuru/aski-ilani-imar-ve-sehircilik-mudurlugu.html",
        "topic": "erdemli",
        "type": "imar",
    },
    "silifke": {
        "url": "https://silifke.bel.tr/hizmet/default/imar-hizmetleri",
        "topic": "silifke",
        "type": "imar",
    },
    "anamur": {
        "url": "https://anamur.bel.tr/category/haberler/duyurular/",
        "topic": "anamur",
        "type": "imar",
    },
    "mut": {
        "url": "https://mut.bel.tr/duyurular",
        "topic": "mut",
        "type": "imar",
    },
    "resmi_gazete": {
        "url": "https://www.resmigazete.gov.tr",
        "topic": "resmi_gazete",
        "type": "kamulastirma",
    },
    "csb_mersin": {
        "url": "https://mersin.csb.gov.tr",
        "topic": "genel",
        "type": "imar",
    },
}

# İmar/kamulaştırma anahtar kelimeleri
KEYWORDS_IMAR = [
    "imar planı", "imar plani",
    "nazım imar", "nazim imar",
    "uygulama imar",
    "plan değişikliği", "plan degisikligi",
    "plan revizyonu",
    "askı ilan", "aski ilan",
    "parselasyon",
    "18. madde", "18 madde",
    "imar uygulaması", "imar uygulamasi",
]

KEYWORDS_KAMULASTIRMA = [
    "kamulaştırma", "kamulastirma",
    "acele kamulaştırma", "acele kamulastirma",
    "istimlak",
    "irtifak hakkı", "irtifak hakki",
]

# Mersin ilçe isimleri (Resmi Gazete filtrelemesi için)
MERSIN_ILCELER = [
    "mersin", "yenişehir", "yenisehir", "mezitli", "toroslar",
    "akdeniz", "tarsus", "erdemli", "silifke", "anamur",
    "mut", "gülnar", "gulnar", "çamlıyayla", "camliyayla",
    "bozyazı", "bozyazi",
]

# İlçe → topic eşleştirme (URL veya başlıktan ilçe çıkarma)
ILCE_TOPIC_MAP = {
    "yenişehir": "yenisehir", "yenisehir": "yenisehir",
    "mezitli": "mezitli",
    "toroslar": "toroslar",
    "akdeniz": "akdeniz",
    "tarsus": "tarsus",
    "erdemli": "erdemli",
    "silifke": "silifke",
    "anamur": "anamur",
    "mut": "mut",
    "gülnar": "gulnar", "gulnar": "gulnar",
    "çamlıyayla": "camliyayla", "camliyayla": "camliyayla",
    "bozyazı": "bozyazi", "bozyazi": "bozyazi",
}

# Veritabanı dosyası
DB_FILE = "/Users/mini/_BERRY_GAMES/_BERRY_HUKUK/boz_hukuk_telegram/sent_items.json"
