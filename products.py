"""Compatibility launcher for product seeding."""

from commerce.db.schema import initialize_database
from commerce.db.seed import seed_products

initialize_database()
seed_products()

__all__ = ["seed_products"]
