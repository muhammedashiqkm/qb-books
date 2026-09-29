"""
Starting the service: `python -m app`.

One entry point, so the address lives in ONE place - config.HOST and
config.PORT, both from the environment. Before this the port was written into
run.ps1, the Dockerfile's CMD, its HEALTHCHECK and the compose file, and moving
it meant finding all four.
"""

import uvicorn

from . import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="info")
