"""Answering questions asked about one recording, over what is stored of it.

The pipeline writes two things about a recording and stops: a transcript
nobody wants to read in full, and a summary that answers the questions
somebody thought of in advance. This is the third thing, and it is not a step:
it is asked for a question at a time, and it exists so that the answer to
"who said they would talk to the client" costs one model call instead of an
hour of reading.

What the model is given is not this module's decision. A conversation carries
whatever the person asking chose to send with it — the summary, the diarized
dialogue, the audio itself — and the three cost wildly different amounts: the
summary is a page, the transcript is a book, and the recording is the whole
hour again, re-encoded and re-uploaded on every single turn. So none of it is
assumed. What arrives is what travels, and the caller is the one who knows
what the question is worth.

Nothing is stored. The conversation lives in the client and comes back whole
with each question, which is what makes a chat about a recording free to
throw away: there is no state here to leave behind.

Any :class:`GenAIConnector` can answer; the Gemini one is only the default,
built on first use so that a recording can be opened without an API key until
somebody actually asks it something. Which model answers, how freely, and how
much of a transcript it is handed all come from the ``chat`` section of the
settings.
"""

from collections.abc import Sequence
from pathlib import Path

from config import settings
from connectors.genai_connectors import (
    CompletionResponse,
    GenAIConnector,
    Media,
    Message,
)
from connectors.genai_connectors.provider.google_gemini import GeminiConnector
from core.audio import PreparedAudio, prepare_audio
from core.types import AudioError, ChatError, Summary, Transcript

SYSTEM_PROMPT = """\
You are Sentry, answering questions about one recording.

What you are given about it is whatever the person asking chose to send: the
summary written from it, the diarized transcript, the audio itself, or any
part of the three. The transcript is diarized: every line is
`[timestamp] Speaker N: text`, where each number is a distinct voice whose
real name you do not know unless it is said out loud in the conversation.

Rules:
- Answer from the recording alone. Never invent what was said.
- Say plainly when what you were given does not hold the answer, and name
  what is missing — the transcript, the summary, the audio — when sending it
  would settle the question.
- Write in the language the question is asked in.
- Point at the moment you are answering from, by timestamp, whenever the
  transcript gives you one.
- Quote sparingly and exactly. A quotation that is not in the transcript is
  worse than no quotation.
- Keep it short: an answer is read next to the recording, not instead of it.\
"""

_PREAMBLE = """\
Here is what you have been given about the recording. Everything after this
message is the conversation itself.\
"""


class Chat:
    """Answers questions about a recording, using a generative model.

    One instance serves every recording: nothing about a conversation is held
    here, so the only thing it carries between calls is the connector — and
    that is what makes it worth keeping rather than building per question.
    """

    def __init__(
        self,
        connector: GenAIConnector | None = None,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        max_characters: int | None = None,
        max_source_bytes: int | None = None,
    ) -> None:
        """Configure the chat.

        Everything left at ``None`` is taken from the ``chat`` section of the
        settings.

        Args:
            connector: Model to answer with. When ``None`` a Gemini connector
                is built on first use, with the system prompt and the
                generation settings below.
            system_prompt: Instructions the model answers under. When ``None``
                the shipped :data:`SYSTEM_PROMPT` is used. It only reaches a
                connector built here: one that was handed over already carries
                its own.
            model: Model the default connector calls.
            temperature: Sampling temperature of the default connector. It
                sits above the summariser's: an answer is allowed to be a
                sentence rather than a heading, and still says only what the
                recording says.
            max_output_tokens: Upper bound on the answer, left to the provider
                when neither this nor the settings name one.
            max_characters: Longest dialogue sent with a question, past which
                the tail is dropped. A transcript too long for it degrades
                into a partly informed answer instead of a rejected request.
            max_source_bytes: Ceiling on the audio sent when the source is
                asked for. A recording too heavy for it is re-encoded to Opus
                rather than refused.
        """
        talking = settings.chat

        self._connector = connector
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self._model = model or talking.model
        self._temperature = talking.temperature if temperature is None else temperature
        self._max_output_tokens = max_output_tokens or talking.max_output_tokens
        self.max_characters = max_characters or talking.max_characters
        self.max_source_bytes = max_source_bytes or talking.max_source_bytes

    @property
    def connector(self) -> GenAIConnector:
        """The model doing the answering, built on first use when not given.

        Raises:
            ChatError: If the default connector cannot be built, usually for
                want of an API key.
        """
        if self._connector is None:
            try:
                self._connector = GeminiConnector(
                    self._model,
                    system_prompt=self.system_prompt,
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                )
            except ValueError as error:
                raise ChatError(str(error)) from error
        return self._connector

    def ask(
        self,
        conversation: Sequence[Message],
        *,
        name: str | None = None,
        transcript: Transcript | None = None,
        summary: Summary | None = None,
        source: Path | None = None,
    ) -> CompletionResponse:
        """Answer the last question of a conversation about a recording.

        Everything the model is to know arrives here: the conversation so far,
        and the parts of the recording that are to travel with it. Nothing is
        remembered between calls, so what is not passed is not known.

        Args:
            conversation: The exchange so far, in chronological order, ending
                with the question to answer.
            name: What the recording is called, when it is worth naming.
            transcript: The diarized dialogue, or ``None`` to withhold it.
            summary: The stored summary, or ``None`` to withhold it.
            source: The media file itself, whose audio is extracted and sent
                with the question, or ``None`` to withhold it. This is the
                expensive one: the whole recording travels on every turn.

        Returns:
            The answer, carrying the model that wrote it and what it cost.

        Raises:
            ChatError: If there is nothing to answer, if the audio cannot be
                prepared, if the model call fails, or if it answers with
                nothing at all.
        """
        if not conversation:
            raise ChatError("There is no question to answer.")

        messages = [*self._context(name, transcript, summary, source), *conversation]
        try:
            response = self.connector.generate(messages)
        except ChatError:
            raise
        except Exception as error:
            raise ChatError(f"The model call failed: {error}") from error

        if not response.text.strip():
            raise ChatError("The model answered with nothing.")
        return response

    # ------------------------------------------------------------- the brief

    def _context(
        self,
        name: str | None,
        transcript: Transcript | None,
        summary: Summary | None,
        source: Path | None,
    ) -> list[Message]:
        """Build the turn carrying what was chosen to be sent, if anything.

        It is one message and it leads the conversation, so the question a
        person actually typed reaches the model as they typed it rather than
        buried under a dossier.
        """
        sections: list[str] = []
        if name:
            sections.append(f"Recording: {name}")
        if summary is not None:
            sections.append(f"Summary:\n{summary.to_markdown()}")
        if transcript is not None:
            sections.append(self._dialogue(transcript))

        media: tuple[Media, ...] = ()
        if source is not None:
            audio = self._audio(source)
            media = (Media(content=audio.content, mime_type=audio.mime_type),)
            sections.append(
                "The recording itself is attached as audio. Listen to it for"
                " anything the transcript does not settle: tone, overlapping"
                " speech, a word written down wrong."
            )

        if not sections:
            return []
        return [
            Message(
                role="user",
                content=f"{_PREAMBLE}\n\n" + "\n\n".join(sections),
                media=media,
            )
        ]

    def _dialogue(self, transcript: Transcript) -> str:
        """Write the transcript section, cut short when it does not fit."""
        dialogue = transcript.dialogue
        truncated = len(dialogue) > self.max_characters
        if truncated:
            dialogue = dialogue[: self.max_characters]

        header = [
            f"Language: {transcript.language}",
            f"Speakers: {len(transcript.speakers)}",
        ]
        if transcript.duration:
            header.append(f"Duration: {transcript.duration / 60:.0f} minutes")
        if truncated:
            header.append(
                "Note: the transcript is cut short. Say so if the answer would"
                " lie past where it stops."
            )
        return "\n".join(header) + f"\n\nTranscript:\n{dialogue}"

    def _audio(self, source: Path) -> PreparedAudio:
        """Extract the audio of the recording, small enough to be sent.

        Raises:
            ChatError: If ffmpeg is missing or fails, or if the recording does
                not fit in one request whatever it is encoded as.
        """
        try:
            return prepare_audio(source, max_bytes=self.max_source_bytes)
        except AudioError as error:
            raise ChatError(f"The recording could not be sent: {error}") from error

    def __repr__(self) -> str:
        """Return a debug representation showing the model behind it."""
        return f"{type(self).__name__}(model={self._model!r})"
