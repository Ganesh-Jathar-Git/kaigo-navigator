"""
Pinecone retrieval with optional metadata filtering.

Supports:
  - Free-text query (bilingual JP/EN)
  - Filter by ward (区)
  - Filter by service_code
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

# Use locally cached model — never hit HuggingFace Hub at runtime
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

from config.settings import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model)


@lru_cache(maxsize=1)
def _get_index():
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index_name)


def retrieve(
    query: str,
    top_k: int = 5,
    ward: str | None = None,
    service_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve top-k care facilities matching the query.

    Args:
        query: Natural language query (JP or EN)
        top_k: Number of results to return
        ward: Filter to a specific ward (e.g. "世田谷区")
        service_codes: Filter to specific service types (e.g. ["11", "13"])

    Returns:
        List of dicts with keys: id, score, name, ward, service_name, address, phone
    """
    model = _get_model()
    index = _get_index()

    # multilingual-e5 query prefix
    query_embedding = model.encode(
        f"query: {query}",
        normalize_embeddings=True,
    ).tolist()

    # Build metadata filter
    filter_dict: dict[str, Any] = {}
    if ward:
        filter_dict["ward"] = {"$eq": ward}
    if service_codes:
        filter_dict["service_code"] = {"$in": service_codes}

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
        filter=filter_dict if filter_dict else None,
    )

    matches = []
    for match in results.matches:
        meta = match.metadata or {}
        matches.append({
            "id": match.id,
            "score": round(float(match.score), 4),
            "name": meta.get("name", ""),
            "ward": meta.get("ward", ""),
            "service_name": meta.get("service_name", ""),
            "service_code": meta.get("service_code", ""),
            "address": meta.get("address", ""),
            "phone": meta.get("phone", ""),
            "capacity": meta.get("capacity", 0),
        })

    return matches
