from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from applyproof.api import app
from applyproof.engine import normalize


def test_normalization_handles_compatibility_unicode_and_spacing() -> None:
    assert normalize("  ＰＹＴＨＯＮ\tSkill  ") == "python skill"


def test_assessment_draft_audit_round_trip_keeps_verbatim_sources() -> None:
    case = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/demo.json").read_text(encoding="utf-8")
    )
    with TestClient(app) as client:
        assessment = client.post("/api/assess", json=case)
        assert assessment.status_code == 200
        draft = client.post("/api/draft", json={**case, "selected_ids": ["degree", "ups"]})
        assert draft.status_code == 200
        result = draft.json()
        assert result["assessment"]["evidence_digest"] == assessment.json()["evidence_digest"]
        assert [b["fact_id"] for b in result["bullets"]] == ["degree", "ups"]
        text = result["bullets"][0]["text"]
        audit = client.post(
            "/api/audit",
            json={
                **case,
                "selected_ids": ["degree"],
                "bullets": [text.swapcase(), text + " invented claim"],
            },
        )
        assert audit.status_code == 200
        assert [b["status"] for b in audit.json()] == ["traceable", "needs_evidence"]
        assert "Human review required" in result["markdown"]


def test_blank_pdf_is_valid_but_needs_text_review_and_page_limit_is_enforced() -> None:
    with TestClient(app) as client:
        for pages, expected in [(1, 200), (21, 422)]:
            writer = PdfWriter()
            for _ in range(pages):
                writer.add_blank_page(width=72, height=72)
            stream = BytesIO()
            writer.write(stream)
            response = client.post(
                "/api/pdf-check",
                files={"file": ("synthetic.pdf", stream.getvalue(), "application/pdf")},
            )
            assert response.status_code == expected
            if expected == 200:
                assert response.json()["characters_by_page"] == [0]
                assert response.json()["status"] == "needs_text_layer_review"
                assert response.json()["stored"] is False
