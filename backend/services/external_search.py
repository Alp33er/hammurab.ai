"""
Harici karar arama servisi — yargi-mcp üzerinden Yargıtay, Danıştay, AYM kararlarına erişim.
Kendi RAG veritabanında bulunamayan kararlar için dış kaynak sorgulaması.
"""

import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# yargi-mcp remote MCP endpoint
YARGI_MCP_URL = "https://yargimcp.fastmcp.app/mcp"

# Doğrudan API endpoint'leri (fallback)
YARGITAY_URL = "https://karararama.yargitay.gov.tr"
DANISTAY_URL = "https://karararama.danistay.gov.tr"
AYM_URL = "https://kararlarbilgibankasi.anayasa.gov.tr"

# Timeout ve retry
TIMEOUT = 30
MAX_RETRIES = 2


async def search_yargitay(query: str, max_results: int = 10,
                           daire: str = "ALL") -> list[dict]:
    """
    Yargıtay karar arama — karararama.yargitay.gov.tr üzerinden.
    Session cookie alıp arama yapar.
    """
    results = []
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=True,
                                      timeout=TIMEOUT) as client:
            # Session cookie al
            await client.get(f"{YARGITAY_URL}/")

            payload = {
                "data": {
                    "arananKelime": query,
                    "birimYrgKurulDaire": daire,
                    "esasYil": "",
                    "esasIlkSiraNo": "",
                    "esasSonSiraNo": "",
                    "kararYil": "",
                    "kararIlkSiraNo": "",
                    "kararSonSiraNo": "",
                    "baslangicTarihi": "",
                    "bitisTarihi": "",
                    "pageSize": max_results,
                    "pageNumber": 1,
                }
            }

            r = await client.post(
                f"{YARGITAY_URL}/aramadetaylist",
                json=payload,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{YARGITAY_URL}/",
                },
            )

            if r.status_code == 200:
                data = r.json()
                inner = data.get("data", {})
                records = inner.get("data", []) if isinstance(inner, dict) else []
                total = inner.get("recordsTotal", 0) if isinstance(inner, dict) else 0

                for rec in records:
                    results.append({
                        "kaynak": "yargitay",
                        "daire": rec.get("dpiDaireBilgisi", ""),
                        "esas_no": rec.get("dpEsasNo", ""),
                        "karar_no": rec.get("dpKararNo", ""),
                        "tarih": rec.get("dpKararTarihi", ""),
                        "ozet": rec.get("dpKararOzeti", ""),
                    })

                logger.info(f"Yargitay arama: '{query}' -> {total} toplam, {len(results)} donduruldu")
    except Exception as e:
        logger.warning(f"Yargitay arama hatasi: {e}")

    return results


async def search_danistay(query: str, max_results: int = 10) -> list[dict]:
    """Danıştay karar arama."""
    results = []
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=True,
                                      timeout=TIMEOUT) as client:
            await client.get(f"{DANISTAY_URL}/")

            payload = {
                "data": {
                    "arananKelime": query,
                    "pageSize": max_results,
                    "pageNumber": 1,
                }
            }

            r = await client.post(
                f"{DANISTAY_URL}/aramadetaylist",
                json=payload,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{DANISTAY_URL}/",
                },
            )

            if r.status_code == 200:
                data = r.json()
                inner = data.get("data", {})
                records = inner.get("data", []) if isinstance(inner, dict) else []

                for rec in records:
                    results.append({
                        "kaynak": "danistay",
                        "daire": rec.get("dpiDaireBilgisi", ""),
                        "esas_no": rec.get("dpEsasNo", ""),
                        "karar_no": rec.get("dpKararNo", ""),
                        "tarih": rec.get("dpKararTarihi", ""),
                        "ozet": rec.get("dpKararOzeti", ""),
                    })

                logger.info(f"Danistay arama: '{query}' -> {len(results)} sonuc")
    except Exception as e:
        logger.warning(f"Danistay arama hatasi: {e}")

    return results


async def search_all(query: str, max_results: int = 10) -> dict:
    """Tüm kaynaklarda arama yap."""
    import asyncio

    yargitay_task = search_yargitay(query, max_results)
    danistay_task = search_danistay(query, max_results)

    yargitay_results, danistay_results = await asyncio.gather(
        yargitay_task, danistay_task,
        return_exceptions=True,
    )

    if isinstance(yargitay_results, Exception):
        yargitay_results = []
    if isinstance(danistay_results, Exception):
        danistay_results = []

    return {
        "query": query,
        "yargitay": yargitay_results,
        "danistay": danistay_results,
        "toplam": len(yargitay_results) + len(danistay_results),
    }
