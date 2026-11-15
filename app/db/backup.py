"""Consistent, project-local snapshots made before schema changes."""

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

from app.core.paths import safe_path


def backup_before_migration(db: sqlite3.Connection) -> Path | None:
    """Snapshot committed main DB, while caller holds BEGIN IMMEDIATE.

    A separate read connection avoids backing up a connection with an active
    write transaction (which would block). The caller's reserved write lock
    prevents concurrent writers until migration finishes. SQLite's backup API
    includes committed WAL frames and produces a standalone restore file.
    """
    filename = next(row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main')
    if not filename:  # In-memory databases have no persistent data to restore.
        return None
    source_path = safe_path(filename)
    directory = safe_path(source_path.parent / 'backups')
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = safe_path(directory / f'{source_path.name}.{timestamp}.bak')
    # Never overwrite an earlier backup, including a collision or linked file.
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise sqlite3.DatabaseError('Invalid backup')
        return destination
    except BaseException:
        # Only remove the file exclusively created above. Never expose a
        # partial file as a valid restore point or print raw SQLite errors.
        try:
            destination.unlink()
        except OSError:
            pass
        raise
