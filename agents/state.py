"""
Shared LangGraph state for the Kaigo Navigator multi-agent system.
All agents read from and write to this state.
"""

from typing import Any, Optional
from typing_extensions import TypedDict


class CareState(TypedDict):
    # ── Input ──────────────────────────────────────────────────
    request_id: str
    patient_name: str          # can be anonymized (e.g. "患者A")
    patient_age: int
    ward: str                  # e.g. "世田谷区"
    care_level: int            # 介護度 1-5 (0 = not yet assessed)
    needs_description: str     # free-text, bilingual

    # ── Service Discovery ──────────────────────────────────────
    required_service_codes: list[str]   # e.g. ["11", "13"]
    discovered_services: list[dict]     # raw retrieval results
    ranked_services: list[dict]         # Claude-ranked + explained

    # ── Paperwork (Phase 2) ────────────────────────────────────
    forms_required: list[str]
    forms_prefilled: list[dict]
    awaiting_human_approval: bool       # GUARD: blocks form submission

    # ── Scheduling (Phase 3) ──────────────────────────────────
    scheduled_visits: list[dict]
    line_reminders: list[dict]
    schedule_meta: Optional[dict]

    # ── Monitoring (Phase 3) ──────────────────────────────────
    care_plan_score: Optional[float]
    monitoring_alerts: list[str]
    monitoring_analysis: Optional[dict]

    # ── Orchestration ─────────────────────────────────────────
    current_agent: str
    status: str                # "processing" | "awaiting_human" | "complete" | "error"
    error: Optional[str]
    messages: list[dict]       # conversation log

    # ── Observability ─────────────────────────────────────────
    _trace: Optional[Any]         # Langfuse trace object (not serialized)
