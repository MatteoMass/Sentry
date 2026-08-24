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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import (
    folders_router,
    mount_frontend,
    notes_router,
    prompts_router,
    recordings_router,
)
from config import CONFIG_FILE, ENV_FILE, settings
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

    The settings were assembled when :mod:`config` was imported, which is
    earlier than this; the files they came from are reported here because a
    key or a setting silently not picked up is the first thing anybody
    suspects.
    """
    logging.basicConfig(level=settings.logging.level)
    logging.getLogger().setLevel(settings.logging.level)

    if ENV_FILE is not None:
        logger.info("Environment read from %s", ENV_FILE)
    if CONFIG_FILE is not None:
        logger.info("Configuration read from %s", CONFIG_FILE)

    memory = MemoryConnector(settings.paths.storage_root)
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
app.include_router(notes_router)
app.include_router(folders_router)
app.include_router(prompts_router)


# ---------------------------------------------------------------------- CORS

# Nothing is installed by default: the same process serves the frontend, so
# the calls are same origin and there is no header worth adding. A frontend
# running somewhere else — Vite in development, a separate host — is named in
# `server.cors_origins`, and only then is the middleware in the way.
if settings.server.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.server.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ------------------------------------------------------------------ frontend

# The built single page application answers everything the API did not claim,
# so it is mounted last; without a build the service is API only.
mount_frontend(app, settings.paths.frontend_dist)

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
async def invalid_change(request: Request, error: MemoryConnectorError) -> JSONResponse:
    """Turn an impossible move, or an unusable name, into a 400."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_400_BAD_REQUEST)


@app.exception_handler(InvalidKey)
async def invalid_key(request: Request, error: InvalidKey) -> JSONResponse:
    """Turn an unsafe id or file name into a 400."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_400_BAD_REQUEST)


@app.exception_handler(MemoryConnectorError)
async def storage_failure(
    request: Request, error: MemoryConnectorError
) -> JSONResponse:
    """Turn any other storage failure into a 500."""
    return JSONResponse(
        {"detail": f"Storage failure: {error}"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
