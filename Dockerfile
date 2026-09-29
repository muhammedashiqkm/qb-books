# qb-books: a PDF goes in, its text comes out.
#
# Tesseract is a native program, so it is installed from the distribution
# rather than pip. The language models are fetched at build time into the image
# instead of being taken from the system folder: the versions are then pinned
# to what this service was measured with, and nothing depends on what happens
# to be installed on the host.

FROM python:3.12-slim

# tesseract-ocr is the engine; the models come below. No recommended extras -
# they pull in a desktop's worth of fonts and X libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts scripts
# "fast" on purpose: on a real Malayalam textbook it read 3.6x quicker than
# "best" and no less accurately. See the README's measurements.
#
# The configs and pdf.ttf are copied in because Tesseract writes a PDF layer
# only with those, and they live beside the distribution's models - which
# QB_BOOKS_TESSDATA below points away from. Without them the readable PDF
# silently comes out as plain text.
RUN python scripts/get_tessdata.py mal eng --flavour fast \
    && cp -r /usr/share/tesseract-ocr/*/tessdata/configs /app/data/tessdata/fast/ \
    && cp /usr/share/tesseract-ocr/*/tessdata/pdf.ttf /app/data/tessdata/fast/

COPY app app

# 0.0.0.0 inside the container: compose decides what the host publishes, and
# that mapping comes from the same QB_BOOKS_PORT this listens on.
ENV QB_BOOKS_HOST=0.0.0.0 \
    QB_BOOKS_PORT=8081 \
    QB_BOOKS_TESSDATA=/app/data/tessdata/fast \
    QB_BOOKS_OCR_LANGS=mal+eng \
    QB_BOOKS_DATA=/data \
    PYTHONUNBUFFERED=1

# Read books live here, and only here: mount it to keep them across restarts.
VOLUME ["/data"]

# Documentation only - the real port is QB_BOOKS_PORT, and the check below
# follows it rather than repeating a number.
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${QB_BOOKS_PORT}/health" || exit 1

# One entry point, so the address is read from config and written nowhere else.
CMD ["python", "-m", "app"]
