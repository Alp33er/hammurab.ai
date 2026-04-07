# Berry Hukuk AI — TODO

## Acil — API Sorunu
- [ ] **Yargıtay API endpoint değişikliği** — karararama.yargitay.gov.tr/aramadetaylist 200 dönüyor ama 0 sonuç. Payload formatı değişmiş olabilir. Tarayıcıdan network tab ile doğru payload'u yakalamak gerekiyor.
- [ ] **emsal.uyap.gov.tr bakımda** — Bakım bitince Bedesten API test edilecek

## Uzun Vade
- [ ] **Kullanıcı sistemi + abonelik** — Kayıt/giriş, avukat profili, Iyzico/Stripe ödeme
- [ ] **UYAP entegrasyonu** — API erişimi araştırılacak, dava takip paneli
- [ ] **Corpus aboneliği** — 736.000+ karar, ayda 11 TL (baro kartı ile)
- [ ] **KararTürk aboneliği** — 9.000.000+ karar
- [ ] **Lexpera lisansı** — 34.200-48.000 TL/yıl. Kurumsal API anlaşması
- [ ] **HMGS/İYÖS benchmark** — Kitapçıktan çıkmış soruları al, AI'ı test et

## Tamamlanan
- [x] RAG v2 (hiyerarşik chunking + metadata) — 2026-03-22
- [x] Dilekçe şablonları (10 adet) — 2026-03-22
- [x] Sözleşme inceleme endpoint — 2026-03-22
- [x] MCP sunucusu (berry-hukuk + yargi-mcp) — 2026-03-22
- [x] Güvenlik middleware — 2026-03-22
- [x] Redis session store — 2026-03-23
- [x] Frontend v2 (3 tab) — 2026-03-22
- [x] Reranking (Claude Haiku) — 2026-03-23
- [x] OCR (Tesseract) — 2026-03-23
- [x] Atıf zinciri (citation_graph.py) — 2026-03-23
- [x] Hibrit retrieval kodu — 2026-03-23
- [x] 300 Yargıtay kararı local RAG'de — 2026-03-23
