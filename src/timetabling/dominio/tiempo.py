"""Creado con Claude.

Manejo del tiempo (§5): las horas son minutos desde medianoche (`int`) y los días son las
letras `L M X J V S D`.
"""

import re
from typing import Annotated, Literal

from pydantic import Field

Dia = Literal["L", "M", "X", "J", "V", "S", "D"]
"""Día de la semana: lunes, martes, miércoles (X), jueves, viernes, sábado, domingo."""

DIAS: tuple[Dia, ...] = ("L", "M", "X", "J", "V", "S", "D")
DIAS_POR_DEFECTO: tuple[Dia, ...] = ("L", "M", "X", "J", "V")
NOMBRES_DIAS: dict[Dia, str] = {
    "L": "Lunes",
    "M": "Martes",
    "X": "Miércoles",
    "J": "Jueves",
    "V": "Viernes",
    "S": "Sábado",
    "D": "Domingo",
}

MINUTOS_DIA = 24 * 60

Minuto = Annotated[int, Field(ge=0, le=MINUTOS_DIA)]
"""Minutos desde medianoche, de 0 a 1440 (inclusive, para poder expresar «hasta las 24:00»)."""

_PATRON_HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def a_minutos(texto: str) -> int:
    """Convierte «HH:MM» en minutos desde medianoche. Lanza `ValueError` si no es válido."""
    coincidencia = _PATRON_HHMM.match(texto)
    if coincidencia is None:
        raise ValueError(f"Hora no válida: «{texto}». Use el formato HH:MM.")
    horas, minutos = int(coincidencia.group(1)), int(coincidencia.group(2))
    if minutos >= 60 or horas > 24 or (horas == 24 and minutos > 0):
        raise ValueError(f"Hora fuera de rango: «{texto}».")
    return horas * 60 + minutos


def a_hhmm(minutos: int) -> str:
    """Convierte minutos desde medianoche en «HH:MM»."""
    if not 0 <= minutos <= MINUTOS_DIA:
        raise ValueError(f"Minutos fuera de rango: {minutos}.")
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def texto_rango(inicio: int, fin: int) -> str:
    """«09:00–09:50»."""
    return f"{a_hhmm(inicio)}–{a_hhmm(fin)}"


def ordenar_dias(dias: list[Dia] | tuple[Dia, ...]) -> list[Dia]:
    """Devuelve los días sin repetir y en el orden de la semana."""
    presentes = set(dias)
    return [dia for dia in DIAS if dia in presentes]


def se_traslapan(a_inicio: int, a_fin: int, b_inicio: int, b_fin: int, margen: int = 0) -> bool:
    """`[a,b)` y `[c,d)` se traslapan si `a < d + m` y `c < b + m` (§7.4)."""
    return a_inicio < b_fin + margen and b_inicio < a_fin + margen
