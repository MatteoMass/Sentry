"""Transcription and diarization done by Gemini, one piece of audio at a time.

Gemini reads the whole clip, writes what was said, and says
which voice said it.

Nothing is sent whole. A meeting goes up in pieces of a few minutes each,
transcribed one after another: a long request is a request that times out, and
a piece that fails is a piece that can be retried without the hour of audio
around it travelling again.

Cutting the audio, though, cuts what the model knows. It hears each piece
without memory of the last, and nothing stops the voice it called ``1`` at
minute four from becoming ``2`` at minute six — which would leave a transcript
where the speakers are numbered but nobody can be followed through it. Two
things are carried across the seam to prevent it: a roster describing every
voice heard so far, and the last seconds of the previous piece as a second
clip the model may listen to but must not transcribe. It is asked to reuse the
number of a voice it recognises, and to open a new one only for somebody it
has genuinely not heard before.
"""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Self

from google import genai
from google.genai import types as genai_types

from config import settings
from core.audio import PreparedAudio, prepare_audio, probe_duration, split_audio
from core.speech import SpeechToText
from core.types import (
    Transcript,
    TranscriptionError,
    Utterance,
    format_timestamp,
    speaker_label,
)

TAIL_LINES = 6
"""How many of the previous piece's lines are quoted into the next prompt."""

TAIL_CHARACTERS = 240
"""How much of one quoted line is kept; a whole paragraph is not needed."""

SYSTEM_PROMPT = """\
You transcribe recordings and tell the speakers apart.

Rules:
- Transcribe verbatim, in the language actually spoken. Never translate,
  never summarise, never tidy up what was said.
- Split the speech into utterances: one uninterrupted run of words by one
  speaker. Start a new utterance whenever the speaker changes.
- Timestamps are seconds from the start of the clip you are transcribing, and
  that clip alone.
- Give every voice an integer tag, and keep it: the same person must carry the
  same tag from the first second of the recording to the last.
- You are given the voices already identified in the earlier parts of this
  recording. Listen for them, and reuse their tags. Open a new tag only for
  somebody you are confident has not been heard before.
- Describe each voice you used, well enough for the next part of the
  recording to recognise it: pitch and timbre, pace, accent, the role the
  person plays in the conversation, and their name when it is said out loud.
  Describe it in English, however the recording is spoken.
- Transcribe only the clip you are told to transcribe. A context clip is
  there so that you can hear voices you already know; not one word of it
  belongs in your answer.
- Write one reading of what you hear. Never offer alternatives, and never
  annotate the text with brackets, notes or markup of any kind.
- Report only what is audible. Never invent speech to fill a silence, and
  return no utterances at all when nothing intelligible is said.\
"""

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "language": {
            "type": "STRING",
            "description": "BCP-47 tag of the language actually spoken, e.g. it-IT.",
        },
        "speakers": {
            "type": "ARRAY",
            "description": "Every voice used in this part, described.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "tag": {"type": "INTEGER"},
                    "description": {"type": "STRING"},
                },
                "required": ["tag", "description"],
            },
        },
        "utterances": {
            "type": "ARRAY",
            "description": "The dialogue of this part, in chronological order.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "speaker": {"type": "INTEGER"},
                    "start": {"type": "NUMBER"},
                    "end": {"type": "NUMBER"},
                    "text": {"type": "STRING"},
                },
                "required": ["speaker", "start", "end", "text"],
            },
        },
    },
    "required": ["language", "speakers", "utterances"],
}


@dataclass(frozen=True, slots=True)
class Voice:
    """One voice as the model described it, so a later piece can find it again.

    Attributes:
        tag: Number the voice carries through the whole recording.
        description: What it sounds like and who it belongs to, as far as the
            recording says.
    """

    tag: int
    description: str

    @property
    def line(self) -> str:
        """The voice as one line of the roster handed to the model."""
        return f"{speaker_label(self.tag)}: {self.description}"


class GeminiSpeechToText(SpeechToText):
    """Gemini as a diarizing recogniser, over pieces of a few minutes each.

    Example:
        >>> transcript = GeminiSpeechToText().transcribe(Path("meeting.m4a"))
        >>> print(transcript.dialogue)
        [00:00:01] Speaker 1: allora, partiamo dal budget
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        language: str | None = None,
        system_prompt: str | None = None,
        chunk_seconds: float | None = None,
        context_seconds: float | None = None,
        timeout: float | None = None,
        attempts: int | None = None,
        max_inline_bytes: int | None = None,
    ) -> None:
        """Configure the recogniser.

        Every argument left at ``None`` is taken from the ``transcription``
        section of the settings, which is where an installation says how it
        wants its audio sent; what is passed here overrules it, since a caller
        building its own recogniser has a reason to.

        Args:
            api_key: Key to call the API with. When ``None`` it is the one the
                environment carries, ``GEMINI_API_KEY`` then
                ``GOOGLE_API_KEY``.
            model: Model to listen with.
            language: Language the recording is expected to be in, as a BCP-47
                tag. It is a hint and not a rule — what the model reports
                hearing is what the transcript records.
            system_prompt: Instructions the recogniser listens under. When
                ``None`` the shipped :data:`SYSTEM_PROMPT` is used.
            chunk_seconds: Length of the pieces the audio is cut into.
            context_seconds: How much of the previous piece travels with each
                request so the voices can be matched across the seam. ``0``
                sends none of it, leaving only the written roster to go on.
            timeout: How long one request may take, in seconds.
            attempts: How many times a piece is tried before the recording is
                given up on.
            max_inline_bytes: Ceiling on the audio of one request. A piece too
                heavy for it is re-encoded to Opus rather than refused.

        Raises:
            TranscriptionError: If no API key can be found.
        """
        tuning = settings.transcription

        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise TranscriptionError(
                "Missing API key: pass `api_key` or set GEMINI_API_KEY."
            )

        self.model = model or tuning.model
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.language = language or tuning.language
        self.chunk_seconds = chunk_seconds or tuning.chunk_seconds
        self.context_seconds = max(
            0.0, tuning.context_seconds if context_seconds is None else context_seconds
        )
        self.timeout = timeout or tuning.timeout_seconds
        self.attempts = max(1, attempts or tuning.attempts)
        self.max_inline_bytes = max_inline_bytes or tuning.max_inline_bytes

    @property
    def provider(self) -> str:
        """Name of the underlying provider."""
        return "gemini"

    @cached_property
    def _client(self) -> genai.Client:
        """SDK client created on first use, reused across the pieces."""
        return genai.Client(api_key=self._api_key)

    def transcribe(self, media: Path | str) -> Transcript:
        """Transcribe a media file, telling the speakers apart.

        The audio is cut into pieces and they are sent one at a time, in
        order: sequential because each request is told what the one before it
        heard, and it is that thread — the roster, the last lines, the last
        seconds of sound — that keeps a voice the same voice from one piece to
        the next.

        Args:
            media: Audio or video file to transcribe.

        Returns:
            The dialogue, in chronological order, with timestamps counted
            from the start of the recording.

        Raises:
            AudioError: If the media cannot be turned into sendable audio.
            TranscriptionError: If a piece fails every attempt, or if the
                model answers something that cannot be read.
        """
        source = Path(media)
        chunks = split_audio(
            source, chunk_seconds=self.chunk_seconds, max_bytes=self.max_inline_bytes
        )

        roster: list[Voice] = []
        utterances: list[Utterance] = []
        language = ""

        for index, chunk in enumerate(chunks):
            answer = self._transcribe_chunk(
                source,
                chunk,
                position=(index, len(chunks)),
                roster=roster,
                tail=utterances,
            )

            language = language or _text(answer.get("language"))
            _merge_voices(roster, answer.get("speakers"))
            utterances.extend(_utterances(answer.get("utterances"), chunk))

        return Transcript(
            utterances=tuple(utterances),
            language=language or self.language,
            provider=self.provider,
            model=self.model,
            duration=probe_duration(source),
        )

    def __enter__(self) -> Self:
        """Return the recogniser itself, for use as a context manager."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Nothing is held open; the client is closed by the SDK."""
        self.close()

    # ------------------------------------------------------------- one piece

    def _transcribe_chunk(
        self,
        source: Path,
        chunk: PreparedAudio,
        *,
        position: tuple[int, int],
        roster: Sequence[Voice],
        tail: Sequence[Utterance],
    ) -> dict[str, Any]:
        """Send one piece and return the object the model answered with.

        Raises:
            TranscriptionError: If every attempt fails, or if the answer
                cannot be read as the JSON that was asked for.
        """
        parts: list[genai_types.Part] = [
            genai_types.Part.from_text(text=self._brief(chunk, position, roster, tail))
        ]

        context = self._context_clip(source, chunk)
        if context is not None:
            parts.append(
                genai_types.Part.from_text(
                    text="CONTEXT CLIP — the seconds just before the audio to "
                    "transcribe. Listen to it only to place the voices you "
                    "already know. Do not transcribe any of it."
                )
            )
            parts.append(_audio_part(context))

        parts.append(
            genai_types.Part.from_text(
                text="AUDIO TO TRANSCRIBE — this, and only this. Its first "
                "second is second 0 of your timestamps."
            )
        )
        parts.append(_audio_part(chunk))

        return _parse(self._ask(parts, position))

    def _ask(
        self, parts: Sequence[genai_types.Part], position: tuple[int, int]
    ) -> str:
        """Call the model, trying again once a failure looks transient.

        Raises:
            TranscriptionError: If no attempt comes back with an answer.
        """
        index, total = position
        failures: list[str] = []

        for attempt in range(1, self.attempts + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=[genai_types.Content(role="user", parts=list(parts))],
                    config=self._config(),
                )
            except Exception as error:  # noqa: BLE001 — the SDK raises broadly
                failures.append(f"attempt {attempt}: {error}")
            else:
                if response.text:
                    return response.text
                failures.append(f"attempt {attempt}: the model answered nothing")

            if attempt < self.attempts:
                time.sleep(2.0 * attempt)

        raise TranscriptionError(
            f"Transcription of part {index + 1} of {total} failed "
            f"({'; '.join(failures)})."
        )

    def _config(self) -> genai_types.GenerateContentConfig:
        """Build the generation config: JSON out, and a long enough leash."""
        return genai_types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            # Transcription is not a place for invention: the same audio
            # should give the same words twice.
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=_SCHEMA,
            # Nothing here calls a tool, and leaving the machinery on only
            # earns a warning on every piece of the recording.
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            http_options=genai_types.HttpOptions(timeout=int(self.timeout * 1000)),
        )

    def _context_clip(
        self, source: Path, chunk: PreparedAudio
    ) -> PreparedAudio | None:
        """Cut the seconds that come just before a piece, if there are any."""
        if self.context_seconds <= 0 or chunk.offset <= 0:
            return None

        length = min(self.context_seconds, chunk.offset)
        return prepare_audio(
            source,
            start=chunk.offset - length,
            length=length,
            max_bytes=self.max_inline_bytes,
        )

    def _brief(
        self,
        chunk: PreparedAudio,
        position: tuple[int, int],
        roster: Sequence[Voice],
        tail: Sequence[Utterance],
    ) -> str:
        """Write the text turn: where this piece sits, and who is in it."""
        index, total = position
        blocks = [
            f"Recording expected in {self.language}; transcribe in whatever "
            "language is actually spoken.",
            f"Part {index + 1} of {total}, beginning at "
            f"{format_timestamp(chunk.offset)} of the recording and lasting "
            f"{format_timestamp(chunk.duration)}.",
        ]

        if roster:
            blocks.append(
                "Voices already identified in this recording — reuse these "
                "numbers for these people:\n"
                + "\n".join(voice.line for voice in roster)
            )
        else:
            blocks.append(
                "This is the beginning of the recording: number the voices "
                "from 1, in the order they first speak."
            )

        if lines := _tail_lines(tail):
            blocks.append("How the previous part ended:\n" + lines)

        return "\n\n".join(blocks)


# ----------------------------------------------------------------- functions


def _audio_part(audio: PreparedAudio) -> genai_types.Part:
    """Wrap encoded audio as a part of the request."""
    return genai_types.Part.from_bytes(
        data=audio.content, mime_type=audio.mime_type
    )


def _parse(text: str) -> dict[str, Any]:
    """Read the object the model was asked to answer with.

    Raises:
        TranscriptionError: If the answer is not a JSON object.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise TranscriptionError(
            f"The model did not answer with JSON: {text.strip()[:300]!r}"
        ) from error

    if not isinstance(payload, dict):
        raise TranscriptionError("The model answered with JSON, but not an object.")
    return payload


def _merge_voices(roster: list[Voice], described: Any) -> None:
    """Add the voices this piece introduced to the running roster.

    A voice keeps the description it was first given: the piece that heard it
    open its mouth is the one that heard it best, and a description that keeps
    changing is one the next piece cannot match anything against.
    """
    if not isinstance(described, list):
        return

    known = {voice.tag for voice in roster}
    for entry in described:
        if not isinstance(entry, dict):
            continue
        tag = _tag(entry.get("tag"))
        description = _text(entry.get("description"))
        if tag is None or tag in known or not description:
            continue
        roster.append(Voice(tag=tag, description=description))
        known.add(tag)


def _utterances(spoken: Any, chunk: PreparedAudio) -> list[Utterance]:
    """Turn the utterances of one piece into utterances of the recording.

    The timestamps arrive counted from the start of the piece and are moved to
    where the piece sits, so the transcript reads against the recording. They
    are also held inside the piece: a model that loses count of the seconds
    must not produce a line that claims to be somewhere else entirely.
    """
    if not isinstance(spoken, list):
        return []

    ceiling = chunk.duration if chunk.duration > 0 else None
    built: list[Utterance] = []

    for entry in spoken:
        if not isinstance(entry, dict):
            continue
        text = _text(entry.get("text"))
        tag = _tag(entry.get("speaker"))
        if not text or tag is None:
            continue

        start = _clamp(_seconds(entry.get("start")), ceiling)
        end = _clamp(_seconds(entry.get("end")), ceiling)
        built.append(
            Utterance(
                speaker=tag,
                text=text,
                start=chunk.offset + start,
                end=chunk.offset + max(start, end),
            )
        )

    built.sort(key=lambda utterance: utterance.start)
    return built


def _tail_lines(utterances: Sequence[Utterance]) -> str:
    """Quote the end of what has been transcribed so far.

    The timestamps are left out on purpose: the next piece counts its seconds
    from its own beginning, and two clocks in one prompt is one too many.
    """
    lines = [
        f"{utterance.label}: {utterance.text[:TAIL_CHARACTERS]}"
        for utterance in utterances[-TAIL_LINES:]
    ]
    return "\n".join(lines)


def _tag(value: Any) -> int | None:
    """Read a speaker tag, refusing anything that is not a real voice."""
    try:
        tag = int(value)
    except (TypeError, ValueError):
        return None
    return tag if tag > 0 else None


def _text(value: Any) -> str:
    """Read a string the model wrote, whitespace stripped."""
    return value.strip() if isinstance(value, str) else ""


def _seconds(value: Any) -> float:
    """Read a timestamp, treating anything unreadable as the start."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, ceiling: float | None) -> float:
    """Hold a timestamp inside the piece it was measured in."""
    return value if ceiling is None else min(value, ceiling)
