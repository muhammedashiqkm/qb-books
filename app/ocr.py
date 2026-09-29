"""
OCR, behind one small interface.

Tesseract is the engine here: it is free, runs offline on the CPU, and is the
only one of the offline engines that ships a Malayalam model. The interface is
kept narrow so a second engine can be added later without the rest of the
service knowing.
"""

import io
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional

from . import config


@dataclass
class OcrResult:
    text: str
    seconds: float
    engine: str
    lang: str


def _find_binary() -> Optional[str]:
    if config.TESSERACT_EXE and os.path.exists(config.TESSERACT_EXE):
        return config.TESSERACT_EXE
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in config.TESSERACT_FALLBACKS:
        if os.path.exists(candidate):
            return candidate
    return None


class Tesseract:
    """A thin wrapper: find the binary, report what it can do, run it."""

    name = "tesseract"

    def __init__(self) -> None:
        self.exe = _find_binary()
        self._version: Optional[str] = None
        self._langs: Optional[List[str]] = None

    @property
    def available(self) -> bool:
        return self.exe is not None

    def _run(self, args: List[str]) -> str:
        env = dict(os.environ)
        if config.TESSDATA_PREFIX:
            env["TESSDATA_PREFIX"] = config.TESSDATA_PREFIX
        out = subprocess.run(
            [self.exe] + args, capture_output=True, text=True, env=env,
            encoding="utf-8", errors="replace",
        )
        return (out.stdout or "") + (out.stderr or "")

    def version(self) -> str:
        if not self.available:
            return ""
        if self._version is None:
            first = self._run(["--version"]).splitlines()
            self._version = first[0].strip() if first else "unknown"
        return self._version

    def languages(self) -> List[str]:
        """The models installed. Malayalam ('mal') is the one that matters here."""
        if not self.available:
            return []
        if self._langs is None:
            lines = self._run(["--list-langs"]).splitlines()
            self._langs = [ln.strip() for ln in lines[1:] if ln.strip() and " " not in ln.strip()]
        return self._langs

    def run_both(self, png: bytes, lang: str = None, psm: int = 6):
        """
        The page read once, answered twice: its text, and the same text as an
        invisible PDF layer.

        One recognition pass for both - asking Tesseract for the text and then
        for the layer would read every page twice and double the wall clock of
        a book. The layer carries no picture (textonly_pdf): it is laid over
        the original page, and re-encoding the scan would only make the file
        several times larger for nothing.
        """
        if not self.available:
            raise RuntimeError("Tesseract is not installed or not found on this machine.")
        env = dict(os.environ)
        if config.TESSDATA_PREFIX:
            env["TESSDATA_PREFIX"] = config.TESSDATA_PREFIX

        with tempfile.TemporaryDirectory(prefix="qbpage") as folder:
            page = os.path.join(folder, "page.png")
            with open(page, "wb") as out:
                out.write(png)
            base = os.path.join(folder, "out")

            started = time.perf_counter()
            proc = subprocess.run(
                [self.exe, page, base, "-l", lang or config.OCR_LANGS, "--psm", str(psm),
                 "-c", "textonly_pdf=1", "txt", "pdf"],
                capture_output=True, env=env,
            )
            seconds = time.perf_counter() - started
            if proc.returncode != 0:
                message = (proc.stderr or b"").decode("utf-8", "replace").strip()
                raise RuntimeError(f"tesseract failed: {message[:400]}")

            text = ""
            if os.path.exists(base + ".txt"):
                with open(base + ".txt", "rb") as f:
                    text = f.read().decode("utf-8", "replace")
            layer = b""
            if os.path.exists(base + ".pdf"):
                with open(base + ".pdf", "rb") as f:
                    layer = f.read()

        return OcrResult(text=text, seconds=seconds, engine=self.name, lang=lang or config.OCR_LANGS), layer

    def run(self, png: bytes, lang: str = None, psm: int = 6) -> OcrResult:
        """
        Read one page image.

        psm 6 ("a single uniform block of text") beats the default on book
        pages: the default hunts for columns and, on a page that is one
        column, invents them and scrambles the reading order.
        """
        if not self.available:
            raise RuntimeError("Tesseract is not installed or not found on this machine.")
        lang = lang or config.OCR_LANGS
        env = dict(os.environ)
        if config.TESSDATA_PREFIX:
            env["TESSDATA_PREFIX"] = config.TESSDATA_PREFIX

        started = time.perf_counter()
        proc = subprocess.run(
            [self.exe, "stdin", "stdout", "-l", lang, "--psm", str(psm)],
            input=png, capture_output=True, env=env,
        )
        seconds = time.perf_counter() - started
        if proc.returncode != 0:
            message = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"tesseract failed: {message[:400]}")
        text = (proc.stdout or b"").decode("utf-8", "replace")
        return OcrResult(text=text, seconds=seconds, engine=self.name, lang=lang)


engine = Tesseract()
