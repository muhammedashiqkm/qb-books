"""
Accuracy against a hand-typed page.

Speed is easy to measure and useless on its own: a fast model that misreads a
third of the letters produces questions about words that are not in the book.
This compares one OCR output with a transcription of the same lines and prints
the character error rate.

    python -m bench.accuracy truth.txt ocr.txt [ocr2.txt ...]

Both sides are normalised first (chillu forms, joiners, whitespace), because
those differences are encoding, not misreading.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.textnorm import compare_key  # noqa: E402


def infix_distance(truth: str, hyp: str) -> int:
    """
    Edit distance from the transcription to the closest run of the OCR page.

    The transcription covers a few lines, the OCR output covers the whole page,
    so the start and the end of the page are free: only the letters between
    them are counted. Anything else measures how much page was left over, not
    how well it was read.
    """
    previous = [0] * (len(hyp) + 1)          # any starting point is free
    for i, ct in enumerate(truth, 1):
        current = [i]
        for j, ch in enumerate(hyp, 1):
            current.append(min(
                previous[j] + 1,                   # delete from truth
                current[j - 1] + 1,                # insert from hypothesis
                previous[j - 1] + (ct != ch),      # substitute
            ))
        previous = current
    return min(previous)                     # any ending point is free


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    truth = compare_key(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(f"truth: {len(truth)} characters\n")
    for path in sys.argv[2:]:
        hyp = compare_key(Path(path).read_text(encoding="utf-8"))
        distance = infix_distance(truth, hyp)
        cer = distance / max(1, len(truth))
        print(f"{Path(path).parent.name:>10}/{Path(path).name:<24} "
              f"CER {cer:6.2%}   ({distance} edits over {len(truth)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
