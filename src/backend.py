"""Entrypoint of the Sentry HTTP service.

This module only assembles the application: it opens the storage, registers
the routers and translates connector errors into status codes. The endpoints
themselves live in :mod:`api`.

Example:
    $ uvicorn backend:app --app-dir src --reload
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from api import folders_router, mount_frontend, recordings_router
from config import ENV_FILE, frontend_dist, storage_root
from connectors.memory_connector import (
    FolderAlreadyExists,
    FolderNotEmpty,
    FolderNotFound,
    InvalidFolderMove,
    InvalidFolderName,
    InvalidKey,
    InvalidRecordingName,
    MemoryConnector,
    MemoryConnectorError,
    RecordingNotFound,
)
from core import ProcessingPipeline

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Open the storage and the pipeline for the life of the process.

    The pipeline builds its backends only when something is actually
    processed, so a service whose API keys are not set still starts and
    still serves everything that does not need them.

    The environment was assembled when :mod:`config` was imported, which is
    earlier than this; it is reported here because a key silently not picked
    up is the first thing anybody suspects.
    """
    if ENV_FILE is not None:
        logger.info("Environment read from %s", ENV_FILE)

    memory = MemoryConnector(storage_root())
    pipeline = ProcessingPipeline(memory)
    app.state.memory = memory
    app.state.pipeline = pipeline
    try:
        yield
    finally:
        pipeline.close()
        memory.close()


app = FastAPI(
    title="Sentry",
    version="0.1.0",
    summary="Recordings, and where each one sits in the processing pipeline.",
    lifespan=lifespan,
)

app.include_router(recordings_router)
app.include_router(folders_router)


# ------------------------------------------------------------------ frontend

# The built single page application answers everything the API did not claim,
# so it is mounted last; without a build the service is API only.
mount_frontend(app, frontend_dist())

# --------------------------------------------------------- error translation


@app.exception_handler(RecordingNotFound)
async def recording_not_found(
    request: Request, error: RecordingNotFound
) -> JSONResponse:
    """Turn a missing recording into a 404."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(FolderNotFound)
async def folder_not_found(request: Request, error: FolderNotFound) -> JSONResponse:
    """Turn a missing folder into a 404."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(FolderAlreadyExists)
@app.exception_handler(FolderNotEmpty)
async def folder_conflict(
    request: Request, error: MemoryConnectorError
) -> JSONResponse:
    """Turn a taken folder name, or a folder still in use, into a 409.

    Both say the same thing: the tree cannot be changed without the client
    deciding something first — another name, or that what is inside may go.
    """
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_409_CONFLICT)


@app.exception_handler(InvalidFolderMove)
@app.exception_handler(InvalidFolderName)
@app.exception_handler(InvalidRecordingName)
async def invalid_change(
    request: Request, error: MemoryConnectorError
) -> JSONResponse:
    """Turn an impossible move, or an unusable name, into a 400."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_400_BAD_REQUEST)


@app.exception_handler(InvalidKey)
async def invalid_key(request: Request, error: InvalidKey) -> JSONResponse:
    """Turn an unsafe id or file name into a 400."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_400_BAD_REQUEST)


@app.exception_handler(MemoryConnectorError)
async def storage_failure(request: Request, error: MemoryConnectorError) -> JSONResponse:
    """Turn any other storage failure into a 500."""
    return JSONResponse(
        {"detail": f"Storage failure: {error}"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
