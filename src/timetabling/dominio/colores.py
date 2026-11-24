"""Creado con Claude.

Colores: texto en contraste sobre el color de una asignatura y colores de apoyo comunes a la
interfaz, Excel y PDF.
"""

GRIS_RECESO = "#D9D9D9"
GRIS_VACIO = "#FFFFFF"
COLOR_POR_DEFECTO = "#9E9E9E"


def a_rgb(color: str) -> tuple[int, int, int]:
    texto = color.lstrip("#")
    if len(texto) != 6:
        texto = COLOR_POR_DEFECTO.lstrip("#")
    return int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16)


def luminancia(color: str) -> float:
    """Luminancia relativa (WCAG 2)."""

    def canal(valor: int) -> float:
        c = valor / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = a_rgb(color)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def color_texto(fondo: str) -> str:
    """Negro o blanco, el que contraste más con el fondo."""
    return "#000000" if contraste(fondo, "#000000") >= contraste(fondo, "#FFFFFF") else "#FFFFFF"
