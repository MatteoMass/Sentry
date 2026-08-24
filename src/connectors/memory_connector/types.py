"""Shared types, statuses and errors of the memory connector."""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final, Literal

RecordingStatus = Literal[
    "to_process",
    "transcribing",
    "transcribed",
    "summarizing",
    "processed",
    "error",
]
"""Where a recording sits in a pipeline made of two steps, not one.

Transcribing costs minutes and money, summarising costs seconds; keeping them
apart in the status is what lets a recording whose summary failed be seen for
what it is — a transcript that is already paid for — rather than as a run to
start over. ``transcribed`` is therefore a resting state, not a passing one:
the audio has been recognised and nothing more has been asked for yet.
"""

RECORDING_STATUSES: tuple[RecordingStatus, ...] = (
    "to_process",
    "transcribing",
    "transcribed",
    "summarizing",
    "processed",
    "error",
)

RUNNING_STATUSES: tuple[RecordingStatus, ...] = ("transcribing", "summarizing")
"""The statuses that mean a worker is holding the recording right now."""

LEGACY_STATUSES: dict[str, RecordingStatus] = {"processing": "transcribing"}
"""Statuses of the single step pipeline, and what they became.

A row left in ``processing`` was being worked on when the process last died,
and the step it died in is no longer knowable; ``transcribing`` is the one it
had certainly reached.
"""

MAX_FOLDER_NAME_LENGTH: Final = 128
MAX_RECORDING_NAME_LENGTH: Final = 256

_FORBIDDEN_IN_NAME: Final = ("/", "\\", "\x00")


class _Sentinel(Enum):
    """Singletons used where ``None`` already carries another meaning."""

    ANY_FOLDER = "any_folder"


ANY_FOLDER: Final = _Sentinel.ANY_FOLDER
"""Placed where a folder is expected, it means "wherever it sits".

A folder filter needs three answers, not two: this folder, the top level, or
no filtering at all. ``None`` is already spoken for — it is how a recording
sitting at the top level stores its (absent) parent — so the third answer
needs a value of its own.
"""

FolderFilter = str | None | Literal[_Sentinel.ANY_FOLDER]
"""A folder id, ``None`` for the top level, or :data:`ANY_FOLDER` for all."""


class MemoryConnectorError(Exception):
    """Base class for every error raised by the memory connector."""


class RecordingNotFound(MemoryConnectorError):
    """Raised when no recording exists for the requested id."""


class RecordingAlreadyExists(MemoryConnectorError):
    """Raised when creating a recording whose id is already taken."""


class FolderNotFound(MemoryConnectorError):
    """Raised when no folder exists for the requested id."""


class FolderAlreadyExists(MemoryConnectorError):
    """Raised when a sibling folder already carries that name."""


class FolderNotEmpty(MemoryConnectorError):
    """Raised when deleting a folder that still holds something."""


class InvalidFolderMove(MemoryConnectorError):
    """Raised when a move would put a folder inside its own subtree."""


class InvalidFolderName(MemoryConnectorError):
    """Raised when a folder name is empty or holds a path separator."""


class InvalidRecordingName(MemoryConnectorError):
    """Raised when a recording name is empty or holds a path separator."""


class BlobNotFound(MemoryConnectorError):
    """Raised when a file is missing from a recording folder."""


class InvalidKey(MemoryConnectorError):
    """Raised when an id or a file name would escape the storage root."""


@dataclass(frozen=True, slots=True)
class Recording:
    """One row of the recordings table.

    Attributes:
        id: Unique identifier, also the name of the recording folder.
        name: Human readable name, usually the original file name.
        uploaded_at: Moment the recording entered the system, in UTC.
        status: Where the recording sits in the processing pipeline.
        folder_id: Folder holding the recording, or ``None`` for the top
            level. It says nothing about where the files live: on disk every
            recording stays directly under the recordings root.
    """

    id: str
    name: str
    uploaded_at: datetime
    status: RecordingStatus
    folder_id: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Recording":
        """Build a recording from a database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
            status=row["status"],
            folder_id=row["folder_id"],
        )


@dataclass(frozen=True, slots=True)
class Folder:
    """One row of the folders table.

    Folders exist only in the index: they group recordings for whoever is
    browsing them, and never appear on disk.

    Attributes:
        id: Unique identifier.
        name: Name shown to the user, unique among its siblings.
        parent_id: Folder holding this one, or ``None`` at the top level.
        created_at: Moment the folder was created, in UTC.
    """

    id: str
    name: str
    parent_id: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Folder":
        """Build a folder from a database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            parent_id=row["parent_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def new_recording_id() -> str:
    """Return a fresh identifier, safe to use as a folder name."""
    return uuid.uuid4().hex


def new_folder_id() -> str:
    """Return a fresh folder identifier."""
    return uuid.uuid4().hex


def validate_status(status: str) -> None:
    """Reject a status that is not part of the pipeline.

    Raises:
        ValueError: If ``status`` is not one of :data:`RECORDING_STATUSES`.
    """
    if status not in RECORDING_STATUSES:
        raise ValueError(
            f"Invalid status: {status!r}. Expected one of: {RECORDING_STATUSES}"
        )


def normalize_recording_name(name: str) -> str:
    """Return a recording name stripped of its surrounding spaces.

    The name is what the recording is called, never where its files sit: those
    live under the identifier, so renaming moves nothing. Separators are
    refused all the same, since the name is what a download is offered under
    and a name holding one would be read as a path there.

    Raises:
        InvalidRecordingName: If the name is empty, too long, or holds a
            separator.
    """
    cleaned = name.strip()
    if not cleaned:
        raise InvalidRecordingName("A recording name cannot be empty.")
    if len(cleaned) > MAX_RECORDING_NAME_LENGTH:
        raise InvalidRecordingName(
            f"Name too long: at most {MAX_RECORDING_NAME_LENGTH} characters."
        )
    if any(character in cleaned for character in _FORBIDDEN_IN_NAME):
        raise InvalidRecordingName(f"Invalid recording name: {name!r}")
    if cleaned in {".", ".."}:
        raise InvalidRecordingName(f"Invalid recording name: {name!r}")
    return cleaned


def normalize_folder_name(name: str) -> str:
    """Return a folder name stripped of its surrounding spaces.

    A name never reaches the filesystem, so this is not a defence against path
    traversal; separators are refused because a name holding one could not be
    told apart from a path once the tree is rendered as ``a/b/c``.

    Raises:
        InvalidFolderName: If the name is empty, too long, or holds a
            separator.
    """
    cleaned = name.strip()
    if not cleaned:
        raise InvalidFolderName("A folder name cannot be empty.")
    if len(cleaned) > MAX_FOLDER_NAME_LENGTH:
        raise InvalidFolderName(
            f"Name too long: at most {MAX_FOLDER_NAME_LENGTH} characters."
        )
    if any(character in cleaned for character in _FORBIDDEN_IN_NAME):
        raise InvalidFolderName(f"Invalid folder name: {name!r}")
    if cleaned in {".", ".."}:
        raise InvalidFolderName(f"Invalid folder name: {name!r}")
    return cleaned
