"""Creado con Claude.

Versiones del esquema (§6.2). `esquema.sql` describe siempre la versión actual y
`MIGRACIONES[n]` lleva un proyecto de la versión `n-1` a la `n`. La v2 de la aplicación empieza
en la versión 1 y no comparte numeración con la versión anterior (esquema v6).
"""

import sqlite3
from collections.abc import Callable
from importlib import resources

VERSION_ESQUEMA = 1
APLICACION = "timetabling-v2"

Migracion = Callable[[sqlite3.Connection], None]
MIGRACIONES: dict[int, Migracion] = {}


class ErrorProyecto(Exception):
    """Error al abrir o usar un archivo de proyecto."""


class ErrorVersionEsquema(ErrorProyecto):
    """El proyecto fue creado con una versión más nueva del programa."""


class ErrorProyectoAnterior(ErrorProyecto):
    """El archivo es de la versión anterior de la aplicación (esquema v6): hay que importarlo."""


class ErrorArchivoNoValido(ErrorProyecto):
    """El archivo no es un proyecto de horarios."""


def texto_esquema() -> str:
    return resources.files("timetabling.persistencia").joinpath("esquema.sql").read_text("utf-8")


def crear_esquema(con: sqlite3.Connection) -> None:
    """Crea el esquema actual en una base vacía (dentro de la transacción en curso)."""
    for sentencia in _sentencias(texto_esquema()):
        con.execute(sentencia)
    con.executemany(
        "INSERT INTO metadatos (clave, valor) VALUES (?, ?)",
        [("aplicacion", APLICACION), ("version_esquema", str(VERSION_ESQUEMA))],
    )


def _sentencias(sql: str) -> list[str]:
    """Divide el script en sentencias (el esquema no usa `;` dentro de literales)."""
    sin_comentarios = "\n".join(
        linea for linea in sql.splitlines() if not linea.lstrip().startswith("--")
    )
    return [s.strip() for s in sin_comentarios.split(";") if s.strip()]


def tablas(con: sqlite3.Connection) -> set[str]:
    filas = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {fila[0] for fila in filas}


def leer_version(con: sqlite3.Connection) -> int:
    """Devuelve la versión del esquema o lanza el error adecuado si el archivo no es de la v2."""
    try:
        existentes = tablas(con)
    except sqlite3.DatabaseError as error:
        raise ErrorArchivoNoValido(
            "El archivo no es una base de datos de proyecto válida."
        ) from error
    if "esquema_version" in existentes and "metadatos" not in existentes:
        raise ErrorProyectoAnterior(
            "Este archivo es de la versión anterior del programa. "
            "Use «Archivo → Importar proyecto anterior…» para convertirlo."
        )
    if "metadatos" not in existentes:
        raise ErrorArchivoNoValido("El archivo no es un proyecto de horarios.")
    filas = dict(con.execute("SELECT clave, valor FROM metadatos").fetchall())
    if filas.get("aplicacion") != APLICACION or "version_esquema" not in filas:
        raise ErrorArchivoNoValido("El archivo no es un proyecto de horarios de esta aplicación.")
    return int(filas["version_esquema"])


def verificar_version(version: int) -> None:
    if version > VERSION_ESQUEMA:
        raise ErrorVersionEsquema(
            f"El proyecto usa la versión {version} del formato y este programa solo entiende "
            f"hasta la {VERSION_ESQUEMA}. Actualice el programa para abrirlo."
        )


def migrar(con: sqlite3.Connection, desde: int) -> int:
    """Aplica las migraciones pendientes (dentro de la transacción en curso)."""
    for destino in range(desde + 1, VERSION_ESQUEMA + 1):
        MIGRACIONES[destino](con)
        con.execute(
            "UPDATE metadatos SET valor = ? WHERE clave = 'version_esquema'", (str(destino),)
        )
    return VERSION_ESQUEMA
