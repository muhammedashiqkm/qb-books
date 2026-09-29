"""
The HTTP face of the service: a PDF goes in, its text comes out.

Six endpoints, which is everything the portal's "Read a book" page uses:

    GET  /health            what this box can do right now
    POST /index             take a PDF, answer at once, read it in the background
    GET  /status/{id}       queued | running | ready | needs_ocr | failed
    GET  /text/{id}         the whole book as plain text
    GET  /pages/{id}        one page, or a range
    GET  /search/{id}?q=    which pages carry a phrase

It follows the shape the portal already knows from QB_AutoGen: one base URL in
the portal's configuration, no login of its own, a shared key instead. Reading
is a job, not a request - a scanned book is minutes of work.
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from . import config, library, ocr, pdfdoc, pipeline, textnorm

app = FastAPI(title="qb-books", version=config.VERSION)


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()


def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """No key configured means development; then anything is let through."""
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="bad or missing X-Api-Key")


@app.get("/health")
def health() -> dict:
    """
    What this box can actually do right now.

    The languages list is the one that matters in practice: without 'mal' a
    Malayalam book comes back as noise, and that is worth seeing before anyone
    uploads one.
    """
    return {
        "service": "qb-books",
        "version": config.VERSION,
        "ocr": {
            "engine": ocr.engine.name,
            "available": ocr.engine.available,
            "path": ocr.engine.exe or "",
            "version": ocr.engine.version(),
            "languages": ocr.engine.languages(),
            "configured_langs": config.OCR_LANGS,
        },
        "render_dpi": config.RENDER_DPI,
        "page_workers": config.PAGE_WORKERS,
        "queue": pipeline.queue_depth(),
    }


@app.post("/index", dependencies=[Depends(require_key)])
async def index(
    file: UploadFile = File(...),
    book_id: str = Form(default=""),
    title: str = Form(default=""),
) -> dict:
    """
    Take the PDF, answer at once, do the work in the background.

    The answer already says what the file is: a PDF carrying its own text is
    ready in about a second, a scan is minutes, and the caller can say which
    before it starts waiting.
    """
    book_id = (book_id or "").strip() or uuid.uuid4().hex
    path = _save_upload(file, book_id)
    report = pdfdoc.scan(str(path))
    library.create(
        book_id=book_id,
        title=title or Path(file.filename or "").stem,
        pages=report.pages,
        verdict=report.verdict,
        ocr_pages=report.image_pages,
    )
    pipeline.submit(book_id, str(path))
    return {
        "book_id": book_id,
        "state": "queued",
        "pages": report.pages,
        "verdict": report.verdict,
        "pages_needing_ocr": report.image_pages,
        "ocr_available": ocr.engine.available,
    }


@app.get("/status/{book_id}", dependencies=[Depends(require_key)])
def status(book_id: str) -> dict:
    book = library.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="unknown book")
    meta = book.meta()
    meta["progress"] = round(book.done_pages / book.pages, 3) if book.pages else 0.0
    return meta


@app.get("/text/{book_id}", dependencies=[Depends(require_key)])
def text(book_id: str, markers: bool = True) -> PlainTextResponse:
    """
    The whole book as plain text - the form an AI can actually read.

    A scanned PDF is a stack of pictures and no chat can read a word of it;
    this is the same book at a fortieth of the size, in UTF-8. Page markers are
    kept by default so any passage can be traced back to the printed page.
    """
    book = library.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="unknown book")
    if book.state not in ("ready", "needs_ocr"):
        raise HTTPException(status_code=409, detail=f"not ready: {book.state}")

    lines = []
    if markers:
        lines.append(book.title)
        lines.append(f"{book.pages} pages, {book.chars:,} characters")
    for page in library.pages(book_id):
        if markers:
            lines.append("")
            lines.append(f"===== page {page.page_no} ({page.source}, {page.chars} chars) =====")
        lines.append(page.text)

    return PlainTextResponse(
        "\n".join(lines).strip() + "\n",
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{book_id}.txt"'},
    )


@app.get("/pdf/{book_id}", dependencies=[Depends(require_key)])
def readable_pdf(book_id: str) -> FileResponse:
    """
    The book as a PDF anyone can read: the original pages, with the recovered
    words laid invisibly over them.

    Built while the book was read, not on demand - the pages are open then, and
    doing it later would mean reading the whole scan a second time.
    """
    book = library.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="unknown book")
    path = library.folder(book_id) / "readable.pdf"
    if not path.exists():
        raise HTTPException(status_code=409, detail=f"no readable PDF yet: {book.state}")
    return FileResponse(path, media_type="application/pdf", filename=f"{book_id}.pdf")


@app.get("/pages/{book_id}", dependencies=[Depends(require_key)])
def pages(book_id: str, first: int = 1, last: int = 10 ** 6, text: bool = True) -> dict:
    if not library.get(book_id):
        raise HTTPException(status_code=404, detail="unknown book")
    rows = []
    for page in library.pages(book_id, first, last):
        row = {"page_no": page.page_no, "source": page.source, "chars": page.chars}
        if text:
            row["text"] = page.text
        rows.append(row)
    return {"book_id": book_id, "pages": rows}


@app.get("/search/{book_id}", dependencies=[Depends(require_key)])
def search(book_id: str, q: str, limit: int = 10) -> dict:
    """
    Which pages carry a phrase.

    The query is normalised the same way the text was, or a word typed with a
    modern chillu would never match what OCR wrote the older way - the two look
    identical on screen and differ in every byte.
    """
    if not library.get(book_id):
        raise HTTPException(status_code=404, detail="unknown book")
    needle = textnorm.compare_key(q)
    if not needle:
        return {"book_id": book_id, "q": q, "hits": []}

    hits = []
    for page in library.pages(book_id):
        if needle in textnorm.compare_key(page.text):
            hits.append({
                "page_no": page.page_no,
                "source": page.source,
                "chars": page.chars,
                "snippet": page.text[:400],
            })
            if len(hits) >= max(1, min(limit, 50)):
                break
    return {"book_id": book_id, "q": q, "hits": hits}


def _save_upload(file: UploadFile, book_id: str) -> Path:
    """
    The upload, held only until it has been read.

    Named after the book so a retry replaces it, and deleted by the pipeline
    when the text is out - see pipeline._forget.
    """
    config.ensure_dirs()
    path = config.UPLOAD_DIR / f"{book_id}.pdf"
    with path.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            out.write(chunk)
    return path
