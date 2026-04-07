#!/usr/bin/env python3
"""
Claude Reranker — RAG sonuçlarını Claude ile yeniden sıralar.
İlk retrieval sonuçlarından en alakalı olanları seçer.

Kullanım: retrieve() sonuçlarını rerank() ile iyileştir.
Maliyet: ~0.01$ per rerank (Haiku ile)
"""

import os
import json
import anthropic

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def rerank(query: str, results: list[dict], top_k: int = 10) -> list[dict]:
    """
    Claude ile sonuçları yeniden sırala.
    
    Args:
        query: Kullanıcı sorusu
        results: retrieve() çıktısı
        top_k: Döndürülecek sonuç sayısı
    
    Returns:
        Yeniden sıralanmış sonuçlar (top_k adet)
    """
    client = _get_client()
    if not client or len(results) <= top_k:
        return results[:top_k]
    
    # Sonuçları numaralandırılmış liste olarak hazırla
    items = []
    for i, r in enumerate(results):
        ref = r.get("ref", "?")
        kanun = r.get("kanun_ad", "?")
        # Metin kısa tut (reranking için tam metin gereksiz)
        text_preview = r.get("text", "")[:300]
        items.append(f"[{i}] {ref} — {kanun}\n{text_preview}")
    
    items_text = "\n\n".join(items)
    
    prompt = f"""Kullanıcı sorusu: \"{query}\"

Aşağıda bu soruyla ilgili olabilecek hukuki kaynaklar var. Her birinin numarası köşeli parantez içinde.

{items_text}

Bu soruyla EN ALAKALI {top_k} kaynağı seç ve numaralarını alakalılık sırasına göre JSON array olarak döndür.
SADECE JSON array döndür, başka bir şey yazma.
Örnek: [3, 0, 7, 1, 5]"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        
        text = response.content[0].text.strip()
        # JSON parse
        indices = json.loads(text)
        
        # Geçerli indeksleri filtrele
        valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(results)]
        
        # Yeniden sıralanmış sonuçlar
        reranked = [results[i] for i in valid[:top_k]]
        
        # Rerank edilemeyen sonuçları sona ekle
        remaining = [r for i, r in enumerate(results) if i not in valid]
        reranked.extend(remaining[:max(0, top_k - len(reranked))])
        
        return reranked[:top_k]
    
    except Exception:
        # Reranking başarısız olursa orijinal sırayı koru
        return results[:top_k]
