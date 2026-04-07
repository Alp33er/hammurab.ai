# Boz Hukuk Telegram — Mersin İmar & Kamulaştırma Takip Botu

Mersin ilindeki imar planı değişiklikleri ve kamulaştırma kararlarını otomatik olarak tarayan ve Telegram grubuna gönderen bot sistemi.

## Telegram Grubu

- **Grup Adı:** BozHukuk_AI
- **Chat ID:** `-1003775246744`
- **Bot:** @BozHukukBot (token: config.py'de)
- **Yapı:** Süper grup + Forum/Topics modu

## Topic'ler

| Topic | Thread ID | İçerik |
|-------|-----------|--------|
| Genel | 4 | Sistem bilgileri, haftalık özet |
| Kamulaştırma | 5 | Tüm ilçeler — acele kamulaştırma kararları |
| Resmi Gazete | 6 | Mersin'i etkileyen mevzuat |
| Yenişehir | 7 | İmar planı askı ilanları |
| Mezitli | 8 | İmar uygulamaları |
| Toroslar | 9 | Parselasyon + imar revizyonları |
| Akdeniz | 10 | Kentsel dönüşüm + imar |
| Tarsus | 11 | İmar + GES projeleri |
| Erdemli | 12 | İmar |
| Silifke | 13 | İmar |
| Anamur | 14 | İmar |
| Mut | 15 | İmar |
| Gülnar | 16 | İmar |
| Çamlıyayla | 17 | İmar |
| Bozyazı | 18 | İmar |

## Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `config.py` | Bot token, chat_id, topic_id'ler, kaynak URL'leri, anahtar kelimeler |
| `telegram_bot.py` | Mesaj gönderme fonksiyonları + mesaj formatlama |
| `scraper.py` | Ana scraper — 9 kaynağı tarar, yeni ilan bulursa Telegram'a gönderir |
| `weekly_summary.py` | Haftalık özet — Pazartesi sabahı Genel topic'e rapor |
| `sent_items.json` | Gönderilmiş ilanların hash'leri (duplicate engeli) |

## Taranan Kaynaklar (9 adet)

1. **Mersin Büyükşehir Belediyesi** — mersin.bel.tr/ilanlar
2. **Yenişehir Belediyesi** — yenisehir.bel.tr/tr/plan-aski-tutanaklari
3. **Mezitli Belediyesi** — mezitli.bel.tr/imar-ve-sehircilik-mudurlugu/
4. **Toroslar Belediyesi** — toroslar-bld.gov.tr/duyurular
5. **Erdemli Belediyesi** — erdemli.bel.tr askı ilanları
6. **Anamur Belediyesi** — anamur.bel.tr duyurular
7. **Mut Belediyesi** — mut.bel.tr/duyurular
8. **Resmi Gazete** — resmigazete.gov.tr (günlük sayfa)
9. **Çevre Bakanlığı Mersin İl Müdürlüğü** — mersin.csb.gov.tr

## LaunchAgent'lar

| Agent | Plist | Zamanlama |
|-------|-------|-----------|
| Günlük Tarama | `com.berrygames.hukuk-scraper` | Her gün 09:00 + 18:00 |
| Haftalık Özet | `com.berrygames.hukuk-weekly` | Her Pazartesi 09:30 |

## Çalışma Mantığı

```
Scraper çalışır (günde 2x)
    ↓
9 kaynağı tarar, imar/kamulaştırma anahtar kelimeleriyle filtreler
    ↓
Her ilan için hash üretir (URL + başlık)
    ↓
sent_items.json'da var mı kontrol eder
    ↓
YENİ → ilgili topic'e Telegram mesajı gönderir
ESKİ → sessiz kalır, spam yapmaz
    ↓
Her Pazartesi → haftalık özet (yeni ilan sayısı, askı süreleri)
```

## Manuel Çalıştırma

```bash
# Scraper'ı manuel çalıştır
cd /Users/mini/_BERRY_GAMES/_BERRY_HUKUK/boz_hukuk_telegram
python3 scraper.py

# Haftalık özeti manuel gönder
python3 weekly_summary.py
```

## Log Dosyaları

- `scraper.log` — Günlük tarama çıktısı
- `scraper_error.log` — Hata logları
- `weekly.log` — Haftalık özet çıktısı

## Kurulum Tarihi

24 Mart 2026
