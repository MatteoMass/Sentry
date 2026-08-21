"""Endpoints of the ``/recordings`` resource.

The routes are a thin shell around :class:`MemoryConnector`: they validate
what arrives over HTTP, hand the bytes to the connector, and let its errors
travel up to the handlers registered on the application. No processing happens
here — an uploaded recording lands in the ``to_process`` status and waits for
the pipeline to pick it up.
"""

import mimetypes
import re
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from api.schemas import RecordingOut
from connectors.memory_connector import MemoryConnector, RecordingStatus

MEDIA_BASENAME = "recording"

_SUFFIX_PATTERN = re.compile(r"\A\.[A-Za-z0-9]{1,10}\Z")

router = APIRouter(prefix="/recordings", tags=["recordings"])


def get_memory(request: Request) -> MemoryConnector:
    """Return the connector opened at startup."""
    return request.app.state.memory


Memory = Annotated[MemoryConnector, Depends(get_memory)]


@router.post(
    "",
    response_model=RecordingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Carica una registrazione",
)
def upload_recording(
    memory: Memory,
    file: Annotated[UploadFile, File(description="File audio o video da archiviare.")],
) -> RecordingOut:
    """Store an uploaded media file and register it as pending work.

    The row is created first, then the bytes are streamed into the recording
    folder; if the write fails the row is removed again, so a recording is
    never listed without its media.

    Args:
        memory: Storage the recording is written to.
        file: The uploaded audio or video file.

    Returns:
        The recording as it was stored, in ``to_process`` status.

    Raises:
        HTTPException: 415 if the upload is not audio or video.
    """
    _ensure_media(file)
    name = Path(file.filename or "").name or MEDIA_BASENAME

    recording = memory.create_recording(name)
    try:
        memory.save_file(recording.id, _media_filename(file), file.file)
    except BaseException:
        memory.delete_recording(recording.id)
        raise

    return RecordingOut.from_recording(recording)


@router.get(
    "",
    response_model=list[RecordingOut],
    summary="Elenca le registrazioni e il loro stato",
)
def list_recordings(
    memory: Memory,
    status_filter: Annotated[
        list[RecordingStatus] | None,
        Query(alias="status", description="Tiene solo questi stati."),
    ] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RecordingOut]:
    """List the stored recordings, newest first.

    Args:
        memory: Storage the recordings are read from.
        status_filter: Statuses to keep. When absent everything is returned.
        limit: Maximum number of recordings to return.
        offset: Number of recordings to skip.

    Returns:
        The matching recordings, ordered by upload time descending.
    """
    recordings = memory.list_recordings(
        status=status_filter, limit=limit, offset=offset
    )
    return [RecordingOut.from_recording(recording) for recording in recordings]


# ------------------------------------------------------------------- helpers


def _ensure_media(upload: UploadFile) -> None:
    """Reject an upload that is neither audio nor video.

    Raises:
        HTTPException: 415 if the file is not a media file.
    """
    if not _content_type(upload).startswith(("audio/", "video/")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Sono accettati solo file audio o video.",
        )


def _content_type(upload: UploadFile) -> str:
    """Return the media type of an upload, falling back to its extension.

    The declared content type wins; when it is missing or generic the file
    name is used instead, since browsers and CLI clients are inconsistent.
    """
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    return (mimetypes.guess_type(upload.filename or "")[0] or "").lower()


def _media_filename(upload: UploadFile) -> str:
    """Return the name the media file takes inside the recording folder.

    The extension of the upload is kept, so the file stays playable and the
    pipeline can tell audio from video; everything else is discarded, which
    keeps the folder layout predictable whatever the client sends.
    """
    suffix = Path(upload.filename or "").suffix.lower()
    if not _SUFFIX_PATTERN.match(suffix):
        suffix = mimetypes.guess_extension(_content_type(upload)) or ""
    return f"{MEDIA_BASENAME}{suffix}"
