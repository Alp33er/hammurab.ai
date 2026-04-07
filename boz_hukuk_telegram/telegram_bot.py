"""
Boz Hukuk — Telegram Bot Modülü
Mesaj gönderme fonksiyonları
"""

import requests
import time
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TOPICS


API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(topic_key: str, text: str, disable_preview: bool = True) -> bool:
    """Belirtilen topic'e mesaj gönderir."""
    thread_id = TOPICS.get(topic_key)
    if not thread_id:
        print(f"[HATA] Bilinmeyen topic: {topic_key}")
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_thread_id": thread_id,
        "parse_mode": "HTML",
        "text": text,
        "disable_web_page_preview": disable_preview,
    }

    try:
        r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=30)
        result = r.json()
        if result.get("ok"):
            print(f"[OK] Mesaj gönderildi → {topic_key}")
            return True
        else:
            print(f"[HATA] Telegram API: {result.get('description', 'Bilinmeyen hata')}")
            return False
    except Exception as e:
        print(f"[HATA] Telegram bağlantı hatası: {e}")
        return False
    finally:
        time.sleep(0.5)  # Rate limit koruması


def format_imar_message(item: dict) -> str:
    """İmar ilanı için formatlanmış Telegram mesajı oluşturur."""
    parts = ["📋 <b>YENİ İMAR İLANI</b>\n"]

    if item.get("title"):
        parts.append(f"<b>{item['title']}</b>\n")

    if item.get("ilce"):
        parts.append(f"📍 <b>İlçe:</b> {item['ilce']}")

    if item.get("mahalle"):
        parts.append(f"🏘 <b>Mahalle:</b> {item['mahalle']}")

    if item.get("ada_parsel"):
        parts.append(f"📐 <b>Ada/Parsel:</b> {item['ada_parsel']}")

    if item.get("plan_tipi"):
        parts.append(f"📏 <b>Plan Tipi:</b> {item['plan_tipi']}")

    if item.get("aski_baslangic") and item.get("aski_bitis"):
        parts.append(f"📅 <b>Askı:</b> {item['aski_baslangic']} – {item['aski_bitis']}")

    if item.get("description"):
        parts.append(f"\n{item['description']}")

    if item.get("url"):
        parts.append(f"\n🔗 <a href='{item['url']}'>Kaynak</a>")

    if item.get("source_name"):
        parts.append(f"📰 {item['source_name']}")

    return "\n".join(parts)


def format_kamulastirma_message(item: dict) -> str:
    """Kamulaştırma kararı için formatlanmış Telegram mesajı oluşturur."""
    parts = ["⚖️ <b>YENİ KAMULAŞTIRMA KARARI</b>\n"]

    if item.get("title"):
        parts.append(f"<b>{item['title']}</b>\n")

    if item.get("tarih"):
        parts.append(f"📅 <b>Tarih:</b> {item['tarih']}")

    if item.get("kurum"):
        parts.append(f"🏛 <b>Yetkili Kurum:</b> {item['kurum']}")

    if item.get("ilce"):
        parts.append(f"📍 <b>İlçe:</b> {item['ilce']}")

    if item.get("alan"):
        parts.append(f"📍 <b>Etkilenen Alan:</b> {item['alan']}")

    if item.get("description"):
        parts.append(f"\n{item['description']}")

    if item.get("url"):
        parts.append(f"\n🔗 <a href='{item['url']}'>Kaynak</a>")

    return "\n".join(parts)


def send_weekly_summary(stats: dict):
    """Haftalık özet mesajı gönderir."""
    yeni_imar = stats.get("yeni_imar", 0)
    yeni_kamulastirma = stats.get("yeni_kamulastirma", 0)
    askida_plan = stats.get("askida_plan", 0)
    yaklasan_son_gun = stats.get("yaklasan_son_gun", [])

    text = "📊 <b>HAFTALIK ÖZET</b>\n"
    text += f"<i>{stats.get('hafta_baslangic', '')} – {stats.get('hafta_bitis', '')}</i>\n\n"

    if yeni_imar == 0 and yeni_kamulastirma == 0:
        text += "Bu hafta yeni imar ilanı veya kamulaştırma kararı tespit edilmedi.\n\n"
    else:
        if yeni_imar > 0:
            text += f"📋 <b>{yeni_imar}</b> yeni imar ilanı\n"
        if yeni_kamulastirma > 0:
            text += f"⚖️ <b>{yeni_kamulastirma}</b> yeni kamulaştırma kararı\n"
        text += "\n"

    if askida_plan > 0:
        text += f"📌 Şu an askıda olan plan sayısı: <b>{askida_plan}</b>\n\n"

    if yaklasan_son_gun:
        text += "⚠️ <b>İtiraz süresi dolmak üzere:</b>\n"
        for plan in yaklasan_son_gun:
            text += f"▫️ {plan['baslik']} — son gün: <b>{plan['son_gun']}</b>\n"
        text += "\n"

    text += "✅ Sistem aktif, taramalar düzenli çalışıyor."

    send_message("genel", text)
