"""Compatibility launcher for the structured AI buyer API."""

from commerce.ai.api import app, main

__all__ = ["app"]


if __name__ == "__main__":
    main()
