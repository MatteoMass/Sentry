"""Facade over the three persistence subsystems of a recording."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Self

from connectors.memory_connector.blobs import RecordingBlobs
from connectors.memory_connector.db import Database
from connectors.memory_connector.folders import FolderTree
from connectors.memory_connector.index import RecordingIndex
from connectors.memory_connector.types import (
    ANY_FOLDER,
    Folder,
    FolderFilter,
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

    Recordings can also be filed into folders, and those folders are purely
    logical: they live as rows, never as directories, so the layout above
    stays flat however deep the tree grows. Filing a recording is one
    ``UPDATE`` — no bytes move, nothing can be half moved, and a folder can
    sit there empty waiting to be filled.

    Whether ``root`` points at a local directory or at a mounted Docker volume
    is irrelevant: both are ordinary filesystem paths, so the choice belongs to
    configuration, not to the code.

    Three subsystems do the actual work, and stay reachable as :attr:`index`,
    :attr:`folders` and :attr:`blobs` for the rare caller that needs one of
    them alone. Everything they expose is mirrored here, so ordinary code only
    ever talks to the facade — which is also the only place aware of all of
    them at once.

    Example:
        >>> memory = MemoryConnector("./data")
        >>> work = memory.create_folder("Lavoro")
        >>> recording = memory.create_recording("standup.mp4", folder_id=work.id)
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
        self.database = Database(self.root / db_filename)
        # Folders first: the recordings table points at the table it owns.
        self.folders = FolderTree(self.database)
        self.index = RecordingIndex(self.database)

    @property
    def db_path(self) -> Path:
        """Path of the SQLite file."""
        return self.database.path

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
        folder_id: str | None = None,
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
            folder_id: Folder to file the recording under. ``None`` leaves it
                at the top level.

        Returns:
            The recording as it was stored.

        Raises:
            RecordingAlreadyExists: If ``recording_id`` is already in use.
            FolderNotFound: If ``folder_id`` matches no folder.
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
                folder_id=folder_id,
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

    def delete_folder(
        self,
        folder_id: str,
        *,
        recursive: bool = False,
        remove_files: bool = True,
    ) -> list[Recording]:
        """Delete a folder, and with ``recursive`` everything inside it.

        The database refuses on its own to drop a folder still in use, which
        is what keeps a careless delete from stranding files on disk. Emptying
        a branch is therefore an explicit choice, and it happens here because
        it is the only place that can drop the rows and the media together:
        every row goes in one transaction, and the media follows once that
        transaction holds, so a crash leaves recoverable orphan folders rather
        than rows pointing at nothing.

        Args:
            folder_id: Folder to delete.
            recursive: When ``True`` the subfolders and the recordings below
                are deleted too.
            remove_files: When ``False`` the media is kept on disk.

        Returns:
            The recordings that were deleted along the way.

        Raises:
            FolderNotFound: If no row matches ``folder_id``.
            FolderNotEmpty: If the folder still holds something and
                ``recursive`` is ``False``.
        """
        if not recursive:
            self.folders.delete(folder_id)
            return []

        branch = self.folders.subtree_ids(folder_id)
        with self.database.transaction():
            deleted = self.index.search(folder_id=branch)
            for recording in deleted:
                self.index.delete(recording.id)
            # The recursive query walks down from the root of the branch, so
            # reading it backwards always reaches a folder after its children.
            for identifier in reversed(branch):
                self.folders.delete(identifier)

        if remove_files:
            for recording in deleted:
                self.blobs.remove_dir(recording.id)
        return deleted

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
        folder_id: FolderFilter = ANY_FOLDER,
        recursive: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Recording]:
        """List recordings, newest first.

        Args:
            status: Keep only these statuses. ``None`` keeps everything.
            folder_id: Keep only what sits in this folder, or — with ``None``
                — at the top level. Defaults to :data:`ANY_FOLDER`, which
                keeps everything.
            recursive: When ``True`` the subfolders are included as well.
            limit: Maximum number of recordings to return.
            offset: Number of recordings to skip.

        Returns:
            The matching recordings, ordered by upload time descending.

        Raises:
            FolderNotFound: If ``folder_id`` matches no folder.
        """
        wanted: FolderFilter | Sequence[str] = folder_id
        if recursive and isinstance(folder_id, str):
            wanted = self.folders.subtree_ids(folder_id)
        elif recursive and folder_id is None:
            # Everything hangs below the top level, so there is nothing left
            # to filter on.
            wanted = ANY_FOLDER

        return self.index.search(
            status=status, folder_id=wanted, limit=limit, offset=offset
        )

    def move_recording(self, recording_id: str, folder_id: str | None) -> Recording:
        """File a recording under another folder, leaving its media in place."""
        return self.index.move(recording_id, folder_id)

    def update_status(self, recording_id: str, status: RecordingStatus) -> Recording:
        """Move a recording to another pipeline status."""
        return self.index.update_status(recording_id, status)

    def claim_next(self) -> Recording | None:
        """Atomically take the oldest pending recording and mark it running."""
        return self.index.claim_next()

    # --------------------------------------------------------- folder facade

    def create_folder(self, name: str, *, parent_id: str | None = None) -> Folder:
        """Create an empty folder. See :meth:`FolderTree.create`."""
        return self.folders.create(name, parent_id=parent_id)

    def get_folder(self, folder_id: str) -> Folder:
        """Return one folder by id."""
        return self.folders.get(folder_id)

    def list_folders(self, parent_id: str | None = None) -> list[Folder]:
        """List the folders sitting directly inside ``parent_id``."""
        return self.folders.children(parent_id)

    def all_folders(self) -> list[Folder]:
        """Return every folder, for a caller drawing the whole tree."""
        return self.folders.all()

    def folder_path(self, folder_id: str) -> list[Folder]:
        """Return the folders leading to ``folder_id``, root first."""
        return self.folders.path(folder_id)

    def rename_folder(self, folder_id: str, name: str) -> Folder:
        """Give a folder another name, leaving it where it is."""
        return self.folders.rename(folder_id, name)

    def move_folder(self, folder_id: str, parent_id: str | None) -> Folder:
        """Move a folder, and everything under it, into ``parent_id``."""
        return self.folders.move(folder_id, parent_id)

    def folder_counts(self) -> dict[str | None, int]:
        """Return how many recordings sit in each folder, top level included."""
        return self.index.count_by_folder()

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
        self.database.close()

    def __enter__(self) -> Self:
        """Return the connector itself, for use as a context manager."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close the database connection when leaving the block."""
        self.close()

    def __repr__(self) -> str:
        """Return a debug representation showing the storage root."""
        return f"{type(self).__name__}(root={str(self.root)!r})"
