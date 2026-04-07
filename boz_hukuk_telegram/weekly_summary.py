#!/usr/bin/env python3
"""
Boz Hukuk — Haftalık Özet
Her Pazartesi 09:30'da çalışır, Genel topic'e haftalık rapor gönderir.
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_FILE
from telegram_bot import send_weekly_summary


def generate_weekly_stats() -> dict:
    """Son 7 günün istatistiklerini hesaplar."""
    if not os.path.exists(DB_FILE):
        return {
            "hafta_baslangic": "",
            "hafta_bitis": "",
            "yeni_imar": 0,
            "yeni_kamulastirma": 0,
            "askida_plan": 0,
            "yaklasan_son_gun": [],
        }

    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    now = datetime.now()
    week_ago = now - timedelta(days=7)

    yeni_imar = 0
    yeni_kamulastirma = 0

    for h, item in db.get("sent", {}).items():
        date_sent = item.get("date_sent", "")
        if not date_sent:
            continue
        try:
            sent_dt = datetime.fromisoformat(date_sent)
        except (ValueError, TypeError):
            continue

        if sent_dt >= week_ago:
            if item.get("type") == "kamulastirma":
                yeni_kamulastirma += 1
            else:
                yeni_imar += 1

    return {
        "hafta_baslangic": week_ago.strftime("%d.%m.%Y"),
        "hafta_bitis": now.strftime("%d.%m.%Y"),
        "yeni_imar": yeni_imar,
        "yeni_kamulastirma": yeni_kamulastirma,
        "askida_plan": 0,  # TODO: askı tarihlerini parse edip hesapla
        "yaklasan_son_gun": [],  # TODO: askı süresi 3 günden az olanlar
    }


def run_weekly():
    print(f"\n{'='*60}")
    print(f"Boz Hukuk — Haftalık Özet")
    print(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*60}\n")

    stats = generate_weekly_stats()
    send_weekly_summary(stats)

    print(f"Haftalık özet gönderildi: {stats['yeni_imar']} imar, {stats['yeni_kamulastirma']} kamulaştırma")


if __name__ == "__main__":
    run_weekly()
