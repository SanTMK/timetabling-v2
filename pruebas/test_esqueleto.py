"""Creado con Claude.

Pruebas triviales de F0: el paquete se importa, la CLI responde `--version` y la red está
bloqueada en ejecución.
"""

import socket

import pytest
from typer.testing import CliRunner

import timetabling
from timetabling.cli import app


def test_version_del_paquete() -> None:
    assert timetabling.__version__ != "0.0.0"


def test_cli_version() -> None:
    resultado = CliRunner().invoke(app, ["--version"])
    assert resultado.exit_code == 0
    assert resultado.output.strip() == f"timetabling {timetabling.__version__}"


def test_red_bloqueada_socket() -> None:
    with pytest.raises(RuntimeError, match="red"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_red_bloqueada_conexion() -> None:
    with pytest.raises(RuntimeError, match="red"):
        socket.create_connection(("127.0.0.1", 9))
