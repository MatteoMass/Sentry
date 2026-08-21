"""Facade over the two persistence subsystems of a recording."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Self

from connectors.memory_connector.blobs import RecordingBlobs
from connectors.memory_connector.index import RecordingIndex
from connectors.memory_connector.types import (
    Recording,
    RecordingStatus,
    new_recording_id,
)

DB_FILENAME = "sentry.db"
RECORDINGS_DIRNAME = "recordings"


class MemoryConnector:
    """Persist recordings as a SQLite index plus one blob folder each.

    The connector owns a single root directory and lays it out like this::

        <root>/
        ├── sentry.db                 # tabular index of every recording
        └── recordings/
            └── <recording id>/       # one folder per recording
                ├── recording.mp4     # the uploaded media
                ├── transcript.txt    # produced later by the pipeline
                └── notes.md          # anything else that belongs to it

    Whether ``root`` points at a local directory or at a mounted Docker volume
    is irrelevant: both are ordinary filesystem paths, so the choice belongs to
    configuration, not to the code.

    Two subsystems do the actual work, and stay reachable as :attr:`index` and
    :attr:`blobs` for the rare caller that needs one of them alone. Everything
    they expose is mirrored here, so ordinary code only ever talks to the
    facade — which is also the only place aware of both sides at once.

    Example:
        >>> memory = MemoryConnector("./data")
        >>> recording = memory.create_recording("standup.mp4")
        >>> memory.save_file(recording.id, "recording.mp4", Path("/tmp/up.mp4"))
        >>> memory.update_status(recording.id, "processed")
    """

    def __init__(self, root: Path | str, *, db_filename: str = DB_FILENAME) -> None:
        """Open (creating it when missing) the storage rooted at ``root``.

        Args:
            root: Directory holding the database and the recording folders.
            db_filename: Name of the SQLite file inside ``root``.
        """
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

        self.blobs = RecordingBlobs(self.root / RECORDINGS_DIRNAME)
        self.index = RecordingIndex(self.root / db_filename)

    @property
    def db_path(self) -> Path:
        """Path of the SQLite file."""
        return self.index.db_path

    @property
    def recordings_root(self) -> Path:
        """Directory holding one folder per recording."""
        return self.blobs.root

    # ------------------------------------------------- crossing both systems

    def create_recording(
        self,
        name: str,
        *,
        recording_id: str | None = None,
        status: RecordingStatus = "to_process",
        uploaded_at: datetime | None = None,
    ) -> Recording:
        """Register a new recording and create its (empty) folder.

        The folder is created before the row is committed: a crash in between
        leaves an orphan folder, which :meth:`orphan_dirs` can find, rather
        than a row pointing at files that do not exist.

        Args:
            name: Human readable name of the recording.
            recording_id: Identifier to use. When ``None`` a random one is
                generated.
            status: Initial pipeline status.
            uploaded_at: Upload time. Defaults to now, in UTC.

        Returns:
            The recording as it was stored.

        Raises:
            RecordingAlreadyExists: If ``recording_id`` is already in use.
            InvalidKey: If ``recording_id`` is not a safe folder name.
        """
        identifier = recording_id or new_recording_id()
        created = self.blobs.ensure_dir(identifier)
        try:
            return self.index.create(
                name,
                recording_id=identifier,
                status=status,
                uploaded_at=uploaded_at,
            )
        except BaseException:
            if created:
                self.blobs.remove_dir(identifier)
            raise

    def delete_recording(self, recording_id: str, *, remove_files: bool = True) -> None:
        """Delete a recording, and by default its folder as well.

        The row goes first, so an interrupted delete leaves files without an
        index entry rather than an entry without files.

        Args:
            recording_id: Recording to delete.
            remove_files: When ``False`` the folder is kept on disk.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        self.index.delete(recording_id)
        if remove_files:
            self.blobs.remove_dir(recording_id)

    def orphan_dirs(self) -> list[str]:
        """List recording folders that have no row in the index.

        These are the leftovers of an interrupted create or delete; sweeping
        them is safe once no upload is in flight.
        """
        return sorted(self.blobs.dir_names() - self.index.known_ids())

    # ---------------------------------------------------------- index facade

    def get_recording(self, recording_id: str) -> Recording:
        """Return one recording by id. See :meth:`RecordingIndex.get`."""
        return self.index.get(recording_id)

    def list_recordings(
        self,
        *,
        status: RecordingStatus | Sequence[RecordingStatus] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Recording]:
        """List recordings, newest first. See :meth:`RecordingIndex.search`."""
        return self.index.search(status=status, limit=limit, offset=offset)

    def update_status(self, recording_id: str, status: RecordingStatus) -> Recording:
        """Move a recording to another pipeline status."""
        return self.index.update_status(recording_id, status)

    def claim_next(self) -> Recording | None:
        """Atomically take the oldest pending recording and mark it processing."""
        return self.index.claim_next()

    # ----------------------------------------------------------- blob facade

    def recording_dir(self, recording_id: str) -> Path:
        """Return the absolute path of a recording folder (no disk access)."""
        return self.blobs.dir_for(recording_id)

    def save_file(
        self,
        recording_id: str,
        filename: str,
        source: BinaryIO | Path | bytes | bytearray | memoryview,
    ) -> Path:
        """Write a file inside a recording folder, atomically."""
        return self.blobs.save(recording_id, filename, source)

    def open_file(self, recording_id: str, filename: str) -> BinaryIO:
        """Open a file of a recording for streaming reads."""
        return self.blobs.open_file(recording_id, filename)

    def read_text(
        self, recording_id: str, filename: str, *, encoding: str = "utf-8"
    ) -> str:
        """Read a whole text file, for transcripts and notes."""
        return self.blobs.read_text(recording_id, filename, encoding=encoding)

    def write_text(
        self, recording_id: str, filename: str, text: str, *, encoding: str = "utf-8"
    ) -> Path:
        """Write a text file inside a recording folder, atomically."""
        return self.blobs.write_text(recording_id, filename, text, encoding=encoding)

    def list_files(self, recording_id: str) -> list[str]:
        """List the files of a recording, relative to its folder."""
        return self.blobs.list_files(recording_id)

    def has_file(self, recording_id: str, filename: str) -> bool:
        """Tell whether a recording holds that file."""
        return self.blobs.has_file(recording_id, filename)

    def delete_file(self, recording_id: str, filename: str) -> bool:
        """Delete one file of a recording."""
        return self.blobs.delete_file(recording_id, filename)

    # ---------------------------------------------------------------- shared

    def close(self) -> None:
        """Close the database connection."""
        self.index.close()

    def __enter__(self) -> Self:
        """Return the connector itself, for use as a context manager."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close the database connection when leaving the block."""
        self.close()

    def __repr__(self) -> str:
        """Return a debug representation showing the storage root."""
        return f"{type(self).__name__}(root={str(self.root)!r})"
