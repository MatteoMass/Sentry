"""Storage: where a recording and everything about it is kept.

:class:`MemoryConnector` is the whole surface — the index, the folder
tree, the files on disk and the stored settings behind one object. The
pieces it is built from are exported too, along with the errors it
raises, which is what the API translates into status codes.
"""

from connectors.memory_connector.blobs import RecordingBlobs
from connectors.memory_connector.connector import (
    DB_FILENAME,
    RECORDINGS_DIRNAME,
    MemoryConnector,
)
from connectors.memory_connector.db import Database
from connectors.memory_connector.folders import FolderTree
from connectors.memory_connector.index import RecordingIndex
from connectors.memory_connector.settings import SettingsStore
from connectors.memory_connector.types import (
    ANY_FOLDER,
    RECORDING_STATUSES,
    RUNNING_STATUSES,
    BlobNotFound,
    Folder,
    FolderAlreadyExists,
    FolderFilter,
    FolderNotEmpty,
    FolderNotFound,
    InvalidFolderMove,
    InvalidFolderName,
    InvalidKey,
    InvalidRecordingName,
    MemoryConnectorError,
    Recording,
    RecordingAlreadyExists,
    RecordingNotFound,
    RecordingStatus,
    new_folder_id,
    new_recording_id,
    normalize_recording_name,
)

__all__ = [
    "ANY_FOLDER",
    "DB_FILENAME",
    "RECORDINGS_DIRNAME",
    "RECORDING_STATUSES",
    "RUNNING_STATUSES",
    "BlobNotFound",
    "Database",
    "Folder",
    "FolderAlreadyExists",
    "FolderFilter",
    "FolderNotEmpty",
    "FolderNotFound",
    "FolderTree",
    "InvalidFolderMove",
    "InvalidFolderName",
    "InvalidKey",
    "InvalidRecordingName",
    "MemoryConnector",
    "MemoryConnectorError",
    "Recording",
    "RecordingAlreadyExists",
    "RecordingBlobs",
    "RecordingIndex",
    "RecordingNotFound",
    "RecordingStatus",
    "SettingsStore",
    "new_folder_id",
    "new_recording_id",
    "normalize_recording_name",
]
