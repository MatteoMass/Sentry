"""Google Gemini Connector (SDK `google-genai`)."""

import os
from collections.abc import Iterator, Sequence
from functools import cached_property

from google import genai
from google.genai import types as genai_types

from connectors.genai_connectors.base import GenAIConnector
from connectors.genai_connectors.types import CompletionResponse, Message, Usage

DEFAULT_MODEL = "gemini-3.1-flash-lite"

_ROLE_MAP = {"user": "user", "assistant": "model"}


class GeminiConnector(GenAIConnector):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        super().__init__(
            model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "API key mancante: passa `api_key` o imposta GEMINI_API_KEY."
            )

    @property
    def provider(self) -> str:
        return "gemini"

    @cached_property
    def _client(self) -> genai.Client:
        """Client SDK creato al primo utilizzo."""
        return genai.Client(api_key=self._api_key)

    def generate(self, messages: Sequence[Message]) -> CompletionResponse:
        response = self._client.models.generate_content(
            model=self.model,
            contents=self._to_contents(messages),
            config=self._config(),
        )
        return self._to_completion(response)

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
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
