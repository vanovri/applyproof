# Technical Debt & Performance Ledger: applyproof

Crosschecked 2026-11-08 WIB. All code diffs below are proposal-only and have not changed production source. Source references and removed patch lines were checked against this working tree. Runtime speedups remain unmeasured unless evidence is explicitly cited.

Reviewed on 2026-11-08 WIB against the current working tree on disk. All line numbers are 1-based and verified directly against the current production files. Every diff below is a non-destructive engineering proposal, not an applied production edit.

## TD-01 — Avoid full `assess(case)` and `evidence_digest` recomputation inside `audit_draft`

- **Location**: `applyproof/engine.py:180-184`
- **Analysis**: `audit_draft` calls `build_draft(case)` solely to read `bullets`, discarding `build_draft`'s `assessment` field (`assess(case)` + full `case.profile.model_dump()` SHA-256 `evidence_digest`) and `fact.source.model_dump()` allocations on every `/api/audit` keystroke/request.

```diff
diff --git a/applyproof/engine.py b/applyproof/engine.py
--- a/applyproof/engine.py
+++ b/applyproof/engine.py
@@ -179,9 +179,10 @@
 
 def audit_draft(case: Audit) -> list[AuditRow]:
     # Exact-match checking is deliberately narrow. It never claims semantic truth detection.
+    facts_by_id = {fact.id: fact for fact in case.profile.facts}
     expected: dict[str, str] = {}
-    for bullet in build_draft(case)["bullets"]:
-        expected.setdefault(normalize(bullet["text"]), bullet["fact_id"])
+    for fact in _validate_selected_facts(facts_by_id, case.selected_ids):
+        expected.setdefault(normalize(fact.text), fact.id)
     rows: list[AuditRow] = []
     for text in case.bullets:
         matched_id = expected.get(normalize(text))
```

- **Validation**: Run `.\.venv\Scripts\python.exe -m pytest -q` and confirm `/api/audit` preserves identical 422 errors for missing/unverified/duplicate `selected_ids`.

## TD-02 — Eliminate duplicate `_validate_pdf_upload` check in `pdf_check` after pre-thread validation

- **Location**: `applyproof/api.py:152-159`
- **Analysis**: `pdf_check` validates size and `%PDF-` magic header via `_validate_pdf_upload(data)` before spawning the worker thread, and `inspect_pdf(data)` immediately calls `_validate_pdf_upload(data)` a second time The duplicate guard consists of constant-time length and short magic-prefix checks, so its elapsed cost has not been established as material. Adopt the extraction only if profiling or validation ownership justifies it.

```diff
diff --git a/applyproof/api.py b/applyproof/api.py
--- a/applyproof/api.py
+++ b/applyproof/api.py
@@ -137,6 +137,10 @@
 
 def inspect_pdf(data: bytes) -> PdfInspectionResult:
     _validate_pdf_upload(data)
+    return _inspect_validated_pdf(data)
+
+
+def _inspect_validated_pdf(data: bytes) -> PdfInspectionResult:
     counts = _extract_pdf_page_counts(data)
     has_text_layer = bool(counts) and all(count > MIN_PAGE_TEXT_CHARS for count in counts)
     status: PdfTextStatus = "text_layer_found" if has_text_layer else "needs_text_layer_review"
@@ -156,7 +160,7 @@
     finally:
         await file.close()
     _validate_pdf_upload(data)
-    return await asyncio.to_thread(inspect_pdf, data)
+    return await asyncio.to_thread(_inspect_validated_pdf, data)
 
 
 def mount_frontend(application: FastAPI, dist_dir: Path) -> bool:
```

- **Validation**: Keep `inspect_pdf(data)` calling `_validate_pdf_upload(data)` for direct callers, delegate to `_inspect_validated_pdf(data)` after validation, and run `.\.venv\Scripts\python.exe -m pytest -q`.
