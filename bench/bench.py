"""
Performance bench for the book pipeline.

Answers the two questions that decide whether OCR is worth building on:
how long does a real book take, and is what comes back actually readable.

    python -m bench.bench "C:\\path\\book.pdf" --pages 6 --dpi 300 --langs mal+eng

It samples pages spread across the book rather than the first N, because the
first pages of a textbook are covers and contents - the easy ones.
"""

import argparse
import json
import statistics
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, ocr, pdfdoc  # noqa: E402

MALAYALAM = range(0x0D00, 0x0D80)


def script_mix(text: str) -> dict:
    """
    A cheap read on quality when there is no ground truth.

    On a Malayalam page, good OCR is overwhelmingly Malayalam letters with a
    little Latin for the English terms. A page that comes back mostly Latin
    letters or punctuation is noise, whatever its length.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return {"letters": 0, "malayalam": 0.0, "latin": 0.0, "other": 0.0}
    mal = sum(1 for c in letters if ord(c) in MALAYALAM)
    lat = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return {
        "letters": len(letters),
        "malayalam": round(mal / len(letters), 3),
        "latin": round(lat / len(letters), 3),
        "other": round((len(letters) - mal - lat) / len(letters), 3),
    }


def sample_pages(total: int, want: int) -> list:
    if want >= total:
        return list(range(1, total + 1))
    step = total / (want + 1)
    return [max(1, min(total, round(step * (i + 1)))) for i in range(want)]


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR performance bench")
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=6, help="how many pages to sample")
    ap.add_argument("--dpi", default="300", help="comma separated, e.g. 200,300,400")
    ap.add_argument("--psm", default="6", help="comma separated Tesseract page-segmentation modes")
    ap.add_argument("--langs", default=config.OCR_LANGS)
    ap.add_argument("--out", default="", help="directory to write the OCR text into")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"no such file: {pdf}")
        return 2

    print(f"file      : {pdf.name}  ({pdf.stat().st_size / 1e6:.1f} MB)")
    t0 = time.perf_counter()
    report = pdfdoc.scan(str(pdf))
    scan_seconds = time.perf_counter() - t0
    print(f"pages     : {report.pages}")
    print(f"verdict   : {report.verdict}  (text layer: {report.chars_per_page} chars/page, "
          f"{report.text_pages} text pages, {report.image_pages} image pages)")
    print(f"scan time : {scan_seconds:.2f}s for the whole file "
          f"({scan_seconds / max(1, report.pages) * 1000:.0f} ms/page)")

    if report.verdict == "text":
        print("\nThis PDF carries its own text. No OCR needed - the whole book is "
              f"readable in about {scan_seconds:.1f}s.")
        return 0

    print(f"\nocr engine: {ocr.engine.name} {ocr.engine.version() or '(not installed)'}")
    if not ocr.engine.available:
        print("Tesseract is not installed, so only the scan above could be measured.")
        return 1
    langs = ocr.engine.languages()
    print(f"models    : {', '.join(langs) or 'none'}")
    for want in args.langs.split("+"):
        if want not in langs:
            print(f"  ! '{want}' is NOT installed - results below will be wrong for that script")

    doc = pdfdoc.open_doc(str(pdf))
    pages = sample_pages(report.pages, args.pages)
    print(f"\nsampling pages: {pages}")

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for dpi in [int(d) for d in args.dpi.split(",")]:
        for psm in [int(p) for p in args.psm.split(",")]:
            renders, ocrs, chars, mixes = [], [], [], []
            for page_no in pages:
                t = time.perf_counter()
                png = pdfdoc.render_png(doc, page_no, dpi=dpi)
                renders.append(time.perf_counter() - t)
                res = ocr.engine.run(png, lang=args.langs, psm=psm)
                ocrs.append(res.seconds)
                chars.append(len(res.text.strip()))
                mixes.append(script_mix(res.text))
                if out_dir:
                    name = f"dpi{dpi}_psm{psm}_p{page_no:03d}.txt"
                    (out_dir / name).write_text(res.text, encoding="utf-8")

            per_page = statistics.median(r + o for r, o in zip(renders, ocrs))
            row = {
                "dpi": dpi,
                "psm": psm,
                "render_s": round(statistics.median(renders), 2),
                "ocr_s": round(statistics.median(ocrs), 2),
                "page_s": round(per_page, 2),
                "chars": int(statistics.median(chars)),
                "malayalam": round(statistics.median(m["malayalam"] for m in mixes), 3),
                "book_minutes": round(per_page * report.image_pages / 60, 1),
            }
            results.append(row)
            print(f"  dpi={dpi:<4} psm={psm:<2} render {row['render_s']:>5.2f}s  "
                  f"ocr {row['ocr_s']:>6.2f}s  = {row['page_s']:>6.2f}s/page  "
                  f"{row['chars']:>5} chars  malayalam {row['malayalam']:.0%}  "
                  f"-> whole book ~{row['book_minutes']} min")

    doc.close()
    if out_dir:
        (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\ntext written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
