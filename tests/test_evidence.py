import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from applyproof.api import app
from applyproof.models import Case, Draft, Audit
from applyproof.engine import assess, build_draft, audit_draft, location_check

@pytest.fixture
def case():
    return json.loads((Path(__file__).resolve().parent.parent / 'examples/demo.json').read_text())

def test_exposure_is_not_hands_on(case):
    rows = assess(Case(**case))['requirements']
    assert rows[1]['status'] == 'partial'
    assert rows[3]['status'] == 'partial'  # language test is not proof of workplace fluency
    assert rows[2]['status'] == 'evidence_unverified'

def test_office_never_implies_role_location(case):
    assert assess(Case(**case))['location']['status'] == 'unverified'

@pytest.mark.parametrize('city,status', [('South Jakarta','matches'),('Bekasi','differs')])
def test_role_location(case, city, status):
    loc = copy.deepcopy(case['job']['locations'][0])
    loc.update(city=city, scope='role')
    case['job']['locations'].append(loc)
    assert location_check(Case(**case).job)['status'] == status

def test_conflicting_locations(case):
    for city in ['South Jakarta','Bekasi']:
        loc = copy.deepcopy(case['job']['locations'][0])
        loc.update(city=city, scope='role')
        case['job']['locations'].append(loc)
    assert location_check(Case(**case).job)['status'] == 'conflicting'

@pytest.mark.parametrize('ids', [['missing'],['cad'],['ups','ups'],[]])
def test_cannot_draft_missing_unverified_duplicate_facts(case, ids):
    with pytest.raises(ValueError):
        build_draft(Draft(**case, selected_ids=ids))

def test_draft_is_verbatim_and_traceable(case):
    result = build_draft(Draft(**case, selected_ids=['ups','degree']))
    assert result['bullets'][0]['text'] == case['profile']['facts'][1]['text']
    assert result['human_review_required']
    assert len(result['assessment']['evidence_digest']) == 64

def test_embellished_claim_is_not_accepted(case):
    result = audit_draft(Audit(**case, selected_ids=['ups'], bullets=[case['profile']['facts'][1]['text'], 'Managed UPS maintenance and improved efficiency by 40%.']))
    assert [b['status'] for b in result] == ['traceable','needs_evidence']

def test_unverified_job_stops_positive_fit(case):
    case['job']['source']['verified'] = False
    assert all(r['status'] == 'job_unverified' for r in assess(Case(**case))['requirements'])

def test_duplicate_ids_rejected(case):
    case['profile']['facts'].append(case['profile']['facts'][0])
    with pytest.raises(ValidationError):
        Case(**case)

def test_api_validation_and_no_submission(case):
    client = TestClient(app)
    assert client.post('/api/assess', json=case).status_code == 200
    assert client.post('/api/draft', json={**case, 'selected_ids':['cad']}).status_code == 422
    assert client.post('/api/submit', json=case).status_code in (404, 405)
    assert client.post('/api/pdf-check', files={'file':('fake.pdf',b'not pdf','application/pdf')}).status_code == 422

def test_digest_changes_when_evidence_changes(case):
    a = assess(Case(**case))['evidence_digest']
    case['profile']['facts'][0]['source']['verified'] = False
    assert assess(Case(**case))['evidence_digest'] != a
