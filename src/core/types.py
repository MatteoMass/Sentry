"""Shared types and errors of the processing pipeline.

A recording walks the same path whoever does the listening: media goes in, a
diarized :class:`Transcript` comes out, and a :class:`Summary` keeps only what
is worth remembering of it. Both know how to serialise themselves, because
they are stored as files inside the recording folder rather than as rows, and
whoever reads them back — the API, a worker, a later run of the pipeline —
must find them in the shape they were left.
"""

from dataclasses import dataclass
from typing import Any, Self

UNKNOWN_SPEAKER = 0
"""Tag used when the provider returned words without telling speakers apart."""


class CoreError(Exception):
    """Base class for every error raised by the processing pipeline."""


class MediaNotFound(CoreError):
    """Raised when a recording folder holds no media file to work on."""


class AudioError(CoreError):
    """Raised when the media cannot be turned into audio the API accepts."""


class TranscriptionError(CoreError):
    """Raised when the speech-to-text provider refuses or fails the job."""


class SummarizationError(CoreError):
    """Raised when the model does not return a summary that can be read."""


def format_timestamp(seconds: float) -> str:
    """Return ``seconds`` as ``HH:MM:SS``, for a timestamp a human reads."""
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def speaker_label(tag: int) -> str:
    """Return the name shown for a speaker tag.

    Diarization tells voices apart, not who they belong to, so a tag is all
    there is: ``1`` becomes ``"Speaker 1"``, and the absence of a tag becomes
    ``"Speaker ?"``.
    """
    return f"Speaker {tag}" if tag != UNKNOWN_SPEAKER else "Speaker ?"


@dataclass(frozen=True, slots=True)
class Utterance:
    """An uninterrupted run of words from a single speaker.

    This is the unit the rest of the system reads: words are what the provider
    returns, but nobody reads a transcript one word at a time.

    Attributes:
        speaker: Diarization tag of the voice.
        text: What was said, as one paragraph.
        start: Offset of the first word, in seconds.
        end: Offset of the last word, in seconds.
    """

    speaker: int
    text: str
    start: float
    end: float

    @property
    def label(self) -> str:
        """Name shown for the speaker, e.g. ``'Speaker 2'``."""
        return speaker_label(self.speaker)

    @property
    def line(self) -> str:
        """The utterance as one dialogue line, timestamp and speaker first."""
        return f"[{format_timestamp(self.start)}] {self.label}: {self.text}"

    def to_dict(self) -> dict[str, Any]:
        """Return the utterance as plain JSON types."""
        return {
            "speaker": self.speaker,
            "text": self.text,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Rebuild an utterance from :meth:`to_dict`."""
        return cls(
            speaker=int(payload["speaker"]),
            text=payload["text"],
            start=float(payload["start"]),
            end=float(payload["end"]),
        )


@dataclass(frozen=True, slots=True)
class Transcript:
    """What was said in a recording, split by speaker.

    Attributes:
        utterances: The dialogue, in chronological order.
        language: Language code the audio was transcribed with.
        provider: Name of the speech-to-text backend, e.g. ``'google'``.
        model: Recognition model that produced it.
        duration: Length of the transcribed audio, in seconds.
    """

    utterances: tuple[Utterance, ...]
    language: str
    provider: str
    model: str
    duration: float = 0.0

    @property
    def speakers(self) -> tuple[int, ...]:
        """The distinct speaker tags, in the order they first talk."""
        seen: dict[int, None] = {}
        for utterance in self.utterances:
            seen.setdefault(utterance.speaker, None)
        return tuple(seen)

    @property
    def text(self) -> str:
        """The plain transcript, one paragraph per utterance, no labels."""
        return "\n".join(utterance.text for utterance in self.utterances)

    @property
    def dialogue(self) -> str:
        """The transcript as timestamped, labelled lines.

        This is the form handed to the model and written to
        ``transcript.txt``: without the labels a summary cannot tell who
        committed to what.
        """
        return "\n".join(utterance.line for utterance in self.utterances)

    def __bool__(self) -> bool:
        """Tell whether anything was recognised at all."""
        return bool(self.utterances)

    def to_dict(self) -> dict[str, Any]:
        """Return the transcript as plain JSON types."""
        return {
            "language": self.language,
            "provider": self.provider,
            "model": self.model,
            "duration": self.duration,
            "speakers": list(self.speakers),
            "utterances": [utterance.to_dict() for utterance in self.utterances],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Rebuild a transcript from :meth:`to_dict`."""
        return cls(
            utterances=tuple(
                Utterance.from_dict(item) for item in payload["utterances"]
            ),
            language=payload["language"],
            provider=payload["provider"],
            model=payload["model"],
            duration=float(payload.get("duration", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class Summary:
    """The handful of things worth remembering of a recording.

    The fields are separated because they are acted upon differently: an
    overview is read once, a decision is quoted later, and an action item is
    chased. Any of the lists can be empty — a rambling conversation decides
    nothing, and saying so is more useful than inventing entries.

    Attributes:
        overview: A few sentences on what the recording was about.
        key_points: The salient points, each standing on its own.
        decisions: What was settled.
        action_items: What somebody agreed to do, with the owner when named.
        model: Model that wrote the summary.
    """

    overview: str
    key_points: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    action_items: tuple[str, ...] = ()
    model: str = ""

    def to_markdown(self, *, title: str | None = None) -> str:
        """Render the summary as the Markdown stored next to the transcript.

        Args:
            title: Heading to open with, usually the recording name. When
                ``None`` the document starts at the first section.

        Returns:
            A Markdown document holding only the sections that have content.
        """
        blocks: list[str] = []
        if title:
            blocks.append(f"# {title}")
        if self.overview:
            blocks.append(f"## Sintesi\n\n{self.overview}")
        for heading, entries in (
            ("Punti salienti", self.key_points),
            ("Decisioni", self.decisions),
            ("Azioni", self.action_items),
        ):
            if entries:
                items = "\n".join(f"- {entry}" for entry in entries)
                blocks.append(f"## {heading}\n\n{items}")
        return "\n\n".join(blocks) + "\n"

    def to_dict(self) -> dict[str, Any]:
        """Return the summary as plain JSON types."""
        return {
            "overview": self.overview,
            "key_points": list(self.key_points),
            "decisions": list(self.decisions),
            "action_items": list(self.action_items),
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Rebuild a summary from :meth:`to_dict`."""
        return cls(
            overview=payload.get("overview", ""),
            key_points=tuple(payload.get("key_points", ())),
            decisions=tuple(payload.get("decisions", ())),
            action_items=tuple(payload.get("action_items", ())),
            model=payload.get("model", ""),
        )
