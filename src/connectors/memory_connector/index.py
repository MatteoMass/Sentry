"""SQLite side of the memory connector: the tabular index of recordings."""

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from connectors.memory_connector.db import Database
from connectors.memory_connector.types import (
    ANY_FOLDER,
    LEGACY_STATUSES,
    RECORDING_STATUSES,
    FolderFilter,
    FolderNotFound,
    Recording,
    RecordingAlreadyExists,
    RecordingNotFound,
    RecordingStatus,
    new_recording_id,
    normalize_recording_name,
    validate_status,
)

_STATUS_CHECK = ", ".join(f"'{status}'" for status in RECORDING_STATUSES)
"""The statuses spelled as SQL, so the table cannot drift from the type."""

_COLUMNS = f"""
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ({_STATUS_CHECK})),
    folder_id   TEXT REFERENCES folders (id) ON DELETE RESTRICT
"""

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS recordings ({_COLUMNS});
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings (status);
CREATE INDEX IF NOT EXISTS idx_recordings_uploaded_at ON recordings (uploaded_at);
CREATE INDEX IF NOT EXISTS idx_recordings_folder ON recordings (folder_id);
"""


class RecordingIndex:
    """The recordings table, backed by a SQLite file.

    This subsystem knows nothing about blobs: it stores and queries rows only.
    Folders it knows by id alone — the tree itself belongs to
    :class:`FolderTree`, which must be built first, since the recordings table
    points at the table it owns.
    """

    def __init__(self, database: Database) -> None:
        """Create the recordings schema on ``database`` when it is missing.

        Args:
            database: Connection shared with the other tabular subsystems.
        """
        self.database = database
        _migrate_statuses(database)
        self.database.executescript(_SCHEMA)

    @property
    def db_path(self) -> Path:
        """Path of the SQLite file."""
        return self.database.path

    def create(
        self,
        name: str,
        *,
        recording_id: str | None = None,
        status: RecordingStatus = "to_process",
        uploaded_at: datetime | None = None,
        folder_id: str | None = None,
    ) -> Recording:
        """Insert a new row.

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
        """
        identifier = recording_id or new_recording_id()
        validate_status(status)
        moment = (uploaded_at or datetime.now(UTC)).astimezone(UTC)

        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO recordings (id, name, uploaded_at, status, folder_id)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (identifier, name, moment.isoformat(), status, folder_id),
                )
        except sqlite3.IntegrityError as error:
            raise _integrity_error(error, identifier, folder_id) from error

        return Recording(
            id=identifier,
            name=name,
            uploaded_at=moment,
            status=status,
            folder_id=folder_id,
        )

    def get(self, recording_id: str) -> Recording:
        """Return one recording by id.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        row = self.database.query_one(
            "SELECT * FROM recordings WHERE id = ?", (recording_id,)
        )
        if row is None:
            raise RecordingNotFound(f"No such recording: {recording_id!r}")
        return Recording.from_row(row)

    def search(
        self,
        *,
        status: RecordingStatus | Sequence[RecordingStatus] | None = None,
        folder_id: FolderFilter | Sequence[str] = ANY_FOLDER,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Recording]:
        """List recordings, newest first.

        Args:
            status: Keep only these statuses. ``None`` keeps everything.
            folder_id: Keep only what sits in this folder, in any of these
                folders, or — with ``None`` — at the top level. Defaults to
                :data:`ANY_FOLDER`, which keeps everything. Listing a whole
                branch is a matter of passing the ids the tree reports for it.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.

        Returns:
            The matching recordings, ordered by upload time descending.
        """
        clauses: list[str] = []
        parameters: list[object] = []

        if status is not None:
            wanted = (status,) if isinstance(status, str) else tuple(status)
            for candidate in wanted:
                validate_status(candidate)
            clauses.append(f"status IN ({', '.join('?' * len(wanted))})")
            parameters.extend(wanted)

        if folder_id is not ANY_FOLDER:
            if folder_id is None:
                clauses.append("folder_id IS NULL")
            elif isinstance(folder_id, str):
                clauses.append("folder_id = ?")
                parameters.append(folder_id)
            else:
                folders = tuple(folder_id)
                if not folders:
                    return []
                clauses.append(f"folder_id IN ({', '.join('?' * len(folders))})")
                parameters.extend(folders)

        query = "SELECT * FROM recordings"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY uploaded_at DESC, id DESC LIMIT ? OFFSET ?"
        parameters.extend((limit if limit is not None else -1, offset))

        return [
            Recording.from_row(row) for row in self.database.query(query, parameters)
        ]

    def update_status(self, recording_id: str, status: RecordingStatus) -> Recording:
        """Move a recording to another pipeline status.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        validate_status(status)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE recordings SET status = ? WHERE id = ?",
                (status, recording_id),
            )
            if cursor.rowcount == 0:
                raise RecordingNotFound(f"No such recording: {recording_id!r}")
        return self.get(recording_id)

    def rename(self, recording_id: str, name: str) -> Recording:
        """Give a recording another name.

        Nothing on disk is touched: the folder holding the media is named
        after the identifier, which a rename never changes. Two recordings may
        carry the same name — they usually do, when the same file is uploaded
        twice — so nothing is checked beyond the name itself.

        Args:
            recording_id: Recording to rename.
            name: New name, stripped of its surrounding spaces.

        Returns:
            The recording as it now stands.

        Raises:
            InvalidRecordingName: If the name is empty or holds a separator.
            RecordingNotFound: If no row matches ``recording_id``.
        """
        cleaned = normalize_recording_name(name)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE recordings SET name = ? WHERE id = ?",
                (cleaned, recording_id),
            )
            if cursor.rowcount == 0:
                raise RecordingNotFound(f"No such recording: {recording_id!r}")
        return self.get(recording_id)

    def move(self, recording_id: str, folder_id: str | None) -> Recording:
        """File a recording under another folder.

        Only this row changes: the media stays exactly where it is on disk.

        Args:
            recording_id: Recording to move.
            folder_id: Destination folder. ``None`` moves it to the top level.

        Returns:
            The recording as it now stands.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
            FolderNotFound: If ``folder_id`` matches no folder.
        """
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE recordings SET folder_id = ? WHERE id = ?",
                    (folder_id, recording_id),
                )
        except sqlite3.IntegrityError as error:
            raise FolderNotFound(f"No such folder: {folder_id!r}") from error
        if cursor.rowcount == 0:
            raise RecordingNotFound(f"No such recording: {recording_id!r}")
        return self.get(recording_id)

    def count_by_folder(self) -> dict[str | None, int]:
        """Return how many recordings sit in each folder.

        Returns:
            A count per folder id, with ``None`` holding the top level. Empty
            folders are absent, since the count comes from the recordings.
        """
        return {
            row["folder_id"]: row["total"]
            for row in self.database.query(
                "SELECT folder_id, COUNT(*) AS total FROM recordings"
                " GROUP BY folder_id"
            )
        }

    def claim_next(self) -> Recording | None:
        """Atomically take the oldest pending recording and mark it running.

        It is claimed as ``transcribing``, which is the step a recording still
        in ``to_process`` has to start with.

        Returns:
            The claimed recording, or ``None`` when nothing is pending.
        """
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM recordings WHERE status = 'to_process'"
                " ORDER BY uploaded_at ASC, id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE recordings SET status = 'transcribing' WHERE id = ?",
                (row["id"],),
            )
        return self.get(row["id"])

    def delete(self, recording_id: str) -> None:
        """Delete one row.

        Raises:
            RecordingNotFound: If no row matches ``recording_id``.
        """
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM recordings WHERE id = ?", (recording_id,)
            )
            if cursor.rowcount == 0:
                raise RecordingNotFound(f"No such recording: {recording_id!r}")

    def known_ids(self) -> set[str]:
        """Return the id of every indexed recording."""
        return {row["id"] for row in self.database.query("SELECT id FROM recordings")}

    def close(self) -> None:
        """Close the shared database connection."""
        self.database.close()

    def __repr__(self) -> str:
        """Return a debug representation showing the database path."""
        return f"{type(self).__name__}(database={self.database!r})"


def _integrity_error(
    error: sqlite3.IntegrityError, recording_id: str, folder_id: str | None
) -> Exception:
    """Tell a taken id apart from a missing folder on a failed insert.

    Both arrive as the same exception, and only its message says which
    constraint gave way.
    """
    if "FOREIGN KEY" in str(error).upper():
        return FolderNotFound(f"No such folder: {folder_id!r}")
    return RecordingAlreadyExists(f"Recording already exists: {recording_id!r}")


def _migrate_statuses(database: Database) -> None:
    """Widen an existing table to the statuses of the two step pipeline.

    ``CREATE TABLE IF NOT EXISTS`` leaves a table that already exists exactly
    as it was, ``CHECK`` constraint included, and SQLite cannot alter one; a
    database written before the pipeline was split therefore has to be rebuilt
    around the new column, with the statuses it holds mapped over.

    The rebuild is skipped as soon as the constraint already names every
    status, which makes this safe to run at every open.
    """
    table = database.query_one(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'recordings'"
    )
    if table is None or all(
        f"'{status}'" in table["sql"] for status in RECORDING_STATUSES
    ):
        return

    mapping = " ".join(
        f"WHEN '{legacy}' THEN '{current}'"
        for legacy, current in LEGACY_STATUSES.items()
    )
    with database.transaction() as connection:
        # The old indexes follow the renamed table and go down with it; the
        # schema script recreates them right after.
        connection.execute("ALTER TABLE recordings RENAME TO recordings_legacy")
        connection.execute(f"CREATE TABLE recordings ({_COLUMNS})")
        connection.execute(
            "INSERT INTO recordings (id, name, uploaded_at, status, folder_id)"
            f" SELECT id, name, uploaded_at, CASE status {mapping} ELSE status END,"
            " folder_id FROM recordings_legacy"
        )
        connection.execute("DROP TABLE recordings_legacy")
