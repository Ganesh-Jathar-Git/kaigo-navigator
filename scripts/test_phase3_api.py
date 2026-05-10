"""Quick Phase 3 API end-to-end test via HTTP."""
import urllib.request, json, sys

BASE = "http://127.0.0.1:8000"

def post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read())

print("=== 1. Submit ===")
r = post("/care-request", {
    "needs_description": "週3回の訪問介護と月1回の訪問看護が必要。認知症初期。",
    "ward": "世田谷区", "patient_age": 78, "patient_name": "患者A", "care_level": 2
})
rid = r["request_id"]
print(f"  request_id : {rid}")
print(f"  status     : {r['status']}")
print(f"  forms      : {len(r['forms_prefilled'])} prefilled")

print("\n=== 2. Approve ===")
a = post(f"/care-request/{rid}/approve")
print(f"  status     : {a['status']}")
print(f"  score      : {a.get('care_plan_score')}/100")
print(f"  visits     : {a.get('scheduled_visits_count')} over 4 weeks")
print(f"  LINE tmpls : {a.get('line_reminders_count')}")

print("\n=== 3. GET /schedule ===")
s = get(f"/care-request/{rid}/schedule")
print(f"  total visits : {len(s['scheduled_visits'])}")
print(f"  visits/week  : {s['total_visits_per_week']}")
print(f"  LINE tmpls   : {len(s['line_reminders'])}")
print(f"  summary EN   : {s['schedule_summary_en']}")
if s['scheduled_visits']:
    v = s['scheduled_visits'][0]
    print(f"  first visit  : {v['date']} {v['time']} — {v['service_name']}")
if s['line_reminders']:
    lr = s['line_reminders'][0]
    print(f"  LINE sample  : {lr['message_jp'][:70]}...")

print("\n=== 4. GET /monitoring ===")
m = get(f"/care-request/{rid}/monitoring")
print(f"  score        : {m['care_plan_score']}/100")
print(f"  risk         : {m['risk_level']}")
print(f"  assessment   : {m['overall_assessment_en'][:100]}")
print(f"  alerts       : {m['monitoring_alerts']}")
for i, rec in enumerate(m['recommendations_en'], 1):
    print(f"  rec {i}        : {rec}")

print(f"\n{'=' * 50}")
print(f"✅ Phase 3 API test complete! request_id={rid}")
