from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path

import pytest

from applyproof.cli import load_case_file, main, run_review, write_review_output


@pytest.fixture
def demo_path() -> Path:
    return Path(__file__).resolve().parent.parent / "examples/demo.json"


def test_cli_assessment_mode_writes_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    demo_path: Path,
) -> None:
    out_file = tmp_path / "assessment.json"
    monkeypatch.setattr(sys, "argv", ["applyproof", str(demo_path), "--output", str(out_file)])
    monkeypatch.delitem(sys.modules, "applyproof.cli", raising=False)
    runpy.run_module("applyproof.cli", run_name="__main__")
    captured = capsys.readouterr()
    assert f"Review saved: {out_file}" in captured.out
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert "requirements" in payload
    assert "markdown" not in payload


def test_cli_manual_select_mode_writes_draft_with_markdown(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    demo_path: Path,
) -> None:
    out_file = tmp_path / "nested" / "draft.json"
    exit_code = main(
        [
            str(demo_path),
            "--select",
            "degree",
            "python",
            "--output",
            str(out_file),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert f"Review saved: {out_file}" in captured.out
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert [b["fact_id"] for b in payload["bullets"]] == ["degree", "python"]
    assert "Human review required" in payload["markdown"]


def test_cli_ollama_mode_uses_mocked_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    demo_path: Path,
) -> None:
    out_file = tmp_path / "ollama-draft.json"
    ollama_reply = json.dumps({"response": json.dumps({"selected_ids": ["ups"]})}).encode()
    monkeypatch.setattr("applyproof.engine.urlopen", lambda *a, **kw: io.BytesIO(ollama_reply))
    assert main([str(demo_path), "--ollama", "qwen2.5:7b", "--output", str(out_file)]) == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["selection_provider"] == "ollama:qwen2.5:7b"
    assert [b["fact_id"] for b in payload["bullets"]] == ["ups"]
    assert "markdown" in payload


def test_cli_empty_select_flag_is_rejected_not_silently_ignored(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    demo_path: Path,
) -> None:
    out_file = tmp_path / "empty-select.json"
    with pytest.raises(SystemExit) as exc_info:
        main([str(demo_path), "--select", "--output", str(out_file)])
    assert exc_info.value.code == 1
    assert "Select at least one verified fact" in capsys.readouterr().err
    assert not out_file.exists()


def test_cli_mutually_exclusive_flags_and_run_review_guard(
    tmp_path: Path,
    demo_path: Path,
) -> None:
    out_file = tmp_path / "conflict.json"
    with pytest.raises(SystemExit) as exc_info:
        main([str(demo_path), "--ollama", "m", "--select", "degree", "--output", str(out_file)])
    assert exc_info.value.code == 2

    case = load_case_file(demo_path)
    with pytest.raises(ValueError, match="Choose either --ollama or --select"):
        run_review(case, ollama_model="m", selected_ids=["degree"])


def test_cli_rejects_missing_file_malformed_json_and_unwritable_output(
    tmp_path: Path,
    demo_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist.json"
    out_file = tmp_path / "out.json"
    with pytest.raises(SystemExit) as missing_exc:
        main([str(missing), "--output", str(out_file)])
    assert missing_exc.value.code == 1

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{broken", encoding="utf-8")
    with pytest.raises(SystemExit) as bad_exc:
        main([str(bad_json), "--output", str(out_file)])
    assert bad_exc.value.code == 1

    existing_dir = tmp_path / "dir_as_file"
    existing_dir.mkdir()
    with pytest.raises(OSError):
        write_review_output(existing_dir, {"ok": True})

    with pytest.raises(SystemExit) as write_exc:
        main([str(demo_path), "--output", str(existing_dir)])
    assert write_exc.value.code == 1
