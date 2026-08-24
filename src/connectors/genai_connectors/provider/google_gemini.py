"""Google Gemini Connector (SDK `google-genai`)."""

from collections.abc import Iterator, Sequence
from functools import cached_property

from google import genai
from google.genai import types as genai_types

from config import settings
from connectors.genai_connectors.base import GenAIConnector
from connectors.genai_connectors.types import CompletionResponse, Message, Usage

DEFAULT_MODEL = "gemini-3.1-flash-lite"
"""Fallback for a connector built with no model named.

What the summariser actually calls is `summarization.model` in the settings;
this is only what a caller reaching for the connector on its own gets.
"""

_ROLE_MAP = {"user": "user", "assistant": "model"}


class GeminiConnector(GenAIConnector):
    """:class:`GenAIConnector` over the ``google-genai`` SDK.

    The key is settled at construction — passed in, or taken from the
    settings — so a connector that exists is a connector that can call. The
    client behind it is not: it is built on first use and kept, which leaves
    an unused connector free.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        """Settle the model and the credentials to call it with.

        Args:
            model: Gemini model to call. Defaults to :data:`DEFAULT_MODEL`.
            api_key: Key to authenticate with. When ``None``, the one the
                settings read from the environment is used.
            system_prompt: Instructions prepended to every conversation.
            temperature: Sampling temperature.
            max_output_tokens: Upper bound on the tokens generated per call.

        Raises:
            ValueError: If no key was passed and none is configured.
        """
        super().__init__(
            model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise ValueError(
                "API key mancante: passa `api_key` o imposta GEMINI_API_KEY."
            )

    @property
    def provider(self) -> str:
        """Name of the underlying provider, ``'gemini'``."""
        return "gemini"

    @cached_property
    def _client(self) -> genai.Client:
        """Client SDK creato al primo utilizzo."""
        return genai.Client(api_key=self._api_key)

    def generate(self, messages: Sequence[Message]) -> CompletionResponse:
        """Run a completion call and return the whole response at once.

        Args:
            messages: Conversation history, in chronological order.

        Returns:
            The generated text with the model name and the token usage
            Gemini reported.
        """
        response = self._client.models.generate_content(
            model=self.model,
            contents=self._to_contents(messages),
            config=self._config(),
        )
        return self._to_completion(response)

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        """Run a completion call and yield the text as it is produced.

        Args:
            messages: Conversation history, in chronological order.

        Yields:
            Text fragments that, once concatenated, form the full answer.
            Chunks carrying no text are skipped.
        """
        chunks = self._client.models.generate_content_stream(
            model=self.model,
            contents=self._to_contents(messages),
            config=self._config(),
        )
        for chunk in chunks:
            if chunk.text:
                yield chunk.text

    def _config(self) -> genai_types.GenerateContentConfig:
        return genai_types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )

    @staticmethod
    def _to_contents(messages: Sequence[Message]) -> list[genai_types.Content]:
        return [
            genai_types.Content(
                role=_ROLE_MAP[message.role],
                parts=[genai_types.Part.from_text(text=message.content)],
            )
            for message in messages
        ]

    def _to_completion(
        self, response: genai_types.GenerateContentResponse
    ) -> CompletionResponse:
        metadata = response.usage_metadata
        return CompletionResponse(
            text=response.text or "",
            model=self.model,
            usage=Usage(
                input_tokens=getattr(metadata, "prompt_token_count", 0) or 0,
                output_tokens=getattr(metadata, "candidates_token_count", 0) or 0,
            ),
            raw=response,
        )
