"""
MHLW Ingestion Pipeline — Diagnostic Test

Tests the full pipeline WITHOUT writing to Pinecone:
  1. MHLW connectivity check
  2. Scrape 1 service code, 1 page (code 11 = 訪問介護, 世田谷区)
  3. Chunk quality report — shows exactly what each vector will contain
  4. Embedding smoke test — confirms model loads and encodes correctly
  5. Gap analysis — live data vs sample data field coverage

Run:
  PYTHONPATH=. python scripts/test_mhlw_pipeline.py
"""

import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
SEP = "─" * 60


# ── Step 1: Connectivity ──────────────────────────────────────────────────────

def test_connectivity() -> bool:
    console.rule("[bold blue]Step 1 — MHLW Connectivity[/bold blue]")
    import httpx
    from config.settings import get_settings
    settings = get_settings()

    url = f"{settings.mhlw_base_url}/{settings.tokyo_pref_code}/index.php"
    console.print(f"Target: [dim]{url}[/dim]")

    try:
        resp = httpx.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; research bot)",
            "Accept-Language": "ja,en;q=0.9",
        })
        console.print(f"Status      : [bold green]{resp.status_code}[/bold green]")
        console.print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")
        console.print(f"Body size   : {len(resp.content):,} bytes")
        return resp.status_code == 200
    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/red]")
        return False


# ── Step 2: Scrape 1 page ─────────────────────────────────────────────────────

async def test_scraper() -> list[dict]:
    console.rule("[bold blue]Step 2 — Live Scrape (code 11, page 1 only)[/bold blue]")

    from scrapers.mhlw_scraper import _fetch_page, _parse_search_results
    import httpx

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en;q=0.9",
    }

    service_code = "11"
    console.print(f"Fetching: service_code={service_code}, page=1")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        html = await _fetch_page(client, service_code, page=1)

    if not html:
        console.print("[red]No HTML returned — MHLW may have changed structure[/red]")
        return []

    console.print(f"HTML received: {len(html):,} chars")

    facilities = _parse_search_results(html, service_code)
    console.print(f"Facilities parsed: [bold]{len(facilities)}[/bold]")

    if facilities:
        console.print("\n[dim]First 3 results:[/dim]")
        for i, f in enumerate(facilities[:3], 1):
            console.print(f"  {i}. {f.get('name')} | {f.get('ward')} | {f.get('phone')}")

    return facilities


# ── Step 3: Chunk quality ─────────────────────────────────────────────────────

def test_chunk_quality(live_facilities: list[dict]):
    console.rule("[bold blue]Step 3 — Chunk Quality Analysis[/bold blue]")

    from rag.chunker import facility_to_chunk
    from scrapers.mhlw_scraper import load_or_generate_sample_data

    sample = load_or_generate_sample_data()
    sample_chunk = facility_to_chunk(sample[0])  # 世田谷ケアサービスセンター

    console.print("\n[bold]Sample data chunk (what we have now):[/bold]")
    console.print(Panel(sample_chunk["text"], border_style="green", title="sample"))

    if live_facilities:
        live_chunk = facility_to_chunk(live_facilities[0])
        console.print("\n[bold]Live scraped chunk:[/bold]")
        console.print(Panel(live_chunk["text"], border_style="yellow", title="live"))

        # Field coverage comparison
        table = Table(title="Field Coverage: Live vs Sample")
        table.add_column("Field", style="bold")
        table.add_column("Sample", style="green")
        table.add_column("Live", style="yellow")

        fields = ["name", "ward", "address", "phone", "service_code",
                  "service_name", "capacity", "operating_hours",
                  "description_jp", "description_en"]

        for field in fields:
            s_val = "✅" if sample[0].get(field) else "❌"
            l_val = "✅" if (live_facilities[0].get(field) if live_facilities else None) else "❌"
            table.add_row(field, s_val, l_val)

        console.print(table)
    else:
        console.print("[yellow]No live data to compare (scraper returned 0 results)[/yellow]")


# ── Step 4: Embedding smoke test ──────────────────────────────────────────────

def test_embedding():
    console.rule("[bold blue]Step 4 — Embedding Smoke Test[/bold blue]")
    from sentence_transformers import SentenceTransformer
    from config.settings import get_settings
    settings = get_settings()

    console.print(f"Loading: [dim]{settings.embedding_model}[/dim]")
    try:
        model = SentenceTransformer(settings.embedding_model)
        test_text = "passage: 世田谷区の訪問介護サービス。Home visit care in Setagaya ward."
        vec = model.encode(test_text, normalize_embeddings=True)
        console.print(f"Model loaded   : ✅")
        console.print(f"Vector dim     : {len(vec)} (expected 1024)")
        console.print(f"Vector norm    : {sum(x**2 for x in vec)**0.5:.4f} (expected ~1.0)")
        return True
    except Exception as e:
        console.print(f"[red]Embedding failed: {e}[/red]")
        return False


# ── Step 5: Pinecone index stats (read-only) ──────────────────────────────────

def test_pinecone_stats():
    console.rule("[bold blue]Step 5 — Pinecone Index Stats (read-only)[/bold blue]")
    from pinecone import Pinecone
    from config.settings import get_settings
    settings = get_settings()

    if not settings.pinecone_api_key:
        console.print("[yellow]PINECONE_API_KEY not set — skipping[/yellow]")
        return

    try:
        pc = Pinecone(api_key=settings.pinecone_api_key)
        index = pc.Index(settings.pinecone_index_name)
        stats = index.describe_index_stats()

        console.print(f"Index name     : {settings.pinecone_index_name}")
        console.print(f"Total vectors  : [bold]{stats.total_vector_count}[/bold]")
        console.print(f"Dimension      : {stats.dimension}")
        console.print(f"Index fullness : {stats.index_fullness:.4%}")

        if stats.namespaces:
            for ns, ns_stats in stats.namespaces.items():
                console.print(f"  Namespace '{ns}': {ns_stats.vector_count} vectors")
    except Exception as e:
        console.print(f"[red]Pinecone error: {e}[/red]")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(connectivity: bool, scraped: list[dict], embedding_ok: bool):
    console.rule("[bold]Summary[/bold]")

    table = Table()
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_column("Notes")

    table.add_row(
        "MHLW connectivity",
        "✅ OK" if connectivity else "❌ Failed",
        "Website reachable" if connectivity else "May have changed URL/structure"
    )
    table.add_row(
        "HTML parsing",
        f"✅ {len(scraped)} facilities" if scraped else "⚠️  0 facilities",
        "Parser found results" if scraped else "Table selector may need updating"
    )

    missing_fields = []
    if scraped:
        f = scraped[0]
        for field in ["capacity", "operating_hours", "description_jp", "description_en"]:
            if not f.get(field):
                missing_fields.append(field)

    table.add_row(
        "Field coverage",
        "⚠️  Partial" if missing_fields else "✅ Full",
        f"Missing: {', '.join(missing_fields)}" if missing_fields else "All fields present"
    )
    table.add_row(
        "Embedding model",
        "✅ OK" if embedding_ok else "❌ Failed",
        "multilingual-e5-large ready" if embedding_ok else "Model may need download"
    )

    console.print(table)

    if missing_fields:
        console.print("\n[yellow bold]⚠️  Action needed before running --live:[/yellow bold]")
        console.print(
            f"Live scraper is missing: [bold]{', '.join(missing_fields)}[/bold]\n"
            "These fields enrich embeddings. Without them, retrieval quality will be lower.\n"
            "See: scrapers/mhlw_scraper.py → _parse_facility_from_row() to add detail page fetching."
        )
    else:
        console.print("\n[green bold]✅ Pipeline is ready for --live ingestion.[/green bold]")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    console.print("\n[bold]MHLW Ingestion Pipeline — Diagnostic[/bold]\n")

    connectivity = test_connectivity()
    scraped = await test_scraper() if connectivity else []
    test_chunk_quality(scraped)
    embedding_ok = test_embedding()
    test_pinecone_stats()
    print_summary(connectivity, scraped, embedding_ok)


if __name__ == "__main__":
    asyncio.run(main())
