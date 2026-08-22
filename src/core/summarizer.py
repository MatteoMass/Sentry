"""Distilling a diarized transcript into the few things worth remembering.

A transcript is a record, not an answer: an hour of talk is faster to re-live
than to search. So the model is asked for the shape a reader actually needs —
what it was about, what stood out, what was decided, and who owes what — and
is told to leave a section empty rather than fill it, because an invented
decision is worse than a missing one.

The diarized dialogue goes in as it is, timestamps and speaker labels
included: they are what lets the summary attribute a commitment to the voice
that made it, and point back at the minute it was made.

Any :class:`GenAIConnector` can do the writing; the Gemini one is only the
default, built on first use so that a pipeline can exist without an API key
until something actually needs summarising.
"""

import json
import re
from typing import Any

from connectors.genai_connectors import GenAIConnector, Message
from connectors.genai_connectors.provider.google_gemini import GeminiConnector
from core.types import SummarizationError, Summary, Transcript

MAX_CHARACTERS = 400_000
"""Longest dialogue sent in one go, past which the tail is dropped.

The audio a single request can carry is worth roughly an hour of speech, well
under this; the cap only exists so that a pathological transcript degrades
into a partial summary instead of a rejected request.
"""

SYSTEM_PROMPT = """\
You summarise transcripts of meetings, calls and voice notes.

The transcript is diarized: every line is `[timestamp] Speaker N: text`, where
each number is a distinct voice whose real name you do not know unless it is
said out loud in the conversation itself.

Rules:
- Write in the language spoken in the transcript.
- Report only what was actually said. Never infer, never fill a gap.
- Attribute what matters to its speaker, by name when the transcript reveals
  one, by label otherwise.
- Keep every entry short and self contained: it is read without the transcript
  next to it.
- Leave a section empty when the conversation holds nothing for it.

Answer with a single JSON object, with no commentary and no code fence:
{
  "overview": "two to four sentences on what the recording was about",
  "key_points": ["the salient points, in the order they came up"],
  "decisions": ["what was settled"],
  "action_items": ["what somebody committed to do, owner first when named"]
}\
"""

_FENCE = re.compile(r"\A```(?:json)?\s*(?P<body>.*?)\s*```\Z", re.DOTALL)


class Summarizer:
    """Writes the summary of a transcript, using a generative model."""

    def __init__(
        self,
        connector: GenAIConnector | None = None,
        *,
        temperature: float = 0.2,
    ) -> None:
        """Configure the summariser.

        Args:
            connector: Model to write with. When ``None`` a Gemini connector
                is built on first use, with :data:`SYSTEM_PROMPT` and
                ``temperature``.
            temperature: Sampling temperature of the default connector. A low
                one keeps the summary close to what was said.
        """
        self._connector = connector
        self._temperature = temperature

    @property
    def connector(self) -> GenAIConnector:
        """The model doing the writing, built on first use when not given.

        Raises:
            SummarizationError: If the default connector cannot be built,
                usually for want of an API key.
        """
        if self._connector is None:
            try:
                self._connector = GeminiConnector(
                    system_prompt=SYSTEM_PROMPT, temperature=self._temperature
                )
            except ValueError as error:
                raise SummarizationError(str(error)) from error
        return self._connector

    def summarize(self, transcript: Transcript) -> Summary:
        """Summarise a transcript.

        Args:
            transcript: The diarized dialogue to read.

        Returns:
            The summary, carrying the name of the model that wrote it.

        Raises:
            SummarizationError: If the transcript is empty, if the model call
                fails, or if its answer is not the JSON that was asked for.
        """
        if not transcript:
            raise SummarizationError("Nothing to summarise: the transcript is empty.")

        connector = self.connector
        try:
            response = connector.generate([Message(role="user", content=_prompt(transcript))])
        except SummarizationError:
            raise
        except Exception as error:
            raise SummarizationError(f"The model call failed: {error}") from error

        payload = _parse(response.text)
        return Summary(
            overview=str(payload.get("overview", "")).strip(),
            key_points=_entries(payload.get("key_points")),
            decisions=_entries(payload.get("decisions")),
            action_items=_entries(payload.get("action_items")),
            model=response.model,
        )


# ----------------------------------------------------------------- functions


def _prompt(transcript: Transcript) -> str:
    """Build the user turn: what the recording is, then what was said."""
    dialogue = transcript.dialogue
    truncated = len(dialogue) > MAX_CHARACTERS
    if truncated:
        dialogue = dialogue[:MAX_CHARACTERS]

    header = [
        f"Language: {transcript.language}",
        f"Speakers: {len(transcript.speakers)}",
    ]
    if transcript.duration:
        header.append(f"Duration: {transcript.duration / 60:.0f} minutes")
    if truncated:
        header.append("Note: the transcript is cut short; summarise what is here.")

    return "\n".join(header) + "\n\nTranscript:\n" + dialogue


def _parse(text: str) -> dict[str, Any]:
    """Read the JSON object out of a model answer.

    A model asked for bare JSON still wraps it in a code fence often enough
    that unwrapping is cheaper than a second call; anything less recoverable
    than that is an error, since a summary nobody can read is worse than none.

    Raises:
        SummarizationError: If no JSON object can be read from the answer.
    """
    candidate = text.strip()
    if match := _FENCE.match(candidate):
        candidate = match.group("body")
    else:
        opening, closing = candidate.find("{"), candidate.rfind("}")
        if opening != -1 and closing > opening:
            candidate = candidate[opening : closing + 1]

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise SummarizationError(
            f"The model did not answer with JSON: {text.strip()[:300]!r}"
        ) from error

    if not isinstance(payload, dict):
        raise SummarizationError("The model answered with JSON, but not an object.")
    return payload


def _entries(value: Any) -> tuple[str, ...]:
    """Normalise a list of bullet points, dropping whatever is not one."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(
        str(entry).strip() for entry in value if entry and str(entry).strip()
    )
