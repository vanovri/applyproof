import io
import json
from pathlib import Path
import pytest
from applyproof.models import Case
from applyproof.engine import ai_select

def sample():
    return Case.model_validate_json((Path(__file__).resolve().parent.parent/'examples/demo.json').read_text())

def test_ai_selects_ids_not_new_claims(monkeypatch):
    def response(request,timeout):
        assert request.full_url=='http://127.0.0.1:11434/api/generate'
        prompt=json.loads(request.data)['prompt']
        assert 'Unconfirmed course note' not in prompt
        return io.BytesIO(json.dumps({'response':json.dumps({'selected_ids':['ups','degree']})}).encode())
    monkeypatch.setattr('applyproof.engine.urlopen',response)
    result=ai_select(sample(),'demo-model')
    assert result['bullets'][0]['text']==sample().profile.facts[1].text
    assert result['selection_provider']=='ollama:demo-model'

@pytest.mark.parametrize('ids',[['invented'],['cad'],['degree','degree']])
def test_ai_cannot_promote_unverified_or_fabricated_evidence(monkeypatch,ids):
    monkeypatch.setattr('applyproof.engine.urlopen',lambda *a,**kw:io.BytesIO(json.dumps({'response':json.dumps({'selected_ids':ids})}).encode()))
    with pytest.raises(ValueError):
        ai_select(sample(),'demo')
