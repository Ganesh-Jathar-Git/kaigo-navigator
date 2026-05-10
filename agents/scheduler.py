"""
Scheduling Agent — Phase 3.

Generates a 4-week visit schedule for approved care services and produces
LINE reminder message templates for each visit type.

Flow:
  1. Read approved service codes + top facility from state
  2. Use Llama (Groq) to generate a structured weekly visit schedule
  3. Produce LINE-style reminder message templates (Japanese)
  4. Store scheduled_visits and line_reminders in state
"""

from __future__ import annotations

import json
from datetime import date, timedelta
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


# ── Service code → visit defaults ─────────────────────────────────────────

SERVICE_VISIT_CONFIG: dict[str, dict] = {
    "11": {
        "service_name": "訪問介護",
        "service_name_en": "Home Visit Care",
        "default_frequency": "3x/week",
        "duration_min": 60,
        "day_pattern": ["月", "水", "金"],
        "time_slot": "10:00",
        "line_emoji": "🏠",
    },
    "12": {
        "service_name": "訪問入浴介護",
        "service_name_en": "Home Visit Bathing Care",
        "default_frequency": "2x/week",
        "duration_min": 60,
        "day_pattern": ["火", "金"],
        "time_slot": "11:00",
        "line_emoji": "🛁",
    },
    "13": {
        "service_name": "訪問看護",
        "service_name_en": "Home Visit Nursing",
        "default_frequency": "1x/week",
        "duration_min": 30,
        "day_pattern": ["水"],
        "time_slot": "14:00",
        "line_emoji": "💊",
    },
    "14": {
        "service_name": "訪問リハビリ",
        "service_name_en": "Home Visit Rehabilitation",
        "default_frequency": "2x/week",
        "duration_min": 40,
        "day_pattern": ["火", "木"],
        "time_slot": "10:30",
        "line_emoji": "🏃",
    },
    "21": {
        "service_name": "通所介護（デイサービス）",
        "service_name_en": "Day Service",
        "default_frequency": "2x/week",
        "duration_min": 360,
        "day_pattern": ["月", "木"],
        "time_slot": "09:00",
        "line_emoji": "🌅",
    },
    "22": {
        "service_name": "通所リハビリ",
        "service_name_en": "Day Rehabilitation",
        "default_frequency": "2x/week",
        "duration_min": 240,
        "day_pattern": ["火", "金"],
        "time_slot": "09:30",
        "line_emoji": "💪",
    },
    "31": {
        "service_name": "短期入所（ショートステイ）",
        "service_name_en": "Short-term Stay",
        "default_frequency": "1x/month",
        "duration_min": 1440,
        "day_pattern": ["月"],
        "time_slot": "10:00",
        "line_emoji": "🏨",
    },
}


SCHEDULE_PROMPT = """\
You are a Japanese eldercare scheduler. Generate a 4-week visit schedule \
for a patient requiring the following care services.

Patient:
- Name: {patient_name}
- Age: {patient_age}
- Ward: {ward}
- Care level (介護度): {care_level}
- Needs: {needs_description}

Approved facility: {facility_name}

Required services: {service_list}

Start date: {start_date}

Generate a practical visit schedule. Return JSON only:
{{
  "schedule_summary": "Brief 1-sentence schedule summary in English",
  "schedule_summary_jp": "Brief 1-sentence schedule summary in Japanese",
  "total_visits_per_week": <number>,
  "weeks": [
    {{
      "week": 1,
      "visits": [
        {{
          "date": "YYYY-MM-DD",
          "day_jp": "月/火/水/木/金/土",
          "service_code": "11",
          "service_name": "訪問介護",
          "service_name_en": "Home Visit Care",
          "time": "HH:MM",
          "duration_min": 60,
          "facility": "{facility_name}",
          "notes": "optional note"
        }}
      ]
    }}
  ]
}}
Provide 4 weeks of visits. Keep it realistic and consistent.
"""

LINE_REMINDER_PROMPT = """\
You are a Japanese eldercare coordinator. Create LINE messenger reminder \
message templates for the following care visits.

Patient name: {patient_name}
Facility: {facility_name}

Services scheduled: {service_list}

Create one LINE reminder template per service type. Return JSON only:
[
  {{
    "service_code": "11",
    "service_name": "訪問介護",
    "trigger": "day_before",
    "message_jp": "明日 {{date}} {{time}} に{{service_name}}があります。\\n施設: {{facility_name}}\\nご準備をお願いします。🏠",
    "message_en": "Reminder: {{service_name}} visit scheduled tomorrow {{date}} at {{time}}.\\nFacility: {{facility_name}}\\nPlease be prepared.",
    "quick_reply_options": ["確認しました ✅", "キャンセル ❌", "時間変更 🕐"]
  }}
]
Create templates for all service types. Keep messages warm and concise.
"""


def _build_service_list(service_codes: list[str], ranked_services: list[dict]) -> str:
    lines = []
    for code in service_codes:
        cfg = SERVICE_VISIT_CONFIG.get(code, {})
        name = cfg.get("service_name", f"サービスコード {code}")
        name_en = cfg.get("service_name_en", "")
        freq = cfg.get("default_frequency", "")
        lines.append(f"  - Code {code}: {name} ({name_en}), {freq}")
    return "\n".join(lines) if lines else "  - 訪問介護 (Home Visit Care)"


SUMMARY_PROMPT = """\
In one sentence (English), summarise this Japanese eldercare visit schedule:
Services: {service_list}
Frequency: {visits_per_week} visits/week over 4 weeks starting {start_date}
Facility: {facility_name}
Reply with the sentence only, no JSON.
"""

SUMMARY_PROMPT_JP = """\
以下の介護訪問スケジュールを一文（日本語）でまとめてください。
サービス: {service_list}
頻度: 週{visits_per_week}回、4週間、開始: {start_date}
施設: {facility_name}
一文だけ返答してください。
"""


def _llm_summary(service_list: str, visits_per_week: int, start_date: str, facility_name: str) -> tuple[str, str]:
    """Get a one-sentence schedule summary from Groq (fast, low token)."""
    try:
        r_en = _groq.chat.completions.create(
            model=settings.critic_model,
            messages=[{"role": "user", "content": SUMMARY_PROMPT.format(
                service_list=service_list, visits_per_week=visits_per_week,
                start_date=start_date, facility_name=facility_name,
            )}],
            temperature=0.2, max_tokens=80, timeout=10,
        )
        summary_en = r_en.choices[0].message.content.strip()
    except Exception:
        summary_en = f"Weekly schedule for {visits_per_week} visits across {facility_name}."

    try:
        r_jp = _groq.chat.completions.create(
            model=settings.critic_model,
            messages=[{"role": "user", "content": SUMMARY_PROMPT_JP.format(
                service_list=service_list, visits_per_week=visits_per_week,
                start_date=start_date, facility_name=facility_name,
            )}],
            temperature=0.2, max_tokens=80, timeout=10,
        )
        summary_jp = r_jp.choices[0].message.content.strip()
    except Exception:
        summary_jp = f"週{visits_per_week}回、{facility_name}の訪問スケジュール。"

    return summary_en, summary_jp


def generate_schedule(state: CareState, trace: Any = None) -> dict:
    """
    Generate a 4-week visit schedule from service config defaults (fast, deterministic).
    Enriches with a short LLM-generated summary sentence.
    """
    service_codes = state.get("required_service_codes", ["11"])
    ranked = state.get("ranked_services", [])
    facility_name = ranked[0].get("name", "担当施設") if ranked else "担当施設"
    start_date = date.today() + timedelta(days=7)
    service_list = _build_service_list(service_codes, ranked)

    schedule_data = _build_deterministic_schedule(service_codes, facility_name, start_date)

    # Short LLM summary (2 small calls instead of one 2000-token call)
    summary_en, summary_jp = _llm_summary(
        service_list,
        schedule_data["total_visits_per_week"],
        start_date.isoformat(),
        facility_name,
    )
    schedule_data["schedule_summary"] = summary_en
    schedule_data["schedule_summary_jp"] = summary_jp

    trace_agent_step(
        trace, "scheduler",
        input_data=f"Service codes: {service_codes}",
        output_data=f"{schedule_data.get('total_visits_per_week', '?')} visits/week",
    )
    return schedule_data


def _build_deterministic_schedule(
    service_codes: list[str],
    facility_name: str,
    start_date: date,
) -> dict:
    """Build a deterministic 4-week schedule from SERVICE_VISIT_CONFIG defaults."""
    weeks = []
    for week_num in range(1, 5):
        visits = []
        week_start = start_date + timedelta(weeks=week_num - 1)
        for code in service_codes:
            cfg = SERVICE_VISIT_CONFIG.get(code, {})
            days = cfg.get("day_pattern", ["月"])
            for day_jp in days:
                offset = ["月", "火", "水", "木", "金", "土", "日"].index(day_jp)
                visit_date = week_start + timedelta(days=offset)
                visits.append({
                    "date": visit_date.isoformat(),
                    "day_jp": day_jp,
                    "service_code": code,
                    "service_name": cfg.get("service_name", "訪問介護"),
                    "service_name_en": cfg.get("service_name_en", "Home Visit Care"),
                    "time": cfg.get("time_slot", "10:00"),
                    "duration_min": cfg.get("duration_min", 60),
                    "facility": facility_name,
                })
        visits.sort(key=lambda v: v["date"])
        weeks.append({"week": week_num, "visits": visits})

    total_per_week = sum(
        len(SERVICE_VISIT_CONFIG.get(c, {}).get("day_pattern", ["月"]))
        for c in service_codes
    )
    return {
        "schedule_summary": "",   # filled by _llm_summary
        "schedule_summary_jp": "",
        "total_visits_per_week": total_per_week,
        "weeks": weeks,
    }


def generate_line_reminders(state: CareState, trace: Any = None) -> list[dict]:
    """
    Generate LINE reminder message templates for each service type.
    Uses heuristic templates (fast, no LLM call needed for reminders).
    """
    service_codes = state.get("required_service_codes", ["11"])
    ranked = state.get("ranked_services", [])
    facility_name = ranked[0].get("name", "担当施設") if ranked else "担当施設"

    reminders = _build_fallback_reminders(service_codes, facility_name)
    trace_agent_step(
        trace, "line_reminders",
        input_data=f"Services: {service_codes}",
        output_data=f"{len(reminders)} LINE template(s) generated",
    )
    return reminders


def _build_fallback_reminders(service_codes: list[str], facility_name: str) -> list[dict]:
    reminders = []
    for code in service_codes:
        cfg = SERVICE_VISIT_CONFIG.get(code, {})
        service_name = cfg.get("service_name", "訪問介護")
        emoji = cfg.get("line_emoji", "🏠")
        reminders.append({
            "service_code": code,
            "service_name": service_name,
            "trigger": "day_before",
            "message_jp": (
                f"{emoji} 明日 {{date}} {{time}} に{service_name}があります。\n"
                f"施設: {facility_name}\n"
                "ご準備をお願いします。"
            ),
            "message_en": (
                f"Reminder: {service_name} visit scheduled tomorrow {{date}} at {{time}}.\n"
                f"Facility: {facility_name}\nPlease be prepared."
            ),
            "quick_reply_options": ["確認しました ✅", "キャンセル ❌", "時間変更 🕐"],
        })
    return reminders


# ── LangGraph node ─────────────────────────────────────────────────────────

def scheduling_node(state: CareState) -> dict:
    """
    LangGraph node: generates visit schedule and LINE reminders.
    Runs after human approval gate.
    """
    trace = state.get("_trace")

    schedule_data = generate_schedule(state, trace)
    line_reminders = generate_line_reminders(state, trace)

    # Flatten all visits across 4 weeks into scheduled_visits list
    all_visits: list[dict] = []
    for week in schedule_data.get("weeks", []):
        all_visits.extend(week.get("visits", []))

    return {
        "scheduled_visits": all_visits,
        "line_reminders": line_reminders,
        "schedule_meta": {
            "summary_en": schedule_data.get("schedule_summary", ""),
            "summary_jp": schedule_data.get("schedule_summary_jp", ""),
            "total_visits_per_week": schedule_data.get("total_visits_per_week", 0),
            "weeks": schedule_data.get("weeks", []),
        },
        "current_agent": "scheduler",
        "messages": state.get("messages", []) + [
            {
                "agent": "scheduler",
                "content": (
                    f"Generated {len(all_visits)}-visit schedule over 4 weeks "
                    f"({schedule_data.get('total_visits_per_week', '?')} visits/week). "
                    f"{schedule_data.get('schedule_summary', '')} "
                    f"{len(line_reminders)} LINE reminder template(s) ready."
                ),
            }
        ],
    }
