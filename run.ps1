# Start the service for development. Ctrl+C stops it.
#
# The port is NOT here: it comes from .env / QB_BOOKS_PORT, through
# app/config.py, so one value serves this script, the container and the compose
# mapping alike.
#
# TESSDATA_PREFIX points at the project's own models rather than the ones beside
# the Tesseract binary: writing into Program Files needs an administrator, and
# keeping them here pins the exact models this was measured with. The "fast"
# flavour is deliberate - on a real Malayalam textbook it read 3.6x quicker than
# "best" and no less accurately.
$env:QB_BOOKS_TESSDATA = Join-Path $PSScriptRoot "data\tessdata\fast"

# Anything set in .env wins over the defaults in config.py, so the file is the
# single place to change the port, the languages or the API key.
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            Set-Item -Path "env:$($matches[1])" -Value $matches[2]
        }
    }
}

.\.venv\Scripts\python.exe -m app
