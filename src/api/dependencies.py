"""What every router needs from the application state."""

from typing import Annotated

from fastapi import Depends, Request

from connectors.memory_connector import MemoryConnector


def get_memory(request: Request) -> MemoryConnector:
    """Return the connector opened at startup."""
    return request.app.state.memory


Memory = Annotated[MemoryConnector, Depends(get_memory)]
