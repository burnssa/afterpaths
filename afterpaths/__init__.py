"""Afterpaths: A research log for AI-assisted work."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("afterpaths")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
