"""The HTTP surface: routers, schemas and the dependencies they share.

Each router owns one kind of thing — recordings, folders, notes,
prompts — and they are gathered here with the schemas they answer in,
so :mod:`backend` builds the application from this one import.
"""

from api.dependencies import Memory, Pipeline, get_memory, get_pipeline
from api.folders import router as folders_router
from api.frontend import mount_frontend
from api.notes import router as notes_router
from api.prompts import router as prompts_router
from api.recordings import router as recordings_router
from api.schemas import (
    ROOT,
    AttachmentOut,
    ChatAsk,
    ChatReply,
    ChatTurn,
    FolderCreate,
    FolderOut,
    FolderUpdate,
    NoteOut,
    NoteUpdate,
    PromptOut,
    PromptUpdate,
    RecordingMove,
    RecordingOut,
    RecordingRename,
    SummaryOut,
    TranscriptOut,
    UtteranceOut,
    folder_ref,
)

__all__ = [
    "ROOT",
    "AttachmentOut",
    "ChatAsk",
    "ChatReply",
    "ChatTurn",
    "FolderCreate",
    "FolderOut",
    "FolderUpdate",
    "Memory",
    "NoteOut",
    "NoteUpdate",
    "Pipeline",
    "PromptOut",
    "PromptUpdate",
    "RecordingMove",
    "RecordingOut",
    "RecordingRename",
    "SummaryOut",
    "TranscriptOut",
    "UtteranceOut",
    "folder_ref",
    "folders_router",
    "get_memory",
    "get_pipeline",
    "mount_frontend",
    "notes_router",
    "prompts_router",
    "recordings_router",
]
