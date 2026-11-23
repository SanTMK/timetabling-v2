"""Creado con Claude.

Configuración común de la suite. Bloquea la red **en ejecución** durante toda la sesión (§2, §20):
cualquier intento de crear un socket o abrir una conexión falla la prueba.
"""

import socket
from collections.abc import Iterator
from typing import Any, NoReturn

import pytest


class RedBloqueadaError(RuntimeError):
    """Se intentó usar la red durante las pruebas."""


def _bloquear(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise RedBloqueadaError("La aplicación no debe usar la red (§2): se intentó abrir un socket.")


@pytest.fixture(autouse=True, scope="session")
def _sin_red() -> Iterator[None]:
    """Sustituye `socket.socket` y `socket.create_connection` durante toda la suite."""
    original_socket = socket.socket
    original_conexion = socket.create_connection
    socket.socket = _bloquear  # type: ignore[misc, assignment]
    socket.create_connection = _bloquear  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = original_socket  # type: ignore[misc]
        socket.create_connection = original_conexion
