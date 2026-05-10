"""
Embedding + Pinecone upsert pipeline.

Uses intfloat/multilingual-e5-large — free, local, supports JP + EN.
Upserts chunks into Pinecone with bilingual text and metadata.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pinecone import Pinecone, ServerlessSpec
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from sentence_transformers import SentenceTransformer

from config.settings import get_settings

console = Console()
settings = get_settings()

DIMENSION = 1024       # multilingual-e5-large output dim
BATCH_SIZE = 32        # upsert batch size
UPSERT_DELAY = 0.2     # seconds between batches


def _get_model() -> SentenceTransformer:
    """Load embedding model (cached after first load)."""
    console.print(f"[dim]Loading embedding model: {settings.embedding_model}[/dim]")
    return SentenceTransformer(settings.embedding_model)


def _get_index(pc: Pinecone):
    """Get or create the Pinecone index."""
    index_name = settings.pinecone_index_name

    existing = [i.name for i in pc.list_indexes()]
    if index_name not in existing:
        console.print(f"[yellow]Creating Pinecone index '{index_name}'...[/yellow]")
        pc.create_index(
            name=index_name,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=settings.pinecone_environment),
        )
        # Wait until ready
        while not pc.describe_index(index_name).status.get("ready"):
            time.sleep(1)
        console.print(f"[green]Index '{index_name}' ready.[/green]")
    else:
        console.print(f"[dim]Using existing index '{index_name}'.[/dim]")

    return pc.Index(index_name)


def embed_and_upsert(chunks: list[dict[str, Any]]) -> int:
    """
    Embed all chunks and upsert into Pinecone.
    Returns number of vectors upserted.
    """
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY not set in .env")

    model = _get_model()
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = _get_index(pc)

    texts = [c["text"] for c in chunks]

    console.print(f"Embedding {len(texts)} chunks with {settings.embedding_model}...")

    # multilingual-e5 requires a query/passage prefix
    prefixed = [f"passage: {t}" for t in texts]
    embeddings = model.encode(
        prefixed,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    # Upsert in batches
    total_upserted = 0
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Upserting to Pinecone", total=len(chunks))

        for i in range(0, len(chunks), BATCH_SIZE):
            batch_chunks = chunks[i : i + BATCH_SIZE]
            batch_vectors = [
                {
                    "id": c["id"],
                    "values": embeddings[i + j].tolist(),
                    "metadata": c["metadata"],
                }
                for j, c in enumerate(batch_chunks)
            ]
            index.upsert(vectors=batch_vectors)
            total_upserted += len(batch_vectors)
            progress.advance(task, len(batch_vectors))
            time.sleep(UPSERT_DELAY)

    console.print(f"[bold green]Upserted {total_upserted} vectors to Pinecone.[/bold green]")
    return total_upserted
