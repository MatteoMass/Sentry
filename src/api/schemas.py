"""Payloads exchanged over HTTP."""

from datetime import datetime
from typing import Final

from pydantic import BaseModel, Field

from connectors.memory_connector import Folder, Recording, RecordingStatus
from core import Summary, Transcript, Utterance, speaker_label

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
    """A recording as the API exposes it.

    The status says what the pipeline is doing or last did; the two flags say
    what came of it, which is not the same question. A recording in ``error``
    holding a transcript failed at the summary and has to be offered one more
    summary, not another transcription — and only the flags can tell the
    client that.
    """

    id: str = Field(description="Identifier of the recording.")
    name: str = Field(description="Human readable name, usually the file name.")
    uploaded_at: datetime = Field(description="Moment the upload completed, in UTC.")
    status: RecordingStatus = Field(description="Where it sits in the pipeline.")
    folder: str | None = Field(
        default=None,
        description="Folder holding it, or null when it sits at the top level.",
    )
    has_transcript: bool = Field(
        default=False, description="Whether a transcript is stored with it."
    )
    has_summary: bool = Field(
        default=False, description="Whether a summary is stored with it."
    )
    media_type: str | None = Field(
        default=None,
        description=(
            "Media type of the stored file, null when the folder holds no"
            " media. It is what tells a client whether to draw a player, and"
            " which one."
        ),
    )

    @classmethod
    def from_recording(
        cls,
        recording: Recording,
        *,
        has_transcript: bool = False,
        has_summary: bool = False,
        media_type: str | None = None,
    ) -> "RecordingOut":
        """Build the payload from a connector recording and what it holds."""
        return cls(
            id=recording.id,
            name=recording.name,
            uploaded_at=recording.uploaded_at,
            status=recording.status,
            folder=recording.folder_id,
            has_transcript=has_transcript,
            has_summary=has_summary,
            media_type=media_type,
        )


class UtteranceOut(BaseModel):
    """One uninterrupted run of words from a single speaker."""

    speaker: int = Field(description="Diarization tag, 0 when unknown.")
    label: str = Field(description="Name shown for that voice, e.g. 'Speaker 2'.")
    text: str = Field(description="What was said, as one paragraph.")
    start: float = Field(description="Offset of the first word, in seconds.")
    end: float = Field(description="Offset of the last word, in seconds.")

    @classmethod
    def from_utterance(cls, utterance: Utterance) -> "UtteranceOut":
        """Build the payload from a core utterance."""
        return cls(
            speaker=utterance.speaker,
            label=utterance.label,
            text=utterance.text,
            start=utterance.start,
            end=utterance.end,
        )


class TranscriptOut(BaseModel):
    """What the first step produced, as the API exposes it."""

    language: str = Field(description="Language the audio was recognised with.")
    provider: str = Field(description="Speech-to-text backend that produced it.")
    model: str = Field(description="Recognition model used.")
    duration: float = Field(description="Length of the transcribed audio, in seconds.")
    speakers: list[str] = Field(
        description="The voices told apart, in the order they first talk."
    )
    utterances: list[UtteranceOut] = Field(description="The dialogue, in order.")

    @classmethod
    def from_transcript(cls, transcript: Transcript) -> "TranscriptOut":
        """Build the payload from a core transcript."""
        return cls(
            language=transcript.language,
            provider=transcript.provider,
            model=transcript.model,
            duration=transcript.duration,
            speakers=[speaker_label(tag) for tag in transcript.speakers],
            utterances=[
                UtteranceOut.from_utterance(utterance)
                for utterance in transcript.utterances
            ],
        )


class SummaryOut(BaseModel):
    """What the second step produced, as the API exposes it."""

    overview: str = Field(description="A few sentences on what it was about.")
    key_points: list[str] = Field(description="The salient points.")
    decisions: list[str] = Field(description="What was settled.")
    action_items: list[str] = Field(description="What somebody agreed to do.")
    model: str = Field(description="Model that wrote it.")
    markdown: str = Field(description="The same summary, ready to be read.")

    @classmethod
    def from_summary(
        cls, summary: Summary, *, title: str | None = None
    ) -> "SummaryOut":
        """Build the payload from a core summary."""
        return cls(
            overview=summary.overview,
            key_points=list(summary.key_points),
            decisions=list(summary.decisions),
            action_items=list(summary.action_items),
            model=summary.model,
            markdown=summary.to_markdown(title=title),
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


class RecordingRename(BaseModel):
    """What a client sends to give a recording another name.

    Only the name travels: where the recording sits is a move, which is its
    own request, and nothing else about it is the client's to set.
    """

    name: str = Field(min_length=1, description="New name to show.")
