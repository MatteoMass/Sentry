"""Settings shared by every entrypoint of Sentry.

The API and the processing worker are separate processes that must agree on
where the recordings live, so the storage location is resolved here and
nowhere else.

This is also where the environment is assembled. Importing this module loads
the ``.env`` file sitting at the root of the project, because that has to
happen before anything reads a variable — and by the time an entrypoint has
imported its settings, it already has: the frontend directory is resolved
while the application is being built, long before the first request. Nothing
in the file overrides a variable that is already set, so a container passing
its own secrets keeps them whatever the file happens to say.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
"""Directory holding ``pyproject.toml``, one level above the sources."""

ENV_FILE_ENV = "SENTRY_ENV_FILE"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

STORAGE_ROOT_ENV = "SENTRY_STORAGE_ROOT"
DEFAULT_STORAGE_ROOT = "./data"

FRONTEND_DIST_ENV = "SENTRY_FRONTEND_DIST"
DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"


def load_environment() -> Path | None:
    """Read the ``.env`` file into the environment, if there is one.

    The file is the one at the root of the project, unless ``SENTRY_ENV_FILE``
    names another — a deployment holding its secrets elsewhere says so there.
    A missing file is not an error: everything it would carry can be set the
    ordinary way, and in production usually is.

    Returns:
        The file that was read, or ``None`` when there was none to read.
    """
    location = Path(os.getenv(ENV_FILE_ENV, DEFAULT_ENV_FILE)).expanduser()
    if not location.is_file():
        return None

    # A variable already in the environment wins: the file is a convenience
    # for a checkout, not a way to overrule what a container was started with.
    load_dotenv(location, override=False)
    return location


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


ENV_FILE: Path | None = load_environment()
"""The ``.env`` that was read at import, or ``None`` if there was none."""
