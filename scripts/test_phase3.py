"""
Phase 3 end-to-end test:
  Submit → Review → Approve → Check Schedule → Check Monitoring
"""
import os
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import json
import sys
from agents.orchestrator import run_care_request, approve_care_request, get_request_state

SEP = "─" * 60


def pretty(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main():
    print(f"\n{SEP}")
    print("=== Phase 3 E2E Test ===")
    print(SEP)

    # ── Step 1: Submit ────────────────────────────────────────
    print("\n[1] Submitting care request...")
    result = run_care_request(
        needs_description="週3回の訪問介護と月1回の訪問看護が必要。認知症初期。",
        ward="世田谷区",
        patient_age=78,
        patient_name="患者A",
        care_level=2,
    )
    request_id = result.get("request_id", "")
    status = result.get("status", "")
    print(f"  request_id : {request_id}")
    print(f"  status     : {status}")
    print(f"  forms      : {result.get('forms_required', [])}")

    if status != "awaiting_human":
        print(f"\n❌ Expected 'awaiting_human', got '{status}'")
        if result.get("error"):
            print(f"  error: {result['error']}")
        sys.exit(1)

    # ── Step 2: Review ────────────────────────────────────────
    print(f"\n[2] Reviewing state ({request_id})...")
    state = get_request_state(request_id)
    print(f"  status      : {state.get('status')}")
    print(f"  top match   : {state.get('ranked_services', [{}])[0].get('name', 'N/A')}")
    print(f"  prefilled   : {len(state.get('forms_prefilled', []))} form(s)")

    # ── Step 3: Approve ───────────────────────────────────────
    print(f"\n[3] Approving request...")
    approved = approve_care_request(request_id)
    print(f"  status      : {approved.get('status')}")
    print(f"  plan score  : {approved.get('care_plan_score')}/100")
    print(f"  alerts      : {approved.get('monitoring_alerts', [])}")

    visits = approved.get("scheduled_visits", [])
    print(f"  visits      : {len(visits)} total over 4 weeks")
    if visits:
        print(f"  first visit : {visits[0].get('date')} {visits[0].get('time')} — {visits[0].get('service_name')}")

    reminders = approved.get("line_reminders", [])
    print(f"  LINE tmpl   : {len(reminders)} template(s)")
    if reminders:
        print(f"  Sample msg  : {reminders[0].get('message_jp', '')[:80]}...")

    # ── Step 4: Check final state via get_request_state ──────
    print(f"\n[4] Final state check...")
    final = get_request_state(request_id)
    analysis = final.get("monitoring_analysis") or {}
    print(f"  risk_level  : {analysis.get('risk_level', 'N/A')}")
    print(f"  assessment  : {analysis.get('overall_assessment_en', '')[:100]}")
    recs = analysis.get("recommendations_en", [])
    for i, r in enumerate(recs, 1):
        print(f"  rec {i}       : {r}")

    # ── Step 5: Check schedule meta ───────────────────────────
    meta = final.get("schedule_meta") or {}
    print(f"\n[5] Schedule summary:")
    print(f"  EN: {meta.get('summary_en', 'N/A')}")
    print(f"  JP: {meta.get('summary_jp', 'N/A')}")
    print(f"  visits/week : {meta.get('total_visits_per_week', 'N/A')}")

    print(f"\n{SEP}")
    print("✅ Phase 3 complete!")
    print(f"   request_id   = {request_id}")
    print(f"   status       = {final.get('status')}")
    print(f"   score        = {final.get('care_plan_score')}/100")
    print(f"   risk         = {analysis.get('risk_level')}")
    print(f"   visits       = {len(final.get('scheduled_visits', []))} over 4 weeks")
    print(f"   LINE tmpls   = {len(final.get('line_reminders', []))}")
    print(SEP)


if __name__ == "__main__":
    main()
