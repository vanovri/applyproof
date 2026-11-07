from __future__ import annotations

import copy
import io
import json
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest
from pydantic import ValidationError

from applyproof.engine import (
    _fact_supports_level,
    _index_profile_facts,
    _parse_ollama_selected_ids,
    ai_select,
    assess,
    audit_draft,
    build_draft,
    evidence_digest,
    location_check,
    markdown,
    normalize,
)
from applyproof.models import (
    Audit,
    Case,
    Draft,
    Fact,
    Job,
    Location,
    Profile,
    Requirement,
    Source,
)


@pytest.fixture
def demo_dict() -> dict[str, Any]:
    demo_path = Path(__file__).resolve().parent.parent / "examples/demo.json"
    return json.loads(demo_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Normalization & Digest Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Python", "python"),
        ("  Electrical   Engineering\n\tDegree ", "electrical engineering degree"),
        ("ＰＹＴＨＯＮ\u3000３．１２", "python 3.12"),
        ("Straße\u00a0Worksite", "strasse worksite"),
        ("C++ / C# & Node.js (v22)", "c++ / c# & node.js (v22)"),
        ("   \t\n  ", ""),
        ("", ""),
    ],
)
def test_normalize_unicode_whitespace_and_punctuation(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize("bad_input", [None, 123, True, 3.14, ["python"]])
def test_normalize_rejects_non_string_inputs(bad_input: Any) -> None:
    with pytest.raises(TypeError, match="Expected str"):
        normalize(bad_input)


def test_evidence_digest_consistent_across_case_draft_and_audit(
    demo_dict: dict[str, Any],
) -> None:
    case_model = Case(**demo_dict)
    draft_model = Draft(**demo_dict, selected_ids=["degree", "ups"])
    audit_model = Audit(**demo_dict, selected_ids=["degree"], bullets=["some bullet"])
    base_digest = evidence_digest(case_model)
    assert len(base_digest) == 64
    assert evidence_digest(draft_model) == base_digest
    assert evidence_digest(audit_model) == base_digest


# ---------------------------------------------------------------------------
# Pydantic Schema & Validation Contract Tests
# ---------------------------------------------------------------------------


def test_duplicate_requirement_ids_rejected(demo_dict: dict[str, Any]) -> None:
    demo_dict["job"]["requirements"].append(copy.deepcopy(demo_dict["job"]["requirements"][0]))
    with pytest.raises(ValidationError, match="Requirement IDs must be unique"):
        Case(**demo_dict)


def test_empty_facts_or_requirements_rejected(demo_dict: dict[str, Any]) -> None:
    no_facts = copy.deepcopy(demo_dict)
    no_facts["profile"]["facts"] = []
    with pytest.raises(ValidationError):
        Case(**no_facts)

    no_reqs = copy.deepcopy(demo_dict)
    no_reqs["job"]["requirements"] = []
    with pytest.raises(ValidationError):
        Case(**no_reqs)


def test_extra_fields_forbidden_everywhere(demo_dict: dict[str, Any]) -> None:
    with_extra = copy.deepcopy(demo_dict)
    with_extra["unexpected"] = "nope"
    with pytest.raises(ValidationError):
        Case(**with_extra)

    fact_extra = copy.deepcopy(demo_dict)
    fact_extra["profile"]["facts"][0]["extra_key"] = 1
    with pytest.raises(ValidationError):
        Case(**fact_extra)


@pytest.mark.parametrize("bad_id", ["", "has space", "bad/slash", "a" * 41, "id$1"])
def test_invalid_identifier_patterns_rejected(demo_dict: dict[str, Any], bad_id: str) -> None:
    bad_fact = copy.deepcopy(demo_dict)
    bad_fact["profile"]["facts"][0]["id"] = bad_id
    with pytest.raises(ValidationError):
        Case(**bad_fact)

    bad_req = copy.deepcopy(demo_dict)
    bad_req["job"]["requirements"][0]["id"] = bad_id
    with pytest.raises(ValidationError):
        Case(**bad_req)


@pytest.mark.parametrize("non_bool", [1, 0, "true", "false", "yes", None])
def test_strict_bool_rejects_int_and_string_coercion(
    demo_dict: dict[str, Any], non_bool: Any
) -> None:
    bad_source = copy.deepcopy(demo_dict)
    bad_source["profile"]["facts"][0]["source"]["verified"] = non_bool
    with pytest.raises(ValidationError):
        Case(**bad_source)

    bad_req = copy.deepcopy(demo_dict)
    bad_req["job"]["requirements"][0]["mandatory"] = non_bool
    with pytest.raises(ValidationError):
        Case(**bad_req)


def test_whitespace_only_strings_and_blank_skill_tags_rejected(
    demo_dict: dict[str, Any],
) -> None:
    blank_name = copy.deepcopy(demo_dict)
    blank_name["profile"]["name"] = "   \t  "
    with pytest.raises(ValidationError):
        Case(**blank_name)

    blank_skill = copy.deepcopy(demo_dict)
    blank_skill["profile"]["facts"][0]["skills"] = ["valid-skill", "   "]
    with pytest.raises(ValidationError):
        Case(**blank_skill)


# ---------------------------------------------------------------------------
# Assessment Level Matrix, Precomputed Index, Gap & Location Tests
# ---------------------------------------------------------------------------


def test_index_profile_facts_normalizes_skill_sets_once(demo_dict: dict[str, Any]) -> None:
    case = Case(**demo_dict)
    indexed = _index_profile_facts(case.profile.facts)
    assert len(indexed) == len(case.profile.facts)
    assert indexed[1][1] == frozenset({"ups"})
    assert indexed[2][1] == frozenset({"python", "documentation"})


@pytest.mark.parametrize(
    ("fact_level", "min_level", "expected_status", "expected_match"),
    [
        ("exposure", "exposure", "supported", True),
        ("exposure", "hands-on", "partial", False),
        ("exposure", "credential", "partial", False),
        ("hands-on", "exposure", "supported", True),
        ("hands-on", "hands-on", "supported", True),
        ("hands-on", "credential", "partial", False),
        ("credential", "exposure", "partial", False),
        ("credential", "hands-on", "partial", False),
        ("credential", "credential", "supported", True),
    ],
)
def test_skill_level_matching_matrix(
    fact_level: str,
    min_level: str,
    expected_status: str,
    expected_match: bool,
) -> None:
    assert _fact_supports_level(fact_level, min_level) is expected_match  # type: ignore[arg-type]
    src = Source(label="Doc", locator="loc://1", excerpt="Excerpt", verified=True)
    case = Case(
        profile=Profile(
            name="Test Candidate",
            facts=[
                Fact(
                    id="f1",
                    text="Evidence statement.",
                    skills=["Python"],
                    level=fact_level,  # type: ignore[arg-type]
                    source=src,
                )
            ],
        ),
        job=Job(
            company="Acme",
            title="Engineer",
            source=src,
            requirements=[
                Requirement(
                    id="r1",
                    label="Python requirement",
                    skill="python",
                    minimum_level=min_level,  # type: ignore[arg-type]
                    mandatory=True,
                )
            ],
        ),
    )
    result = assess(case)
    assert result["requirements"][0]["status"] == expected_status


def test_gap_optional_requirement_and_ready_for_human_review() -> None:
    src = Source(label="Verified Doc", locator="loc://v", excerpt="Verified", verified=True)
    case = Case(
        profile=Profile(
            name="Alex",
            facts=[
                Fact(
                    id="py",
                    text="Built Python ETL service.",
                    skills=["  ＰＹＴＨＯＮ  "],
                    level="hands-on",
                    source=src,
                )
            ],
        ),
        job=Job(
            company="Acme",
            title="Backend Dev",
            source=src,
            preferred_city="",
            requirements=[
                Requirement(
                    id="req_py",
                    label="Python development",
                    skill="python",
                    minimum_level="hands-on",
                    mandatory=True,
                ),
                Requirement(
                    id="req_rust",
                    label="Nice-to-have Rust",
                    skill="rust",
                    minimum_level="exposure",
                    mandatory=False,
                ),
            ],
            locations=[
                Location(city="Bandung", scope="role", source=src),
                Location(city="  bandung ", scope="role", source=src),
            ],
        ),
    )
    result = assess(case)
    assert result["requirements"][0]["status"] == "supported"
    assert result["requirements"][1]["status"] == "gap"
    assert result["requirements"][1]["fact_ids"] == []
    assert result["unresolved_requirements"] == []
    assert result["location"]["status"] == "verified"
    assert result["review_status"] == "ready_for_human_review"


def test_unverified_role_location_is_ignored_in_location_check(
    demo_dict: dict[str, Any],
) -> None:
    unverified_role = {
        "city": "South Jakarta",
        "scope": "role",
        "source": {
            "label": "Rumor",
            "locator": "chat://1",
            "excerpt": "Maybe South Jakarta",
            "verified": False,
        },
    }
    demo_dict["job"]["locations"].append(unverified_role)
    loc = location_check(Case(**demo_dict).job)
    assert loc["status"] == "unverified"
    assert loc["role_cities"] == []


# ---------------------------------------------------------------------------
# Draft, Audit, Markdown & Ollama Selection Edge Cases
# ---------------------------------------------------------------------------


def test_markdown_formats_complete_draft_and_unresolved_items(
    demo_dict: dict[str, Any],
) -> None:
    draft_result = build_draft(Draft(**demo_dict, selected_ids=["degree", "python"]))
    md = markdown(draft_result)
    assert md.startswith("# Alex Morgan (fictional demo)\n")
    assert (
        "Application preparation: Junior Electrical Engineer at Northline Engineering (fictional)"
        in md
    )
    assert "- Completed a BEng in Electrical Engineering in 2026." in md
    assert "  Evidence: degree | Demo diploma | demo://degree" in md
    assert "Actual role location: unverified" in md
    assert "- Verify requirement: Hands-on UPS systems" in md
    assert f"Evidence SHA256: {draft_result['assessment']['evidence_digest']}" in md


def test_audit_draft_handles_empty_and_whitespace_bullets(
    demo_dict: dict[str, Any],
) -> None:
    fact_text = demo_dict["profile"]["facts"][0]["text"]
    audited = audit_draft(
        Audit(
            **demo_dict,
            selected_ids=["degree"],
            bullets=["", "   ", f"  {fact_text}  "],
        )
    )
    assert audited[0] == {"text": "", "status": "needs_evidence", "fact_id": None}
    assert audited[1] == {"text": "", "status": "needs_evidence", "fact_id": None}
    assert audited[2]["status"] == "traceable"
    assert audited[2]["fact_id"] == "degree"


def test_ai_select_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch, demo_dict: dict[str, Any]
) -> None:
    huge = b"x" * 100_001
    monkeypatch.setattr("applyproof.engine.urlopen", lambda *a, **kw: io.BytesIO(huge))
    with pytest.raises(ValueError, match="Model response exceeds limit"):
        ai_select(Case(**demo_dict), "demo-model")


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfeinvalid-utf8",
        b"not-json",
        b"[]",
        json.dumps({"error": "model not found"}).encode(),
        json.dumps({"no_response_key": 1}).encode(),
        json.dumps({"response": 123}).encode(),
        json.dumps({"response": "not-json"}).encode(),
        json.dumps({"response": json.dumps(["array"])}).encode(),
        json.dumps({"response": json.dumps({"wrong_key": []})}).encode(),
        json.dumps({"response": json.dumps({"selected_ids": "degree"})}).encode(),
        json.dumps({"response": json.dumps({"selected_ids": [123]})}).encode(),
    ],
)
def test_ai_select_rejects_malformed_provider_payloads(
    monkeypatch: pytest.MonkeyPatch, demo_dict: dict[str, Any], payload: bytes
) -> None:
    with pytest.raises(ValueError):
        _parse_ollama_selected_ids(payload)

    monkeypatch.setattr("applyproof.engine.urlopen", lambda *a, **kw: io.BytesIO(payload))
    with pytest.raises(ValueError):
        ai_select(Case(**demo_dict), "demo-model")


def test_ai_select_rejects_empty_model_and_handles_network_error(
    monkeypatch: pytest.MonkeyPatch, demo_dict: dict[str, Any]
) -> None:
    case = Case(**demo_dict)
    with pytest.raises(ValueError, match="Model name must be a non-empty string"):
        ai_select(case, "   ")

    def broken_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        raise URLError("Connection refused")

    monkeypatch.setattr("applyproof.engine.urlopen", broken_urlopen)
    with pytest.raises(ConnectionError, match="Unable to reach local Ollama service"):
        ai_select(case, "demo-model")
