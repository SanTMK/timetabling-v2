"""Creado con Claude.

Configuración común de la suite. Bloquea la red **en ejecución** durante toda la sesión (§2, §20):
cualquier intento de crear un socket o abrir una conexión falla la prueba.
"""

import os
import socket
from collections.abc import Iterator
from typing import Any, NoReturn

import pytest

# Las pruebas de interfaz no abren ventanas visibles.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


@pytest.fixture
def ventana(qtbot: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Ventana principal con diálogos falsos y preferencias en una carpeta temporal."""
    from pruebas.gui_utiles import DialogosFalsos
    from timetabling.gui.app import VentanaPrincipal

    monkeypatch.setenv("TIMETABLING_CONFIG", str(tmp_path / "config"))
    dialogos = DialogosFalsos()
    principal = VentanaPrincipal(dialogos=dialogos)
    qtbot.addWidget(principal)
    principal.show()
    yield principal
    if principal.contexto.sesion is not None:
        principal.contexto.sesion.cerrar()
        principal.contexto.sesion = None
