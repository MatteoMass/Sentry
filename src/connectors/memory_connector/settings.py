"""Key/value side of the memory connector: what the user changed by hand.

Everything here is an override. A setting that was never touched has no row
at all, and the caller is the one holding the default — which is what lets a
default be improved in the code and reach every installation that never
disagreed with it.

The values are opaque text: this subsystem stores and returns them, and what
they mean belongs to whoever asked. Prompts are the only ones so far.
"""

from collections.abc import Iterator

from connectors.memory_connector.db import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


class SettingsStore:
    """The settings table: one row per value that differs from the default.

    Example:
        >>> settings = SettingsStore(database)
        >>> settings.set("prompt.transcription", "You transcribe…")
        >>> settings.get("prompt.transcription")
        'You transcribe…'
    """

    def __init__(self, database: Database) -> None:
        """Create the settings schema on ``database`` when it is missing.

        Args:
            database: Connection shared with the other tabular subsystems.
        """
        self.database = database
        self.database.executescript(_SCHEMA)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Return the stored value of ``key``, or ``default`` when unset."""
        row = self.database.query_one(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return default if row is None else str(row["value"])

    def set(self, key: str, value: str) -> str:
        """Store ``value`` under ``key``, replacing whatever was there.

        Returns:
            The value as it was stored.
        """
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO settings (key, value, updated_at)"
                " VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                " ON CONFLICT (key) DO UPDATE SET"
                " value = excluded.value, updated_at = excluded.updated_at",
                (key, value),
            )
        return value

    def unset(self, key: str) -> bool:
        """Drop the override of ``key``, putting the default back in charge.

        Returns:
            ``True`` when a row was actually deleted.
        """
        with self.database.transaction() as connection:
            return (
                connection.execute(
                    "DELETE FROM settings WHERE key = ?", (key,)
                ).rowcount
                > 0
            )

    def all(self) -> dict[str, str]:
        """Return every stored override, by key."""
        return {
            str(row["key"]): str(row["value"])
            for row in self.database.query("SELECT key, value FROM settings")
        }

    def __contains__(self, key: object) -> bool:
        """Tell whether that key carries an override."""
        return isinstance(key, str) and self.get(key) is not None

    def __iter__(self) -> Iterator[str]:
        """Iterate over the keys that carry an override."""
        return iter(self.all())

    def __repr__(self) -> str:
        """Return a debug representation showing the database behind it."""
        return f"{type(self).__name__}(database={self.database!r})"
