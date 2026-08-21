"""Filesystem side of the memory connector: one folder per recording."""

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from connectors.memory_connector.types import BlobNotFound, InvalidKey

_ID_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class RecordingBlobs:
    """The media files of every recording, stored under a single root.

    Each recording owns a folder named after its id, holding the uploaded
    media plus whatever the pipeline produces later (transcript, notes, ...).
    This subsystem knows nothing about the index: it never checks whether a
    recording is registered, it only reads and writes files.
    """

    def __init__(self, root: Path | str) -> None:
        """Open the blob storage rooted at ``root``, creating it when missing.

        Args:
            root: Directory that holds one folder per recording. It may be a
                local path or the mount point of a Docker volume.
        """
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def dir_for(self, recording_id: str) -> Path:
        """Return the absolute path of a recording folder (no disk access).

        Raises:
            InvalidKey: If ``recording_id`` is not a safe folder name.
        """
        if not _ID_PATTERN.match(recording_id):
            raise InvalidKey(f"Invalid recording id: {recording_id!r}")
        return self.root / recording_id

    def ensure_dir(self, recording_id: str) -> bool:
        """Create the folder of a recording if it is not there yet.

        Returns:
            ``True`` when the folder was created by this call, ``False`` when
            it already existed. The caller uses it to know what to clean up.
        """
        directory = self.dir_for(recording_id)
        existed = directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        return not existed

    def remove_dir(self, recording_id: str) -> None:
        """Delete the folder of a recording and everything inside it."""
        shutil.rmtree(self.dir_for(recording_id), ignore_errors=True)

    def save(
        self,
        recording_id: str,
        filename: str,
        source: BinaryIO | Path | bytes | bytearray | memoryview,
    ) -> Path:
        """Write a file inside a recording folder, atomically.

        The bytes land in a temporary file that is then renamed over the
        target, so readers never observe a half written blob. Streams and paths
        are copied in chunks, which keeps memory flat on large media files.

        Args:
            recording_id: Recording that owns the file.
            filename: Name of the file, optionally with subfolders
                (``"chunks/001.wav"``). It must stay inside the folder.
            source: An open binary stream, a path to copy from, or raw bytes.

        Returns:
            The path the file was written to.

        Raises:
            InvalidKey: If the resulting path would escape the folder.
        """
        target = self._resolve(recording_id, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")

        try:
            with temporary.open("wb") as destination:
                if isinstance(source, bytes | bytearray | memoryview):
                    destination.write(source)
                elif isinstance(source, Path):
                    with source.open("rb") as origin:
                        shutil.copyfileobj(origin, destination)
                else:
                    shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        return target

    def open_file(self, recording_id: str, filename: str) -> BinaryIO:
        """Open a file of a recording for streaming reads.

        The caller owns the handle and is expected to close it.

        Raises:
            BlobNotFound: If the file does not exist.
        """
        path = self._resolve(recording_id, filename)
        try:
            return path.open("rb")
        except FileNotFoundError as error:
            raise BlobNotFound(
                f"No such file: {recording_id!r}/{filename!r}"
            ) from error

    def read_text(
        self, recording_id: str, filename: str, *, encoding: str = "utf-8"
    ) -> str:
        """Read a whole text file, for transcripts and notes.

        Raises:
            BlobNotFound: If the file does not exist.
        """
        path = self._resolve(recording_id, filename)
        try:
            return path.read_text(encoding=encoding)
        except FileNotFoundError as error:
            raise BlobNotFound(
                f"No such file: {recording_id!r}/{filename!r}"
            ) from error

    def write_text(
        self, recording_id: str, filename: str, text: str, *, encoding: str = "utf-8"
    ) -> Path:
        """Write a text file inside a recording folder, atomically."""
        return self.save(recording_id, filename, text.encode(encoding))

    def list_files(self, recording_id: str) -> list[str]:
        """List the files of a recording, relative to its folder.

        Returns:
            Sorted relative names, subfolders included. Empty when the folder
            does not exist yet.
        """
        directory = self.dir_for(recording_id)
        if not directory.is_dir():
            return []
        return sorted(
            str(path.relative_to(directory))
            for path in directory.rglob("*")
            if path.is_file() and not path.name.endswith(".tmp")
        )

    def has_file(self, recording_id: str, filename: str) -> bool:
        """Tell whether a recording holds that file."""
        return self._resolve(recording_id, filename).is_file()

    def delete_file(self, recording_id: str, filename: str) -> bool:
        """Delete one file of a recording.

        Returns:
            ``True`` if a file was removed, ``False`` if it was already gone.
        """
        path = self._resolve(recording_id, filename)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def dir_names(self) -> set[str]:
        """Return the name of every recording folder currently on disk."""
        return {path.name for path in self.root.iterdir() if path.is_dir()}

    def _resolve(self, recording_id: str, filename: str) -> Path:
        """Resolve a file name inside a recording folder, refusing escapes."""
        directory = self.dir_for(recording_id)
        if not filename or "\x00" in filename or Path(filename).is_absolute():
            raise InvalidKey(f"Invalid file name: {filename!r}")
        resolved = (directory / filename).resolve()
        if not resolved.is_relative_to(directory.resolve()):
            raise InvalidKey(f"Invalid file name: {filename!r}")
        return resolved

    def __repr__(self) -> str:
        """Return a debug representation showing the blob root."""
        return f"{type(self).__name__}(root={str(self.root)!r})"
