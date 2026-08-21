"""Provider-agnostic interface for generative AI backends."""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence

from connectors.genai_connectors.types import CompletionResponse, Message


class GenAIConnector(ABC):
    """Base class for connectors to a generative AI provider.

    Subclasses wrap a specific vendor SDK (Gemini, OpenAI, ...) behind a
    common surface, so callers can swap providers without changing code.
    A concrete connector must implement :attr:`provider`, :meth:`generate`
    and :meth:`stream`; everything else is provided here.
    """

    def __init__(
        self,
        model: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        """Store the generation settings shared by every provider.

        Args:
            model: Identifier of the model to call, as expected by the provider.
            system_prompt: Instructions prepended to every conversation. When
                ``None``, the provider default is used.
            temperature: Sampling temperature. When ``None``, the provider
                default is used.
            max_output_tokens: Upper bound on the tokens generated per call.
                When ``None``, the provider default is used.
        """
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    @property
    @abstractmethod
    def provider(self) -> str:
        """Name of the underlying provider, e.g. ``'gemini'``."""

    @abstractmethod
    def generate(self, messages: Sequence[Message]) -> CompletionResponse:
        """Run a completion call and return the whole response at once.

        Args:
            messages: Conversation history, in chronological order.

        Returns:
            The generated text together with the model name and token usage.
        """

    @abstractmethod
    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        """Run a completion call and yield the text as it is produced.

        Args:
            messages: Conversation history, in chronological order.

        Yields:
            Text fragments that, once concatenated, form the full answer.
        """

    def complete(self, prompt: str) -> CompletionResponse:
        """Shortcut for a single user turn.

        Args:
            prompt: The user message to send.

        Returns:
            The response produced by :meth:`generate` for that single message.
        """
        return self.generate([Message(role="user", content=prompt)])

    def __repr__(self) -> str:
        """Return a debug representation showing the provider and the model."""
        return f"{type(self).__name__}(provider={self.provider!r}, model={self.model!r})"
