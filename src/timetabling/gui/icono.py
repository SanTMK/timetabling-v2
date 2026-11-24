"""Creado con Claude.

Ícono de la aplicación dibujado con Qt (§19): un calendario con la barra superior y una
cuadrícula de clases de colores. Lo usan la ventana y el empaquetado (`.icns` / `.ico`).
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

TAMANOS = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
_COLORES = ["#E57373", "#64B5F6", "#81C784", "#FFB74D", "#BA68C8", "#4DB6AC"]
# Qué celdas de la cuadrícula 4 × 3 llevan clase (índice de color o None).
_CELDAS = [[0, 1, None, 2], [3, None, 4, 0], [1, 5, 2, None]]


def dibujar(tamano: int) -> QImage:
    imagen = QImage(tamano, tamano, QImage.Format.Format_ARGB32)
    imagen.fill(Qt.GlobalColor.transparent)
    p = QPainter(imagen)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = tamano / 100.0
    hoja = QRectF(8 * s, 12 * s, 84 * s, 80 * s)
    sombra = QPainterPath()
    sombra.addRoundedRect(hoja.translated(0, 2 * s), 12 * s, 12 * s)
    p.fillPath(sombra, QColor(0, 0, 0, 50))
    cuerpo = QPainterPath()
    cuerpo.addRoundedRect(hoja, 12 * s, 12 * s)
    p.fillPath(cuerpo, QColor("#FFFFFF"))
    # Barra superior roja (recortada a la hoja redondeada).
    p.save()
    p.setClipPath(cuerpo)
    p.fillRect(QRectF(hoja.left(), hoja.top(), hoja.width(), 20 * s), QColor("#C62828"))
    p.restore()
    # Argollas.
    for x in (30, 70):
        p.fillRect(QRectF((x - 3) * s, 6 * s, 6 * s, 14 * s), QColor("#424242"))
    # Cuadrícula de clases.
    izquierda, arriba = hoja.left() + 7 * s, hoja.top() + 27 * s
    ancho, alto = (hoja.width() - 14 * s) / 4, (hoja.height() - 33 * s) / 3
    if tamano >= 32:
        p.setPen(QPen(QColor("#BDBDBD"), max(1.0, s)))
    else:
        p.setPen(Qt.PenStyle.NoPen)
    for i, fila in enumerate(_CELDAS):
        for j, color in enumerate(fila):
            celda = QRectF(izquierda + j * ancho, arriba + i * alto, ancho, alto)
            if color is not None:
                p.fillRect(celda.adjusted(1.5 * s, 1.5 * s, -1.5 * s, -1.5 * s),
                           QColor(_COLORES[color]))  # fmt: skip
            if tamano >= 32:
                p.drawRect(celda)
    p.end()
    return imagen


def icono() -> QIcon:
    resultado = QIcon()
    for tamano in TAMANOS:
        resultado.addPixmap(QPixmap.fromImage(dibujar(tamano)))
    return resultado
