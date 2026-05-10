"""
Converts raw facility records into bilingual text chunks for embedding.
Each chunk = one facility, with both JP and EN content merged.
"""

from typing import Any


def facility_to_chunk(facility: dict[str, Any]) -> dict[str, Any]:
    """
    Build a single text chunk + metadata from a raw facility dict.
    The text is bilingual (JP + EN) to support both languages in search.
    """
    name = facility.get("name", "")
    ward = facility.get("ward", "")
    address = facility.get("address", "")
    service_name = facility.get("service_name", "")
    phone = facility.get("phone", "")
    capacity = facility.get("capacity", "")
    hours = facility.get("operating_hours", "")
    desc_jp = facility.get("description_jp", "")
    desc_en = facility.get("description_en", "")

    # Bilingual chunk text — used for embedding
    text = f"""
施設名 / Facility: {name}
区 / Ward: {ward}
住所 / Address: {address}
サービス種別 / Service Type: {service_name}
電話 / Phone: {phone}
定員 / Capacity: {capacity}
営業時間 / Hours: {hours}
{desc_jp}
{desc_en}
""".strip()

    # Metadata stored in Pinecone — used for filtering
    metadata = {
        "name": name,
        "ward": ward,
        "address": address,
        "service_code": facility.get("service_code", ""),
        "service_name": service_name,
        "phone": phone,
        "capacity": int(capacity) if str(capacity).isdigit() else 0,
        "source": facility.get("source", ""),
        "prefecture": facility.get("prefecture", "東京都"),
    }

    return {"text": text, "metadata": metadata}


def build_chunks(facilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a list of raw facility records into embedding-ready chunks."""
    chunks = []
    for i, facility in enumerate(facilities):
        chunk = facility_to_chunk(facility)
        # Stable ID: prefecture + service_code + index
        chunk["id"] = f"tokyo-{facility.get('service_code', 'xx')}-{i:04d}"
        chunks.append(chunk)
    return chunks
