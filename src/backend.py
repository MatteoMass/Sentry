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

from api import folders_router, recordings_router
from config import storage_root
from connectors.memory_connector import (
    FolderAlreadyExists,
    FolderNotEmpty,
    FolderNotFound,
    InvalidFolderMove,
    InvalidFolderName,
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
    summary="Recordings, and where each one sits in the processing pipeline.",
    lifespan=lifespan,
)

app.include_router(recordings_router)
app.include_router(folders_router)


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
async def invalid_folder(
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
