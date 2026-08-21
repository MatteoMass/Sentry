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
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from api.dependencies import Memory
from api.schemas import RecordingMove, RecordingOut, folder_ref
from connectors.memory_connector import ANY_FOLDER, FolderFilter, RecordingStatus

MEDIA_BASENAME = "recording"

_SUFFIX_PATTERN = re.compile(r"\A\.[A-Za-z0-9]{1,10}\Z")

router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.post(
    "",
    response_model=RecordingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a recording",
)
def upload_recording(
    memory: Memory,
    file: Annotated[UploadFile, File(description="Audio or video file to store.")],
    folder: Annotated[
        str | None,
        Form(description="Folder to file it under. Absent: the top level."),
    ] = None,
) -> RecordingOut:
    """Store an uploaded media file and register it as pending work.

    The row is created first, then the bytes are streamed into the recording
    folder; if the write fails the row is removed again, so a recording is
    never listed without its media.

    The destination folder decides nothing about where the bytes land: on disk
    every recording keeps its own folder directly under the recordings root,
    whatever the tree looks like.

    Args:
        memory: Storage the recording is written to.
        file: The uploaded audio or video file.
        folder: Folder to file it under. When absent it stays at the top
            level.

    Returns:
        The recording as it was stored, in ``to_process`` status.

    Raises:
        HTTPException: 415 if the upload is not audio or video, 404 if the
            folder does not exist.
    """
    _ensure_media(file)
    name = Path(file.filename or "").name or MEDIA_BASENAME

    recording = memory.create_recording(name, folder_id=folder_ref(folder))
    try:
        memory.save_file(recording.id, _media_filename(file), file.file)
    except BaseException:
        memory.delete_recording(recording.id)
        raise

    return RecordingOut.from_recording(recording)


@router.get(
    "",
    response_model=list[RecordingOut],
    summary="List the recordings and their status",
)
def list_recordings(
    memory: Memory,
    status_filter: Annotated[
        list[RecordingStatus] | None,
        Query(alias="status", description="Keep only these statuses."),
    ] = None,
    folder: Annotated[
        str | None,
        Query(description="Keep only this folder. Absent: every folder."),
    ] = None,
    recursive: Annotated[
        bool, Query(description="Include the subfolders as well.")
    ] = False,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RecordingOut]:
    """List the stored recordings, newest first.

    Args:
        memory: Storage the recordings are read from.
        status_filter: Statuses to keep. When absent everything is returned.
        folder: Folder to look into, ``root`` for the top level. When absent
            the recordings are listed wherever they sit.
        recursive: When true the subfolders are included as well.
        limit: Maximum number of recordings to return.
        offset: Number of recordings to skip.

    Returns:
        The matching recordings, ordered by upload time descending.

    Raises:
        HTTPException: 404 if ``folder`` does not exist.
    """
    wanted: FolderFilter = ANY_FOLDER if folder is None else folder_ref(folder)
    if isinstance(wanted, str):
        memory.get_folder(wanted)

    recordings = memory.list_recordings(
        status=status_filter,
        folder_id=wanted,
        recursive=recursive,
        limit=limit,
        offset=offset,
    )
    return [RecordingOut.from_recording(recording) for recording in recordings]


@router.patch(
    "/{recording_id}/folder",
    response_model=RecordingOut,
    summary="Move a recording to another folder",
)
def move_recording(
    memory: Memory, recording_id: str, payload: RecordingMove
) -> RecordingOut:
    """File a recording under another folder.

    Only the index changes: the media stays exactly where it is, so the move
    is atomic and cannot be left half done.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording to move.
        payload: Destination folder, ``root`` for the top level.

    Returns:
        The recording as it now stands.

    Raises:
        HTTPException: 404 if the recording or the folder does not exist.
    """
    recording = memory.move_recording(recording_id, folder_ref(payload.folder))
    return RecordingOut.from_recording(recording)


@router.delete(
    "/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recording",
)
def delete_recording(memory: Memory, recording_id: str) -> Response:
    """Delete a recording, media included.

    Nothing of it is kept: the row goes first and the folder holding the media
    follows, so an interrupted delete leaves files nothing points at rather
    than an entry pointing at files that are gone.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording to delete.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 if the recording does not exist.
    """
    memory.delete_recording(recording_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- helpers


def _ensure_media(upload: UploadFile) -> None:
    """Reject an upload that is neither audio nor video.

    Raises:
        HTTPException: 415 if the file is not a media file.
    """
    if not _content_type(upload).startswith(("audio/", "video/")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only audio or video files are accepted.",
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
