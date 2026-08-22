"""The contract a speech-to-text backend answers to.

One call, one recording: a media file goes in and a diarized
:class:`~core.types.Transcript` comes out, with the words credited to the
voices that said them and the timestamps counted from the start of the
recording.

What happens in between belongs to the backend alone. How much audio travels
at a time, in what encoding, in one request or in fifteen, and whether the
speakers are told apart by the provider or by a model listening to them are
all answers only the backend has — so the file is handed over as it was
uploaded, and nothing above this line has to know what its API will take.

:mod:`core.gemini_speech` is the implementation the pipeline builds by
default, and the only one there is.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from core.types import Transcript

LANGUAGE_ENV = "SENTRY_TRANSCRIPTION_LANGUAGE"
"""Environment variable naming the language the recordings are expected in."""


class SpeechToText(ABC):
    """Base class for a backend that turns audio into a diarized transcript.

    Subclasses wrap one vendor API behind a single call, so the pipeline can
    change provider without knowing that anything changed.
    """

    @property
    @abstractmethod
    def provider(self) -> str:
        """Name of the underlying provider, e.g. ``'gemini'``."""

    @abstractmethod
    def transcribe(self, media: Path | str) -> Transcript:
        """Transcribe a media file, telling the speakers apart.

        Args:
            media: Audio or video file to transcribe.

        Returns:
            The dialogue, in chronological order, with timestamps counted from
            the start of the recording.

        Raises:
            AudioError: If the media cannot be turned into sendable audio.
            TranscriptionError: If the provider refuses or fails the job.
        """

    def close(self) -> None:
        """Release whatever the backend holds open.

        Backends that hold nothing — a stub, a local model — inherit this and
        do nothing, so a caller can close any of them without asking which.
        """

    def __repr__(self) -> str:
        """Return a debug representation showing the provider."""
        return f"{type(self).__name__}(provider={self.provider!r})"
