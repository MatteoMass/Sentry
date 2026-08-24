"""Serving the built single page application next to the API.

The frontend lives in ``src/frontend`` and is compiled to static files; there
is nothing to render server side, so the whole app is one mount. It is
optional on purpose: a checkout that has never run ``npm run build`` still
starts, and only answers the API.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

INDEX_FILENAME = "index.html"


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """Serve the built frontend at the root, when there is one.

    The mount goes last, after every router, because a mount at ``/`` catches
    whatever the routes above it did not.

    Args:
        app: Application the files are attached to.
        dist: Directory holding the build output.

    Returns:
        True if the build was found and mounted, False if there is none.
    """
    if not (dist / INDEX_FILENAME).is_file():
        return False

    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return True
