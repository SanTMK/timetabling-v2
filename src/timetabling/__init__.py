"""Creado con Claude.

Timetabling escolar v2: generación y edición manual de horarios sin conexión.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("timetabling")
except PackageNotFoundError:  # pragma: no cover - solo sin instalar
    __version__ = "0.0.0"

__all__ = ["__version__"]
