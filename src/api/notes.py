"""Endpoints of the ``/recordings/{id}/notes`` resource.

What the pipeline writes about a recording is read only; this is the part of
its folder a person writes. The note is one text, and the files stored beside
it are what a text alone cannot hold — a screenshot of the slide, the deck
that was shared, the diagram somebody drew afterwards.

The two are saved apart on purpose. A note is typed and saved as a whole,
while a file arrives on its own and stays until it is deleted: writing the
text is never a reason to lose an attachment, and uploading one is never a
reason to overwrite a sentence somebody is still typing.

Nothing here is written to the index — it all lives in the recording folder —
so notes are untouched by every step of the pipeline, including a run that
transcribes the audio again, and they travel in the archive the recording is
downloaded as without the archive being taught anything about them.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from api.dependencies import Memory
from api.schemas import AttachmentOut, NoteOut, NoteUpdate
from core import (
    add_attachment,
    attachment_file,
    attachment_type,
    delete_attachment,
    list_attachments,
    read_note,
    write_note,
)

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
"""How large a file stored with a note may be.

Attachments are meant to be read next to the note — screenshots, slides, a
page of figures — and they are held in the browser alongside everything else
the panel shows. The media of the recording is what the upload endpoint is
for, and it has no such limit.
"""

router = APIRouter(prefix="/recordings/{recording_id}/notes", tags=["notes"])


@router.get(
    "",
    response_model=NoteOut,
    summary="Read the note of a recording",
)
def read_recording_note(memory: Memory, recording_id: str) -> NoteOut:
    """Return what somebody added to a recording, files included.

    A recording nobody annotated answers with an empty note rather than a
    404: there is nothing missing about it, and the client would have to draw
    the same empty editor either way.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording whose note is read.

    Returns:
        The note text and the files stored with it.

    Raises:
        HTTPException: 404 if the recording does not exist.
    """
    memory.get_recording(recording_id)
    return NoteOut.from_note(
        read_note(memory, recording_id),
        list_attachments(memory, recording_id),
        recording_id=recording_id,
    )


@router.put(
    "",
    response_model=NoteOut,
    summary="Write the note of a recording",
)
def write_recording_note(
    memory: Memory, recording_id: str, payload: NoteUpdate
) -> NoteOut:
    """Store the note of a recording, replacing whatever was there.

    An empty text is how a note is cleared, and clears only the text: the
    files stored with it are deleted one at a time, and never as a side
    effect of somebody emptying the editor.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the note belongs to.
        payload: The note, as Markdown.

    Returns:
        The note as it now stands, files included.

    Raises:
        HTTPException: 404 if the recording does not exist.
    """
    memory.get_recording(recording_id)
    return NoteOut.from_note(
        write_note(memory, recording_id, payload.text),
        list_attachments(memory, recording_id),
        recording_id=recording_id,
    )


@router.post(
    "/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Store a file with the note of a recording",
)
def upload_attachment(
    memory: Memory,
    recording_id: str,
    file: Annotated[UploadFile, File(description="File to store with the note.")],
) -> AttachmentOut:
    """Store one uploaded file with the note of a recording.

    Any kind of file is taken: the point of a note is that it holds what the
    pipeline could not, and refusing everything but images would only move
    the problem elsewhere.

    The name it lands under is not always the one it arrived with — it is made
    safe, and a name already taken is numbered rather than overwritten — so
    the answer carries the name that was actually used, and the URL to read it
    back from.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the file is stored with.
        file: The uploaded file.

    Returns:
        The attachment as it was stored.

    Raises:
        HTTPException: 404 if the recording does not exist, 413 if the file is
            larger than :data:`MAX_ATTACHMENT_BYTES`.
    """
    memory.get_recording(recording_id)
    if file.size is not None and file.size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "That file is too large to store with a note"
                f" (the limit is {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)."
            ),
        )

    stored = add_attachment(
        memory, recording_id, Path(file.filename or "").name, file.file
    )
    return AttachmentOut.from_attachment(stored, recording_id=recording_id)


@router.get(
    "/attachments/{name}",
    response_class=FileResponse,
    summary="Read a file stored with the note of a recording",
)
def read_attachment(memory: Memory, recording_id: str, name: str) -> FileResponse:
    """Serve one file stored with a note, to be shown where it is.

    Nothing is attached: a screenshot is worth having in the panel next to
    the sentence about it, not in the downloads folder. Saving it is a click
    on the link the client draws, and the whole folder is what the archive is
    for.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the file is stored with.
        name: File name inside the attachments folder.

    Returns:
        The file, as it was uploaded.

    Raises:
        HTTPException: 404 if the recording does not exist, or holds no such
            attachment.
    """
    memory.get_recording(recording_id)
    path = attachment_file(memory, recording_id, name)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such file is stored with that note.",
        )
    return FileResponse(path, media_type=attachment_type(name))


@router.delete(
    "/attachments/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a file stored with the note of a recording",
)
def remove_attachment(memory: Memory, recording_id: str, name: str) -> Response:
    """Delete one file stored with a note, leaving the text as it is.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the file is stored with.
        name: File name inside the attachments folder.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 if the recording does not exist, or holds no such
            attachment.
    """
    memory.get_recording(recording_id)
    if not delete_attachment(memory, recording_id, name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such file is stored with that note.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
