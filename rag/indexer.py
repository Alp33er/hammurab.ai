#!/usr/bin/env python3
"""
Kanun maddelerini chunk'la, embedding oluştur ve ChromaDB'ye yükle.
BM25 index de oluştur (hybrid search için).

v2 — Hiyerarşik chunking + metadata zenginleştirme + summary-augmented chunks
"""

import json
import pickle
import re
import sys
import time
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

# ─── KONFİGÜRASYON ─────────────────────────────────

JSON_DIR = Path(__file__).parent.parent / "scraper" / "data" / "json"
YARGITAY_DIR = Path(__file__).parent.parent / "scraper" / "data" / "yargitay" / "json"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
BM25_PATH = Path(__file__).parent / "bm25_index.pkl"
COLLECTION_NAME = "mevzuat"

# Embedding modeli — multilingual, retrieval için optimize, 1024 dim
MODEL_NAME = "intfloat/multilingual-e5-large"

# Chunk boyutu (karakter) — bir madde çok uzunsa böl
MAX_CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200  # Chunk'lar arası overlap


# ─── HUKUK DALI SINIFLANDIRMA ────────────────────────

HUKUK_DALI_MAP = {
    # Medeni Hukuk
    "tmk": "medeni", "aile_koruma": "medeni",
    "ailenin_korunmasi_6284": "medeni",
    # Borçlar Hukuku
    "tbk": "borclar",
    # Ceza Hukuku
    "tck": "ceza", "cmk": "ceza", "cgtik": "ceza", "infaz": "ceza",
    # İş Hukuku
    "ik": "is", "isg": "is", "sendikalar": "is",
    # Ticaret Hukuku
    "ttk": "ticaret", "cek_5941": "ticaret", "kooperatifler": "ticaret",
    "bankacilik_5411": "ticaret",
    # İdare Hukuku
    "iyuk": "idare", "belediye_5393": "idare", "buyuksehir_5216": "idare",
    "dmk": "idare",
    # Anayasa Hukuku
    "anayasa_2709": "anayasa", "aym_6216": "anayasa",
    # İcra ve İflas
    "iik": "icra_iflas",
    # Tüketici Hukuku
    "tuketici": "tuketici",
    # Usul Hukuku
    "hmk": "usul", "hukuk_uyusmazliklari": "usul",
    "arabuluculuk_6325": "usul",
    # SGK / Sosyal Güvenlik
    "sgk": "sosyal_guvenlik",
    # Kişisel Veriler
    "kvkk": "kisisel_veri",
    # Avukatlık
    "avukatlik_1136": "avukatlik",
    # Vergi
    "vuk": "vergi", "gelir_vergisi": "vergi",
    # Diğer
    "dernekler_5253": "dernekler", "bilgi_edinme_4982": "idare",
    "kabahatler_5326": "ceza", "noter": "noter",
    "tapu_kadastro": "esya",
}

# Hukuk dalı → açıklama (retrieval'da anahtar kelime olarak kullanılır)
HUKUK_DALI_LABELS = {
    "medeni": "Medeni Hukuk (aile, miras, eşya, kişiler)",
    "borclar": "Borçlar Hukuku (sözleşme, haksız fiil, sebepsiz zenginleşme)",
    "ceza": "Ceza Hukuku (suç, ceza, kovuşturma)",
    "is": "İş Hukuku (işçi, işveren, iş güvenliği)",
    "ticaret": "Ticaret Hukuku (şirketler, kıymetli evrak, banka)",
    "idare": "İdare Hukuku (idari dava, belediye, kamu)",
    "anayasa": "Anayasa Hukuku (temel haklar, devlet yapısı)",
    "icra_iflas": "İcra ve İflas Hukuku",
    "tuketici": "Tüketici Hukuku",
    "usul": "Usul Hukuku (dava, yargılama, arabuluculuk)",
    "sosyal_guvenlik": "Sosyal Güvenlik Hukuku",
    "kisisel_veri": "Kişisel Verilerin Korunması",
    "avukatlik": "Avukatlık Hukuku",
    "vergi": "Vergi Hukuku",
    "dernekler": "Dernekler Hukuku",
    "noter": "Noterlik Hukuku",
    "esya": "Eşya Hukuku (tapu, kadastro)",
}


def detect_hukuk_dali(kanun_kisa: str) -> str:
    """Kanun kısa adından hukuk dalını belirle."""
    # Doğrudan eşleşme
    if kanun_kisa in HUKUK_DALI_MAP:
        return HUKUK_DALI_MAP[kanun_kisa]

    # Kısmi eşleşme
    for key, dal in HUKUK_DALI_MAP.items():
        if key in kanun_kisa or kanun_kisa in key:
            return dal

    return "genel"


# ─── TÜRKÇE TOKENİZASYON ────────────────────────────

def tokenize_turkish(text: str) -> list[str]:
    """Basit Türkçe tokenizer — BM25 için."""
    text = text.lower()
    text = re.sub(r'[^\w\sçğıöşü]', ' ', text)
    tokens = text.split()
    # Çok kısa kelimeleri filtrele
    return [t for t in tokens if len(t) > 1]


# ─── FIKRA/BENT PARSER ──────────────────────────────

FIKRA_PATTERN = re.compile(
    r'(?:^|\n)\s*\((\d+)\)\s+',  # (1) ... formatı
)
BENT_PATTERN = re.compile(
    r'(?:^|\n)\s*([a-zçğıöşü])\)\s+',  # a) ... formatı
)
NUMBERED_BENT_PATTERN = re.compile(
    r'(?:^|\n)\s*(\d+)\.\s+',  # 1. ... formatı (fıkra içi bent)
)


def parse_fikra_bent(text: str) -> dict:
    """
    Madde metnini fıkra ve bent yapısına ayır.
    Returns: {
        "giris": "madde giriş cümlesi",
        "fikralar": [
            {"no": 1, "text": "...", "bentler": [{"no": "a", "text": "..."}]}
        ]
    }
    """
    result = {"giris": "", "fikralar": []}

    # Fıkra bölme
    fikra_splits = FIKRA_PATTERN.split(text)

    if len(fikra_splits) <= 1:
        # Fıkra yok — tüm metin giriş
        result["giris"] = text.strip()
        return result

    # İlk parça giriş (fıkra numarasından önce)
    result["giris"] = fikra_splits[0].strip()

    # Fıkraları eşleştir: [giriş, no1, text1, no2, text2, ...]
    for i in range(1, len(fikra_splits), 2):
        if i + 1 >= len(fikra_splits):
            break
        fikra_no = int(fikra_splits[i])
        fikra_text = fikra_splits[i + 1].strip()

        # Fıkra içindeki bentleri ayır
        bentler = []
        bent_splits = BENT_PATTERN.split(fikra_text)
        if len(bent_splits) > 1:
            fikra_text_clean = bent_splits[0].strip()
            for j in range(1, len(bent_splits), 2):
                if j + 1 >= len(bent_splits):
                    break
                bentler.append({
                    "no": bent_splits[j],
                    "text": bent_splits[j + 1].strip(),
                })
        else:
            fikra_text_clean = fikra_text

        result["fikralar"].append({
            "no": fikra_no,
            "text": fikra_text_clean,
            "bentler": bentler,
        })

    return result


# ─── SUMMARY FONKSİYONU ─────────────────────────────

def generate_summary(madde_text: str, kanun_ad: str, madde_no: int) -> str:
    """
    Madde metninden kısa özet oluştur (Claude API kullanmadan, kural tabanlı).
    İlk cümle + anahtar kelimeler ile lightweight özet.
    """
    # İlk cümleyi al
    first_sentence = madde_text.split(".")[0].strip() if "." in madde_text else madde_text[:200]

    # "Madde X -" prefix'ini temizle
    first_sentence = re.sub(r'^Madde\s+\d+[A-Z]?\s*[-–—]\s*', '', first_sentence).strip()

    # Başlık bilgisini ayıkla (fıkra/bent başlıklarından)
    # TMK gibi kanunlarda madde sonundaki başlıklar (örn: "II. İyiniyet")
    baslik_match = re.search(r'(?:^|\s)([IVXLC]+\.\s+.+?)$', madde_text, re.MULTILINE)
    baslik = baslik_match.group(1).strip() if baslik_match else ""

    # Konu tespiti
    parts = [f"{kanun_ad} m.{madde_no}"]
    if baslik:
        parts.append(baslik)
    if first_sentence and len(first_sentence) < 200:
        parts.append(first_sentence)

    return " — ".join(parts)


# ─── CHUNK FONKSİYONLARI ────────────────────────────

def chunk_madde(madde: dict, hukuk_dali: str) -> list[dict]:
    """
    Maddeyi hiyerarşik yapıda chunk'lara böl.
    - Kısa madde → tek chunk (summary-augmented)
    - Orta madde → fıkra bazlı chunk
    - Uzun madde → fıkra bazlı + cümle bazlı bölme
    """
    text = madde["text"]
    ref = madde["ref"]
    kanun_ad = madde["kanun_ad"]
    kanun_kisa = madde["kanun_kisa"]
    madde_no = madde["madde_no"]
    kanun_no = madde["kanun_no"]

    # Hukuk dalı label
    dal_label = HUKUK_DALI_LABELS.get(hukuk_dali, "Genel Hukuk")

    # Summary oluştur
    summary = generate_summary(text, kanun_ad, madde_no)

    # Zenginleştirilmiş header — summary + hukuk dalı dahil
    header = f"[{ref}] {kanun_ad} | {dal_label}\nÖzet: {summary}\n\n"

    # Base metadata
    base_meta = {
        "kanun_no": kanun_no,
        "kanun_ad": kanun_ad,
        "kanun_kisa": kanun_kisa,
        "madde_no": madde_no,
        "ref": ref,
        "tip": "kanun",
        "hukuk_dali": hukuk_dali,
        "dal_label": dal_label,
    }

    # ── Kısa madde → tek chunk ──
    if len(text) <= MAX_CHUNK_SIZE:
        return [{
            "id": f"{kanun_kisa}_m{madde_no}",
            "text": header + text,
            "metadata": {**base_meta, "chunk": 0, "chunk_type": "tam_madde"},
        }]

    # ── Hiyerarşik parse ──
    parsed = parse_fikra_bent(text)
    chunks = []
    chunk_idx = 0

    # Fıkra bazlı chunk'lama
    if parsed["fikralar"]:
        for fikra in parsed["fikralar"]:
            fikra_text = f"({fikra['no']}) {fikra['text']}"
            if fikra["bentler"]:
                for bent in fikra["bentler"]:
                    fikra_text += f"\n  {bent['no']}) {bent['text']}"

            # Fıkra tek başına chunk boyutuna sığıyorsa
            if len(fikra_text) <= MAX_CHUNK_SIZE:
                chunks.append({
                    "id": f"{kanun_kisa}_m{madde_no}_f{fikra['no']}",
                    "text": header + fikra_text,
                    "metadata": {
                        **base_meta,
                        "chunk": chunk_idx,
                        "chunk_type": "fikra",
                        "fikra_no": fikra["no"],
                    },
                })
                chunk_idx += 1
            else:
                # Fıkra çok uzun — cümle bazlı böl
                sub_chunks = _split_by_sentences(fikra_text, header, base_meta,
                                                  kanun_kisa, madde_no, chunk_idx,
                                                  f"f{fikra['no']}")
                chunks.extend(sub_chunks)
                chunk_idx += len(sub_chunks)
    else:
        # Fıkra yapısı yok — cümle bazlı böl (eski davranış, iyileştirilmiş)
        sub_chunks = _split_by_sentences(text, header, base_meta,
                                          kanun_kisa, madde_no, 0, "")
        chunks.extend(sub_chunks)

    return chunks


def _split_by_sentences(text: str, header: str, base_meta: dict,
                        kanun_kisa: str, madde_no: int,
                        start_idx: int, id_prefix: str) -> list[dict]:
    """Uzun metni cümle bazlı chunk'lara böl (overlap ile)."""
    chunks = []
    sentences = text.replace(". ", ".\n").split("\n")
    current = ""
    chunk_idx = start_idx
    prev_tail = ""

    for sent in sentences:
        if len(current) + len(sent) > MAX_CHUNK_SIZE and current:
            chunk_text = prev_tail + current.strip() if chunk_idx > start_idx else current.strip()
            suffix = f"_{id_prefix}_c{chunk_idx}" if id_prefix else f"_c{chunk_idx}"
            chunks.append({
                "id": f"{kanun_kisa}_m{madde_no}{suffix}",
                "text": header + chunk_text,
                "metadata": {**base_meta, "chunk": chunk_idx, "chunk_type": "cumle"},
            })
            prev_tail = current.strip()[-CHUNK_OVERLAP:] + " " if len(current.strip()) > CHUNK_OVERLAP else current.strip() + " "
            current = ""
            chunk_idx += 1
        current += sent + " "

    if current.strip():
        chunk_text = prev_tail + current.strip() if chunk_idx > start_idx else current.strip()
        suffix = f"_{id_prefix}_c{chunk_idx}" if id_prefix else f"_c{chunk_idx}"
        chunks.append({
            "id": f"{kanun_kisa}_m{madde_no}{suffix}",
            "text": header + chunk_text,
            "metadata": {**base_meta, "chunk": chunk_idx, "chunk_type": "cumle"},
        })

    return chunks


# ─── YARGITAY KARARI CHUNK ───────────────────────────

def chunk_yargitay_karari(karar: dict) -> list[tuple]:
    """Yargıtay kararını chunk'la (zenginleştirilmiş metadata ile)."""
    karar_id = karar.get("id", "")
    tam_metin = karar.get("tam_metin", "")
    if not tam_metin or len(tam_metin) < 50:
        return []

    daire = karar.get("daire", "Bilinmiyor")
    esas_no = karar.get("esas_no", "")
    karar_no = karar.get("karar_no", "")
    tarih = karar.get("tarih", "")
    ref = f"Yargıtay {daire} E.{esas_no} K.{karar_no}"

    # Daire'den hukuk dalı tahmin et
    daire_lower = daire.lower()
    if "ceza" in daire_lower:
        hukuk_dali = "ceza"
    elif "hukuk" in daire_lower:
        # Daire numarasından tahmin (yaklaşık)
        if any(x in daire_lower for x in ["9.", "22.", "7."]):
            hukuk_dali = "is"
        elif any(x in daire_lower for x in ["2.", "18."]):
            hukuk_dali = "medeni"
        elif any(x in daire_lower for x in ["11.", "19.", "23."]):
            hukuk_dali = "ticaret"
        elif any(x in daire_lower for x in ["12.", "8."]):
            hukuk_dali = "icra_iflas"
        else:
            hukuk_dali = "genel"
    else:
        hukuk_dali = "genel"

    dal_label = HUKUK_DALI_LABELS.get(hukuk_dali, "Genel Hukuk")

    # Karar özeti — ilk 200 karakter
    ozet = tam_metin[:200].strip()
    if len(tam_metin) > 200:
        ozet = ozet.rsplit(" ", 1)[0] + "..."

    header = f"[{ref}] ({tarih}) | {dal_label}\nÖzet: {ozet}\n\n"
    metadata = {
        "kanun_no": 0,
        "kanun_ad": f"Yargıtay {daire} Kararı",
        "kanun_kisa": "yargitay",
        "madde_no": 0,
        "ref": ref,
        "chunk": 0,
        "tip": "karar",
        "tarih": tarih,
        "hukuk_dali": hukuk_dali,
        "dal_label": dal_label,
        "daire": daire,
        "chunk_type": "karar",
    }

    if len(tam_metin) <= MAX_CHUNK_SIZE:
        return [(f"yrgty_{karar_id}", header + tam_metin, metadata)]

    # Uzun kararları böl
    sentences = tam_metin.replace(". ", ".\n").split("\n")
    current = ""
    chunk_idx = 0
    chunks = []

    for sent in sentences:
        if len(current) + len(sent) > MAX_CHUNK_SIZE and current:
            chunk_meta = {**metadata, "chunk": chunk_idx}
            chunks.append((
                f"yrgty_{karar_id}_c{chunk_idx}",
                header + current.strip(),
                chunk_meta,
            ))
            current = current.strip()[-CHUNK_OVERLAP:] + " " if len(current.strip()) > CHUNK_OVERLAP else ""
            chunk_idx += 1
        current += sent + " "

    if current.strip():
        chunk_meta = {**metadata, "chunk": chunk_idx}
        chunks.append((
            f"yrgty_{karar_id}_c{chunk_idx}",
            header + current.strip(),
            chunk_meta,
        ))

    return chunks


# ─── ANA FONKSİYON ──────────────────────────────────

def build_index():
    """Tüm kanunları ChromaDB + BM25'e yükle."""
    print("=" * 60)
    print("RAG INDEXER v2 — Berry Hukuk AI")
    print("  Hiyerarşik chunking + Metadata zenginleştirme")
    print(f"  Model: {MODEL_NAME}")
    print(f"  Distance: cosine")
    print("=" * 60)

    # Index dosyasını oku
    index_path = JSON_DIR / "index.json"
    if not index_path.exists():
        print("HATA: index.json bulunamadı. Önce scraper'ı çalıştır.")
        sys.exit(1)

    index = json.loads(index_path.read_text())
    print(f"Kanun sayısı: {len(index['kanunlar'])}")
    print(f"Toplam madde: {index['toplam_madde']}")
    print()

    # Embedding modeli yükle
    print(f"Model yükleniyor: {MODEL_NAME}")
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"Model yüklendi ({time.time() - t0:.1f}s)")
    print()

    # ChromaDB başlat
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Koleksiyonu sıfırdan oluştur — cosine distance
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Eski koleksiyon silindi: {COLLECTION_NAME}")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={
            "description": "Türk mevzuatı — kanun maddeleri + içtihat",
            "hnsw:space": "cosine",
        }
    )
    print(f"Koleksiyon oluşturuldu: {COLLECTION_NAME} (cosine)")
    print()

    # BM25 için corpus
    bm25_corpus = []

    # Her kanunu işle
    total_chunks = 0
    batch_ids = []
    batch_texts = []
    batch_embeddings = []
    batch_metadatas = []
    BATCH_SIZE = 100

    dal_stats = {}  # Hukuk dalı istatistikleri

    def flush_batch():
        nonlocal batch_ids, batch_texts, batch_embeddings, batch_metadatas
        if not batch_ids:
            return
        collection.add(
            ids=batch_ids,
            documents=batch_texts,
            embeddings=batch_embeddings,
            metadatas=batch_metadatas,
        )
        batch_ids = []
        batch_texts = []
        batch_embeddings = []
        batch_metadatas = []

    for kanun_info in index["kanunlar"]:
        json_path = JSON_DIR / kanun_info["dosya"]
        if not json_path.exists():
            print(f"  ✗ {kanun_info['tam_ad']}: dosya yok")
            continue

        kanun_data = json.loads(json_path.read_text())
        kanun_kisa = kanun_data.get("kanun_kisa", kanun_info.get("kisa_ad", ""))
        hukuk_dali = detect_hukuk_dali(kanun_kisa)
        dal_stats[hukuk_dali] = dal_stats.get(hukuk_dali, 0)

        kanun_chunks = []
        for madde in kanun_data["maddeler"]:
            kanun_chunks.extend(chunk_madde(madde, hukuk_dali))

        # Embedding oluştur — e5 modeli "passage: " prefix istiyor
        texts = [c["text"] for c in kanun_chunks]
        if not texts:
            print(f"  ✗ {kanun_info['tam_ad']}: madde yok")
            continue

        prefixed_texts = [f"passage: {t}" for t in texts]
        embeddings = model.encode(prefixed_texts, show_progress_bar=False, batch_size=32).tolist()

        for chunk, embedding in zip(kanun_chunks, embeddings):
            batch_ids.append(chunk["id"])
            batch_texts.append(chunk["text"])
            batch_embeddings.append(embedding)
            batch_metadatas.append(chunk["metadata"])

            bm25_corpus.append({
                "id": chunk["id"],
                "tokens": tokenize_turkish(chunk["text"]),
                "metadata": chunk["metadata"],
            })

            if len(batch_ids) >= BATCH_SIZE:
                flush_batch()

        dal_stats[hukuk_dali] = dal_stats.get(hukuk_dali, 0) + len(kanun_chunks)
        total_chunks += len(kanun_chunks)
        print(f"  ✓ {kanun_info['kisa_ad'].upper():16s} {len(kanun_chunks):5d} chunk — {kanun_info['tam_ad']} [{hukuk_dali}]")

    flush_batch()

    # ── YARGITAY KARARLARI ──
    yargitay_path = YARGITAY_DIR / "yargitay_kararlar.json"
    yargitay_chunks = 0
    if yargitay_path.exists():
        print(f"\nYargıtay kararları yükleniyor...")
        kararlar = json.loads(yargitay_path.read_text())
        print(f"  Toplam karar: {len(kararlar)}")

        for karar in kararlar:
            chunks = chunk_yargitay_karari(karar)
            for cid, ctext, cmeta in chunks:
                prefixed = f"passage: {ctext}"
                embedding = model.encode(prefixed).tolist()

                batch_ids.append(cid)
                batch_texts.append(ctext)
                batch_embeddings.append(embedding)
                batch_metadatas.append(cmeta)

                bm25_corpus.append({
                    "id": cid,
                    "tokens": tokenize_turkish(ctext),
                    "metadata": cmeta,
                })

                if len(batch_ids) >= BATCH_SIZE:
                    flush_batch()

                yargitay_chunks += 1

        flush_batch()
        total_chunks += yargitay_chunks
        print(f"  ✓ YARGITAY         {yargitay_chunks:5d} chunk — {len(kararlar)} karar")
    else:
        print(f"\nYargıtay kararları bulunamadı ({yargitay_path}), atlanıyor...")

    # BM25 index'i kaydet
    print(f"\nBM25 index oluşturuluyor ({len(bm25_corpus)} döküman)...")
    with open(BM25_PATH, "wb") as f:
        pickle.dump(bm25_corpus, f)
    print(f"BM25 index kaydedildi: {BM25_PATH}")

    # İstatistikler
    print()
    print("=" * 60)
    print(f"Toplam: {total_chunks} chunk → ChromaDB ({CHROMA_DIR})")
    print(f"Koleksiyon: {COLLECTION_NAME} ({collection.count()} kayıt)")
    print(f"BM25: {len(bm25_corpus)} döküman")
    print()
    print("Hukuk Dalı Dağılımı:")
    for dal, count in sorted(dal_stats.items(), key=lambda x: -x[1]):
        label = HUKUK_DALI_LABELS.get(dal, dal)
        print(f"  {label:45s} {count:5d} chunk")
    print("=" * 60)


if __name__ == "__main__":
    build_index()
