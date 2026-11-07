from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .engine import ai_select, assess, build_draft, markdown
from .models import AssessmentResult, Case, Draft, DraftResult

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare traceable evidence for an application. Never submits."
    )
    parser.add_argument("case", type=Path, help="JSON with profile and job")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--ollama",
        metavar="MODEL",
        help="Opt in to evidence-ID selection using local Ollama",
    )
    mode_group.add_argument(
        "--select",
        nargs="*",
        help="Verified fact IDs for a manual draft",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("application-review.json"),
    )
    return parser


def load_case_file(path: Path) -> Case:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Cannot read case file '%s': %s", path, exc)
        raise ValueError(f"Cannot read case file '{path}': {exc}") from exc
    try:
        return Case.model_validate_json(raw_text)
    except ValidationError as exc:
        logger.error("Invalid case schema in '%s': %s", path, exc)
        raise ValueError(f"Invalid case file '{path}': {exc}") from exc


def run_review(
    case: Case,
    *,
    ollama_model: str | None = None,
    selected_ids: Sequence[str] | None = None,
) -> AssessmentResult | DraftResult:
    if ollama_model is not None and selected_ids is not None:
        raise ValueError("Choose either --ollama or --select, not both.")
    if ollama_model is not None:
        draft_result = ai_select(case, ollama_model)
        draft_result["markdown"] = markdown(draft_result)
        return draft_result
    if selected_ids is not None:
        draft_result = build_draft(
            Draft(profile=case.profile, job=case.job, selected_ids=list(selected_ids))
        )
        draft_result["markdown"] = markdown(draft_result)
        return draft_result
    return assess(case)


def write_review_output(output_path: Path, payload: Mapping[str, Any]) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)
        output_path.write_text(serialized, encoding="utf-8")
    except OSError as exc:
        logger.error("Cannot write review output to '%s': %s", output_path, exc)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        case = load_case_file(args.case)
        result = run_review(
            case,
            ollama_model=args.ollama,
            selected_ids=args.select,
        )
        write_review_output(args.output, result)
    except (ValueError, OSError) as exc:
        logger.error("ApplyProof CLI failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Review saved: {args.output}")
    return 0


if __name__ == "__main__":
    main()
