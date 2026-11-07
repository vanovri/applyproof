from __future__ import annotations

import asyncio
import json
import logging
import zlib
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from pypdf.errors import DependencyError, PdfReadError, PyPdfError

from . import __version__
from .engine import assess, audit_draft, build_draft, markdown
from .models import (
    AssessmentResult,
    Audit,
    AuditRow,
    Case,
    Draft,
    DraftResult,
    PdfInspectionResult,
    PdfTextStatus,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEMO_CASE_PATH = ROOT / "examples/demo.json"
FRONTEND_DIST_DIR = ROOT / "frontend/dist"

MAX_REQUEST_BYTES = 6_000_000
MAX_PDF_BYTES = 5_000_000
MAX_PDF_PAGES = 20
MIN_PAGE_TEXT_CHARS = 50
PDF_MAGIC_HEADER = b"%PDF-"
PDF_NOTE = "Text-layer check only. It does not measure ATS ranking or layout quality."
PDF_ERROR_DETAIL = "Cannot inspect PDF. Use an unencrypted, valid PDF with at most 20 pages."

app = FastAPI(title="ApplyProof", docs_url=None, redoc_url=None)


def _is_valid_content_length(header_value: str) -> bool:
    return (
        header_value.isascii()
        and header_value.isdigit()
        and int(header_value) <= MAX_REQUEST_BYTES
    )


@app.middleware("http")
async def size_limit(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    length = request.headers.get("content-length")
    if length and not _is_valid_content_length(length):
        logger.warning("Rejected request with invalid or oversized Content-Length: %r", length)
        return JSONResponse({"detail": "Request exceeds 6 MB."}, status_code=413)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def load_demo_case(demo_file: Path = DEMO_CASE_PATH) -> dict[str, Any]:
    try:
        parsed = json.loads(demo_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load demo case from %s: %s", demo_file, exc)
        raise HTTPException(status_code=500, detail="Demo case is unavailable.") from exc
    if not isinstance(parsed, dict):
        logger.error("Demo case at %s did not deserialize to a JSON object.", demo_file)
        raise HTTPException(status_code=500, detail="Demo case is invalid.")
    return parsed


@app.get("/api/demo")
def demo() -> dict[str, Any]:
    return load_demo_case()


@app.post("/api/assess")
def assessment(case: Case) -> AssessmentResult:
    return assess(case)


@app.post("/api/draft")
def draft(case: Draft) -> DraftResult:
    try:
        result = build_draft(case)
        result["markdown"] = markdown(result)
        return result
    except ValueError as exc:
        logger.info("Draft request rejected: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/audit")
def audit(case: Audit) -> list[AuditRow]:
    try:
        return audit_draft(case)
    except ValueError as exc:
        logger.info("Audit request rejected: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_pdf_upload(data: bytes) -> None:
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds 5 MB.")
    if not data.startswith(PDF_MAGIC_HEADER):
        raise HTTPException(status_code=422, detail="Expected a PDF file.")


def _extract_pdf_page_counts(data: bytes) -> list[int]:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Unlock the PDF locally first.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(f"Limit is {MAX_PDF_PAGES} pages.")
        return [len((page.extract_text() or "").strip()) for page in reader.pages]
    except ValueError as exc:
        logger.warning("PDF rejected by inspection policy: %s", exc)
        raise HTTPException(status_code=422, detail=PDF_ERROR_DETAIL) from exc
    except (PdfReadError, PyPdfError, DependencyError, zlib.error, EOFError) as exc:
        logger.warning("PDF parsing failed: %s", exc)
        raise HTTPException(status_code=422, detail=PDF_ERROR_DETAIL) from exc


def inspect_pdf(data: bytes) -> PdfInspectionResult:
    _validate_pdf_upload(data)
    counts = _extract_pdf_page_counts(data)
    has_text_layer = bool(counts) and all(count > MIN_PAGE_TEXT_CHARS for count in counts)
    status: PdfTextStatus = "text_layer_found" if has_text_layer else "needs_text_layer_review"
    return {
        "pages": len(counts),
        "characters_by_page": counts,
        "status": status,
        "stored": False,
        "note": PDF_NOTE,
    }


@app.post("/api/pdf-check")
async def pdf_check(file: Annotated[UploadFile, File(...)]) -> PdfInspectionResult:
    try:
        data = await file.read(MAX_PDF_BYTES + 1)
    finally:
        await file.close()
    _validate_pdf_upload(data)
    return await asyncio.to_thread(inspect_pdf, data)


def mount_frontend(application: FastAPI, dist_dir: Path) -> bool:
    if dist_dir.is_dir():
        application.mount("/", StaticFiles(directory=dist_dir, html=True), name="ui")
        return True
    return False


mount_frontend(app, FRONTEND_DIST_DIR)
