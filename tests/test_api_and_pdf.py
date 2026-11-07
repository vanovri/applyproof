from __future__ import annotations

import asyncio
import json
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import applyproof.api as api_module
from applyproof.api import (
    _is_valid_content_length,
    app,
    inspect_pdf,
    load_demo_case,
    mount_frontend,
)


def make_pdf_bytes(page_texts: list[str], *, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            font_ref = writer._add_object(font)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
            )
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(password)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def demo_case() -> dict[str, Any]:
    demo_path = Path(__file__).resolve().parent.parent / "examples/demo.json"
    return json.loads(demo_path.read_text(encoding="utf-8"))


def test_health_and_demo_endpoints() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "version": "0.1.0"}

        demo = client.get("/api/demo")
        assert demo.status_code == 200
        data = demo.json()
        assert "profile" in data and "job" in data


def test_load_demo_case_error_handling(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as missing_exc:
        load_demo_case(tmp_path / "missing.json")
    assert missing_exc.value.status_code == 500

    non_dict = tmp_path / "list.json"
    non_dict.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(HTTPException) as invalid_exc:
        load_demo_case(non_dict)
    assert invalid_exc.value.status_code == 500


def test_mount_frontend_when_present_and_absent(tmp_path: Path) -> None:
    sub_app = FastAPI()
    assert mount_frontend(sub_app, tmp_path / "missing-dist") is False

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>ApplyProof UI</body></html>", encoding="utf-8")
    assert mount_frontend(sub_app, dist_dir) is True
    with TestClient(sub_app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ApplyProof UI" in resp.text


def test_is_valid_content_length_guards_unicode_digits_and_bounds() -> None:
    assert _is_valid_content_length("0") is True
    assert _is_valid_content_length("6000000") is True
    assert _is_valid_content_length("6000001") is False
    assert _is_valid_content_length("²") is False
    assert _is_valid_content_length("١٢٣") is False
    assert _is_valid_content_length("-1") is False


@pytest.mark.parametrize("bad_length", ["6000001", "not-a-number", "-10", "+100", "12.34"])
def test_size_limit_middleware_rejects_oversized_or_invalid_content_length(
    bad_length: str,
) -> None:
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"content-length": bad_length})
        assert resp.status_code == 413
        assert resp.json() == {"detail": "Request exceeds 6 MB."}


def test_api_malformed_json_and_audit_unverified_fact_errors(
    demo_case: dict[str, Any],
) -> None:
    with TestClient(app) as client:
        malformed = client.post(
            "/api/assess",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert malformed.status_code == 422

        bad_audit = client.post(
            "/api/audit",
            json={**demo_case, "selected_ids": ["cad"], "bullets": ["anything"]},
        )
        assert bad_audit.status_code == 422
        assert "missing or unverified" in bad_audit.json()["detail"]


def test_pdf_check_oversized_upload_returns_413() -> None:
    oversized = b"%PDF-1.7\n" + (b"0" * 5_000_000)
    assert len(oversized) > 5_000_000
    with pytest.raises(HTTPException) as direct_exc:
        inspect_pdf(oversized)
    assert direct_exc.value.status_code == 413

    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf-check",
            files={"file": ("huge.pdf", oversized, "application/pdf")},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "PDF exceeds 5 MB."


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"plain text cv",
        b"%PDF-1.7\ncorrupt-stream-without-xref",
        make_pdf_bytes(["A" * 60], password="secret"),
        make_pdf_bytes(["A" * 60] * 21),
    ],
)
def test_pdf_check_rejects_non_pdf_corrupt_encrypted_and_over_page_limit(
    payload: bytes,
) -> None:
    with pytest.raises(HTTPException) as direct_exc:
        inspect_pdf(payload)
    assert direct_exc.value.status_code == 422

    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf-check",
            files={"file": ("bad.pdf", payload, "application/pdf")},
        )
        assert resp.status_code == 422


@pytest.mark.parametrize(
    ("page_texts", "expected_status", "expected_counts"),
    [
        ([], "needs_text_layer_review", []),
        (["   "], "needs_text_layer_review", [0]),
        (["A" * 50], "needs_text_layer_review", [50]),
        (["A" * 51], "text_layer_found", [51]),
        (["A" * 80, "B" * 50], "needs_text_layer_review", [80, 50]),
        (["A" * 51] * 20, "text_layer_found", [51] * 20),
    ],
)
def test_pdf_check_text_layer_threshold_and_zero_or_twenty_pages(
    page_texts: list[str],
    expected_status: str,
    expected_counts: list[int],
) -> None:
    pdf_bytes = make_pdf_bytes(page_texts)
    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf-check",
            files={"file": ("cv.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pages"] == len(expected_counts)
        assert body["characters_by_page"] == expected_counts
        assert body["status"] == expected_status
        assert body["stored"] is False


def test_pdf_check_closes_upload_file_even_when_read_fails() -> None:
    closed = False

    class FailingUpload(UploadFile):
        async def read(self, size: int = -1) -> bytes:
            raise OSError("Simulated stream failure")

        async def close(self) -> None:
            nonlocal closed
            closed = True

    upload = FailingUpload(filename="broken.pdf", file=BytesIO(b"%PDF-1.4"))
    with pytest.raises(OSError, match="Simulated stream failure"):
        asyncio.run(api_module.pdf_check(file=upload))
    assert closed is True


def test_pdf_check_does_not_block_async_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    entered_pdf = threading.Event()
    release_pdf = threading.Event()
    real_reader = PdfReader

    def slow_reader(stream: BytesIO) -> PdfReader:
        entered_pdf.set()
        release_pdf.wait(timeout=2.0)
        return real_reader(stream)

    monkeypatch.setattr(api_module, "PdfReader", slow_reader)
    valid_pdf = make_pdf_bytes(["A" * 60])

    async def run_concurrent() -> tuple[float, int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            pdf_task = asyncio.create_task(
                client.post(
                    "/api/pdf-check",
                    files={"file": ("cv.pdf", valid_pdf, "application/pdf")},
                )
            )
            await asyncio.to_thread(entered_pdf.wait, 1.0)
            t0 = time.perf_counter()
            health_resp = await client.get("/api/health")
            health_elapsed = time.perf_counter() - t0
            release_pdf.set()
            pdf_resp = await pdf_task
            return health_elapsed, health_resp.status_code, pdf_resp.status_code

    elapsed, health_code, pdf_code = asyncio.run(run_concurrent())
    assert health_code == 200
    assert pdf_code == 200
    assert elapsed < 0.5
