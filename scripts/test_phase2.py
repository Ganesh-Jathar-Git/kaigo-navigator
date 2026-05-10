"""Test Phase 2 pipeline: paperwork + human approval gate."""
import json
import sys
sys.path.insert(0, '.')

from agents.orchestrator import run_care_request, get_request_state, approve_care_request

print("=== Step 1: Submit care request ===")
result = run_care_request(
    needs_description='週3回の訪問介護と月1回の訪問看護が必要。認知症初期。',
    ward='世田谷区',
    patient_age=78,
    care_level=2,
    patient_name='患者A'
)
request_id = result.get('request_id')
print('Request ID:', request_id)
print('Status:', result.get('status'))
print('Forms required:', result.get('forms_required'))
print('Forms prefilled count:', len(result.get('forms_prefilled', [])))

print("\n=== Step 2: Review prefilled form ===")
state = get_request_state(request_id)
if state.get('forms_prefilled'):
    form = state['forms_prefilled'][0]
    print('Form name:', form.get('form_name'))
    print('Fields:', json.dumps(form.get('fields', {}), ensure_ascii=False, indent=2))
    print('Notes EN:', form.get('notes_en'))
    print('Requires manual input:', form.get('requires_fields'))
else:
    print('No forms found in state')

print("\n=== Step 3: Human approves ===")
approved = approve_care_request(request_id)
print('Status after approval:', approved.get('status'))
msgs = approved.get('messages', [])
if msgs:
    print('Last message:', msgs[-1].get('content'))
print("\nPhase 2 complete!")
