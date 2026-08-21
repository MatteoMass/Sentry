"""Payloads exchanged over HTTP."""

from datetime import datetime
from typing import Final

from pydantic import BaseModel, Field

from connectors.memory_connector import Folder, Recording, RecordingStatus

ROOT: Final = "root"
"""How the top level is named over HTTP, where ``None`` cannot be spelled.

A recording outside every folder stores ``None`` as its parent, but a query
string has no way to say it and an omitted parameter already means "no filter
at all". Identifiers are hexadecimal, so the word can never collide with one.
"""

_FOLDER_REF = (
    f"Identifier of the folder, or {ROOT!r} for the top level."
)


def folder_ref(value: str | None) -> str | None:
    """Turn a folder reference coming from a client into a folder id.

    Args:
        value: A folder id, or :data:`ROOT` for the top level.

    Returns:
        The folder id, or ``None`` when the top level was asked for.
    """
    return None if value == ROOT else value


class RecordingOut(BaseModel):
    """A recording as the API exposes it."""

    id: str = Field(description="Identifier of the recording.")
    name: str = Field(description="Human readable name, usually the file name.")
    uploaded_at: datetime = Field(description="Moment the upload completed, in UTC.")
    status: RecordingStatus = Field(description="Where it sits in the pipeline.")
    folder: str | None = Field(
        default=None,
        description="Folder holding it, or null when it sits at the top level.",
    )

    @classmethod
    def from_recording(cls, recording: Recording) -> "RecordingOut":
        """Build the payload from a connector recording."""
        return cls(
            id=recording.id,
            name=recording.name,
            uploaded_at=recording.uploaded_at,
            status=recording.status,
            folder=recording.folder_id,
        )


class FolderOut(BaseModel):
    """A folder as the API exposes it."""

    id: str = Field(description="Identifier of the folder.")
    name: str = Field(description="Name shown to the user.")
    parent: str | None = Field(
        default=None,
        description="Folder holding it, or null when it sits at the top level.",
    )
    created_at: datetime = Field(description="Moment the folder was created, in UTC.")
    recordings: int = Field(
        default=0,
        description="Recordings filed directly in it, subfolders excluded.",
    )

    @classmethod
    def from_folder(cls, folder: Folder, *, recordings: int = 0) -> "FolderOut":
        """Build the payload from a connector folder."""
        return cls(
            id=folder.id,
            name=folder.name,
            parent=folder.parent_id,
            created_at=folder.created_at,
            recordings=recordings,
        )


class FolderCreate(BaseModel):
    """What a client sends to create a folder."""

    name: str = Field(min_length=1, description="Name to show.")
    parent: str | None = Field(default=None, description=_FOLDER_REF)


class FolderUpdate(BaseModel):
    """What a client sends to rename or move a folder.

    Both fields are optional and left out means "leave it as it is", so
    moving a folder to the top level is spelled ``{"parent": "root"}`` rather
    than with a null the API could not tell apart from an absence.
    """

    name: str | None = Field(
        default=None, min_length=1, description="New name, when renaming."
    )
    parent: str | None = Field(default=None, description=_FOLDER_REF)


class RecordingMove(BaseModel):
    """What a client sends to file a recording under another folder."""

    folder: str = Field(description=_FOLDER_REF)
