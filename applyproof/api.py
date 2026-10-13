from io import BytesIO
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from .models import Case, Draft, Audit
from .engine import assess, build_draft, audit_draft, markdown

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title='ApplyProof', docs_url=None, redoc_url=None)

@app.middleware('http')
async def size_limit(request: Request, call_next):
    length = request.headers.get('content-length')
    if length and (not length.isdigit() or int(length) > 6_000_000):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Request exceeds 6 MB.'}, status_code=413)
    return await call_next(request)

@app.get('/api/health')
def health():
    return {'status':'ok', 'version':'0.1.0'}

@app.get('/api/demo')
def demo():
    return json.loads((ROOT / 'examples/demo.json').read_text(encoding='utf-8'))

@app.post('/api/assess')
def assessment(case: Case):
    return assess(case)

@app.post('/api/draft')
def draft(case: Draft):
    try:
        result = build_draft(case)
        result['markdown'] = markdown(result)
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/audit')
def audit(case: Audit):
    try:
        return audit_draft(case)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/pdf-check')
async def pdf_check(file: UploadFile = File(...)):
    data = await file.read(5_000_001)
    await file.close()
    if len(data) > 5_000_000:
        raise HTTPException(413, 'PDF exceeds 5 MB.')
    if not data.startswith(b'%PDF-'):
        raise HTTPException(422, 'Expected a PDF file.')
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError('Unlock the PDF locally first.')
        if len(reader.pages) > 20:
            raise ValueError('Limit is 20 pages.')
        counts = [len((page.extract_text() or '').strip()) for page in reader.pages]
    except Exception as exc:
        raise HTTPException(422, 'Cannot inspect PDF. Use an unencrypted, valid PDF with at most 20 pages.') from exc
    return {'pages': len(counts), 'characters_by_page': counts,
            'status': 'text_layer_found' if counts and all(n > 50 for n in counts) else 'needs_text_layer_review',
            'stored': False, 'note': 'Text-layer check only. It does not measure ATS ranking or layout quality.'}

dist = ROOT / 'frontend/dist'
if dist.is_dir():
    app.mount('/', StaticFiles(directory=dist, html=True), name='ui')
