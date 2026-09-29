"""
Turning one PDF into pages of text.

Two rules carry the whole thing:

  * never OCR what the file already tells you - a page with a text layer is
    copied in milliseconds, a scanned page costs seconds;
  * read several pages at once - Tesseract is single-threaded per page, so the
    cores are the difference between 104 seconds and five minutes for a book.

The uploaded PDF is deleted once it has been read. The text is what this
service exists to produce; keeping the scan as well would fill the disk with
copies of books the portal already holds.
"""

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

import fitz

from . import config, library, ocr, pdfdoc, textnorm

# One book at a time (WORKERS), several pages of it at once (PAGE_WORKERS).
_books = ThreadPoolExecutor(max_workers=max(1, config.WORKERS), thread_name_prefix="book")


def read_book(book_id: str, file_path: str) -> None:
    """Runs in a worker thread; every outcome ends up on the book's meta."""
    library.set_state(book_id, "running")
    started = time.perf_counter()
    try:
        doc = pdfdoc.open_doc(file_path)
    except Exception as exc:  # a corrupt upload, or one with a password
        library.finish(book_id, "failed", f"cannot open the PDF: {exc}")
        _forget(file_path)
        return

    try:
        # Pass one: the pages the PDF can read out itself, and the list of the
        # ones it cannot.
        to_ocr = []
        for pt in pdfdoc.page_texts(doc):
            if pt.chars >= config.TEXT_LAYER_MIN_CHARS:
                library.add_page(book_id, library.Page(
                    page_no=pt.page_no, source="text",
                    chars=len(pt.text.strip()), seconds=0.0,
                    text=textnorm.normalise(pt.text)))
            else:
                to_ocr.append(pt.page_no)

        if to_ocr and not ocr.engine.available:
            library.finish(
                book_id, "needs_ocr",
                f"{len(to_ocr)} pages are pictures and no OCR engine is installed here.")
            return

        if config.OCR_PAGE_CAP:
            for page_no in to_ocr[config.OCR_PAGE_CAP:]:
                # Recorded as skipped rather than dropped, so the page numbers
                # still line up with the printed book.
                library.add_page(book_id, library.Page(
                    page_no=page_no, source="skipped", chars=0, seconds=0.0, text=""))
            to_ocr = to_ocr[:config.OCR_PAGE_CAP]

        # The invisible text layer of each page read, kept to build the
        # readable PDF once the whole book is done.
        layers: Dict[int, bytes] = {}
        guard = threading.Lock()

        def read_page(page_no: int) -> None:
            png = pdfdoc.render_png(doc, page_no)
            result, layer = ocr.engine.run_both(png)
            text = textnorm.normalise(result.text)
            library.add_page(book_id, library.Page(
                page_no=page_no, source="ocr", chars=len(text.strip()),
                seconds=result.seconds, text=text))
            if layer:
                with guard:
                    layers[page_no] = layer

        if to_ocr:
            with ThreadPoolExecutor(max_workers=max(1, config.PAGE_WORKERS)) as pages:
                list(pages.map(read_page, to_ocr))

        _write_readable_pdf(book_id, doc, file_path, layers)

        elapsed = round(time.perf_counter() - started, 1)
        library.finish(book_id, "ready", f"read in {elapsed}s")
    except Exception as exc:
        library.finish(book_id, "failed", str(exc)[:500])
    finally:
        doc.close()
        _forget(file_path)


def _write_readable_pdf(book_id: str, doc, file_path: str, layers: Dict[int, bytes]) -> None:
    """
    The scan with its words behind it, saved beside the text.

    The pages are left exactly as they were uploaded and only the invisible
    text is laid over them: a PDF rebuilt from pictures of the pages is seven
    times the size and no clearer. A PDF that already carried its text is
    copied as it is - it is already readable, and re-saving it would only
    change the bytes.
    """
    target = library.folder(book_id) / "readable.pdf"
    try:
        if not layers:
            shutil.copyfile(file_path, target)
            return
        for page_no, layer in layers.items():
            with fitz.open("pdf", layer) as text_pdf:
                page = doc.load_page(page_no - 1)
                page.show_pdf_page(page.rect, text_pdf, 0, overlay=True)
        doc.save(str(target), deflate=True, garbage=3)
    except Exception as exc:
        # Worth nothing on its own: the text is the product, and a teacher who
        # cannot download the PDF still has the words.
        print(f"readable pdf for {book_id} failed: {exc}")


def _forget(file_path: str) -> None:
    """The scan has given up its words; there is no reason to keep it."""
    try:
        Path(file_path).unlink(missing_ok=True)
    except Exception:
        pass


def submit(book_id: str, file_path: str) -> None:
    _books.submit(read_book, book_id, file_path)


def queue_depth() -> Optional[int]:
    try:
        return _books._work_queue.qsize()  # good enough for a health line
    except Exception:
        return None
