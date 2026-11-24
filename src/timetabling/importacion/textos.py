"""Creado con Claude.

Utilidades de texto de los cuadros de Excel (§15): comparación sin acentos, horas «8:00-8:45»
en reloj de 12 h, recesos y tutorías (configurables), nombres de grado por hoja y de maestro.
"""

import re
import unicodedata
from collections.abc import Iterable

DIAS_INGLES = {"monday": "L", "tuesday": "M", "wednesday": "X", "thursday": "J", "friday": "V"}
DIAS_ESPANOL = {"lunes": "L", "martes": "M", "miercoles": "X", "jueves": "J", "viernes": "V"}
RECESOS_POR_DEFECTO = ("lunch", "snack", "playground", "recess", "receso", "recreo")
TUTORIAS_POR_DEFECTO = ("tutoria", "tutoring")
FIN_TABLA = "horarios de examen"

ORDINALES = ["primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "septimo", "octavo",
             "noveno", "decimo", "undecimo", "duodecimo"]  # fmt: skip

COLORES = [
    "#E57373", "#64B5F6", "#81C784", "#FFB74D", "#BA68C8", "#4DB6AC", "#F06292",
    "#A1887F", "#7986CB", "#AED581", "#FFD54F", "#4FC3F7", "#9575CD", "#FF8A65",
    "#90A4AE", "#DCE775", "#F48FB1", "#80CBC4", "#CE93D8", "#BCAAA4",
]  # fmt: skip


def clave(texto: str) -> str:
    """Forma comparable: sin acentos, minúsculas y espacios simples."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_acentos.lower().split())


def limpio(texto: object) -> str:
    """Texto de una celda con espacios simples ('' si está vacía)."""
    return " ".join(str(texto).split()) if texto is not None else ""


def dia_de(texto: object) -> str | None:
    """Letra del día si la celda es el nombre de un día (en inglés o español)."""
    k = clave(limpio(texto))
    return DIAS_INGLES.get(k) or DIAS_ESPANOL.get(k)


def contiene(texto: str, palabras: Iterable[str]) -> bool:
    k = clave(texto)
    return any(clave(p) in k for p in palabras if p.strip())


def a_minutos_12h(hora: str) -> int:
    """«1:10» → 13:10. El cuadro usa reloj de 12 h sin a. m./p. m.: antes de las 7 es tarde."""
    h, m = (int(x) for x in hora.split(":"))
    if h < 7:
        h += 12
    return h * 60 + m


_RANGO = re.compile(r"(\d{1,2}:\d{2})\s*[-–a]\s*(\d{1,2}:\d{2})")


def rango(texto: object) -> tuple[int, int] | None:
    """«8:00-8:45» → (480, 525); `None` si la celda no es un rango de horas."""
    if not isinstance(texto, str):
        return None
    coincidencia = re.fullmatch(r"\s*" + _RANGO.pattern + r"\s*", texto)
    if not coincidencia:
        return None
    return a_minutos_12h(coincidencia[1]), a_minutos_12h(coincidencia[2])


def rango_dentro(texto: str) -> tuple[int, int] | None:
    """Un rango de horas escrito dentro de una celda («2A (8:00-8:45)»)."""
    coincidencia = _RANGO.search(texto)
    if not coincidencia:
        return None
    return a_minutos_12h(coincidencia[1]), a_minutos_12h(coincidencia[2])


def nombres_grado(texto: str) -> set[str]:
    """Claves con las que puede llamarse un grado («1st», «1°», «primero», «kinder»…)."""
    k = clave(texto)
    numero = re.match(r"(\d+)", k)
    if numero:
        n = int(numero[1])
        nombres = {str(n), f"{n}o", f"{n}.o", f"{n}º", f"{n}.º", f"{n}°", f"{n}.°", k}
        if 1 <= n <= len(ORDINALES):
            nombres.add(ORDINALES[n - 1])
        return nombres
    return {k}


def mismo_grado(hoja: str, grado: str) -> bool:
    return bool(nombres_grado(hoja) & nombres_grado(grado))


_TITULO = re.compile(r"^\s*(mrs|mr|ms|miss|prof|profa|mtro|mtra|maestro|maestra)\.?\s*", re.I)
_TITULOS = {
    "mrs": "Mrs.", "mr": "Mr.", "ms": "Ms.", "miss": "Miss", "prof": "Prof.", "profa": "Profa.",
    "mtro": "Mtro.", "mtra": "Mtra.", "maestro": "Maestro", "maestra": "Maestra",
}  # fmt: skip


def sin_titulo(texto: str) -> str:
    return _TITULO.sub("", texto).strip()


def nombre_maestro(texto: str) -> str:
    """«MS. ANA PEREZ» y «Ms.Ana Perez» → «Ms. Ana Perez»: el título se normaliza (§15.2); al
    comparar con los profesores del proyecto se ignora (`clave_maestro`)."""
    texto = limpio(texto)
    titulo = _TITULO.match(texto)
    resto = texto[titulo.end() :] if titulo else texto
    nombre = " ".join(p[:1].upper() + p[1:].lower() for p in resto.split())
    return f"{_TITULOS[titulo[1].lower()]} {nombre}" if titulo else nombre


def clave_maestro(texto: str) -> str:
    return clave(sin_titulo(limpio(texto)))
