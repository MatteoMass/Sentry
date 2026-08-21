"""Entrypoint of the Sentry HTTP service.

This module only assembles the application: it opens the storage, registers
the routers and translates connector errors into status codes. The endpoints
themselves live in :mod:`api`.

Example:
    $ uvicorn backend:app --app-dir src --reload
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from api import recordings_router
from config import storage_root
from connectors.memory_connector import (
    InvalidKey,
    MemoryConnector,
    MemoryConnectorError,
    RecordingNotFound,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Open the storage for the whole life of the process, then close it."""
    memory = MemoryConnector(storage_root())
    app.state.memory = memory
    try:
        yield
    finally:
        memory.close()


app = FastAPI(
    title="Sentry",
    version="0.1.0",
    summary="Archivio delle registrazioni e del loro stato di elaborazione.",
    lifespan=lifespan,
)

app.include_router(recordings_router)


# --------------------------------------------------------- error translation


@app.exception_handler(RecordingNotFound)
async def recording_not_found(
    request: Request, error: RecordingNotFound
) -> JSONResponse:
    """Turn a missing recording into a 404."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(InvalidKey)
async def invalid_key(request: Request, error: InvalidKey) -> JSONResponse:
    """Turn an unsafe id or file name into a 400."""
    return JSONResponse({"detail": str(error)}, status_code=status.HTTP_400_BAD_REQUEST)


@app.exception_handler(MemoryConnectorError)
async def storage_failure(request: Request, error: MemoryConnectorError) -> JSONResponse:
    """Turn any other storage failure into a 500."""
    return JSONResponse(
        {"detail": f"Errore di archiviazione: {error}"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
