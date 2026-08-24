"""Endpoints of the ``/recordings`` resource.

The routes are a thin shell around :class:`MemoryConnector`: they validate
what arrives over HTTP, hand the bytes to the connector, and let its errors
travel up to the handlers registered on the application. An uploaded recording
lands in the ``to_process`` status and stays there until somebody asks for it
to be processed.

That request does not wait for the answer. Transcribing a meeting takes
minutes, which no browser will hold a connection open for, so the endpoint
moves the recording to the status of the step it is about to start, hands the
work to a background task and returns at once. What happened is then read from
the status, which is why the single recording is fetchable on its own: it is
what the client polls while the pipeline runs.

What was uploaded is served back as well, and twice: as a stream a player
can seek inside, which is what makes a transcript worth clicking on, and as
an archive of the whole recording folder, which is everything the pipeline
ever wrote about it in one file.

The two steps are also two endpoints. Transcribing is what costs minutes and
money; summarising reads what it left behind. Keeping them apart is what lets
a recording whose summary failed be offered another summary — over the
transcript already stored — instead of a whole run from the audio.
"""

import logging
import mimetypes
import re
import tempfile
import zipfile
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from api.dependencies import Memory, Pipeline
from api.schemas import (
    RecordingMove,
    RecordingOut,
    RecordingRename,
    SummaryOut,
    TranscriptOut,
    folder_ref,
)
from connectors.memory_connector import (
    ANY_FOLDER,
    RUNNING_STATUSES,
    FolderFilter,
    MemoryConnector,
    Recording,
    RecordingStatus,
)
from core import (
    ARTIFACTS,
    MEDIA_BASENAME,
    SUMMARY_JSON,
    TRANSCRIPT_JSON,
    media_filename,
)

logger = logging.getLogger(__name__)

_SUFFIX_PATTERN = re.compile(r"\A\.[A-Za-z0-9]{1,10}\Z")

_UNSAFE_IN_FILENAME = re.compile(r"[^\w \-.]+")
"""What is taken out of a name before it is offered as a file name."""

_FALLBACK_TYPE = "application/octet-stream"

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
        memory.save_file(recording.id, _upload_filename(file), file.file)
    except BaseException:
        memory.delete_recording(recording.id)
        raise

    return _out(memory, recording)


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
    return [_out(memory, recording) for recording in recordings]


@router.get(
    "/{recording_id}",
    response_model=RecordingOut,
    summary="Read a recording",
)
def get_recording(memory: Memory, recording_id: str) -> RecordingOut:
    """Return one recording, and above all the status it now carries.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording to read.

    Returns:
        The recording as it now stands.

    Raises:
        HTTPException: 404 if the recording does not exist.
    """
    return _out(memory, memory.get_recording(recording_id))


@router.post(
    "/{recording_id}/process",
    response_model=RecordingOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Transcribe and summarise a recording",
)
def process_recording(
    memory: Memory,
    pipeline: Pipeline,
    background: BackgroundTasks,
    recording_id: str,
    force: Annotated[
        bool,
        Query(description="Redo the work even where a result is already stored."),
    ] = False,
) -> RecordingOut:
    """Start the whole pipeline on a recording and answer before it is done.

    The status moves while the request is still being served, not once the
    task starts: that is what makes the answer worth reading, and what lets a
    second click be turned down rather than run the same recording twice. It
    moves to the step the run will actually begin with — ``summarizing`` when
    a transcript is already stored and is not being redone.

    The results are written by the pipeline into the folder that already holds
    the media — a transcript and a summary, each in a readable and a
    machine readable form — and the status settles on ``processed`` or
    ``error`` once it is over.

    Args:
        memory: Storage the recording lives in.
        pipeline: Processing pipeline built at startup.
        background: Where the work is queued once the answer is on its way.
        recording_id: Recording to process.
        force: When true the audio is transcribed again even if a transcript
            is already stored. Without it a run picks up where the last one
            failed, which is what makes a retry cheap.

    Returns:
        The recording in ``processing``, with a 202 saying the work is only
        starting.

    Raises:
        HTTPException: 404 if the recording does not exist, 409 if it is
            already being processed.
    """
    recording = _claim(
        memory, recording_id, pipeline.next_status(recording_id, force=force)
    )
    background.add_task(
        _run,
        partial(pipeline.process, recording_id, force=force),
        recording_id,
        "Processing",
    )
    return _out(memory, recording)


@router.post(
    "/{recording_id}/transcribe",
    response_model=RecordingOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Transcribe and diarize a recording",
)
def transcribe_recording(
    memory: Memory,
    pipeline: Pipeline,
    background: BackgroundTasks,
    recording_id: str,
    force: Annotated[
        bool,
        Query(description="Send the audio again even if a transcript is stored."),
    ] = False,
) -> RecordingOut:
    """Run the first step alone, and answer before it is done.

    This is the expensive half: the audio is prepared and sent, and what comes
    back is written next to the media. The recording settles on
    ``transcribed`` — no summary is asked for, and none is written — or on
    ``error`` if the provider refused the job.

    A stored summary is dropped when the audio is transcribed again: it
    describes a dialogue that no longer exists.

    Args:
        memory: Storage the recording lives in.
        pipeline: Processing pipeline built at startup.
        background: Where the work is queued once the answer is on its way.
        recording_id: Recording to transcribe.
        force: When true the audio is sent again even if a transcript is
            already stored, which is the only way to replace one.

    Returns:
        The recording in ``transcribing``, with a 202 saying the work is only
        starting.

    Raises:
        HTTPException: 404 if the recording does not exist, 409 if a step is
            already running on it.
    """
    recording = _claim(memory, recording_id, "transcribing")
    background.add_task(
        _run,
        partial(pipeline.transcribe, recording_id, force=force),
        recording_id,
        "Transcription",
    )
    return _out(memory, recording)


@router.post(
    "/{recording_id}/summarize",
    response_model=RecordingOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Summarise the transcript of a recording",
)
def summarize_recording(
    memory: Memory,
    pipeline: Pipeline,
    background: BackgroundTasks,
    recording_id: str,
    force: Annotated[
        bool,
        Query(description="Write a new summary even if one is already stored."),
    ] = True,
) -> RecordingOut:
    """Run the second step alone, over the transcript already stored.

    This is what a failed summary is retried with: the audio never travels
    again, so the retry costs a model call and nothing else. It is also how a
    recording left in ``transcribed`` is finished off.

    Args:
        memory: Storage the recording lives in.
        pipeline: Processing pipeline built at startup.
        background: Where the work is queued once the answer is on its way.
        recording_id: Recording to summarise.
        force: When true — as it is by default, since asking again can only
            mean the stored summary is not wanted — a new summary is written
            over the one already there.

    Returns:
        The recording in ``summarizing``, with a 202 saying the work is only
        starting.

    Raises:
        HTTPException: 404 if the recording does not exist, 409 if a step is
            already running on it or if no transcript is stored to read.
    """
    if not pipeline.has_transcript(recording_id):
        # Reported here rather than left to the task: the client can act on
        # it, and there is nothing to run in the background.
        memory.get_recording(recording_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That recording has no transcript to summarise yet.",
        )

    recording = _claim(memory, recording_id, "summarizing")
    background.add_task(
        _run,
        partial(pipeline.summarize, recording_id, force=force),
        recording_id,
        "Summarisation",
    )
    return _out(memory, recording)


@router.get(
    "/{recording_id}/transcript",
    response_model=TranscriptOut,
    summary="Read the transcript of a recording",
)
def read_transcript(pipeline: Pipeline, recording_id: str) -> TranscriptOut:
    """Return what the first step stored, whatever became of the second.

    Args:
        pipeline: Processing pipeline, which knows where its results are kept.
        recording_id: Recording to read.

    Returns:
        The dialogue, split by speaker and in chronological order.

    Raises:
        HTTPException: 404 if the recording does not exist, or holds no
            readable transcript.
    """
    pipeline.memory.get_recording(recording_id)
    transcript = pipeline.read_transcript(recording_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No transcript stored for that recording.",
        )
    return TranscriptOut.from_transcript(transcript)


@router.get(
    "/{recording_id}/summary",
    response_model=SummaryOut,
    summary="Read the summary of a recording",
)
def read_summary(pipeline: Pipeline, recording_id: str) -> SummaryOut:
    """Return what the second step stored.

    Args:
        pipeline: Processing pipeline, which knows where its results are kept.
        recording_id: Recording to read.

    Returns:
        The summary, with the Markdown rendering it is read as.

    Raises:
        HTTPException: 404 if the recording does not exist, or holds no
            readable summary.
    """
    recording = pipeline.memory.get_recording(recording_id)
    summary = pipeline.read_summary(recording_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No summary stored for that recording.",
        )
    return SummaryOut.from_summary(summary, title=recording.name)


@router.get(
    "/{recording_id}/media",
    response_class=FileResponse,
    summary="Stream the media of a recording",
)
def stream_media(memory: Memory, recording_id: str) -> FileResponse:
    """Serve the stored media, seekable, for a player to read.

    The bytes are served from disk with their range headers intact, which is
    what lets a player jump to a timestamp without pulling the whole file
    first — the point of the whole endpoint, since the transcript is read by
    clicking on it.

    Nothing is attached: the file is meant to be played where it is, not
    saved. Saving it is what the archive is for.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording whose media is served.

    Returns:
        The media file, as it was uploaded.

    Raises:
        HTTPException: 404 if the recording does not exist, or holds no media.
    """
    memory.get_recording(recording_id)
    name = media_filename(memory, recording_id)
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No media stored for that recording.",
        )
    return FileResponse(
        memory.recording_dir(recording_id) / name, media_type=_media_type(name)
    )


@router.get(
    "/{recording_id}/download",
    response_class=FileResponse,
    summary="Download everything stored with a recording",
)
def download_recording(memory: Memory, recording_id: str) -> FileResponse:
    """Hand back the recording folder as one zip archive.

    Everything the folder holds travels: the media as it was uploaded, and
    whatever the pipeline wrote next to it. The names inside the archive are
    the ones on disk, under a folder named after the recording, so unpacking
    it twice never spills two recordings into each other.

    The archive is built into a temporary file rather than streamed: it lets
    the answer carry its length, so a browser can show how far along the
    download is, and the file is removed once the response has been sent.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording to hand back.

    Returns:
        A zip archive of the whole recording folder.

    Raises:
        HTTPException: 404 if the recording does not exist, or nothing is
            stored with it yet.
    """
    recording = memory.get_recording(recording_id)
    stored = memory.list_files(recording_id)
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nothing is stored with that recording yet.",
        )

    directory = memory.recording_dir(recording_id)
    stem = _archive_stem(recording)
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    archive_path = Path(handle.name)
    try:
        with handle, zipfile.ZipFile(handle, "w") as archive:
            for name in stored:
                archive.write(
                    directory / name,
                    arcname=f"{stem}/{name}",
                    # Only what the pipeline wrote is text; deflating media
                    # that is already compressed costs time and saves nothing.
                    compress_type=(
                        zipfile.ZIP_DEFLATED
                        if name in ARTIFACTS
                        else zipfile.ZIP_STORED
                    ),
                )
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise

    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{stem}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@router.patch(
    "/{recording_id}",
    response_model=RecordingOut,
    summary="Rename a recording",
)
def rename_recording(
    memory: Memory, recording_id: str, payload: RecordingRename
) -> RecordingOut:
    """Give a recording another name.

    Only the index changes: the folder holding the media is named after the
    identifier, so a rename never touches a file and can be done while the
    pipeline is running on it.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording to rename.
        payload: The new name.

    Returns:
        The recording as it now stands.

    Raises:
        HTTPException: 404 if the recording does not exist, 400 if the name is
            empty or holds a path separator.
    """
    return _out(memory, memory.rename_recording(recording_id, payload.name))


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
    return _out(memory, recording)


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


def _out(memory: MemoryConnector, recording: Recording) -> RecordingOut:
    """Build the payload, asking the folder what the pipeline left in it.

    The two flags are read from disk rather than inferred from the status: the
    files are the truth, and they are what tells a summary that failed apart
    from a transcription that never ran.
    """
    stored = media_filename(memory, recording.id)
    return RecordingOut.from_recording(
        recording,
        has_transcript=memory.has_file(recording.id, TRANSCRIPT_JSON),
        has_summary=memory.has_file(recording.id, SUMMARY_JSON),
        media_type=None if stored is None else _media_type(stored),
    )


def _claim(
    memory: MemoryConnector, recording_id: str, moving_to: RecordingStatus
) -> Recording:
    """Move a recording into a running status, unless one already holds it.

    The check and the move share a transaction, so two clicks arriving
    together cannot both start a run on the same recording.

    Raises:
        HTTPException: 409 if a step is already running on it.
    """
    with memory.database.transaction():
        recording = memory.get_recording(recording_id)
        if recording.status in RUNNING_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That recording is already being processed.",
            )
        return memory.update_status(recording_id, moving_to)


def _run(work: Callable[[], object], recording_id: str, step: str) -> None:
    """Run a step outside the request, and swallow nothing silently.

    The pipeline records its own failure on the recording, which is what the
    client sees; the traceback would be lost with it, so it is logged here
    before the task ends.
    """
    try:
        work()
    except Exception:
        logger.exception("%s failed for recording %s", step, recording_id)


def _media_type(filename: str) -> str:
    """Return what a stored file is served as, guessed from its name.

    The type of the upload is not kept anywhere, and the extension is: it is
    what the pipeline already tells audio from video with, so it is what the
    player is told as well.
    """
    return mimetypes.guess_type(filename)[0] or _FALLBACK_TYPE


def _archive_stem(recording: Recording) -> str:
    """Name the archive after the recording, safely.

    A name is free text and lands here in a header a client will save a file
    under, so anything that is not a letter, a digit or ordinary punctuation
    is replaced. The extension of the media it usually carries is dropped —
    the archive is not that file — and a name left with nothing usable falls
    back to the identifier, which is always a valid name.
    """
    cleaned = _UNSAFE_IN_FILENAME.sub("_", Path(recording.name).stem).strip(" .")
    return cleaned or recording.id


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


def _upload_filename(upload: UploadFile) -> str:
    """Return the name the media file takes inside the recording folder.

    The extension of the upload is kept, so the file stays playable and the
    pipeline can tell audio from video; everything else is discarded, which
    keeps the folder layout predictable whatever the client sends.
    """
    suffix = Path(upload.filename or "").suffix.lower()
    if not _SUFFIX_PATTERN.match(suffix):
        suffix = mimetypes.guess_extension(_content_type(upload)) or ""
    return f"{MEDIA_BASENAME}{suffix}"
