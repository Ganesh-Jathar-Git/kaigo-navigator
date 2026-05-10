"""
Kaigo Navigator — FastAPI application.

Endpoints:
  POST /care-request               → run full agent graph, return ranked services + prefilled forms
  GET  /care-request/{id}/review   → get current state + prefilled forms for human review
  POST /care-request/{id}/approve  → approve forms and continue to submission
  POST /care-request/{id}/reject   → reject and reset
  GET  /health                     → health check
  GET  /services                   → list available service types
"""

from __future__ import annotations

import os
import time
from typing import Optional

# Use cached HuggingFace models — avoid slow network checks on startup
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config.settings import get_settings

settings = get_settings()
app = FastAPI(
    title="Kaigo Navigator API",
    description="Multi-agent eldercare coordination system — 介護ナビゲーター",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def warmup():
    """Pre-load embedding model and Pinecone index on startup to avoid cold-start timeouts."""
    import asyncio
    import concurrent.futures
    def _warm():
        try:
            from rag.retriever import retrieve
            retrieve("warmup", top_k=1)
        except Exception:
            pass
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1), _warm)


# ── Request / Response models ──────────────────────────────────────────────

class CareRequestInput(BaseModel):
    needs_description: str = Field(
        ...,
        description="Patient care needs in Japanese or English",
        examples=["週3回の訪問介護と月1回の訪問看護が必要です。認知症初期。"],
    )
    ward: str = Field(..., description="Tokyo ward (区)", examples=["世田谷区"])
    patient_age: int = Field(..., ge=60, le=120)
    patient_name: str = Field(default="患者", description="Anonymized name")
    care_level: int = Field(default=0, ge=0, le=5, description="介護度 (0=未認定)")


class CareRequestResponse(BaseModel):
    request_id: str
    status: str
    elapsed_ms: float
    ward: str
    service_codes_identified: list[str]
    top_matches: list[dict]
    forms_required: list[str]
    forms_prefilled: list[dict]
    messages: list[dict]
    error: Optional[str]


class ReviewResponse(BaseModel):
    request_id: str
    status: str
    forms_required: list[str]
    forms_prefilled: list[dict]
    top_matches: list[dict]
    messages: list[dict]


class ApprovalResponse(BaseModel):
    request_id: str
    status: str
    message: str
    messages: list[dict]
    care_plan_score: Optional[float] = None
    scheduled_visits_count: Optional[int] = None
    line_reminders_count: Optional[int] = None


class ScheduleResponse(BaseModel):
    request_id: str
    status: str
    scheduled_visits: list[dict]
    line_reminders: list[dict]
    schedule_summary_en: str
    schedule_summary_jp: str
    total_visits_per_week: int
    weeks: list[dict]


class MonitoringResponse(BaseModel):
    request_id: str
    status: str
    care_plan_score: Optional[float]
    monitoring_alerts: list[str]
    risk_level: str
    overall_assessment_en: str
    overall_assessment_jp: str
    recommendations_en: list[str]
    recommendations_jp: list[str]
    next_review_days: int


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "kaigo-navigator", "version": "0.3.0"}


@app.get("/services")
def list_service_types():
    return {"service_types": settings.service_type_codes}


@app.get("/wards")
def list_wards():
    return {"wards": settings.tokyo_wards}


@app.post("/care-request", response_model=CareRequestResponse)
def care_request(body: CareRequestInput) -> CareRequestResponse:
    """
    Phase 1+2: Runs the full pipeline:
      intake → service_discovery → paperwork → human_gate (paused)

    Returns ranked facilities + pre-filled forms.
    Status will be 'awaiting_human' — call /approve to continue.
    """
    from agents.orchestrator import run_care_request

    start = time.perf_counter()
    try:
        final_state = run_care_request(
            needs_description=body.needs_description,
            ward=body.ward,
            patient_age=body.patient_age,
            patient_name=body.patient_name,
            care_level=body.care_level,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    elapsed = round((time.perf_counter() - start) * 1000, 1)

    return CareRequestResponse(
        request_id=final_state.get("request_id", ""),
        status=final_state.get("status", "unknown"),
        elapsed_ms=elapsed,
        ward=body.ward,
        service_codes_identified=final_state.get("required_service_codes", []),
        top_matches=final_state.get("ranked_services", [])[:5],
        forms_required=final_state.get("forms_required", []),
        forms_prefilled=final_state.get("forms_prefilled", []),
        messages=final_state.get("messages", []),
        error=final_state.get("error"),
    )


@app.get("/care-request/{request_id}/review", response_model=ReviewResponse)
def review_request(request_id: str) -> ReviewResponse:
    """
    Retrieve the current state of a paused care request.
    Shows pre-filled forms for human review before approval.
    """
    from agents.orchestrator import get_request_state

    try:
        state = get_request_state(request_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not state:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    return ReviewResponse(
        request_id=request_id,
        status=state.get("status", "unknown"),
        forms_required=state.get("forms_required", []),
        forms_prefilled=state.get("forms_prefilled", []),
        top_matches=state.get("ranked_services", [])[:5],
        messages=state.get("messages", []),
    )


@app.post("/care-request/{request_id}/approve", response_model=ApprovalResponse)
def approve_request(request_id: str) -> ApprovalResponse:
    """
    Human approves the pre-filled forms.
    Resumes the graph → continues to format_response.
    """
    from agents.orchestrator import approve_care_request, get_request_state

    # Check it exists and is awaiting approval
    state = get_request_state(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")
    if state.get("status") != "awaiting_human":
        raise HTTPException(
            status_code=400,
            detail=f"Request is not awaiting approval (status: {state.get('status')})"
        )

    try:
        final_state = approve_care_request(request_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ApprovalResponse(
        request_id=request_id,
        status=final_state.get("status", "complete"),
        message="Forms approved. Care request submitted successfully. / 申請書を承認しました。",
        messages=final_state.get("messages", []),
        care_plan_score=final_state.get("care_plan_score"),
        scheduled_visits_count=len(final_state.get("scheduled_visits", [])),
        line_reminders_count=len(final_state.get("line_reminders", [])),
    )


@app.get("/care-request/{request_id}/schedule", response_model=ScheduleResponse)
def get_schedule(request_id: str) -> ScheduleResponse:
    """
    Retrieve the generated visit schedule and LINE reminder templates
    for an approved care request.
    """
    from agents.orchestrator import get_request_state

    state = get_request_state(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    meta = state.get("schedule_meta") or {}
    return ScheduleResponse(
        request_id=request_id,
        status=state.get("status", "unknown"),
        scheduled_visits=state.get("scheduled_visits", []),
        line_reminders=state.get("line_reminders", []),
        schedule_summary_en=meta.get("summary_en", ""),
        schedule_summary_jp=meta.get("summary_jp", ""),
        total_visits_per_week=meta.get("total_visits_per_week", 0),
        weeks=meta.get("weeks", []),
    )


@app.get("/care-request/{request_id}/monitoring", response_model=MonitoringResponse)
def get_monitoring(request_id: str) -> MonitoringResponse:
    """
    Retrieve care plan quality score, risk level, alerts, and LLM recommendations.
    """
    from agents.orchestrator import get_request_state

    state = get_request_state(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    analysis = state.get("monitoring_analysis") or {}
    return MonitoringResponse(
        request_id=request_id,
        status=state.get("status", "unknown"),
        care_plan_score=state.get("care_plan_score"),
        monitoring_alerts=state.get("monitoring_alerts", []),
        risk_level=analysis.get("risk_level", "unknown"),
        overall_assessment_en=analysis.get("overall_assessment_en", ""),
        overall_assessment_jp=analysis.get("overall_assessment_jp", ""),
        recommendations_en=analysis.get("recommendations_en", []),
        recommendations_jp=analysis.get("recommendations_jp", []),
        next_review_days=analysis.get("next_review_days", 30),
    )


@app.post("/care-request/{request_id}/reject", response_model=ApprovalResponse)
def reject_request(request_id: str) -> ApprovalResponse:
    """
    Human rejects the pre-filled forms.
    Marks the request as rejected — no submission.
    """
    from agents.orchestrator import get_request_state

    state = get_request_state(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    return ApprovalResponse(
        request_id=request_id,
        status="rejected",
        message="Forms rejected. Please re-submit with corrected information. / 申請書を却下しました。",
        messages=state.get("messages", []) + [
            {"agent": "human", "content": "Forms rejected by human reviewer."}
        ],
    )

