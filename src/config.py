"""Settings shared by every entrypoint of Sentry.

The API and the processing worker are separate processes that must agree on
where the recordings live, so the storage location is resolved here and
nowhere else.
"""

import os
from pathlib import Path

STORAGE_ROOT_ENV = "SENTRY_STORAGE_ROOT"
DEFAULT_STORAGE_ROOT = "./data"

FRONTEND_DIST_ENV = "SENTRY_FRONTEND_DIST"
DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"


def storage_root() -> Path:
    """Return the directory holding the database and the recording folders.

    It comes from the ``SENTRY_STORAGE_ROOT`` environment variable, so a
    container can point it at a mounted volume without touching the code.
    """
    return Path(os.getenv(STORAGE_ROOT_ENV, DEFAULT_STORAGE_ROOT))


def frontend_dist() -> Path:
    """Return the directory holding the built frontend.

    It defaults to the build output of ``src/frontend``, which is where a
    local ``npm run build`` leaves it; an image that compiles the app
    elsewhere points ``SENTRY_FRONTEND_DIST`` at the result instead.
    """
    location = os.getenv(FRONTEND_DIST_ENV)
    return Path(location) if location else DEFAULT_FRONTEND_DIST
