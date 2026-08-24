"""Tree side of the memory connector: the folders recordings are filed under."""

import sqlite3
from datetime import UTC, datetime

from connectors.memory_connector.db import Database
from connectors.memory_connector.types import (
    Folder,
    FolderAlreadyExists,
    FolderNotEmpty,
    FolderNotFound,
    InvalidFolderMove,
    new_folder_id,
    normalize_folder_name,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id         TEXT PRIMARY KEY,
    parent_id  TEXT REFERENCES folders (id) ON DELETE RESTRICT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders (parent_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_sibling_name
    ON folders (ifnull(parent_id, ''), name);
"""

_SUBTREE = """
WITH RECURSIVE subtree (id) AS (
    SELECT id FROM folders WHERE id = ?
    UNION ALL
    SELECT folders.id FROM folders JOIN subtree ON folders.parent_id = subtree.id
)
SELECT id FROM subtree
"""

_ANCESTRY = """
WITH RECURSIVE ancestry (id, parent_id, name, created_at, depth) AS (
    SELECT id, parent_id, name, created_at, 0 FROM folders WHERE id = ?
    UNION ALL
    SELECT folders.id, folders.parent_id, folders.name, folders.created_at,
           ancestry.depth + 1
    FROM folders JOIN ancestry ON folders.id = ancestry.parent_id
)
SELECT * FROM ancestry ORDER BY depth DESC
"""


class FolderTree:
    """The folders table, a tree stored as an adjacency list.

    A folder is a label, not a directory: nothing here ever touches the disk,
    where every recording keeps living in its own flat folder under the
    recordings root. Filing a recording, or moving a whole branch, is a single
    ``UPDATE`` — no bytes move.

    The tree is held as ``parent_id`` pointers rather than materialised paths,
    so renaming a folder stays one row rather than a rewrite of everything
    below it. Reading a branch costs a recursive query instead, which is what
    the two module level statements do.

    This subsystem knows nothing about recordings: the foreign key pointing
    the other way is declared on their table, and it is the database that
    refuses to drop a folder still in use.
    """

    def __init__(self, database: Database) -> None:
        """Create the folders schema on ``database`` when it is missing.

        Args:
            database: Connection shared with the other tabular subsystems.
        """
        self.database = database
        self.database.executescript(_SCHEMA)

    def create(
        self,
        name: str,
        *,
        parent_id: str | None = None,
        folder_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Folder:
        """Create a folder, empty, under ``parent_id``.

        Args:
            name: Name to show. It is stripped of surrounding spaces and must
                be free among its siblings.
            parent_id: Folder to create it in. ``None`` puts it at the top.
            folder_id: Identifier to use. When ``None`` a random one is
                generated.
            created_at: Creation time. Defaults to now, in UTC.

        Returns:
            The folder as it was stored.

        Raises:
            InvalidFolderName: If ``name`` is empty or holds a separator.
            FolderNotFound: If ``parent_id`` matches no folder.
            FolderAlreadyExists: If a sibling already carries that name.
        """
        cleaned = normalize_folder_name(name)
        identifier = folder_id or new_folder_id()
        moment = (created_at or datetime.now(UTC)).astimezone(UTC)

        with self.database.transaction() as connection:
            # Checked rather than left to the foreign key, which cannot say
            # whether it was the parent or something else that went missing.
            self._ensure_exists(parent_id)
            try:
                connection.execute(
                    "INSERT INTO folders (id, parent_id, name, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (identifier, parent_id, cleaned, moment.isoformat()),
                )
            except sqlite3.IntegrityError as error:
                raise FolderAlreadyExists(
                    f"A folder here is already named {cleaned!r}"
                ) from error

        return Folder(
            id=identifier, name=cleaned, parent_id=parent_id, created_at=moment
        )

    def get(self, folder_id: str) -> Folder:
        """Return one folder by id.

        Raises:
            FolderNotFound: If no row matches ``folder_id``.
        """
        row = self.database.query_one(
            "SELECT * FROM folders WHERE id = ?", (folder_id,)
        )
        if row is None:
            raise FolderNotFound(f"No such folder: {folder_id!r}")
        return Folder.from_row(row)

    def children(self, parent_id: str | None = None) -> list[Folder]:
        """List the folders sitting directly inside ``parent_id``.

        Args:
            parent_id: Folder to look into. ``None`` lists the top level.

        Returns:
            The direct children, ordered by name.
        """
        if parent_id is None:
            query = "SELECT * FROM folders WHERE parent_id IS NULL ORDER BY name"
            parameters: tuple[object, ...] = ()
        else:
            query = "SELECT * FROM folders WHERE parent_id = ? ORDER BY name"
            parameters = (parent_id,)
        return [Folder.from_row(row) for row in self.database.query(query, parameters)]

    def all(self) -> list[Folder]:
        """Return every folder, ordered by name.

        The whole tree is small enough to travel in one piece, which is what a
        sidebar wants: it can nest the rows itself instead of asking level by
        level.
        """
        return [
            Folder.from_row(row)
            for row in self.database.query("SELECT * FROM folders ORDER BY name")
        ]

    def path(self, folder_id: str) -> list[Folder]:
        """Return the folders leading to ``folder_id``, root first.

        The last element is the folder itself, so the result reads as a
        breadcrumb.

        Raises:
            FolderNotFound: If no row matches ``folder_id``.
        """
        rows = self.database.query(_ANCESTRY, (folder_id,))
        if not rows:
            raise FolderNotFound(f"No such folder: {folder_id!r}")
        return [Folder.from_row(row) for row in rows]

    def subtree_ids(self, folder_id: str) -> list[str]:
        """Return the id of ``folder_id`` and of every folder below it.

        Raises:
            FolderNotFound: If no row matches ``folder_id``.
        """
        rows = self.database.query(_SUBTREE, (folder_id,))
        if not rows:
            raise FolderNotFound(f"No such folder: {folder_id!r}")
        return [row["id"] for row in rows]

    def rename(self, folder_id: str, name: str) -> Folder:
        """Give a folder another name, leaving it where it is.

        Nothing below the folder is touched: the tree stores pointers, so a
        rename never propagates.

        Raises:
            InvalidFolderName: If ``name`` is empty or holds a separator.
            FolderNotFound: If no row matches ``folder_id``.
            FolderAlreadyExists: If a sibling already carries that name.
        """
        cleaned = normalize_folder_name(name)
        with self.database.transaction() as connection:
            try:
                cursor = connection.execute(
                    "UPDATE folders SET name = ? WHERE id = ?", (cleaned, folder_id)
                )
            except sqlite3.IntegrityError as error:
                raise FolderAlreadyExists(
                    f"A folder here is already named {cleaned!r}"
                ) from error
            if cursor.rowcount == 0:
                raise FolderNotFound(f"No such folder: {folder_id!r}")
        return self.get(folder_id)

    def move(self, folder_id: str, parent_id: str | None) -> Folder:
        """Move a folder, and everything under it, into ``parent_id``.

        Args:
            folder_id: Folder to move.
            parent_id: Destination. ``None`` moves it to the top level.

        Returns:
            The folder as it now stands.

        Raises:
            FolderNotFound: If either id matches no folder.
            InvalidFolderMove: If the destination is the folder itself or one
                of its descendants, which would detach the branch.
            FolderAlreadyExists: If the destination already holds a folder
                with that name.
        """
        with self.database.transaction() as connection:
            self.get(folder_id)
            self._ensure_exists(parent_id)
            if parent_id is not None and parent_id in self.subtree_ids(folder_id):
                raise InvalidFolderMove("A folder cannot be moved inside itself.")
            try:
                connection.execute(
                    "UPDATE folders SET parent_id = ? WHERE id = ?",
                    (parent_id, folder_id),
                )
            except sqlite3.IntegrityError as error:
                raise FolderAlreadyExists(
                    "The destination already holds a folder with this name."
                ) from error
        return self.get(folder_id)

    def delete(self, folder_id: str) -> None:
        """Delete one empty folder.

        Emptiness is enforced twice over: subfolders are looked up here, while
        recordings are left to the foreign key on their table, which keeps
        this subsystem unaware of them.

        Raises:
            FolderNotFound: If no row matches ``folder_id``.
            FolderNotEmpty: If the folder still holds subfolders or
                recordings.
        """
        with self.database.transaction() as connection:
            if self.children(folder_id):
                raise FolderNotEmpty(
                    f"The folder still holds subfolders: {folder_id!r}"
                )
            try:
                cursor = connection.execute(
                    "DELETE FROM folders WHERE id = ?", (folder_id,)
                )
            except sqlite3.IntegrityError as error:
                raise FolderNotEmpty(
                    f"The folder still holds recordings: {folder_id!r}"
                ) from error
            if cursor.rowcount == 0:
                raise FolderNotFound(f"No such folder: {folder_id!r}")

    def _ensure_exists(self, folder_id: str | None) -> None:
        """Raise unless ``folder_id`` is a real folder, ``None`` being the top.

        Raises:
            FolderNotFound: If no row matches ``folder_id``.
        """
        if folder_id is not None:
            self.get(folder_id)

    def __repr__(self) -> str:
        """Return a debug representation showing the database path."""
        return f"{type(self).__name__}(database={self.database!r})"
