"""Creado con Claude.

Verifica que cada `.py` de `src/` y `pruebas/` empiece con un docstring de módulo cuya primera
línea sea «Creado con Claude.», y que el README lo indique al principio (§0, regla 4).
"""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
MARCA = "Creado con Claude."


def _archivos_python() -> list[Path]:
    archivos: list[Path] = []
    for carpeta in ("src", "pruebas"):
        archivos.extend(sorted((RAIZ / carpeta).rglob("*.py")))
    return archivos


def test_hay_archivos_que_revisar() -> None:
    assert _archivos_python(), "No se encontraron archivos .py en src/ ni pruebas/"


@pytest.mark.parametrize(
    "ruta", _archivos_python(), ids=lambda r: str(r.relative_to(RAIZ)).replace("\\", "/")
)
def test_py_empieza_con_marca(ruta: Path) -> None:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    assert arbol.body, f"{ruta.name} está vacío: falta el docstring de módulo"
    primero = arbol.body[0]
    assert (
        isinstance(primero, ast.Expr)
        and isinstance(primero.value, ast.Constant)
        and isinstance(primero.value.value, str)
    ), f"{ruta.name} no empieza con un docstring de módulo"
    primera_linea = primero.value.value.strip().splitlines()[0].strip()
    assert primera_linea == MARCA, f"{ruta.name}: la primera línea del docstring debe ser «{MARCA}»"


def test_readme_empieza_con_marca() -> None:
    lineas = [
        linea.strip()
        for linea in (RAIZ / "README.md").read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]
    assert any(MARCA in linea for linea in lineas[:3]), (
        f"El README debe indicar «{MARCA}» al principio"
    )
