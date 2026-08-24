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
class Message:
    """One turn of a conversation, from either side.

    Attributes:
        role: Who is speaking — the user, or the model answering.
        content: What was said, as plain text.
    """

    role: Role
    content: str


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
