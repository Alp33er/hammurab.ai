#!/usr/bin/env python3
"""
RAG Retriever v2 — Hybrid search: Semantic (E5) + BM25 (keyword).
Hukuk dalı filtreleme + zenginleştirilmiş metadata desteği.
"""

import math
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_DIR = Path(__file__).parent / "chroma_db"
BM25_PATH = Path(__file__).parent / "bm25_index.pkl"
COLLECTION_NAME = "mevzuat"
MODEL_NAME = "intfloat/multilingual-e5-large"

# Hybrid ağırlıklar (toplamı 1.0)
SEMANTIC_WEIGHT = 0.6
BM25_WEIGHT = 0.4

_model = None
_collection = None
_bm25_corpus = None
_bm25_idf = None
_bm25_avgdl = None


# ─── TÜRKÇE TOKENİZASYON ────────────────────────────

def tokenize_turkish(text: str) -> list[str]:
    """Basit Türkçe tokenizer."""
    text = text.lower()
    text = re.sub(r'[^\w\sçğıöşü]', ' ', text)
    tokens = text.split()
    return [t for t in tokens if len(t) > 1]


# ─── BM25 ────────────────────────────────────────────

def _compute_bm25_idf():
    """IDF değerlerini hesapla."""
    global _bm25_idf, _bm25_avgdl
    if _bm25_corpus is None:
        return

    n_docs = len(_bm25_corpus)
    df = defaultdict(int)
    total_len = 0

    for doc in _bm25_corpus:
        total_len += len(doc["tokens"])
        unique_tokens = set(doc["tokens"])
        for token in unique_tokens:
            df[token] += 1

    _bm25_avgdl = total_len / n_docs if n_docs > 0 else 1

    _bm25_idf = {}
    for token, freq in df.items():
        _bm25_idf[token] = math.log((n_docs - freq + 0.5) / (freq + 0.5) + 1)


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], k1=1.5, b=0.75) -> float:
    """Tek döküman için BM25 skoru hesapla."""
    if not _bm25_idf or not doc_tokens:
        return 0.0

    dl = len(doc_tokens)
    tf = defaultdict(int)
    for t in doc_tokens:
        tf[t] += 1

    score = 0.0
    for qt in query_tokens:
        if qt not in _bm25_idf:
            continue
        idf = _bm25_idf[qt]
        freq = tf.get(qt, 0)
        numerator = freq * (k1 + 1)
        denominator = freq + k1 * (1 - b + b * dl / _bm25_avgdl)
        score += idf * numerator / denominator

    return score


def _bm25_search(query: str, n_results: int = 30,
                 kanun_filter: str = None,
                 hukuk_dali_filter: str = None,
                 tip_filter: str = None) -> list[dict]:
    """BM25 ile keyword arama. Hukuk dalı ve tip filtresi destekler."""
    if _bm25_corpus is None:
        return []

    query_tokens = tokenize_turkish(query)
    if not query_tokens:
        return []

    results = []
    for doc in _bm25_corpus:
        meta = doc["metadata"]
        if kanun_filter and meta.get("kanun_kisa") != kanun_filter.lower():
            continue
        if hukuk_dali_filter and meta.get("hukuk_dali") != hukuk_dali_filter:
            continue
        if tip_filter and meta.get("tip") != tip_filter:
            continue

        score = _bm25_score(query_tokens, doc["tokens"])
        if score > 0:
            results.append({
                "id": doc["id"],
                "score": score,
                "metadata": meta,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:n_results]


# ─── INIT ────────────────────────────────────────────

def _init():
    """Model ve DB'yi lazy yükle."""
    global _model, _collection, _bm25_corpus
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(COLLECTION_NAME)
    if _bm25_corpus is None and BM25_PATH.exists():
        with open(BM25_PATH, "rb") as f:
            _bm25_corpus = pickle.load(f)
        _compute_bm25_idf()


# ─── HYBRID RETRIEVE ────────────────────────────────

def retrieve(query: str, n_results: int = 15,
             kanun_filter: str = None,
             hukuk_dali_filter: str = None,
             tip_filter: str = None) -> list[dict]:
    """
    Hybrid search: Semantic (E5 cosine) + BM25 (keyword).

    Args:
        query: Kullanıcı sorusu / arama metni
        n_results: Döndürülecek sonuç sayısı
        kanun_filter: Sadece belirli bir kanundan ara (örn: "tmk")
        hukuk_dali_filter: Hukuk dalı filtresi (örn: "ceza", "is", "medeni")
        tip_filter: İçerik tipi filtresi ("kanun" veya "karar")

    Returns:
        [{ref, text, kanun_ad, madde_no, score, hukuk_dali, tip, ...}, ...]
    """
    _init()

    # ── 1. Semantic arama (ChromaDB + E5) ──
    query_embedding = _model.encode(f"query: {query}").tolist()

    # ChromaDB where filtresi oluştur
    where_conditions = []
    if kanun_filter:
        where_conditions.append({"kanun_kisa": kanun_filter.lower()})
    if hukuk_dali_filter:
        where_conditions.append({"hukuk_dali": hukuk_dali_filter})
    if tip_filter:
        where_conditions.append({"tip": tip_filter})

    where = None
    if len(where_conditions) == 1:
        where = where_conditions[0]
    elif len(where_conditions) > 1:
        where = {"$and": where_conditions}

    fetch_n = min(n_results * 3, 50)

    semantic_results = _collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch_n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    # Semantic skorları normalize et
    semantic_scores = {}
    for i in range(len(semantic_results["ids"][0])):
        doc_id = semantic_results["ids"][0][i]
        distance = semantic_results["distances"][0][i]
        score = max(0, 1 - distance)
        semantic_scores[doc_id] = {
            "score": score,
            "text": semantic_results["documents"][0][i],
            "metadata": semantic_results["metadatas"][0][i],
        }

    # ── 2. BM25 arama ──
    bm25_results = _bm25_search(
        query, n_results=fetch_n,
        kanun_filter=kanun_filter,
        hukuk_dali_filter=hukuk_dali_filter,
        tip_filter=tip_filter,
    )

    # BM25 skorları normalize et
    bm25_scores = {}
    if bm25_results:
        max_bm25 = max(r["score"] for r in bm25_results)
        min_bm25 = min(r["score"] for r in bm25_results)
        range_bm25 = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1
        for r in bm25_results:
            bm25_scores[r["id"]] = (r["score"] - min_bm25) / range_bm25

    # ── 3. Hybrid skor birleştir ──
    all_ids = set(semantic_scores.keys()) | set(bm25_scores.keys())
    combined = []

    for doc_id in all_ids:
        sem_score = semantic_scores.get(doc_id, {}).get("score", 0)
        bm25_score_val = bm25_scores.get(doc_id, 0)
        hybrid_score = SEMANTIC_WEIGHT * sem_score + BM25_WEIGHT * bm25_score_val

        if doc_id in semantic_scores:
            text = semantic_scores[doc_id]["text"]
            meta = semantic_scores[doc_id]["metadata"]
        else:
            try:
                result = _collection.get(ids=[doc_id], include=["documents", "metadatas"])
                text = result["documents"][0]
                meta = result["metadatas"][0]
            except Exception:
                continue

        # Kanun maddelerine boost — Yargıtay kararları genelde daha uzun
        # ve semantik olarak yüksek skor alıyor ama kanun maddesi daha değerli
        tip = meta.get("tip", "kanun")
        if tip == "kanun":
            hybrid_score *= 1.15  # Kanun maddelerine %15 boost
        elif tip == "karar":
            hybrid_score *= 0.90  # Kararları biraz geri çek

        combined.append({
            "id": doc_id,
            "score": hybrid_score,
            "text": text,
            "metadata": meta,
        })

    combined.sort(key=lambda x: x["score"], reverse=True)

    # Aynı maddenin farklı chunk'larını birleştirme + çeşitlilik kontrolü
    items = []
    seen_refs = set()
    karar_count = 0
    MAX_KARAR = 5  # Sonuçlarda max 5 Yargıtay kararı

    for item in combined:
        ref = item["metadata"]["ref"]
        if ref in seen_refs:
            continue

        # Yargıtay kararı limiti — kanun maddelerine yer aç
        if item["metadata"].get("tip") == "karar":
            if karar_count >= MAX_KARAR:
                continue
            karar_count += 1

        seen_refs.add(ref)

        result_item = {
            "ref": ref,
            "text": item["text"],
            "kanun_ad": item["metadata"]["kanun_ad"],
            "kanun_kisa": item["metadata"]["kanun_kisa"],
            "madde_no": item["metadata"]["madde_no"],
            "score": round(item["score"], 4),
            "hukuk_dali": item["metadata"].get("hukuk_dali", "genel"),
            "dal_label": item["metadata"].get("dal_label", ""),
            "tip": item["metadata"].get("tip", "kanun"),
        }

        # Karar ise ek bilgiler
        if item["metadata"].get("tip") == "karar":
            result_item["tarih"] = item["metadata"].get("tarih", "")
            result_item["daire"] = item["metadata"].get("daire", "")

        items.append(result_item)

        if len(items) >= n_results:
            break

    return items




def hybrid_retrieve(query: str, n_results: int = 15,
                    kanun_filter: str = None,
                    hukuk_dali_filter: str = None,
                    include_live: bool = True) -> list[dict]:
    """
    Hibrit retrieval: Local RAG + Canlı Yargıtay araması.

    Local'den kanun maddeleri + mevcut kararlar,
    Yargıtay API'sinden canlı kararlar getirir ve birleştirir.
    """
    # 1. Local RAG araması
    local_results = retrieve(
        query, n_results=n_results,
        kanun_filter=kanun_filter,
        hukuk_dali_filter=hukuk_dali_filter,
    )

    if not include_live:
        return local_results

    # 2. Canlı Yargıtay araması
    try:
        from rag.live_search import search_yargitay_sync
        live_results = search_yargitay_sync(query, max_results=5)
    except Exception:
        live_results = []

    if not live_results:
        return local_results

    # 3. Birleştir — local sonuçlar önce, canlı sonuçlar sona
    # Duplikasyon kontrolü (aynı esas no)
    seen_refs = set(r["ref"] for r in local_results)

    combined = list(local_results)
    for lr in live_results:
        if lr["ref"] not in seen_refs:
            seen_refs.add(lr["ref"])
            combined.append(lr)

    return combined[:n_results + 5]  # Canlı sonuçlar için biraz fazla döndür


def format_context(results: list[dict]) -> str:
    """Sonuçları Claude'a gönderilecek context formatına çevir."""
    if not results:
        return "İlgili mevzuat bulunamadı."

    # Kanun ve karar sonuçlarını ayır
    kanun_results = [r for r in results if r.get("tip") != "karar"]
    karar_results = [r for r in results if r.get("tip") == "karar"]

    lines = []

    if kanun_results:
        lines.append("# İLGİLİ MEVZUAT\n")
        for r in kanun_results:
            dal = f" | {r['dal_label']}" if r.get("dal_label") else ""
            lines.append(f"## [{r['ref']}] — {r['kanun_ad']}{dal}")
            lines.append(r["text"])
            lines.append("")

    if karar_results:
        lines.append("\n# İLGİLİ İÇTİHATLAR\n")
        for r in karar_results:
            tarih = f" ({r.get('tarih', '')})" if r.get("tarih") else ""
            lines.append(f"## [{r['ref']}]{tarih}")
            lines.append(r["text"])
            lines.append("")

    return "\n".join(lines)


# ─── CLI TEST ────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python3 retriever.py 'sorgu' [--dal ceza] [--tip karar]")
        print("Örnek: python3 retriever.py 'iş kazası tazminat'")
        print("Örnek: python3 retriever.py 'hırsızlık cezası' --dal ceza")
        sys.exit(1)

    # Argüman parse
    args = sys.argv[1:]
    query_parts = []
    hukuk_dali = None
    tip = None
    i = 0
    while i < len(args):
        if args[i] == "--dal" and i + 1 < len(args):
            hukuk_dali = args[i + 1]
            i += 2
        elif args[i] == "--tip" and i + 1 < len(args):
            tip = args[i + 1]
            i += 2
        else:
            query_parts.append(args[i])
            i += 1

    query = " ".join(query_parts)
    print(f"Sorgu: {query}")
    print(f"Model: {MODEL_NAME}")
    print(f"Hybrid: semantic={SEMANTIC_WEIGHT} + bm25={BM25_WEIGHT}")
    if hukuk_dali:
        print(f"Hukuk dalı filtresi: {hukuk_dali}")
    if tip:
        print(f"Tip filtresi: {tip}")
    print("=" * 60)

    results = retrieve(query, n_results=10,
                       hukuk_dali_filter=hukuk_dali,
                       tip_filter=tip)

    for i, r in enumerate(results, 1):
        dal_info = f" [{r.get('hukuk_dali', '')}]" if r.get("hukuk_dali") else ""
        tip_info = f" ({r.get('tip', '')})" if r.get("tip") else ""
        print(f"\n--- #{i} (skor: {r['score']}){dal_info}{tip_info} ---")
        print(f"[{r['ref']}] — {r['kanun_ad']}")
        print(r["text"][:300] + ("..." if len(r["text"]) > 300 else ""))

    print(f"\n{'=' * 60}")
    print(f"Toplam {len(results)} sonuç")
