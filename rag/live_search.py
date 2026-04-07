#!/usr/bin/env python3
"""
Canlı Karar Arama — yargi-mcp üzerinden Yargıtay, Danıştay, AYM'den anlık arama.
Local RAG ile birleştirilir (hibrit retrieval).
"""

import asyncio
import logging
from typing import Optional

from yargitay_mcp_module.client import YargitayOfficialApiClient
from yargitay_mcp_module.models import YargitayDetailedSearchRequest

logger = logging.getLogger(__name__)

_yargitay_client = None


def _get_yargitay_client():
    global _yargitay_client
    if _yargitay_client is None:
        _yargitay_client = YargitayOfficialApiClient(request_timeout=15.0)
    return _yargitay_client


async def search_yargitay_live(query: str, max_results: int = 10, daire: str = "ALL") -> list[dict]:
    """Yargıtay'dan canlı karar ara."""
    try:
        client = _get_yargitay_client()
        req = YargitayDetailedSearchRequest(
            arananKelime=query,
            birimYrgKurulDaire=daire,
            pageSize=min(max_results, 20),
        )
        result = await client.search_detailed_decisions(req)
        d = result.model_dump()
        data = d.get("data", {})

        if isinstance(data, dict):
            records = data.get("data", [])
            total = data.get("recordsTotal", 0)
        elif isinstance(data, list):
            records = data
            total = len(data)
        else:
            return []

        results = []
        for r in records[:max_results]:
            if not isinstance(r, dict):
                continue
            results.append({
                "ref": f"Yargıtay {r.get('dpiDaireBilgisi', '?')} E.{r.get('dpEsasNo', '?')} K.{r.get('dpKararNo', '?')}",
                "kanun_ad": f"Yargıtay {r.get('dpiDaireBilgisi', '?')} Kararı",
                "kanun_kisa": "yargitay_live",
                "madde_no": 0,
                "score": 0.7,
                "text": r.get("dpKararOzeti", r.get("dpKararMetni", ""))[:1500] or "Özet mevcut değil",
                "hukuk_dali": "karar",
                "tip": "karar_canli",
                "kaynak": "yargitay_canli",
                "toplam_sonuc": total,
            })

        return results
    except Exception as e:
        logger.warning(f"Yargıtay canlı arama hatası: {e}")
        return []


def search_yargitay_sync(query: str, max_results: int = 10) -> list[dict]:
    """Senkron wrapper — FastAPI endpoint'lerinden çağrılabilir."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Zaten bir event loop varsa (FastAPI), yeni thread'de çalıştır
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, search_yargitay_live(query, max_results))
                return future.result(timeout=20)
        else:
            return asyncio.run(search_yargitay_live(query, max_results))
    except Exception as e:
        logger.warning(f"Yargıtay sync arama hatası: {e}")
        return []


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "kıdem tazminatı"
    print(f"Sorgu: {query}")
    print("=" * 60)
    results = asyncio.run(search_yargitay_live(query, max_results=5))
    print(f"Toplam: {results[0].get('toplam_sonuc', '?') if results else 0}")
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['ref']}")
        print(f"   {r['text'][:200]}...")
    print("=" * 60)
