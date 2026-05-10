"""
Monitoring Agent — Phase 3.

Scores the assembled care plan (0–100) and raises alerts for gaps or risks.
Runs after the Scheduling Agent, before format_response.

Scoring dimensions:
  - Service coverage      (40 pts) — do codes cover all stated needs?
  - Care level fit        (20 pts) — is the care level matched to services?
  - Schedule completeness (20 pts) — are all services scheduled?
  - Facility match        (20 pts) — top match score normalised
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


# ── Heuristic scoring ─────────────────────────────────────────────────────

def _score_service_coverage(service_codes: list[str], needs: str) -> tuple[int, list[str]]:
    """
    Rule-based coverage check.
    Returns (score 0-40, alerts).
    """
    alerts: list[str] = []
    needs_lower = needs.lower()

    # Keywords → required codes
    keyword_code_map = {
        "訪問介護": "11", "ホームビジット": "11", "home visit care": "11",
        "訪問看護": "13", "看護": "13", "nursing": "13",
        "訪問入浴": "12", "入浴": "12", "bath": "12",
        "リハビリ": "14", "rehabilitation": "14",
        "デイサービス": "21", "通所": "21", "day service": "21",
        "ショートステイ": "31", "short stay": "31",
    }

    expected: set[str] = set()
    for keyword, code in keyword_code_map.items():
        if keyword in needs or keyword in needs_lower:
            expected.add(code)

    missing = expected - set(service_codes)
    if missing:
        for code in missing:
            alerts.append(f"Service code {code} appears needed from description but is not in plan.")

    if not service_codes:
        alerts.append("No service codes identified — care plan is incomplete.")
        return 0, alerts

    covered = len(expected - missing)
    if not expected:
        return 35, alerts  # No keywords found — give benefit of doubt

    return int(40 * covered / len(expected)), alerts


def _score_care_level_fit(care_level: int, service_codes: list[str]) -> tuple[int, list[str]]:
    """
    Check whether care level is appropriate for chosen services.
    Returns (score 0-20, alerts).
    """
    alerts: list[str] = []
    # Residential services require care level ≥ 3
    heavy_codes = {"41", "42", "31"}
    if heavy_codes & set(service_codes) and care_level < 3:
        alerts.append(
            f"Care level {care_level} may be insufficient for residential/short-stay services. "
            "Level ≥ 3 is typically required."
        )
        return 8, alerts

    if care_level == 0:
        alerts.append("Care level not yet assessed (介護度未認定). Reassessment recommended.")
        return 10, alerts

    return 20, alerts


def _score_schedule_completeness(
    service_codes: list[str], scheduled_visits: list[dict]
) -> tuple[int, list[str]]:
    alerts: list[str] = []
    if not scheduled_visits:
        alerts.append("No visits scheduled yet.")
        return 0, alerts

    scheduled_codes = {v.get("service_code") for v in scheduled_visits}
    missing_scheduled = set(service_codes) - scheduled_codes
    if missing_scheduled:
        for code in missing_scheduled:
            alerts.append(f"Service {code} is approved but has no scheduled visits.")

    covered = len(set(service_codes) - missing_scheduled)
    total = len(service_codes) if service_codes else 1
    return int(20 * covered / total), alerts


def _score_facility_match(ranked_services: list[dict]) -> tuple[int, list[str]]:
    alerts: list[str] = []
    if not ranked_services:
        alerts.append("No facility matched — manual facility selection required.")
        return 0, alerts

    top_score = ranked_services[0].get("match_score", 0)
    normalised = int(20 * top_score / 100)

    if top_score < 60:
        alerts.append(
            f"Top facility match score is {top_score}/100 — consider searching in adjacent wards."
        )

    return normalised, alerts


# ── LLM analysis ──────────────────────────────────────────────────────────

MONITORING_PROMPT = """\
You are a Japanese eldercare quality assessor. Review the following care plan \
and provide an expert analysis.

Patient: {patient_name}, age {patient_age}, {ward}, 介護度 {care_level}
Needs: {needs_description}
Service codes assigned: {service_codes}
Top facility: {facility_name} (match score: {match_score}/100)
Visits scheduled per week: {visits_per_week}
Heuristic score: {heuristic_score}/100

Provide a brief expert review. Return JSON only:
{{
  "overall_assessment_en": "2-3 sentence assessment of this care plan",
  "overall_assessment_jp": "2〜3文の介護計画評価（日本語）",
  "risk_level": "low|medium|high",
  "recommendations_en": ["up to 3 actionable recommendations"],
  "recommendations_jp": ["最大3件の推奨事項（日本語）"],
  "next_review_days": 30
}}
"""


def llm_analyze(state: CareState, heuristic_score: int, trace: Any = None) -> dict:
    ranked = state.get("ranked_services", [])
    facility_name = ranked[0].get("name", "未選択") if ranked else "未選択"
    match_score = ranked[0].get("match_score", 0) if ranked else 0
    visits_per_week = len(set(
        v.get("service_code") for v in state.get("scheduled_visits", [])
        if v.get("service_code")
    ))

    prompt = MONITORING_PROMPT.format(
        patient_name=state.get("patient_name", "患者"),
        patient_age=state.get("patient_age", ""),
        ward=state.get("ward", ""),
        care_level=state.get("care_level", 0),
        needs_description=state.get("needs_description", "")[:200],
        service_codes=", ".join(state.get("required_service_codes", [])),
        facility_name=facility_name,
        match_score=match_score,
        visits_per_week=visits_per_week,
        heuristic_score=heuristic_score,
    )

    try:
        response = _groq.chat.completions.create(
            model=settings.critic_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=600,
            timeout=15,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        analysis = json.loads(raw)
        # Normalise risk_level so it's consistent with the heuristic score
        score_based_risk = "low" if heuristic_score >= 80 else "medium" if heuristic_score >= 55 else "high"
        if analysis.get("risk_level") not in ("low", "medium", "high"):
            analysis["risk_level"] = score_based_risk
        # LLM shouldn't report high/medium risk when score is 80+
        if heuristic_score >= 80 and analysis.get("risk_level") == "high":
            analysis["risk_level"] = "medium"
        if heuristic_score >= 90 and analysis.get("risk_level") == "medium":
            analysis["risk_level"] = "low"
        trace_agent_step(
            trace, "monitoring_llm",
            input_data=f"Heuristic score: {heuristic_score}",
            output_data=f"Risk: {analysis.get('risk_level')}",
        )
        return analysis
    except Exception:
        risk = "low" if heuristic_score >= 70 else "medium" if heuristic_score >= 50 else "high"
        return {
            "overall_assessment_en": f"Care plan scored {heuristic_score}/100 by heuristic analysis.",
            "overall_assessment_jp": f"ヒューリスティック分析による介護計画スコア: {heuristic_score}/100。",
            "risk_level": risk,
            "recommendations_en": ["Verify all manual fields in submitted forms."],
            "recommendations_jp": ["提出書類の手動入力欄を確認してください。"],
            "next_review_days": 30,
        }


# ── LangGraph node ─────────────────────────────────────────────────────────

def monitoring_node(state: CareState) -> dict:
    """
    LangGraph node: scores the care plan and surfaces alerts.
    Runs after scheduling_node.
    """
    trace = state.get("_trace")
    service_codes = state.get("required_service_codes", [])
    needs = state.get("needs_description", "")

    # Heuristic sub-scores
    s1, a1 = _score_service_coverage(service_codes, needs)
    s2, a2 = _score_care_level_fit(state.get("care_level", 0), service_codes)
    s3, a3 = _score_schedule_completeness(service_codes, state.get("scheduled_visits", []))
    s4, a4 = _score_facility_match(state.get("ranked_services", []))

    heuristic_score = s1 + s2 + s3 + s4
    all_alerts = a1 + a2 + a3 + a4

    trace_agent_step(
        trace, "monitoring_heuristic",
        input_data=f"Codes: {service_codes}",
        output_data=f"Score: {heuristic_score}/100, Alerts: {len(all_alerts)}",
    )

    # LLM enrichment
    llm_analysis = llm_analyze(state, heuristic_score, trace)

    return {
        "care_plan_score": float(heuristic_score),
        "monitoring_alerts": all_alerts,
        "monitoring_analysis": llm_analysis,
        "current_agent": "monitoring",
        "messages": state.get("messages", []) + [
            {
                "agent": "monitoring",
                "content": (
                    f"Care plan score: {heuristic_score}/100. "
                    f"Risk level: {llm_analysis.get('risk_level', 'unknown')}. "
                    f"{len(all_alerts)} alert(s). "
                    f"{llm_analysis.get('overall_assessment_en', '')}"
                ),
            }
        ],
    }
