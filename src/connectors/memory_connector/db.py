"""The SQLite file shared by the tabular subsystems of the connector."""

import sqlite3
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Self

_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
)


class Database:
    """One SQLite connection, shared by every tabular subsystem.

    Folders and recordings live in the same file and point at each other
    through a foreign key, so they must also share a connection: two
    connections could not commit a change spanning both tables atomically, and
    SQLite applies ``PRAGMA foreign_keys`` per connection anyway.

    It is safe to share between threads, since the file runs in WAL mode and
    every statement is serialised on an internal lock.
    """

    def __init__(self, path: Path | str) -> None:
        """Open the database, creating the file when missing.

        Args:
            path: Path of the SQLite file. Its parent must already exist.
        """
        self.path = Path(path)
        self._lock = threading.RLock()
        self._depth = 0
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            for pragma in _PRAGMAS:
                self._connection.execute(pragma)

    def executescript(self, script: str) -> None:
        """Run a schema script, outside of any transaction."""
        with self._lock:
            self._connection.executescript(script)

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """Run a block inside a write transaction, rolling back on failure.

        Nesting is allowed, so a caller spanning two subsystems can wrap both
        in one atomic unit: the outermost block owns the transaction and the
        inner ones take a savepoint, which lets an inner failure be caught and
        undone without losing the work done by the outer one.

        Yields:
            The underlying connection, inside a transaction.
        """
        with self._lock:
            if self._depth:
                yield from self._savepoint()
                return

            self._connection.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self._connection
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")
            finally:
                self._depth = 0

    def _savepoint(self) -> Generator[sqlite3.Connection]:
        """Run a nested block inside a savepoint of the running transaction."""
        name = f"nested_{self._depth}"
        self._connection.execute(f"SAVEPOINT {name}")
        self._depth += 1
        try:
            yield self._connection
        except BaseException:
            self._connection.execute(f"ROLLBACK TO {name}")
            raise
        finally:
            self._depth -= 1
            self._connection.execute(f"RELEASE {name}")

    def query(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> list[sqlite3.Row]:
        """Run a read query and return every row."""
        with self._lock:
            return self._connection.execute(sql, parameters).fetchall()

    def query_one(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Row | None:
        """Run a read query and return its first row, if any."""
        with self._lock:
            return self._connection.execute(sql, parameters).fetchone()

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            self._connection.close()

    def __enter__(self) -> Self:
        """Return the database itself, for use as a context manager."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close the connection when leaving the block."""
        self.close()

    def __repr__(self) -> str:
        """Return a debug representation showing the file path."""
        return f"{type(self).__name__}(path={str(self.path)!r})"
