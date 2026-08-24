"""What every router needs from the application state."""

from typing import Annotated

from fastapi import Depends, Request

from connectors.memory_connector import MemoryConnector
from core import ProcessingPipeline


def get_memory(request: Request) -> MemoryConnector:
    """Return the connector opened at startup."""
    return request.app.state.memory


def get_pipeline(request: Request) -> ProcessingPipeline:
    """Return the pipeline built at startup.

    One instance serves the whole process: its backends are built the first
    time something is transcribed and then reused, so the connection pool and
    the credentials outlive the request that needed them.
    """
    return request.app.state.pipeline


Memory = Annotated[MemoryConnector, Depends(get_memory)]
Pipeline = Annotated[ProcessingPipeline, Depends(get_pipeline)]
