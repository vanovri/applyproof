# Architecture: applyproof

Crosscheck: 2026-11-08 WIB. The repository-local offline checks completed with exit code 0 in an interpreter/environment containing the declared dependencies. Hardware, live providers, deployment and unexecuted CI platforms are separate evidence boundaries.

Reviewed on 2026-11-07 against the local working tree (`.`). `graphify-out/graph.json` provides the local AST symbol graph.

## 1. System Context & Data Flow

Traceable job-application evidence workbench (FastAPI + React + CLI) that validates structured candidate facts via strict Pydantic models, evaluates requirement & location coverage, generates verbatim evidence drafts, audits edited bullets by normalized exact match, and inspects PDF text layers in memory.

```mermaid
graph TD
User["Reviewer"] --> UI["React Workspace (frontend/src/main.jsx)"]
    User --> CLI["applyproof CLI (applyproof/cli.py)"]
    UI --> API["FastAPI Routes (applyproof/api.py)"]
    API --> Models["Strict Pydantic Schemas (applyproof/models.py)"]
    CLI --> Models
    Models --> Engine["Evidence Engine (applyproof/engine.py)"]
    CLI -. explicit opt-in .-> Ollama["Localhost Ollama Fact-ID Selector"]
    Ollama --> Engine
    API --> PDF["Bounded Off-Loop PDF Text Inspector (pypdf)"]
    Engine --> Out["JSON Assessment / Verbatim Markdown Draft / Exact-Match Audit"]
```

## 2. Execution & Pipeline Sequence

```mermaid
sequenceDiagram
actor U as Reviewer
    participant UI as React UI
    participant API as FastAPI (api.py)
    participant E as engine.py
    U->>UI: Load case & select verified fact IDs
    UI->>API: POST /api/assess
    API->>E: assess(Case)
    E-->>UI: Requirement coverage + SHA-256 evidence_digest
    UI->>API: POST /api/draft
    API->>E: build_draft(Draft) + markdown()
    E-->>UI: Verbatim bullets + provenance locators
    UI->>API: POST /api/audit
    API->>E: audit_draft(Audit)
    E-->>UI: Per-bullet traceable | needs_evidence status
```

## 3. Module Breakdown

| Path | Responsibility |
| :--- | :--- |
| `applyproof/models.py` | Strict `extra='forbid'` Pydantic models (`Case`, `Profile`, `Fact`, `Source`, `Job`, `Draft`, `Audit`) with unique-ID invariants and size caps. |
| `applyproof/engine.py` | NFKC/whitespace normalization, SHA-256 `evidence_digest`, pre-indexed requirement matching, verbatim `build_draft`, exact-match `audit_draft`, Markdown renderer, and localhost Ollama ID selector. |
| `applyproof/api.py` | Request-size guard middleware, `/api/health`, `/api/demo`, `/api/assess`, `/api/draft`, `/api/audit`, async `asyncio.to_thread` `/api/pdf-check`, and optional static UI mount. |
| `applyproof/cli.py` | CLI workflow supporting manual or localhost Ollama fact-ID selection and JSON export. |
| `frontend/src/main.jsx` | Session-scoped React workspace managing case state, fact selection, draft preview, bullet auditing, and PDF inspection. |
| `tests/` | 6 pytest modules (`test_models_and_engine.py`, `test_evidence.py`, `test_api_and_pdf.py`, `test_cli.py`, `test_provider.py`, `test_review_pipeline.py`). |

## 4. State Management & Failure Handling

Backend routes are completely stateless with no database or disk upload retention (`UploadFile` is bounded to 5 MB + 1 byte, closed in `finally`, and parsed in memory via `asyncio.to_thread`). React holds session state in memory and invalidates downstream draft/audit results whenever inputs change.

## 5. Verification Commands

```powershell
Set-Location 'python' -m pytest -q
```

## 6. Integration Boundaries

Never fabricates resume prose or submits external applications; optional Ollama integration selects existing verified fact IDs only and is mocked in automated tests.
