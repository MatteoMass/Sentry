"""The vocabulary every generative connector speaks.

A provider SDK has its own objects for a turn of conversation and its own
shape for what comes back. These are the ones the rest of Sentry sees: a
connector translates into them on the way out and out of them on the way in,
so swapping Gemini for another backend changes nothing above
:mod:`connectors.genai_connectors.base`.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class Media:
    """A file travelling with a message: audio, an image, a document.

    The bytes are carried as they are meant to be read, encoding included:
    what fits in one request, and in which codec, is decided long before a
    connector sees them.

    Attributes:
        content: The encoded bytes.
        mime_type: What the provider is told they are, e.g. ``'audio/flac'``.
    """

    content: bytes = field(repr=False)
    mime_type: str

    def __len__(self) -> int:
        """Return the size of the payload in bytes."""
        return len(self.content)


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of a conversation, from either side.

    Attributes:
        role: Who is speaking — the user, or the model answering.
        content: What was said, as plain text.
        media: Files sent with the turn, none for a plain text one. Only a
            connector over a provider that reads them can carry them, which
            is the caller's to know: the audio of a recording is worth the
            bytes only where something can listen to it.
    """

    role: Role
    content: str
    media: tuple[Media, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    """What a call cost, in tokens.

    Providers that report nothing leave the counts at zero, so the fields are
    always readable and a caller never has to check for a missing total.

    Attributes:
        input_tokens: Tokens the prompt was billed for.
        output_tokens: Tokens the answer was billed for.
    """

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return the tokens billed for the call, prompt and answer together."""
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    """A finished completion, as the caller receives it.

    Attributes:
        text: The generated answer.
        model: The model that produced it, as the provider named it — which
            may be more precise than the identifier that was asked for.
        usage: What the call cost.
        raw: The untouched provider response, kept for debugging and left out
            of the repr. Its shape belongs to the SDK, so nothing above the
            connector should read it.
    """

    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    raw: Any = field(default=None, repr=False)
