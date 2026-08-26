"""The generative backend, behind a provider-agnostic interface.

:class:`GenAIConnector` is the surface a caller codes against and the
types are the vocabulary it speaks; the concrete providers live under
``provider`` and are not exported, so nothing above chooses a vendor by
importing one.
"""

from connectors.genai_connectors.base import GenAIConnector
from connectors.genai_connectors.types import (
    CompletionResponse,
    Media,
    Message,
    Role,
    Usage,
)

__all__ = [
    "CompletionResponse",
    "GenAIConnector",
    "Media",
    "Message",
    "Role",
    "Usage",
]
