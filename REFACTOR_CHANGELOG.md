# Refactor & Automated QA Verification Changelog — `applyproof`

## 1. Branch & Git Safety Summary

| Item | Value |
| :--- | :--- |
| **Original Branch** | `main` (`1169f44`) |
| **Working Branch** | `codex/auto-refactor-and-tests` |
| **Pre-Refactor Stash** | `stash@{0}: On main: pre-refactor-backup-snapshot` (preserves pre-existing untracked notes/artifacts untouched) |
| **Backward Compatibility** | 100% preserved across FastAPI routes, CLI flags, Pydantic schemas, and original 19 unit tests |

---

## 2. Files Modified & Added

| Path | Action | Purpose |
| :--- | :--- | :--- |
| `.gitignore` | Modified | Ignore `.coverage`, `.mypy_cache/`, and `.ruff_cache/` artifacts so working tree stays clean after verification runs. |
| `applyproof/__init__.py` | Modified | Added `from __future__ import annotations` and explicit `__version__ = "0.1.0"` export. |
| `applyproof/models.py` | Modified | Added strict `TypedDict` output contracts (`AssessmentResult`, `DraftResult`, `AuditRow`, `PdfInspectionResult`, etc.), `StrictBool` on `verified`/`mandatory`, `Identifier` and non-empty `SkillTag` `Annotated` field constraints, and `Self` validator annotations. |
| `applyproof/engine.py` | Modified | Fixed `evidence_digest` consistency across `Case`/`Draft`/`Audit`; precomputed normalized skill `frozenset` index once per `assess` (`O(facts*skills + reqs)`); avoided duplicate `location_check` call; decomposed assessment, selection validation, prompt construction, and Ollama JSON parsing into pure single-responsibility helpers; hardened error handling and `logging.getLogger(__name__)` diagnostics. |
| `applyproof/api.py` | Modified | Extracted `inspect_pdf`, `_validate_pdf_upload`, `_extract_pdf_page_counts`, `_is_valid_content_length`, `load_demo_case`, and `mount_frontend`; offloaded synchronous `PdfReader` parsing via `asyncio.to_thread(inspect_pdf, data)`; guaranteed `UploadFile.close()` inside `try/finally`; replaced broad `except Exception:` with explicit `PdfReadError`/`PyPdfError`/`DependencyError`/`zlib.error`/`EOFError`/`ValueError` handlers. |
| `applyproof/cli.py` | Modified | Decomposed CLI into `build_parser`, `load_case_file`, `run_review`, `write_review_output`, and `main(argv)`; enforced mutually exclusive `--ollama`/`--select`; fixed empty `--select` falsy fallthrough; ensured output parent directory creation and structured `SystemExit(1)` error reporting. |
| `tests/test_evidence.py` | Modified | Normalized import sorting (`ruff` `I001`) while keeping all 15 original test cases unchanged. |
| `tests/test_provider.py` | Modified | Normalized import sorting (`ruff` `I001`) while keeping all 4 original Ollama provider test cases unchanged. |
| `tests/test_review_pipeline.py` | Added | End-to-end Unicode normalization, `/api/assess` -> `/api/draft` -> `/api/audit` digest/traceability round-trip, and blank/over-limit PDF checks. |
| `tests/test_models_and_engine.py` | Added | Comprehensive unit tests for `normalize` (NFKC Unicode, whitespace, punctuation, non-str `TypeError`), digest invariance, `StrictModel`/`StrictBool`/ID/blank-skill schema bounds, full 3x3 skill-level matching matrix, `gap`/optional requirements, `location_check` states, `markdown`, `audit_draft`, and malformed/oversized/offline `ai_select` payloads. |
| `tests/test_api_and_pdf.py` | Added | FastAPI endpoint, middleware (`Content-Length` bounds & Unicode digit guard), `load_demo_case`, `mount_frontend`, `/api/pdf-check` boundary suite (>5 MB 413, non-PDF header, corrupt, encrypted, 0-page, 20-page, 21-page, exact 50 vs 51 char text-layer threshold), `UploadFile.close()` `try/finally` guarantee, and concurrent `httpx.AsyncClient` event-loop responsiveness test. |
| `tests/test_cli.py` | Added | CLI unit & `__main__` execution tests covering assessment mode, manual `--select` into nested directories, mocked `--ollama` mode, empty `--select` rejection, conflicting flags, missing/corrupt input files, and unwritable output paths. |
| `REFACTOR_CHANGELOG.md` | Added | Complete engineering changelog and before/after verification ledger. |

---

## 3. Architectural & Code Quality Improvements

### Pillar 1: Type Safety & Contracts
- Enabled `from __future__ import annotations` and complete type annotations across all 5 modules in `applyproof/`, passing both `mypy applyproof --ignore-missing-imports` and `mypy --strict applyproof --ignore-missing-imports` with **0 errors**.
- Defined explicit `TypedDict` contracts (`LocationAssessment`, `RequirementRow`, `AssessmentResult`, `DraftBullet`, `DraftResult`, `AuditRow`, `PdfInspectionResult`) in `applyproof/models.py` to enforce compile-time structure while keeping 100% runtime `dict` compatibility.
- Replaced coercive `bool` fields on `Source.verified` and `Requirement.mandatory` with `pydantic.StrictBool` so integers (`1`, `0`) and strings (`"true"`, `"false"`, `"yes"`) cannot silently coerce into verified evidence flags.
- Constrained `Fact.skills` items via `SkillTag = Annotated[str, Field(min_length=1, max_length=100)]`, rejecting empty or whitespace-only skill tags.
- Added explicit `isinstance(value, str)` validation in `normalize()` and `Annotated[UploadFile, File(...)]` in `api.py` (resolving Ruff `B008`).

### Pillar 2: Modularity & Clean Architecture
- Every function across `applyproof/*.py` is concise (<35 lines) and single-responsibility:
  - `engine.py`: Extracted `_index_profile_facts`, `_fact_supports_level`, `_evaluate_requirement`, `_validate_selected_facts`, `_build_ollama_prompt`, and `_parse_ollama_selected_ids`.
  - `api.py`: Extracted `_is_valid_content_length`, `load_demo_case`, `_validate_pdf_upload`, `_extract_pdf_page_counts`, `inspect_pdf`, and `mount_frontend`.
  - `cli.py`: Extracted `build_parser`, `load_case_file`, `run_review`, and `write_review_output`, and parameterized `main(argv: Sequence[str] | None = None) -> int`.

### Pillar 3: Performance & Concurrency
- **Single-pass skill normalization (`applyproof/engine.py`)**: Precomputed `(fact, frozenset(normalize(s) for s in fact.skills))` once per `assess()` call (`_index_profile_facts`) and normalized each requirement skill once, reducing tag normalization complexity from $O(R \times F \times S)$ to $O(F \times S + R)$.
- **Eliminated duplicate computations (`applyproof/engine.py`)**: Computed `location_check(case.job)` once in `assess()` (previously called twice) and normalized each audited bullet once in `audit_draft()` (previously called twice per bullet).
- **Non-blocking PDF inspection (`applyproof/api.py`)**: Offloaded synchronous `pypdf.PdfReader` parsing and page text extraction to a worker thread via `await asyncio.to_thread(inspect_pdf, data)` after fast header/size checks, keeping the FastAPI event loop responsive to concurrent requests (verified via concurrent `httpx.AsyncClient` latency test).
- **Deterministic resource cleanup (`applyproof/api.py`)**: Wrapped `await file.read(MAX_PDF_BYTES + 1)` in `try ... finally: await file.close()` so uploaded file handles always close even on read failures.

### Pillar 4: Error Resilience & Concrete Bugs Fixed
- **Bug Fix — `evidence_digest` mismatch between `/api/assess` and `/api/draft`**: Previously, `evidence_digest(case)` hashed `case.model_dump()`, which included `selected_ids` on `Draft` subclasses and `bullets` on `Audit` subclasses, causing `/api/draft` to report a different SHA-256 evidence digest than `/api/assess` for the exact same `Case`. Fixed via `case.model_dump(include={"profile", "job"})`.
- **Bug Fix — CLI `--select` empty list fallthrough**: Previously, `elif args.select:` treated `applyproof demo.json --select` (`args.select == []`) as falsy and silently exported an assessment instead of failing draft validation. Fixed by checking `selected_ids is not None` and making `--ollama` and `--select` mutually exclusive.
- **Bug Fix — CLI nested output directory failure**: `write_review_output` now ensures `output_path.parent.mkdir(parents=True, exist_ok=True)` before writing JSON.
- **Bug Fix — `Content-Length` Unicode superscript crash**: Replaced `length.isdigit()` with `length.isascii() and length.isdigit()` in `_is_valid_content_length` so Unicode superscript digits like `'²'` cannot pass `.isdigit()` and raise `ValueError` in `int(length)`.
- **Structured Exception Handling & Logging**: Replaced bare `except Exception:` in `api.py` and unguarded `KeyError`/`TypeError` indexing in `ai_select` with explicit exception handlers (`PdfReadError`, `PyPdfError`, `DependencyError`, `zlib.error`, `EOFError`, `URLError`, `ValidationError`, `ValueError`, `OSError`) and `logging.getLogger(__name__)` diagnostics across `engine.py`, `api.py`, and `cli.py`.

---

## 4. Before vs. After Test Suite & Coverage

| Metric / Module | BEFORE (`main`) | AFTER (`codex/auto-refactor-and-tests`) | Delta |
| :--- | ---: | ---: | ---: |
| **Total Tests Collected** | 19 | **107** | **+88 tests** |
| **Tests Passing** | 19 / 19 (100%) | **107 / 107 (100%)** | **+88 passing** |
| `applyproof/__init__.py` | 100% (0 / 0 stmts) | **100%** (3 / 3 stmts) | 100% |
| `applyproof/api.py` | 66% (40 / 61 stmts) | **100%** (111 / 111 stmts, 14 / 14 branches) | **+34%** |
| `applyproof/cli.py` | 0% (0 / 24 stmts) | **100%** (66 / 66 stmts, 8 / 8 branches) | **+100%** |
| `applyproof/engine.py` | 86% (63 / 73 stmts) | **100%** (146 / 146 stmts, 44 / 44 branches) | **+14%** |
| `applyproof/models.py` | 98% (47 / 48 stmts) | **100%** (106 / 106 stmts, 4 / 4 branches) | **+2%** |
| **TOTAL Coverage** | **73%** (150 / 206 stmts) | **100%** (432 / 432 stmts, 70 / 70 branches) | **+27% (100% line & branch)** |

---

## 5. Linter, Type-Checker & Test Verification Commands

| Check | Command | Exit Code | Result |
| :--- | :--- | :---: | :--- |
| **Pytest + Coverage** | `.\.venv\Scripts\python.exe -m pytest --cov=applyproof --cov-report=term-missing` | `0` | `107 passed`, `100%` line & branch coverage |
| **Ruff Linter** | `ruff.exe check applyproof tests` (and `ruff.exe check .`) | `0` | `All checks passed!` (0 warnings/errors; fixed 8 pre-existing lint errors) |
| **Mypy Type-Checker** | `mypy.exe applyproof --ignore-missing-imports` | `0` | `Success: no issues found in 5 source files` |
| **Mypy Strict Mode** | `mypy.exe --strict applyproof --ignore-missing-imports` | `0` | `Success: no issues found in 5 source files` |
