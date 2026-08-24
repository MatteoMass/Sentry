"""What a person adds to a recording, next to what the model made of it.

The pipeline writes a transcript and a summary; this is the other half of a
recording's folder — a note somebody typed, and the files they dropped in
beside it. A screenshot of the slide being discussed belongs to the meeting
as much as its dialogue does, and it is worth nothing if it is kept somewhere
else.

So it is kept here: the note is one Markdown file at the top of the recording
folder, the files sit in a subfolder of their own, and both travel in the
archive the recording is downloaded as without anything being taught about
them. Nothing is written to the index, which means notes survive every step
of the pipeline — including a run that transcribes the audio again.

The subfolder is also what keeps the media findable. A recording folder holds
its media as "whatever the pipeline did not write", so anything added here has
to be recognisable as not being that: :func:`is_note_file` is what
:func:`core.pipeline.media_filename` asks.
"""

import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from connectors.memory_connector import BlobNotFound, MemoryConnector

NOTES_FILE = "notes.md"
"""The note itself, as one Markdown file in the recording folder."""

ATTACHMENTS_DIR = "attachments"
"""Subfolder of the recording folder holding what was uploaded to the note."""

_FALLBACK_TYPE = "application/octet-stream"

_FALLBACK_NAME = "attachment"

_UNSAFE_IN_FILENAME = re.compile(r"[^\w\-.]+")
"""What is taken out of an uploaded name before it becomes a file name."""

_MAX_STEM = 80
"""How much of a name is kept; the rest says nothing a person reads."""


@dataclass(frozen=True, slots=True)
class Attachment:
    """One file stored with the note of a recording.

    Attributes:
        name: File name inside the attachments folder, which is what every
            endpoint addresses it by.
        media_type: What it is served as, guessed from the extension.
        size: Size on disk, in bytes.
        added_at: When it was written, in UTC.
    """

    name: str
    media_type: str
    size: int
    added_at: datetime

    @property
    def path(self) -> str:
        """Return the name of the file relative to the recording folder."""
        return f"{ATTACHMENTS_DIR}/{self.name}"


def is_note_file(name: str) -> bool:
    """Tell whether a stored file belongs to the note rather than the media.

    Args:
        name: A file name relative to the recording folder, as
            :meth:`MemoryConnector.list_files` returns it.

    Returns:
        ``True`` for the note and for anything inside the attachments folder.
    """
    parts = Path(name).parts
    return name == NOTES_FILE or (len(parts) > 1 and parts[0] == ATTACHMENTS_DIR)


def read_note(memory: MemoryConnector, recording_id: str) -> str:
    """Return the note stored with a recording, empty when there is none.

    A recording that was never annotated and one whose note was cleared read
    the same, because they are the same: clearing a note removes the file.
    """
    try:
        return memory.read_text(recording_id, NOTES_FILE)
    except BlobNotFound:
        return ""


def write_note(memory: MemoryConnector, recording_id: str, text: str) -> str:
    """Store the note of a recording, replacing whatever was there.

    A note holding nothing but blank space is not a note: the file is deleted
    instead of being written empty, so the folder — and the archive built from
    it — carries only what somebody actually wrote.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the note belongs to.
        text: The note, as Markdown.

    Returns:
        The note as it is now stored, which is empty when it was cleared.
    """
    if not text.strip():
        memory.delete_file(recording_id, NOTES_FILE)
        return ""
    memory.write_text(recording_id, NOTES_FILE, text)
    return text


def list_attachments(memory: MemoryConnector, recording_id: str) -> list[Attachment]:
    """List the files stored with the note of a recording, by name.

    The folder listing is the whole of the truth: nothing about an attachment
    is written to the index, so a file dropped into the folder by hand is an
    attachment too, and one deleted behind the app's back is simply gone.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording whose attachments are listed.

    Returns:
        The attachments, in the order their names sort. Empty when the
        recording holds none, or does not exist.
    """
    directory = memory.recording_dir(recording_id) / ATTACHMENTS_DIR
    if not directory.is_dir():
        return []
    return [
        _describe(path)
        for path in sorted(directory.iterdir(), key=lambda entry: entry.name)
        if path.is_file() and not path.name.endswith(".tmp")
    ]


def add_attachment(
    memory: MemoryConnector,
    recording_id: str,
    filename: str,
    source: BinaryIO | Path | bytes | bytearray | memoryview,
) -> Attachment:
    """Store a file with the note of a recording, under a safe name.

    The name the client sent is kept as far as it can be — it is what the
    person recognises the file by — but it is a name that will be written to
    disk and handed back in a URL, so anything but letters, digits, dashes and
    dots is replaced. A name already taken is given a number rather than
    overwritten: two screenshots pasted from the same tool carry the same
    name, and neither of them is a correction of the other.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the file is stored with.
        filename: Name the file arrived under.
        source: An open binary stream, a path to copy from, or raw bytes.

    Returns:
        The attachment as it was stored, under the name it actually took.
    """
    taken = {entry.name for entry in list_attachments(memory, recording_id)}
    name = _free_name(filename, taken)
    path = memory.save_file(recording_id, f"{ATTACHMENTS_DIR}/{name}", source)
    return _describe(path)


def delete_attachment(memory: MemoryConnector, recording_id: str, name: str) -> bool:
    """Delete one file stored with the note of a recording.

    Args:
        memory: Storage the recording lives in.
        recording_id: Recording the file is stored with.
        name: File name inside the attachments folder.

    Returns:
        ``True`` when a file was removed, ``False`` when it was already gone.
    """
    if not _is_plain_name(name):
        return False
    return memory.delete_file(recording_id, f"{ATTACHMENTS_DIR}/{name}")


def attachment_file(
    memory: MemoryConnector, recording_id: str, name: str
) -> Path | None:
    """Return the path of one attachment, or ``None`` when there is no such file.

    The name is checked before it is joined: it arrives from a URL, and a
    single segment of a file name is the only thing it is ever allowed to be.
    """
    if not _is_plain_name(name):
        return None
    path = memory.recording_dir(recording_id) / ATTACHMENTS_DIR / name
    return path if path.is_file() else None


def has_notes(memory: MemoryConnector, recording_id: str) -> bool:
    """Tell whether a recording carries a note or any file stored with one."""
    return memory.has_file(recording_id, NOTES_FILE) or bool(
        list_attachments(memory, recording_id)
    )


def attachment_type(name: str) -> str:
    """Return what a stored attachment is served as, guessed from its name."""
    return mimetypes.guess_type(name)[0] or _FALLBACK_TYPE


# ------------------------------------------------------------------- helpers


def _describe(path: Path) -> Attachment:
    """Read what the filesystem knows about a stored attachment."""
    stat = path.stat()
    return Attachment(
        name=path.name,
        media_type=attachment_type(path.name),
        size=stat.st_size,
        added_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def _is_plain_name(name: str) -> bool:
    """Tell whether a name addresses one file inside the attachments folder."""
    return bool(name) and name not in {".", ".."} and Path(name).name == name


def _free_name(filename: str, taken: set[str]) -> str:
    """Turn an uploaded name into a safe one no stored file already carries."""
    original = Path(filename).name
    stem = _UNSAFE_IN_FILENAME.sub("-", Path(original).stem).strip("-.")[:_MAX_STEM]
    suffix = _UNSAFE_IN_FILENAME.sub("", Path(original).suffix)[:16]
    stem = stem or _FALLBACK_NAME

    candidate = f"{stem}{suffix}"
    counter = 2
    while candidate in taken:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate
