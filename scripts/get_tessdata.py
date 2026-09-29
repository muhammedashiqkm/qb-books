"""
Fetch Tesseract language models into the project, not into Program Files.

Two reasons: writing next to the binary needs an administrator, and keeping the
models here lets the service pin the exact ones it was tested with. Point
QB_BOOKS_TESSDATA at the folder this writes.

    python scripts/get_tessdata.py mal eng --flavour best

"best" is the slow, accurate LSTM model; "fast" is the quantised one. For
Indic scripts the gap is large enough to be worth measuring both.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

REPOS = {
    "best": "https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata",
    "fast": "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata",
    "std": "https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata",
}

ROOT = Path(__file__).resolve().parent.parent


def fetch(lang: str, flavour: str) -> Path:
    target_dir = ROOT / "data" / "tessdata" / flavour
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{lang}.traineddata"
    if target.exists() and target.stat().st_size > 100_000:
        print(f"  have {flavour}/{lang} ({target.stat().st_size / 1e6:.1f} MB)")
        return target
    url = REPOS[flavour].format(lang=lang)
    print(f"  get  {flavour}/{lang} <- {url}")
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as out:
        out.write(response.read())
    print(f"       {target.stat().st_size / 1e6:.1f} MB")
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("langs", nargs="+")
    ap.add_argument("--flavour", default="best", choices=sorted(REPOS))
    args = ap.parse_args()
    for lang in args.langs:
        fetch(lang, args.flavour)
    print(f"\nTESSDATA_PREFIX -> {ROOT / 'data' / 'tessdata' / args.flavour}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
