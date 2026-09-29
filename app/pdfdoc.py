"""
Reading a PDF: its text layer, and pictures of its pages for OCR.

Named pdfdoc rather than pdf so it cannot shadow anything on sys.path.
"""

from dataclasses import dataclass
from typing import Iterator

import fitz  # PyMuPDF

from . import config


@dataclass
class PageText:
    page_no: int          # 1-based, as a reader counts
    text: str
    chars: int


@dataclass
class ScanReport:
    """What a PDF is, before a minute of OCR is spent finding out."""
    pages: int
    chars: int
    chars_per_page: float
    text_pages: int       # pages whose own text layer is usable
    image_pages: int      # pages that will need OCR
    encrypted: bool
    verdict: str          # "text" | "scanned" | "mixed"


def open_doc(path: str) -> fitz.Document:
    return fitz.open(path)


def page_texts(doc: fitz.Document) -> Iterator[PageText]:
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        yield PageText(page_no=i + 1, text=text, chars=len(text.strip()))


def scan(path: str) -> ScanReport:
    """
    Classify a PDF without OCR-ing it.

    This is the cheap question every upload asks: is the text already in the
    file (seconds of work), or is the file a stack of photographs (minutes)?
    """
    doc = open_doc(path)
    try:
        chars = 0
        text_pages = 0
        for pt in page_texts(doc):
            chars += pt.chars
            if pt.chars >= config.TEXT_LAYER_MIN_CHARS:
                text_pages += 1
        pages = doc.page_count
        image_pages = pages - text_pages
        if text_pages == 0:
            verdict = "scanned"
        elif image_pages == 0:
            verdict = "text"
        else:
            verdict = "mixed"
        return ScanReport(
            pages=pages,
            chars=chars,
            chars_per_page=round(chars / pages, 1) if pages else 0.0,
            text_pages=text_pages,
            image_pages=image_pages,
            encrypted=bool(doc.is_encrypted),
            verdict=verdict,
        )
    finally:
        doc.close()


def render_png(doc: fitz.Document, page_no: int, dpi: int = None) -> bytes:
    """One page as a PNG, at the resolution OCR wants."""
    page = doc.load_page(page_no - 1)
    pix = page.get_pixmap(dpi=dpi or config.RENDER_DPI, colorspace=fitz.csGRAY)
    return pix.tobytes("png")
