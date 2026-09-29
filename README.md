# qb-books

A PDF goes in, its text comes out.

A scanned book is a stack of photographs: nothing can quote it, search it, or
hand it to an AI chat. This reads the pictures — 179 pages of Malayalam in 104
seconds — and answers with the words, page by page.

It is a **separate service** and stays one: the tools are Python's (PyMuPDF,
Tesseract), the work is minutes of CPU per book, and neither belongs inside a
web request or in a portal's publish output. The portal reaches it the way it
reaches QB_AutoGen — one base URL in configuration, no login of its own, an
optional shared key.

**No AI service is involved.** Tesseract is a 5 MB local model file. The book
never leaves the machine it is read on.

## Endpoints

| Method | Path | What it is for |
|---|---|---|
| GET | `/health` | engine, version, **which language models are installed** |
| POST | `/index` | take a PDF, answer at once, read it in the background |
| GET | `/status/{id}` | `queued / running / ready / needs_ocr / failed`, with progress |
| GET | `/text/{id}` | the whole book as plain text, with page markers |
| GET | `/pages/{id}?first=&last=` | one page, or a range |
| GET | `/search/{id}?q=` | which pages carry a phrase |

That is the whole API, and it is exactly what the portal's **Read a book** page
(`/curriculum/book-text`) uses.

## No database

A read book is a folder:

```
data/books/<book_id>/meta.json     what it is and how far it got
data/books/<book_id>/pages.json    the text, page by page
```

There was a SQLite schema here once — connections, a lock, upserts, a migration
to keep in mind — for data that is written once, read whole and thrown away.
Files do that with nothing to keep in step, and a folder can be read, copied or
deleted by anyone looking at the disk.

The uploaded PDF is **deleted once it has been read**: the text is the product,
and the portal already holds the book. Old books are pruned to the most recent
`QB_BOOKS_KEEP` (20), because nothing here is a record.

## One place for the port

`.env` at the project root - copy `.env.example` to `.env` on a new machine;
the live file is not in the repository, because it is where the shared key
goes. The service reads it through `config.PORT`, compose
uses it for the published mapping, the container's health check follows it, and
`run.ps1` loads the same file:

```ini
QB_BOOKS_PORT=8081
```

Changing that one line moves everything. The portal's `appsettings.json` holds
the matching URL under `QbBooks` — a different application, and the only other
copy of the number.

## Run it with Docker

```bash
docker compose up --build -d
curl http://127.0.0.1:8081/health      # or whatever QB_BOOKS_PORT says
```

Compose publishes on `127.0.0.1` on purpose — this holds whole textbooks and
has no login of its own. Put it on a public interface only behind a firewall
rule, and set `QB_BOOKS_API_KEY` (the portal's `QbBooksApiKey` must match).
Read books live in the `qb-books-data` volume.

The image installs Tesseract from Debian and fetches the language models at
build time, so the versions are pinned to what this was measured with rather
than to whatever the host happens to have.

## Run it without Docker

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

winget install --id UB-Mannheim.TesseractOCR -e          # the engine
.\.venv\Scripts\python.exe scripts\get_tessdata.py mal eng --flavour fast

.\run.ps1                                                 # http://127.0.0.1:8081
```

Settings, all via environment (or `.env`): `QB_BOOKS_PORT` (8081),
`QB_BOOKS_HOST`, `QB_BOOKS_OCR_LANGS` (`mal+eng`), `QB_BOOKS_DPI`
(300), `QB_BOOKS_PAGE_WORKERS` (cores − 1), `QB_BOOKS_KEEP` (20),
`QB_BOOKS_API_KEY`, `QB_BOOKS_DATA`, `QB_BOOKS_TESSERACT`, `QB_BOOKS_TESSDATA`,
`QB_BOOKS_OCR_PAGE_CAP`.

## Measured on real books

*Malayala Sahithyaswadanam* (Calicut University BSc Malayalam), 179 pages,
17.6 MB, **fully scanned — no text layer at all**. 8-core laptop, CPU only.

| Step | Result |
|---|---|
| Deciding what the PDF is | 0.2 s for the whole file — "scanned, 179 image pages" |
| OCR, `fast` models, 300 dpi | 2.1 s/page on one core |
| OCR, `best` models, 300 dpi | 7.6 s/page on one core |
| 7 workers, whole book end to end | **104 s**, 312,634 characters |
| Accuracy vs a typed page (`fast`) | **0.0 % CER** (0 edits in 349 characters) |
| Accuracy (`best`) | 0.6 % CER |
| Output | 98 % Malayalam letters, median 2,013 chars/page |

Two more books read the same way: *Sahithyavicharam* 152 pages in 110 s,
*Sahithyanusheelanam* 161 pages in 110 s.

### What the numbers say

* **A scanned Malayalam textbook is not a problem.** Under two minutes a book,
  offline, free.
* **Use the `fast` models, not `best`.** 3.6× quicker and, on these books, no
  less accurate.
* **300 dpi is the sweet spot.** 200 saved nothing, 400 cost 25 % more time for
  the same text.
* **Cores, not resolution, decide the wall clock.** One page is single-threaded;
  seven at once turned 5 minutes into 104 seconds.
* **Normalisation is not optional.** Tesseract writes chillu letters the legacy
  way (`ല` + virama + ZWJ); a keyboard writes `ൽ`. Without `textnorm.py` every
  Malayalam search returns nothing — which is exactly what happened here before
  it was fixed. Note the trap: consonant + virama + ZWNJ is **not** a chillu,
  it is a word-final chandrakkala, and converting it turns `കടലാണ്` into
  `കടലാൺ`.

## Bench

```powershell
# speed and script mix over pages sampled across a book
.\.venv\Scripts\python.exe -m bench.bench "C:\path\book.pdf" --pages 5 --dpi 300 --out out\run

# accuracy against a page typed by hand
.\.venv\Scripts\python.exe -m bench.accuracy bench\truth\p030.txt out\run\dpi300_psm6_p030.txt
```

`bench.accuracy` aligns the transcription against the best-matching run of the
OCR page, so the rest of the page is not counted as errors.
