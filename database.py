"""Compatibility exports for database helpers."""

from commerce.config import DB_NAME
from commerce.db.connection import get_connection
from commerce.db.schema import initialize_database

# Preserve the original public name used by existing scripts.
initilize_database = initialize_database

__all__ = ["DB_NAME", "get_connection", "initialize_database", "initilize_database"]
