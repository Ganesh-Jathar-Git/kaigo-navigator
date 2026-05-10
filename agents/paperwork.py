"""
Paperwork Agent — Phase 2.

Automatically pre-fills 介護認定申請 (care certification) forms
using patient data and the top-ranked facility from service discovery.

Flow:
  1. Identify required forms based on service codes
  2. Pre-fill each form with patient + facility data using Llama
  3. Set awaiting_human_approval = True (blocks submission until approved)
  4. Return prefilled forms into state
"""

from __future__ import annotations

import json

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


# ── Form templates ─────────────────────────────────────────────────────────

# Maps service codes → required forms
SERVICE_CODE_TO_FORMS = {
    "11": ["介護認定申請書", "訪問介護利用申込書"],
    "12": ["介護認定申請書", "訪問入浴介護申込書"],
    "13": ["介護認定申請書", "訪問看護指示書依頼書"],
    "14": ["介護認定申請書", "訪問リハビリ申込書"],
    "21": ["介護認定申請書", "通所介護利用申込書"],
    "22": ["介護認定申請書", "通所リハビリ申込書"],
    "31": ["介護認定申請書", "短期入所利用申込書"],
    "41": ["介護認定申請書", "特別養護老人ホーム入所申込書"],
    "42": ["介護認定申請書", "老健施設入所申込書"],
}

PREFILL_PROMPT = """\
You are a Japanese eldercare administrator. Pre-fill the following care form \
fields using the patient and facility information provided.

Form: {form_name}

Patient information:
- Name: {patient_name}
- Age: {patient_age}
- Ward: {ward}
- Care level (介護度): {care_level}
- Needs: {needs_description}

Facility information:
- Name: {facility_name}
- Address: {facility_address}
- Phone: {facility_phone}
- Services: {facility_services}

Respond with JSON only — fill in what you can, use null for unknown fields:
{{
  "form_name": "{form_name}",
  "fields": {{
    "申請者氏名": "{patient_name}",
    "生年月日": null,
    "年齢": {patient_age},
    "住所": "{ward}",
    "電話番号": null,
    "介護度": "{care_level}",
    "サービス事業者名": "{facility_name}",
    "事業者住所": "{facility_address}",
    "事業者電話": "{facility_phone}",
    "申請日": "自動記入",
    "申請理由": "{needs_summary}"
  }},
  "status": "prefilled",
  "requires_fields": ["生年月日", "電話番号"],
  "notes_en": "Auto-filled from patient record. Date of birth and phone number require manual entry.",
  "notes_jp": "患者記録から自動入力。生年月日と電話番号は手動入力が必要です。"
}}
"""


def identify_required_forms(service_codes: list[str]) -> list[str]:
    """Map service codes to required forms, deduplicated."""
    forms = set()
    for code in service_codes:
        forms.update(SERVICE_CODE_TO_FORMS.get(code, ["介護認定申請書"]))
    return sorted(forms)


# Per-form field definitions — which fields each form requires
FORM_FIELDS: dict[str, list[str]] = {
    "介護認定申請書":           ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
    "訪問介護利用申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
    "訪問看護指示書依頼書":      ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "サービス内容", "申請理由"],
    "訪問入浴介護申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
    "訪問リハビリ申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
    "通所介護利用申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
    "通所リハビリ申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
    "短期入所利用申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "利用期間", "申請理由"],
    "特別養護老人ホーム入所申込書": ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "サービス内容", "申請理由"],
    "老健施設入所申込書":        ["申請者氏名", "生年月日", "年齢", "住所", "電話番号", "介護度", "サービス事業者名", "事業者住所", "事業者電話", "申請日", "申請理由"],
}

# Fields we can always fill from state — never need manual entry
AUTO_FILLABLE = {"申請者氏名", "年齢", "住所", "介護度", "サービス事業者名", "申請日", "申請理由"}


def _build_fallback_prefill(form_name: str, state: CareState, facility: dict) -> dict:
    """
    Complete deterministic prefill from state + facility data.
    Used when LLM call fails or returns malformed JSON.
    Marks only genuinely unknown fields as requiring manual entry.
    """
    needs = state.get("needs_description", "")
    needs_summary = needs[:100] + "..." if len(needs) > 100 else needs

    # Base values we always know
    known: dict = {
        "申請者氏名": state.get("patient_name", "患者"),
        "年齢": state.get("patient_age"),
        "住所": state.get("ward", ""),
        "介護度": str(state.get("care_level", 0)),
        "サービス事業者名": facility.get("name", ""),
        "申請日": "自動記入",
        "申請理由": needs_summary,
        # Facility fields — may be empty if not in Pinecone metadata
        "事業者住所": facility.get("address") or None,
        "事業者電話": facility.get("phone") or None,
    }

    # Build fields dict for this specific form
    form_field_list = FORM_FIELDS.get(form_name, list(known.keys()))
    fields = {}
    requires_manual = []

    for field in form_field_list:
        val = known.get(field)
        if field in ("生年月日", "電話番号", "利用期間", "サービス内容"):
            fields[field] = None
            requires_manual.append(field)
        elif val is None or val == "":
            fields[field] = None
            requires_manual.append(field)
        else:
            fields[field] = val

    manual_names = "、".join(requires_manual) if requires_manual else "なし"
    return {
        "form_name": form_name,
        "fields": fields,
        "status": "prefilled",
        "requires_fields": requires_manual,
        "notes_en": (
            f"Auto-filled from patient record and facility information. "
            f"All known fields have been filled. "
            f"{', '.join(requires_manual)} require manual entry." if requires_manual
            else "All fields auto-filled from patient record."
        ),
        "notes_jp": (
            f"患者記録から自動入力。{manual_names}は手動入力が必要です。"
        ),
    }


def prefill_form(
    form_name: str,
    state: CareState,
    facility: dict,
    trace=None,
) -> dict:
    """Use Llama to pre-fill a single form, with robust fallback."""
    needs = state.get("needs_description", "")
    # Short summary for the form
    needs_summary = needs[:100] + "..." if len(needs) > 100 else needs

    prompt = PREFILL_PROMPT.format(
        form_name=form_name,
        patient_name=state.get("patient_name", "患者"),
        patient_age=state.get("patient_age", ""),
        ward=state.get("ward", ""),
        care_level=state.get("care_level", 0),
        needs_description=needs,
        needs_summary=needs_summary,
        facility_name=facility.get("name", ""),
        facility_address=facility.get("address", ""),
        facility_phone=facility.get("phone", ""),
        facility_services=facility.get("service_name", ""),
    )

    try:
        response = _groq.chat.completions.create(
            model=settings.critic_model,
            max_tokens=512,
            timeout=10,   # 10-second hard timeout per form
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        try:
            prefilled = json.loads(raw)
        except json.JSONDecodeError:
            # Try to salvage truncated/malformed JSON by extracting the fields block
            import re
            fields_match = re.search(r'"fields"\s*:\s*(\{[^}]+\})', raw, re.DOTALL)
            if fields_match:
                prefilled = _build_fallback_prefill(form_name, state, facility)
                try:
                    extracted_fields = json.loads(fields_match.group(1))
                    prefilled["fields"].update({k: v for k, v in extracted_fields.items() if v is not None})
                except Exception:
                    pass
            else:
                raise  # fall through to except block

    except Exception:
        prefilled = _build_fallback_prefill(form_name, state, facility)

    trace_agent_step(
        trace, f"prefill_{form_name}",
        input_data={"form": form_name, "patient": state.get("patient_name")},
        output_data=prefilled,
        model=settings.critic_model,
    )
    return prefilled


# ── Main node ──────────────────────────────────────────────────────────────

def paperwork_node(state: CareState) -> dict:
    """
    LangGraph node: identifies required forms and pre-fills them.
    Sets awaiting_human_approval=True to gate submission.
    """
    trace = state.get("_trace")
    service_codes = state.get("required_service_codes", ["11"])
    ranked = state.get("ranked_services", [])

    # Use top-ranked facility
    top_facility = ranked[0] if ranked else {}

    # Step 1: identify forms
    forms_required = identify_required_forms(service_codes)

    # Step 2: pre-fill each form
    forms_prefilled = []
    for form_name in forms_required:
        prefilled = prefill_form(form_name, state, top_facility, trace)
        forms_prefilled.append(prefilled)

    trace_agent_step(
        trace, "paperwork",
        input_data={"service_codes": service_codes, "forms": forms_required},
        output_data={"forms_prefilled": len(forms_prefilled)},
    )

    return {
        "forms_required": forms_required,
        "forms_prefilled": forms_prefilled,
        "awaiting_human_approval": True,   # ← GATE: blocks submission
        "current_agent": "paperwork",
        "messages": state.get("messages", []) + [
            {
                "agent": "paperwork",
                "content": (
                    f"Pre-filled {len(forms_prefilled)} form(s): "
                    f"{', '.join(forms_required)}. "
                    f"Awaiting human approval before submission."
                ),
            }
        ],
    }
