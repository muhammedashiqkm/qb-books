"""
Settings for the book-text service.

Everything comes from the environment, so the same image runs on a laptop and
on the server without an edit. The defaults are what a developer wants.
"""

import os
from pathlib import Path

BASE_DIR = Path(os.getenv("QB_BOOKS_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(os.getenv("QB_BOOKS_DATA", BASE_DIR / "data"))

# A read book: data/books/<id>/{meta.json,pages.json}. No database.
BOOKS_DIR = DATA_DIR / "books"

# The uploaded PDF, held only while it is being read and deleted afterwards:
# the text is the thing worth keeping, and a textbook is tens of megabytes.
UPLOAD_DIR = DATA_DIR / "incoming"

# Where the service listens. THE one place the port is set: run.ps1, the
# container's command and its health check all start `python -m app`, and the
# compose file reads QB_BOOKS_PORT from .env for the published mapping. The
# portal's own appsettings.json holds the matching URL - a different
# application, and the only other copy.
HOST = os.getenv("QB_BOOKS_HOST", "127.0.0.1")
PORT = int(os.getenv("QB_BOOKS_PORT", "8081"))

# The portal is the only caller. A shared secret is enough to keep the rest of
# the network out; leave it unset in development and the check is skipped.
API_KEY = os.getenv("QB_BOOKS_API_KEY", "").strip()

# Tesseract is a native program, not a Python package. On Windows it is not on
# PATH after the usual installer, so the common location is tried as well.
TESSERACT_EXE = os.getenv("QB_BOOKS_TESSERACT", "").strip() or None
TESSERACT_FALLBACKS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
)
# Where the language files live, when they are not beside the binary.
TESSDATA_PREFIX = os.getenv("QB_BOOKS_TESSDATA", "").strip() or None

# Every model named here reads every page - the setting is the work done per
# page, not a list of what the service could read. The real value lives in
# .env; this fallback is the pair that is present in any install, so a run
# without .env still reads the course books rather than failing on a model
# that was never downloaded.
OCR_LANGS = os.getenv("QB_BOOKS_OCR_LANGS", "mal+eng")

# 300 DPI is the resolution Tesseract is trained for. Lower loses the small
# Malayalam vowel signs; higher costs time for nothing.
RENDER_DPI = int(os.getenv("QB_BOOKS_DPI", "300"))

# Below this many characters, a page's text layer is treated as absent and the
# page goes to OCR. Scanned pages usually yield 0; a real page of a textbook
# holds well over a thousand.
TEXT_LAYER_MIN_CHARS = int(os.getenv("QB_BOOKS_MIN_CHARS", "120"))

# One book at a time. OCR is minutes per book, and letting two share the cores
# only makes both slower.
WORKERS = int(os.getenv("QB_BOOKS_WORKERS", "1"))

# Pages of one book read at once. Tesseract is single-threaded per page, so
# this is where the wall-clock time goes: on an 8-core box, 7 workers turn a
# 179-page book from 5 minutes into 104 seconds. Leave headroom for the rest of
# the machine rather than taking every core.
PAGE_WORKERS = int(os.getenv("QB_BOOKS_PAGE_WORKERS", str(max(1, (os.cpu_count() or 2) - 1))))

# A guard against a 900-page upload tying up the box for an hour. 0 = no cap.
OCR_PAGE_CAP = int(os.getenv("QB_BOOKS_OCR_PAGE_CAP", "0"))

# How many read books are kept before the oldest are dropped. Nothing here is a
# record: a book is uploaded, read, and taken away as text.
KEEP_BOOKS = int(os.getenv("QB_BOOKS_KEEP", "20"))

VERSION = "0.2.0"


def ensure_dirs() -> None:
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
