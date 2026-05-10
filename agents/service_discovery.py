"""
Service Discovery Agent — Phase 1 core agent.

Flow:
  1. Parse patient needs → identify required service codes
  2. Query Pinecone RAG with ward filter
  3. Ask Claude to rank + explain the top matches in bilingual output
  4. Return ranked_services into state

All steps are traced via Langfuse.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from groq import Groq

from agents.state import CareState
from config.settings import get_settings
from observability.tracing import trace_agent_step

settings = get_settings()
_groq = Groq(
    api_key=settings.groq_api_key,
    http_client=httpx.Client(timeout=httpx.Timeout(timeout=120.0, connect=30.0)),
    max_retries=3,
)


# ── Step 1: Identify required service codes ────────────────────────────────

CLASSIFY_PROMPT = """\
You are a Japanese eldercare coordinator. Given a patient's care needs, \
identify which 介護保険 service type codes are required.

Service codes:
11 = 訪問介護 (Home Visit Care) — daily living assistance
12 = 訪問入浴介護 (Home Visit Bathing) — for bedridden patients
13 = 訪問看護 (Home Visit Nursing) — medical nursing at home
14 = 訪問リハビリ (Home Visit Rehab) — physiotherapy at home
21 = 通所介護 (Day Service) — daytime social/care centre
22 = 通所リハビリ (Day Rehab) — daytime physiotherapy
31 = 短期入所 (Short-Stay) — respite / temporary residential care
41 = 特養 (Special Nursing Home) — full-time residential care level 3+
42 = 老健 (Care Health Facility) — post-hospital rehab

Patient needs:
{needs}

Respond with JSON only: {{"service_codes": ["11", "13"], "reasoning": "..."}}
"""


def classify_needs(needs: str, trace=None) -> tuple[list[str], str]:
    """Use Claude Haiku to map patient needs → service codes."""
    prompt = CLASSIFY_PROMPT.format(needs=needs)

    response = _groq.chat.completions.create(
        model=settings.critic_model,
        max_tokens=256,
        timeout=30,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()

    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        codes = parsed.get("service_codes", [])
        reasoning = parsed.get("reasoning", "")
    except json.JSONDecodeError:
        codes = ["11"]  # default fallback
        reasoning = "Could not parse classification, defaulting to home visit care."

    trace_agent_step(
        trace, "classify_needs",
        input_data=needs, output_data={"codes": codes, "reasoning": reasoning},
        model=settings.critic_model,
    )
    return codes, reasoning


# ── Step 2: Retrieve + rank with Claude ───────────────────────────────────

RANK_PROMPT = """\
You are a Japanese eldercare coordinator. Rank the following care facilities \
for this patient. Explain your ranking in both English and Japanese.

Patient:
- Age: {age}
- Ward: {ward}
- Care level (介護度): {care_level}
- Needs: {needs}

Candidate facilities (from database):
{facilities}

For each facility, provide:
1. Rank (1 = best match)
2. Match score 0-100
3. Reason in English (1-2 sentences)
4. 理由 in Japanese (1-2 sentences)
5. Any caution flags

Respond with JSON only:
{{
  "ranked": [
    {{
      "rank": 1,
      "id": "...",
      "name": "...",
      "match_score": 85,
      "reason_en": "...",
      "reason_jp": "...",
      "cautions": []
    }}
  ],
  "confidence": 0.87
}}
"""


def rank_services(
    state: CareState,
    candidates: list[dict],
    trace=None,
) -> tuple[list[dict], float]:
    """Use Claude Sonnet to rank candidate facilities for the patient."""
    facility_text = json.dumps(candidates, ensure_ascii=False, indent=2)

    prompt = RANK_PROMPT.format(
        age=state["patient_age"],
        ward=state["ward"],
        care_level=state.get("care_level", 0),
        needs=state["needs_description"],
        facilities=facility_text,
    )

    response = _groq.chat.completions.create(
        model=settings.orchestrator_model,
        max_tokens=512,
        timeout=30,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()

    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        ranked = parsed.get("ranked", [])
        confidence = float(parsed.get("confidence", 0.5))
    except (json.JSONDecodeError, ValueError):
        # Fallback: return candidates unsorted
        ranked = [
            {**c, "rank": i + 1, "match_score": 50,
             "reason_en": "Ranking unavailable.", "reason_jp": "ランキング不可。",
             "cautions": []}
            for i, c in enumerate(candidates)
        ]
        confidence = 0.3

    trace_agent_step(
        trace, "rank_services",
        input_data=f"{len(candidates)} candidates",
        output_data={"top": ranked[0] if ranked else None, "confidence": confidence},
        model=settings.orchestrator_model,
        confidence=confidence,
    )
    return ranked, confidence


# ── LangGraph node ─────────────────────────────────────────────────────────

def service_discovery_node(state: CareState) -> dict:
    """
    LangGraph node: Service Discovery Agent.
    Mutates state with discovered_services and ranked_services.
    """
    from rag.retriever import retrieve

    trace = state.get("_trace")
    needs = state["needs_description"]
    ward = state["ward"]

    # Step 1: Classify needs → service codes
    service_codes, classification_reason = classify_needs(needs, trace)

    # Step 2: Retrieve from Pinecone
    candidates = retrieve(
        query=needs,
        top_k=3,
        ward=ward,
        service_codes=service_codes if service_codes else None,
    )

    if not candidates:
        # Try again without ward filter (patient might accept nearby wards)
        candidates = retrieve(query=needs, top_k=3, service_codes=service_codes)

    # Step 3: Rank with Claude
    ranked, confidence = rank_services(state, candidates, trace)

    return {
        "required_service_codes": service_codes,
        "discovered_services": candidates,
        "ranked_services": ranked,
        "current_agent": "service_discovery",
        "messages": state.get("messages", []) + [
            {
                "agent": "service_discovery",
                "content": (
                    f"Found {len(candidates)} candidates. "
                    f"Service codes needed: {service_codes}. "
                    f"Ranking confidence: {confidence:.0%}. "
                    f"Reason: {classification_reason}"
                ),
            }
        ],
    }
