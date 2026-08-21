"""Payloads exchanged over HTTP."""

from datetime import datetime

from pydantic import BaseModel, Field

from connectors.memory_connector import Recording, RecordingStatus


class RecordingOut(BaseModel):
    """A recording as the API exposes it."""

    id: str = Field(description="Identifier of the recording.")
    name: str = Field(description="Human readable name, usually the file name.")
    uploaded_at: datetime = Field(description="Moment the upload completed, in UTC.")
    status: RecordingStatus = Field(description="Where it sits in the pipeline.")

    @classmethod
    def from_recording(cls, recording: Recording) -> "RecordingOut":
        """Build the payload from a connector recording."""
        return cls(
            id=recording.id,
            name=recording.name,
            uploaded_at=recording.uploaded_at,
            status=recording.status,
        )
