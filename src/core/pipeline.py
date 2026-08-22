"""The path a recording walks from uploaded media to a summary.

An upload lands in ``to_process`` and stops there: the API stores bytes and
nothing else. This is where the rest happens — the audio is extracted, sent to
be transcribed and diarized, and what comes back is written next to the media
and handed to the model that summarises it.

Every step leaves its result on disk before the next one starts, which is what
makes the pipeline cheap to resume: a summary that failed is retried against
the transcript already paid for, and only ``force`` makes the audio travel
again. The status is moved in step with those files, so a recording is never
reported ``processed`` while something is still missing from its folder.

The two steps are also two statuses, and can be asked for one at a time. A
transcription that succeeded is worth keeping whatever becomes of the summary:
it settles on ``transcribed``, and a summary that then fails leaves the
recording in ``error`` with its transcript still there to be read — and to be
summarised again without the audio ever travelling twice.
"""

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from connectors.memory_connector import (
    BlobNotFound,
    MemoryConnector,
    MemoryConnectorError,
    Recording,
    RecordingStatus,
)
from core.gemini_speech import GeminiSpeechToText
from core.speech import SpeechToText
from core.summarizer import Summarizer
from core.types import (
    CoreError,
    MediaNotFound,
    SummarizationError,
    Summary,
    Transcript,
)

TRANSCRIPT_JSON = "transcript.json"
TRANSCRIPT_TEXT = "transcript.txt"
SUMMARY_JSON = "summary.json"
SUMMARY_MARKDOWN = "summary.md"

ARTIFACTS: frozenset[str] = frozenset(
    {TRANSCRIPT_JSON, TRANSCRIPT_TEXT, SUMMARY_JSON, SUMMARY_MARKDOWN}
)
"""The files the pipeline writes; everything else in a folder is the media."""

MEDIA_BASENAME = "recording"
"""Stem the upload endpoint gives the media, extension aside."""


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """What one run of the pipeline produced.

    Attributes:
        recording: The recording as it stands once processed.
        transcript: What was said, split by speaker.
        summary: What is worth remembering of it.
    """

    recording: Recording
    transcript: Transcript
    summary: Summary


class ProcessingPipeline:
    """Transcribes and summarises the recordings held by a connector.

    The two backends are built on first use, so a pipeline can be constructed
    where no API key is set — at application startup, say — and only fail when
    it is actually asked to do something.

    Example:
        >>> pipeline = ProcessingPipeline(MemoryConnector("./data"))
        >>> result = pipeline.process(recording_id)
        >>> print(result.summary.to_markdown())
    """

    def __init__(
        self,
        memory: MemoryConnector,
        *,
        transcriber: SpeechToText | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        """Bind the pipeline to a storage, and optionally to given backends.

        Args:
            memory: Storage holding the media and receiving the results.
            transcriber: Speech-to-text backend. When ``None`` a
                :class:`GeminiSpeechToText` is built on first use.
            summarizer: Summariser. When ``None`` a default
                :class:`Summarizer` is built on first use.
        """
        self.memory = memory
        self._transcriber = transcriber
        self._summarizer = summarizer

    @property
    def transcriber(self) -> SpeechToText:
        """The speech-to-text backend, built on first use when not given."""
        if self._transcriber is None:
            self._transcriber = GeminiSpeechToText()
        return self._transcriber

    @property
    def summarizer(self) -> Summarizer:
        """The summariser, built on first use when not given."""
        if self._summarizer is None:
            self._summarizer = Summarizer()
        return self._summarizer

    # ---------------------------------------------------------- the pipeline

    def process(self, recording_id: str, *, force: bool = False) -> ProcessingResult:
        """Take one recording all the way to its summary.

        Both steps run, each moving the status on its own, so a run that dies
        halfway is found in the state it actually reached rather than in a
        blanket ``processing``.

        Args:
            recording_id: Recording to process.
            force: Redo the work even where a result is already on disk.

        Returns:
            The transcript and the summary, with the recording as it now
            stands.

        Raises:
            RecordingNotFound: If no recording matches ``recording_id``.
            CoreError: If either step fails. The recording is left in
                ``error``, keeping whatever the step before it had stored.
        """
        self.memory.get_recording(recording_id)

        transcript = self.transcribe(recording_id, force=force)
        summary = self.summarize(recording_id, transcript, force=force)

        # Both steps report their own outcome; this only covers the run where
        # each of them had nothing left to do and moved nothing.
        recording = self.memory.update_status(recording_id, "processed")
        return ProcessingResult(
            recording=recording, transcript=transcript, summary=summary
        )

    def process_pending(
        self,
        *,
        limit: int | None = None,
        on_error: Callable[[Recording, CoreError], None] | None = None,
    ) -> list[ProcessingResult]:
        """Process the recordings waiting in ``to_process``, oldest first.

        Each recording is claimed atomically before any work starts, so two
        workers running side by side never pick up the same one.

        Args:
            limit: Most recordings to process. ``None`` drains the queue.
            on_error: Called with the recording and the failure when one goes
                wrong. The run continues either way, and the recording is left
                in ``error``; without a callback the failure is only visible
                as that status.

        Returns:
            The results of the recordings that made it through.
        """
        results: list[ProcessingResult] = []

        while limit is None or len(results) < limit:
            claimed = self.memory.claim_next()
            if claimed is None:
                break
            try:
                results.append(self.process(claimed.id))
            except CoreError as error:
                if on_error is not None:
                    on_error(claimed, error)

        return results

    # ------------------------------------------------------------- the steps

    def transcribe(self, recording_id: str, *, force: bool = False) -> Transcript:
        """Transcribe and diarize the media of a recording.

        The transcript is written to ``transcript.json``, and to a readable
        ``transcript.txt`` beside it. An existing one is reused unless
        ``force`` is set: sending the audio again is the expensive half of the
        pipeline.

        The recording is left in ``transcribed`` — the step is a resting place
        of its own, and reaching it is worth recording whether or not anybody
        goes on to ask for a summary. A stored summary is dropped when the
        audio is transcribed again, since it describes a dialogue that no
        longer exists.

        Args:
            recording_id: Recording whose media is transcribed.
            force: Transcribe again even if a transcript is already there.

        Returns:
            The dialogue, in chronological order.

        Raises:
            MediaNotFound: If the recording folder holds no media.
            AudioError: If the media cannot be turned into sendable audio.
            TranscriptionError: If the provider refuses or fails the job.
        """
        if not force:
            if (existing := self.read_transcript(recording_id)) is not None:
                return existing

        self.memory.update_status(recording_id, "transcribing")
        try:
            media = self.media_path(recording_id)
            transcript = self.transcriber.transcribe(media)

            self.memory.write_text(
                recording_id,
                TRANSCRIPT_JSON,
                json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2),
            )
            self.memory.write_text(recording_id, TRANSCRIPT_TEXT, transcript.dialogue)
            self._discard_summary(recording_id)
        except BaseException:
            self._failed(recording_id)
            raise

        self.memory.update_status(recording_id, "transcribed")
        return transcript

    def summarize(
        self,
        recording_id: str,
        transcript: Transcript | None = None,
        *,
        force: bool = False,
    ) -> Summary:
        """Summarise the transcript of a recording.

        The summary is written to ``summary.json``, and rendered to
        ``summary.md`` for whoever reads it rather than parses it. This is the
        cheap half of the pipeline, and the one that can be asked for on its
        own: the transcript it reads has already been paid for, so a failed
        summary is retried without the audio travelling again.

        Args:
            recording_id: Recording to summarise.
            transcript: The dialogue to read. When ``None`` it is read back
                from the recording folder.
            force: Summarise again even if a summary is already there.

        Returns:
            The summary, as it was stored.

        Raises:
            SummarizationError: If no transcript is stored and none was
                given, or if the model fails or answers unusably. The
                recording is left in ``error``, transcript untouched.
        """
        if not force:
            if (existing := self.read_summary(recording_id)) is not None:
                return existing

        self.memory.update_status(recording_id, "summarizing")
        try:
            if transcript is None:
                transcript = self.read_transcript(recording_id)
                if transcript is None:
                    raise SummarizationError(
                        f"No transcript stored for recording {recording_id!r}."
                    )

            recording = self.memory.get_recording(recording_id)
            summary = self.summarizer.summarize(transcript)

            self.memory.write_text(
                recording_id,
                SUMMARY_JSON,
                json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
            )
            self.memory.write_text(
                recording_id,
                SUMMARY_MARKDOWN,
                summary.to_markdown(title=recording.name),
            )
        except BaseException:
            self._failed(recording_id)
            raise

        self.memory.update_status(recording_id, "processed")
        return summary

    # ------------------------------------------------------- reading it back

    def read_transcript(self, recording_id: str) -> Transcript | None:
        """Return the stored transcript of a recording, or ``None``."""
        return _read(self.memory, recording_id, TRANSCRIPT_JSON, Transcript.from_dict)

    def read_summary(self, recording_id: str) -> Summary | None:
        """Return the stored summary of a recording, or ``None``."""
        return _read(self.memory, recording_id, SUMMARY_JSON, Summary.from_dict)

    def has_transcript(self, recording_id: str) -> bool:
        """Tell whether the transcription step has left its result on disk."""
        return self.memory.has_file(recording_id, TRANSCRIPT_JSON)

    def has_summary(self, recording_id: str) -> bool:
        """Tell whether the summarisation step has left its result on disk."""
        return self.memory.has_file(recording_id, SUMMARY_JSON)

    def next_status(self, recording_id: str, *, force: bool = False) -> RecordingStatus:
        """Return the status a full run would move the recording to first.

        A caller answering before the work starts — the API does, since no
        browser waits minutes for a transcription — has to say where the
        recording now sits, and that depends on what is already stored.
        """
        return (
            "transcribing"
            if force or not self.has_transcript(recording_id)
            else "summarizing"
        )

    def media_path(self, recording_id: str) -> Path:
        """Return the media file of a recording.

        The upload endpoint stores it as ``recording.<ext>``, so that name
        wins; anything else in the folder that the pipeline did not write is
        taken as the media, which keeps a hand placed file working.

        Raises:
            MediaNotFound: If the folder holds nothing but artifacts.
        """
        candidates = [
            name for name in self.memory.list_files(recording_id)
            if name not in ARTIFACTS
        ]
        if not candidates:
            raise MediaNotFound(f"No media stored for recording {recording_id!r}.")

        chosen = next(
            (name for name in candidates if Path(name).stem == MEDIA_BASENAME),
            candidates[0],
        )
        return self.memory.recording_dir(recording_id) / chosen

    def _failed(self, recording_id: str) -> None:
        """Record that the running step is over and went wrong.

        The recording must not stay in a running status once nobody is working
        on it, and a failure to say so cannot be allowed to replace the
        failure that caused it — which is the only reason the storage error is
        swallowed here.
        """
        with suppress(MemoryConnectorError):
            self.memory.update_status(recording_id, "error")

    def _discard_summary(self, recording_id: str) -> None:
        """Drop a summary that no longer belongs to the stored transcript."""
        for filename in (SUMMARY_JSON, SUMMARY_MARKDOWN):
            with suppress(MemoryConnectorError):
                self.memory.delete_file(recording_id, filename)

    def close(self) -> None:
        """Release what the backends hold open, the storage aside.

        The connector is not closed here: the pipeline was handed it and does
        not own it, whereas the recogniser it built is its own to release.
        """
        if self._transcriber is not None:
            self._transcriber.close()

    def __repr__(self) -> str:
        """Return a debug representation showing the storage behind it."""
        return f"{type(self).__name__}(memory={self.memory!r})"


def _read[T](
    memory: MemoryConnector,
    recording_id: str,
    filename: str,
    build: Callable[[dict], T],
) -> T | None:
    """Read one stored artifact, treating a missing or broken file as absent.

    A half written file is worth no more than no file at all: both mean the
    step has to run again, and the next run overwrites it.
    """
    try:
        payload = json.loads(memory.read_text(recording_id, filename))
    except (BlobNotFound, json.JSONDecodeError):
        return None
    try:
        return build(payload)
    except (KeyError, TypeError, ValueError):
        return None
