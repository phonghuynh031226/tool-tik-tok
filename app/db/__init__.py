"""SQLite history implementation; importing does not open a database."""

from .repository import DuplicateJobError, SQLiteHistoryRepository

__all__ = ['DuplicateJobError', 'SQLiteHistoryRepository']
