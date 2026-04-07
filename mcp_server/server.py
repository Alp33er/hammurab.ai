#!/usr/bin/env python3
"""
Berry Hukuk AI — Mevzuat MCP Sunucusu

Türk mevzuatı ve Yargıtay kararlarına MCP (Model Context Protocol) üzerinden erişim.
Claude Desktop veya diğer MCP istemcileri ile kullanılabilir.

Araçlar:
  - mevzuat_ara: Mevzuat ve içtihat arama (hybrid RAG)
  - kanun_madde: Belirli bir kanun maddesini getir
  - kanun_listele: Mevcut kanunları listele
  - yargitay_ara: Yargıtay kararlarında arama
  - sure_hesapla: Hukuki süre hesaplama
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# RAG modülünü import et
from rag.retriever import retrieve, format_context
from rag.citation_graph import query_citations, GRAPH_PATH

# Veri yolları
JSON_DIR = PROJECT_ROOT / "scraper" / "data" / "json"
YARGITAY_DIR = PROJECT_ROOT / "scraper" / "data" / "yargitay" / "json"

app = Server("berry-hukuk-mevzuat")


# ─── YARDIMCI FONKSİYONLAR ──────────────────────────

def _load_kanun_index() -> dict:
    """Kanun index'ini yükle."""
    index_path = JSON_DIR / "index.json"
    if not index_path.exists():
        return {"kanunlar": []}
    return json.loads(index_path.read_text(encoding="utf-8"))


def _load_kanun(kanun_kisa: str) -> dict | None:
    """Belirli bir kanunu yükle."""
    index = _load_kanun_index()
    for k in index["kanunlar"]:
        if k["kisa_ad"].lower() == kanun_kisa.lower():
            json_path = JSON_DIR / k["dosya"]
            if json_path.exists():
                return json.loads(json_path.read_text(encoding="utf-8"))
    return None


def _get_madde(kanun_kisa: str, madde_no: int) -> dict | None:
    """Belirli bir kanun maddesini getir."""
    kanun = _load_kanun(kanun_kisa)
    if not kanun:
        return None
    for madde in kanun["maddeler"]:
        if madde["madde_no"] == madde_no:
            return madde
    return None


# ─── SÜRE HESAPLAMA ──────────────────────────────────

HUKUKI_SURELER = {
    "istinaf_hukuk": {"gun": 14, "aciklama": "HMK m.345 — İstinaf süresi (hukuk)"},
    "temyiz_hukuk": {"gun": 14, "aciklama": "HMK m.361 — Temyiz süresi (hukuk)"},
    "istinaf_ceza": {"gun": 7, "aciklama": "CMK m.273 — İstinaf süresi (ceza)"},
    "temyiz_ceza": {"gun": 15, "aciklama": "CMK m.291 — Temyiz süresi (ceza)"},
    "idari_dava": {"gun": 60, "aciklama": "İYUK m.7 — İdari dava açma süresi"},
    "icra_itiraz": {"gun": 7, "aciklama": "İİK m.16 — İcra itiraz süresi"},
    "arabuluculuk_is": {"gun": 21, "aciklama": "İş uyuşmazlıklarında arabuluculuk (3 haftaya kadar uzatılabilir)"},
    "ihtarname_cevap": {"gun": 7, "aciklama": "Genel ihtarname cevap süresi"},
    "tuketici_sikayet": {"gun": 30, "aciklama": "Tüketici şikâyet başvuru süresi"},
}


# ─── MCP ARAÇLARI ────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="mevzuat_ara",
            description="Türk mevzuatı ve Yargıtay kararlarında arama yapar. Kanun maddeleri ve içtihatları hybrid search (semantik + anahtar kelime) ile bulur.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sorgu": {
                        "type": "string",
                        "description": "Aranacak metin (örn: 'iş kazası tazminat', 'boşanma nafaka')",
                    },
                    "hukuk_dali": {
                        "type": "string",
                        "description": "Hukuk dalı filtresi (medeni, borclar, ceza, is, ticaret, idare, icra_iflas, usul)",
                        "enum": ["medeni", "borclar", "ceza", "is", "ticaret", "idare",
                                 "icra_iflas", "usul", "anayasa", "tuketici", "sosyal_guvenlik"],
                    },
                    "tip": {
                        "type": "string",
                        "description": "İçerik tipi filtresi",
                        "enum": ["kanun", "karar"],
                    },
                    "sonuc_sayisi": {
                        "type": "integer",
                        "description": "Döndürülecek sonuç sayısı (varsayılan: 10)",
                        "default": 10,
                    },
                },
                "required": ["sorgu"],
            },
        ),
        Tool(
            name="kanun_madde",
            description="Belirli bir kanunun belirli bir maddesini getirir. Tam metin döner.",
            inputSchema={
                "type": "object",
                "properties": {
                    "kanun": {
                        "type": "string",
                        "description": "Kanun kısa adı (tmk, tbk, tck, cmk, hmk, ik, ttk, iik, iyuk, anayasa vb.)",
                    },
                    "madde_no": {
                        "type": "integer",
                        "description": "Madde numarası",
                    },
                },
                "required": ["kanun", "madde_no"],
            },
        ),
        Tool(
            name="kanun_listele",
            description="Veritabanındaki tüm kanunları listeler (kısa ad, tam ad, madde sayısı).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="sure_hesapla",
            description="Hukuki süre hesaplar. Tebliğ tarihinden itibaren sürenin dolacağı tarihi verir.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sure_turu": {
                        "type": "string",
                        "description": "Süre türü",
                        "enum": list(HUKUKI_SURELER.keys()),
                    },
                    "teblig_tarihi": {
                        "type": "string",
                        "description": "Tebliğ/başlangıç tarihi (GG/AA/YYYY formatında)",
                    },
                },
                "required": ["sure_turu", "teblig_tarihi"],
            },
        ),
                Tool(
            name="atif_sorgula",
            description="Belirli bir kanun maddesine yapilan atiflari ve bu maddenin atif yaptigi diger maddeleri gosterir.",
            inputSchema={
                "type": "object",
                "properties": {
                    "kanun": {
                        "type": "string",
                        "description": "Kanun kisa adi (tmk, tbk, tck, hmk, ik vb.)",
                    },
                    "madde_no": {
                        "type": "integer",
                        "description": "Madde numarasi",
                    },
                },
                "required": ["kanun", "madde_no"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "mevzuat_ara":
        sorgu = arguments["sorgu"]
        hukuk_dali = arguments.get("hukuk_dali")
        tip = arguments.get("tip")
        n = arguments.get("sonuc_sayisi", 10)

        results = retrieve(
            query=sorgu,
            n_results=n,
            hukuk_dali_filter=hukuk_dali,
            tip_filter=tip,
        )

        if not results:
            return [TextContent(type="text", text=f"'{sorgu}' için sonuç bulunamadı.")]

        context = format_context(results)
        summary = f"**{len(results)} sonuç bulundu** (sorgu: '{sorgu}')\n\n"
        return [TextContent(type="text", text=summary + context)]

    elif name == "kanun_madde":
        kanun = arguments["kanun"]
        madde_no = arguments["madde_no"]

        madde = _get_madde(kanun, madde_no)
        if not madde:
            return [TextContent(type="text", text=f"{kanun.upper()} m.{madde_no} bulunamadı.")]

        text = f"**[{madde['ref']}]** — {madde['kanun_ad']}\n\n{madde['text']}"
        return [TextContent(type="text", text=text)]

    elif name == "kanun_listele":
        index = _load_kanun_index()
        lines = ["# Mevcut Kanunlar\n"]
        lines.append(f"| Kısa Ad | Tam Ad | Madde Sayısı |")
        lines.append(f"|---------|--------|-------------|")
        for k in index["kanunlar"]:
            lines.append(f"| {k['kisa_ad']} | {k['tam_ad']} | {k['madde_sayisi']} |")
        lines.append(f"\n**Toplam: {len(index['kanunlar'])} kanun, {index.get('toplam_madde', '?')} madde**")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "sure_hesapla":
        sure_turu = arguments["sure_turu"]
        teblig_str = arguments["teblig_tarihi"]

        sure_info = HUKUKI_SURELER.get(sure_turu)
        if not sure_info:
            return [TextContent(type="text", text=f"Bilinmeyen sure turu: {sure_turu}")]

        try:
            teblig = datetime.strptime(teblig_str, "%d/%m/%Y")
        except ValueError:
            return [TextContent(type="text", text="Tarih formati hatali. GG/AA/YYYY kullanin.")]

        bitis = teblig + timedelta(days=sure_info["gun"])
        if bitis.weekday() == 5:
            bitis += timedelta(days=2)
        elif bitis.weekday() == 6:
            bitis += timedelta(days=1)

        kalan = (bitis - datetime.now()).days
        warn = " SURESI GECMIS!" if kalan < 0 else " SON 3 GUN!" if kalan <= 3 else ""
        text = (
            f"# Sure Hesaplama\n\n"
            f"**Sure Turu**: {sure_info['aciklama']}\n"
            f"**Sure**: {sure_info['gun']} gun\n"
            f"**Teblig Tarihi**: {teblig.strftime('%d/%m/%Y')}\n"
            f"**Son Gun**: {bitis.strftime('%d/%m/%Y')}\n"
            f"**Kalan Gun**: {kalan} gun{warn}\n"
        )
        return [TextContent(type="text", text=text)]

    elif name == "atif_sorgula":
        kanun = arguments["kanun"].lower()
        madde_no = arguments["madde_no"]
        
        if not GRAPH_PATH.exists():
            return [TextContent(type="text", text="Atif grafi bulunamadi.")]
        
        import json as _json
        graph_data = _json.loads(GRAPH_PATH.read_text())
        graph = graph_data["graph"]
        
        ref = f"{kanun}:m{madde_no}"
        if ref not in graph:
            return [TextContent(type="text", text=f"{ref.upper()} atif grafinda bulunamadi.")]
        
        data = graph[ref]
        lines = [f"# Atif Analizi: {ref.upper()}", ""]
        
        if data["cites"]:
            lines.append(f"## Atif yaptigi maddeler ({len(data['cites'])})")
            for c in sorted(data["cites"]):
                lines.append(f"- {c}")
            lines.append("")
        
        if data["cited_by"]:
            lines.append(f"## Bu maddeye atif yapan maddeler ({len(data['cited_by'])})")
            for c in sorted(data["cited_by"]):
                lines.append(f"- {c}")
        
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "atif_sorgula":
        kanun = arguments["kanun"].lower()
        madde_no = arguments["madde_no"]
        
        if not GRAPH_PATH.exists():
            return [TextContent(type="text", text="Atif grafi bulunamadi.")]
        
        import json as _json
        graph_data = _json.loads(GRAPH_PATH.read_text())
        graph = graph_data["graph"]
        
        ref = f"{kanun}:m{madde_no}"
        if ref not in graph:
            return [TextContent(type="text", text=f"{ref.upper()} atif grafinda bulunamadi.")]
        
        data = graph[ref]
        lines = [f"# Atif Analizi: {ref.upper()}", ""]
        
        if data["cites"]:
            lines.append(f"## Atif yaptigi maddeler ({len(data['cites'])})")
            for c in sorted(data["cites"]):
                lines.append(f"- {c}")
            lines.append("")
        
        if data["cited_by"]:
            lines.append(f"## Bu maddeye atif yapan maddeler ({len(data['cited_by'])})")
            for c in sorted(data["cited_by"]):
                lines.append(f"- {c}")
        
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Bilinmeyen araç: {name}")]


# ─── ANA GİRİŞ ──────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
