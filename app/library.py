"""
Where a read book is kept: one folder, two JSON files. No database.

    data/books/<book_id>/meta.json    what it is and how far it got
    data/books/<book_id>/pages.json   the text, page by page

There was a SQLite schema here once, with connections, a lock, upserts and a
migration to think about - all of it for data that is written once, read whole,
and thrown away. Files do that with nothing to keep in step, and a folder can
be read, copied or deleted by anyone looking at the disk.

A book being read lives in memory while it is worked on; the pages are written
once, at the end, so a long OCR run is not a thousand small writes.
"""

import json
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from . import config


@dataclass
class Page:
    page_no: int           # 1-based, as a reader counts
    source: str            # 'text' (the PDF's own) or 'ocr'
    chars: int
    seconds: float
    text: str


@dataclass
class Book:
    id: str
    title: str = ""
    pages: int = 0
    state: str = "queued"      # queued | running | ready | needs_ocr | failed
    verdict: str = ""          # scanned | text | mixed
    ocr_pages: int = 0
    done_pages: int = 0
    chars: int = 0
    seconds: float = 0.0
    error: str = ""
    # The models this book is read with, e.g. "mal+eng". Every model named
    # here reads every page, so this is the book's cost as much as its
    # language: nine models are seven times the work of two.
    langs: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def meta(self) -> Dict[str, Any]:
        return asdict(self)


_lock = threading.Lock()
_books: Dict[str, Book] = {}
_pages: Dict[str, List[Page]] = {}


def _folder(book_id: str):
    return config.BOOKS_DIR / book_id


def folder(book_id: str):
    """The book's folder, for whoever writes the readable PDF into it."""
    path = _folder(book_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_meta(book: Book) -> None:
    folder = _folder(book.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(
        json.dumps(book.meta(), ensure_ascii=False, indent=1), encoding="utf-8")


def create(book_id: str, title: str, pages: int, verdict: str, ocr_pages: int,
           langs: str = "") -> Book:
    """Starts a book afresh, dropping anything an earlier run left."""
    with _lock:
        shutil.rmtree(_folder(book_id), ignore_errors=True)
        book = Book(id=book_id, title=title, pages=pages, verdict=verdict,
                    ocr_pages=ocr_pages, langs=langs)
        _books[book_id] = book
        _pages[book_id] = []
        _write_meta(book)
    prune()
    return book


def set_state(book_id: str, state: str, error: str = "") -> None:
    with _lock:
        book = _books.get(book_id)
        if not book:
            return
        book.state = state
        book.error = error
        book.updated_at = time.time()
        _write_meta(book)


def add_page(book_id: str, page: Page) -> None:
    """One page of a book being read. Kept in memory until the book is done."""
    with _lock:
        book = _books.get(book_id)
        if not book:
            return
        _pages.setdefault(book_id, []).append(page)
        book.done_pages += 1
        book.chars += page.chars
        book.seconds += page.seconds
        book.updated_at = time.time()
        # The meta is what /status reads, so it is written as the work goes;
        # the pages wait for finish(), where they are written in one go.
        _write_meta(book)


def finish(book_id: str, state: str, error: str = "") -> None:
    """Writes the pages out and marks the book done."""
    with _lock:
        book = _books.get(book_id)
        if not book:
            return
        # Sorted IN PLACE, not just on the way to the file. Seven workers
        # finish pages out of order, so the list is in completion order - and
        # everything served before the next restart (the text, a search, a
        # page) would come back shuffled while the file on disk looked right.
        pages = sorted(_pages.get(book_id, []), key=lambda p: p.page_no)
        _pages[book_id] = pages
        folder = _folder(book_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pages.json").write_text(
            json.dumps([asdict(p) for p in pages], ensure_ascii=False), encoding="utf-8")
        book.state = state
        book.error = error
        book.updated_at = time.time()
        _write_meta(book)


def get(book_id: str) -> Optional[Book]:
    """A book from memory, or from its folder after a restart."""
    with _lock:
        book = _books.get(book_id)
        if book:
            return book
    meta = _folder(book_id) / "meta.json"
    if not meta.exists():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        book = Book(**data)
    except Exception:
        return None
    with _lock:
        _books[book_id] = book
    return book


def pages(book_id: str, first: int = 1, last: int = 10 ** 6) -> List[Page]:
    """The book's pages, loaded from disk the first time they are asked for."""
    with _lock:
        loaded = _pages.get(book_id)
    if loaded is None:
        path = _folder(book_id) / "pages.json"
        loaded = []
        if path.exists():
            try:
                loaded = [Page(**row) for row in json.loads(path.read_text(encoding="utf-8"))]
            except Exception:
                loaded = []
        with _lock:
            _pages[book_id] = loaded
    # Defensive: a book still being read is asked about too, and its pages
    # arrive in whatever order the workers finished them.
    return sorted((p for p in loaded if first <= p.page_no <= last), key=lambda p: p.page_no)


def prune() -> None:
    """
    Keeps the most recent books and removes the rest.

    Nothing here is a record - a book is uploaded, read and taken away as text.
    Without this the folder grows for the life of the service.
    """
    keep = max(1, config.KEEP_BOOKS)
    folders = [f for f in config.BOOKS_DIR.glob("*") if f.is_dir()]
    if len(folders) <= keep:
        return
    folders.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    for old in folders[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        with _lock:
            _books.pop(old.name, None)
            _pages.pop(old.name, None)
