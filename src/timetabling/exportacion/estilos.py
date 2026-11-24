"""Creado con Claude.

Estilos compartidos por las exportaciones: nombres de hoja seguros y textos de encabezado.
"""

import re

LIMITE_NOMBRE_HOJA = 31
_PROHIBIDOS = re.compile(r"[\[\]:*?/\\]")


def nombre_hoja(texto: str, usados: set[str]) -> str:
    """Sanea (`[]:*?/\\` → `_`), recorta a 31 caracteres y agrega « (2)», « (3)»… si se repite
    (sin distinguir mayúsculas, como Excel)."""
    base = _PROHIBIDOS.sub("_", texto).strip().strip("'") or "Hoja"
    base = base[:LIMITE_NOMBRE_HOJA]
    nombre = base
    n = 2
    while nombre.lower() in {u.lower() for u in usados}:
        sufijo = f" ({n})"
        nombre = base[: LIMITE_NOMBRE_HOJA - len(sufijo)] + sufijo
        n += 1
    usados.add(nombre)
    return nombre
