"""
Making OCR output comparable to text people type.

Tesseract writes Malayalam in the older encoding: a chillu letter comes out as
consonant + virama + zero-width JOINER (ല്‍), while a teacher's keyboard and the
syllabus in the portal's database produce the single modern character (ൽ). The
two look identical on screen and never match in a search, so every string that
leaves this service is normalised the same way.

The joiner is the whole distinction and it is easy to get wrong: consonant +
virama + zero-width NON-joiner is not a chillu at all, it is an ordinary word
final chandrakkala (കാറ്റ്). Converting those too turns കടലാണ് into കടലാൺ - a
different word, and one the book never contains.
"""

import re
import unicodedata

ZWNJ = "‌"
ZWJ = "‍"
VIRAMA = "്"

# consonant + virama + ZWJ  ->  the atomic chillu
CHILLU = {
    "ണ": "ൺ",  # ണ -> ൺ
    "ന": "ൻ",  # ന -> ൻ
    "ര": "ർ",  # ര -> ർ
    "ല": "ൽ",  # ല -> ൽ
    "ള": "ൾ",  # ള -> ൾ
    "ക": "ൿ",  # ക -> ൿ
}

_CHILLU_RE = re.compile("([" + "".join(CHILLU) + "])" + VIRAMA + ZWJ)
_SPACE_RE = re.compile(r"[ \t ]+")
_BLANK_RE = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    """Modern chillus, no stray joiners, tidy whitespace, NFC."""
    if not text:
        return ""
    text = _CHILLU_RE.sub(lambda m: CHILLU[m.group(1)], text)
    text = text.replace(ZWNJ, "").replace(ZWJ, "")
    text = unicodedata.normalize("NFC", text)
    text = _SPACE_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def compare_key(text: str) -> str:
    """
    A harsher form, for measuring accuracy only.

    Line breaks and hyphenation differ between a printed page and any
    transcription of it, and counting those as errors tells you nothing about
    whether the OCR read the letters.
    """
    text = normalise(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
