#!/usr/bin/env python3
"""
Lokal Reranker — RAG sonuçlarını keyword matching ile yeniden sıralar.
Claude API yerine basit TF-IDF benzeri skorlama kullanır.
"""

import re


def _tokenize(text: str) -> list[str]:
    """Basit Türkçe tokenizer."""
    text = text.lower()
    text = re.sub(r'[^\w\sçğıöşü]', ' ', text)
    return [t for t in text.split() if len(t) > 1]


def _keyword_overlap_score(query_tokens: list[str], doc_text: str) -> float:
    """Sorgu ve döküman arasındaki keyword overlap skoru."""
    doc_tokens = set(_tokenize(doc_text))
    if not query_tokens or not doc_tokens:
        return 0.0

    overlap = sum(1 for t in query_tokens if t in doc_tokens)
    return overlap / len(query_tokens)


def rerank(query: str, results: list[dict], top_k: int = 10) -> list[dict]:
    """
    Sonuçları keyword overlap + orijinal skor ile yeniden sırala.

    Args:
        query: Kullanıcı sorusu
        results: retrieve() çıktısı
        top_k: Döndürülecek sonuç sayısı

    Returns:
        Yeniden sıralanmış sonuçlar (top_k adet)
    """
    if len(results) <= top_k:
        return results[:top_k]

    query_tokens = _tokenize(query)

    scored = []
    for r in results:
        text = r.get("text", "")
        keyword_score = _keyword_overlap_score(query_tokens, text)
        original_score = r.get("score", 0.0)
        # Kombine skor: %60 orijinal RAG skoru + %40 keyword overlap
        combined = 0.6 * original_score + 0.4 * keyword_score
        scored.append((combined, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]
