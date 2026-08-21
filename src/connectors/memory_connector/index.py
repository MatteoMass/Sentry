"""SQLite side of the memory connector: the tabular index of recordings."""

import sqlite3
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from connectors.memory_connector.types import (
    Recording,
    RecordingAlreadyExists,
    RecordingNotFound,
    RecordingStatus,
    new_recording_id,
    validate_status,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    status      TEXT NOT NULL
                CHECK (status IN ('to_process', 'processing', 'processed', 'error'))
);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings (status);
CREATE INDEX IF NOT EXISTS idx_recordings_uploaded_at ON recordings (uploaded_at);
"""


class RecordingIndex:
    """The recordings table, backed by a SQLite file.

    This subsystem knows nothing about blobs: it stores and queries rows only.
    It is safe to share between threads, since SQLite runs in WAL mode and
    every statement is serialised on an internal lock.
    """

    def __init__(self, db_path: Path | str) -> None:
        """Open the index, creating the database and the schema when missing.

        Args:
            db_path: Path of the SQLite file. Its parent must already exist.
        """
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()

    def _configure(self) -> None:
        """Apply the connection pragmas and create the schema if needed."""
        with self._lock:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.executescript(_SCHEMA)

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """Run a block inside a write transaction, rolling back on failure.

        Yields:
            The underlying connection, inside a ``BEGIN IMMEDIATE``.
        """
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            self._connection.execute("COMMIT")

    def create(
        self,
        name: str,
        *,
        recording_id: str | None = None,
        status: RecordingStatus = "to_process",
        uploaded_at: datetime | None = None,
    ) -> Recording:
        """Insert a new row.

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
        """
        identifier = recording_id or new_recording_id()
        validate_status(status)
        moment = (uploaded_at or datetime.now(UTC)).astimezone(UTC)

        try:
            with self.transaction() as connection:
                connection.execute(
                    "INSERT INTO recordings (id, name, uploaded_at, status)"
                    " VALUES (?, ?, ?, ?)",
                    (identifier, name, moment.isoformat(), status),
                )
        except sqlite3.IntegrityError as error:
            raise RecordingAlreadyExists(
                f"Registrazione già esistente: {identifier!r}"
            ) from error

        return Recording(id=identifier, name=name, uploaded_at=moment, status=status)

    def get(self, recording_id: str) -> Recording:
        """Return one recording by id.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        if row is None:
            raise RecordingNotFound(f"Registrazione inesistente: {recording_id!r}")
        return Recording.from_row(row)

    def search(
        self,
        *,
        status: RecordingStatus | Sequence[RecordingStatus] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Recording]:
        """List recordings, newest first.

        Args:
            status: Keep only these statuses. ``None`` keeps everything.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.

        Returns:
            The matching recordings, ordered by upload time descending.
        """
        query = "SELECT * FROM recordings"
        parameters: list[object] = []

        if status is not None:
            wanted = (status,) if isinstance(status, str) else tuple(status)
            for candidate in wanted:
                validate_status(candidate)
            placeholders = ", ".join("?" * len(wanted))
            query += f" WHERE status IN ({placeholders})"
            parameters.extend(wanted)

        query += " ORDER BY uploaded_at DESC, id DESC LIMIT ? OFFSET ?"
        parameters.extend((limit if limit is not None else -1, offset))

        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [Recording.from_row(row) for row in rows]

    def update_status(self, recording_id: str, status: RecordingStatus) -> Recording:
        """Move a recording to another pipeline status.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        validate_status(status)
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE recordings SET status = ? WHERE id = ?",
                (status, recording_id),
            )
            if cursor.rowcount == 0:
                raise RecordingNotFound(f"Registrazione inesistente: {recording_id!r}")
        return self.get(recording_id)

    def claim_next(self) -> Recording | None:
        """Atomically take the oldest pending recording and mark it processing.

        Returns:
            The claimed recording, or ``None`` when nothing is pending.
        """
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM recordings WHERE status = 'to_process'"
                " ORDER BY uploaded_at ASC, id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE recordings SET status = 'processing' WHERE id = ?",
                (row["id"],),
            )
        return self.get(row["id"])

    def delete(self, recording_id: str) -> None:
        """Delete one row.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM recordings WHERE id = ?", (recording_id,)
            )
            if cursor.rowcount == 0:
                raise RecordingNotFound(f"Registrazione inesistente: {recording_id!r}")

    def known_ids(self) -> set[str]:
        """Return the id of every indexed recording."""
        with self._lock:
            return {
                row["id"]
                for row in self._connection.execute("SELECT id FROM recordings")
            }

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._connection.close()

    def __enter__(self) -> Self:
        """Return the index itself, for use as a context manager."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close the database connection when leaving the block."""
        self.close()

    def __repr__(self) -> str:
        """Return a debug representation showing the database path."""
        return f"{type(self).__name__}(db_path={str(self.db_path)!r})"
