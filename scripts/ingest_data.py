"""
Data ingestion pipeline — run this once before starting the API.

Steps:
  1. Load or scrape MHLW care facility data
  2. Chunk into bilingual text blocks
  3. Embed with multilingual-e5-large
  4. Upsert into Pinecone

Usage:
  python scripts/ingest_data.py          # uses sample data (no scraping)
  python scripts/ingest_data.py --live   # scrapes MHLW live
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console

console = Console()


def main(use_live: bool = False):
    console.rule("[bold blue]Kaigo Navigator — Data Ingestion[/bold blue]")

    # Step 1: Load data
    if use_live:
        console.print("[yellow]Live mode: scraping MHLW...[/yellow]")
        from scrapers.mhlw_scraper import run_scraper
        facilities = asyncio.run(run_scraper())
    else:
        console.print("[dim]Using sample data (pass --live to scrape MHLW)[/dim]")
        from scrapers.mhlw_scraper import load_or_generate_sample_data
        facilities = load_or_generate_sample_data()

    console.print(f"Loaded [bold]{len(facilities)}[/bold] facilities.")

    # Step 2: Chunk
    from rag.chunker import build_chunks
    chunks = build_chunks(facilities)
    console.print(f"Built [bold]{len(chunks)}[/bold] chunks.")

    # Step 3: Embed + upsert
    from rag.embedder import embed_and_upsert
    total = embed_and_upsert(chunks)

    console.rule("[bold green]Ingestion complete[/bold green]")
    console.print(f"[green]{total} vectors in Pinecone.[/green]")
    console.print("You can now run: [bold]uvicorn api.main:app --reload[/bold]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Scrape MHLW live data")
    args = parser.parse_args()
    main(use_live=args.live)
