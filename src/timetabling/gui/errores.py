"""Creado con Claude.

Traducción de errores de pydantic al español, agrupados por campo (§17: «los errores de
pydantic se traducen al español y se muestran junto al campo»).
"""

from pydantic import ValidationError

GENERAL = ""
"""Clave de los errores que no son de un campo concreto (validadores del modelo)."""

_PLANTILLAS: dict[str, str] = {
    "missing": "Este dato es obligatorio.",
    "greater_than_equal": "Debe ser mayor o igual que {ge}.",
    "less_than_equal": "Debe ser menor o igual que {le}.",
    "greater_than": "Debe ser mayor que {gt}.",
    "less_than": "Debe ser menor que {lt}.",
    "too_short": "Debe tener al menos {min_length} elementos.",
    "too_long": "Debe tener a lo más {max_length} elementos.",
    "string_too_short": "Debe tener al menos {min_length} caracteres.",
    "int_parsing": "Debe ser un número entero.",
    "int_type": "Debe ser un número entero.",
    "float_parsing": "Debe ser un número.",
    "literal_error": "Valor no permitido.",
    "enum": "Valor no permitido.",
    "extra_forbidden": "Dato no reconocido.",
    "bool_parsing": "Debe ser sí o no.",
    "string_type": "Debe ser un texto.",
}


def traducir(error: ValidationError) -> dict[str, str]:
    """`campo → mensaje` (el primero de cada campo). Los errores de los validadores propios ya
    vienen en español; se les quita el prefijo «Value error, »."""
    resultado: dict[str, str] = {}
    for detalle in error.errors():
        campo = str(detalle["loc"][0]) if detalle["loc"] else GENERAL
        tipo = detalle["type"]
        if tipo in ("value_error", "assertion_error"):
            mensaje = str(detalle["msg"])
            for prefijo in ("Value error, ", "Assertion failed, "):
                mensaje = mensaje.removeprefix(prefijo)
        elif tipo in _PLANTILLAS:
            try:
                mensaje = _PLANTILLAS[tipo].format(**(detalle.get("ctx") or {}))
            except KeyError:
                mensaje = _PLANTILLAS[tipo]
        else:
            mensaje = "Valor no válido."
        resultado.setdefault(campo, mensaje)
    return resultado
