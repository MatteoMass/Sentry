"""Shared types, statuses and errors of the memory connector."""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

RecordingStatus = Literal["to_process", "processing", "processed", "error"]

RECORDING_STATUSES: tuple[RecordingStatus, ...] = (
    "to_process",
    "processing",
    "processed",
    "error",
)


class MemoryConnectorError(Exception):
    """Base class for every error raised by the memory connector."""


class RecordingNotFound(MemoryConnectorError):
    """Raised when no recording exists for the requested id."""


class RecordingAlreadyExists(MemoryConnectorError):
    """Raised when creating a recording whose id is already taken."""


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
    """

    id: str
    name: str
    uploaded_at: datetime
    status: RecordingStatus

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Recording":
        """Build a recording from a database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
            status=row["status"],
        )


def new_recording_id() -> str:
    """Return a fresh identifier, safe to use as a folder name."""
    return uuid.uuid4().hex


def validate_status(status: str) -> None:
    """Reject a status that is not part of the pipeline.

    Raises:
        ValueError: If ``status`` is not one of :data:`RECORDING_STATUSES`.
    """
    if status not in RECORDING_STATUSES:
        raise ValueError(
            f"Stato non valido: {status!r}. Attesi: {RECORDING_STATUSES}"
        )
