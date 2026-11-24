"""Creado con Claude.

Editor de disponibilidad (§17): cuadrícula de días × intervalos de 5 min. Se arrastra para
marcar disponible (verde), preferible no (naranja) o no disponible (gris); bandas tenues
muestran las franjas de referencia de cada nivel. También se maneja con el teclado (flechas y
espacio). Cada estado lleva además un patrón, para quien no distingue colores.
"""

from collections.abc import Sequence

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from timetabling.dominio.modelos import Disponibilidad, TipoDisponibilidad
from timetabling.dominio.tiempo import Dia, a_hhmm
from timetabling.nucleo.franjas import Franja

PASO = 5
ALTO_FILA = 4
MARGEN_IZQ = 44
MARGEN_SUP = 20
COLORES: dict[TipoDisponibilidad, QColor] = {
    "disponible": QColor("#66BB6A"),
    "preferible_no": QColor("#FFA726"),
    "no_disponible": QColor("#9E9E9E"),
}
PATRONES: dict[TipoDisponibilidad, Qt.BrushStyle] = {
    "disponible": Qt.BrushStyle.SolidPattern,
    "preferible_no": Qt.BrushStyle.Dense4Pattern,
    "no_disponible": Qt.BrushStyle.BDiagPattern,
}
NOMBRES: dict[TipoDisponibilidad, str] = {
    "disponible": "Disponible",
    "preferible_no": "Preferible no",
    "no_disponible": "No disponible",
}


class EditorDisponibilidad(QWidget):
    cambiado = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dias: list[Dia] = ["L", "M", "X", "J", "V"]
        self.inicio = 7 * 60
        self.fin = 15 * 60
        self.bandas: list[Franja] = []
        self.celdas: dict[tuple[Dia, int], TipoDisponibilidad] = {}
        self.herramienta: TipoDisponibilidad | None = "disponible"
        self.cursor = (0, 0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Editor de disponibilidad")
        self.setToolTip(
            "Arrastre para marcar. Flechas para moverse y espacio para marcar con el teclado."
        )

    # ------------------------------------------------------------------ configuración

    def configurar(
        self, dias: Sequence[Dia], inicio: int, fin: int, bandas: Sequence[Franja]
    ) -> None:
        self.dias = list(dias) or ["L", "M", "X", "J", "V"]
        self.inicio = (inicio // PASO) * PASO
        self.fin = -(-fin // PASO) * PASO
        self.bandas = list(bandas)
        self.setFixedHeight(MARGEN_SUP + self.filas * ALTO_FILA + 2)
        self.update()

    @property
    def filas(self) -> int:
        return max(1, (self.fin - self.inicio) // PASO)

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return QSize(MARGEN_IZQ + 90 * len(self.dias), MARGEN_SUP + self.filas * ALTO_FILA + 2)

    # ------------------------------------------------------------------ datos

    def poner(self, disponibilidad: Sequence[Disponibilidad]) -> None:
        self.celdas = {}
        for rango in disponibilidad:
            for minuto in range((rango.inicio // PASO) * PASO, rango.fin, PASO):
                self.celdas[(rango.dia, minuto)] = rango.tipo
        self.update()

    def leer(self) -> list[Disponibilidad]:
        """Une las celdas consecutivas del mismo tipo en rangos."""
        resultado: list[Disponibilidad] = []
        for dia in [d for d in ("L", "M", "X", "J", "V", "S", "D")]:
            minutos = sorted(m for (d, m) in self.celdas if d == dia)
            inicio: int | None = None
            tipo: TipoDisponibilidad | None = None
            anterior = -PASO * 2
            for minuto in minutos:
                actual = self.celdas[(dia, minuto)]  # type: ignore[index]
                if inicio is not None and (minuto != anterior + PASO or actual != tipo):
                    resultado.append(Disponibilidad(dia=dia, inicio=inicio, fin=anterior + PASO,
                                                    tipo=tipo))  # type: ignore[arg-type]  # fmt: skip
                    inicio = None
                if inicio is None:
                    inicio, tipo = minuto, actual
                anterior = minuto
            if inicio is not None:
                resultado.append(Disponibilidad(dia=dia, inicio=inicio, fin=anterior + PASO,
                                                tipo=tipo))  # type: ignore[arg-type]  # fmt: skip
        return resultado

    def marcar(self, dia: Dia, desde: int, hasta: int, tipo: TipoDisponibilidad | None) -> None:
        """Marca (o borra con `None`) el rango `[desde, hasta)` de un día."""
        for minuto in range((desde // PASO) * PASO, hasta, PASO):
            if tipo is None:
                self.celdas.pop((dia, minuto), None)
            else:
                self.celdas[(dia, minuto)] = tipo
        self.update()
        self.cambiado.emit()

    def copiar_dia(self, origen: Dia) -> None:
        """Copia el día a toda la semana."""
        del_dia = {m: t for (d, m), t in self.celdas.items() if d == origen}
        self.celdas = {(dia, m): t for dia in self.dias for m, t in del_dia.items()} | {
            k: v for k, v in self.celdas.items() if k[0] not in self.dias
        }
        self.update()
        self.cambiado.emit()

    def limpiar(self) -> None:
        self.celdas = {}
        self.update()
        self.cambiado.emit()

    @property
    def dia_actual(self) -> Dia:
        return self.dias[min(self.cursor[0], len(self.dias) - 1)]

    # ------------------------------------------------------------------ geometría

    def _ancho_columna(self) -> float:
        return max(20.0, (self.width() - MARGEN_IZQ) / max(1, len(self.dias)))

    def _celda_en(self, punto: QPoint) -> tuple[int, int] | None:
        columna = int((punto.x() - MARGEN_IZQ) // self._ancho_columna())
        fila = (punto.y() - MARGEN_SUP) // ALTO_FILA
        if 0 <= columna < len(self.dias) and 0 <= fila < self.filas:
            return columna, fila
        return None

    def _rect(self, columna: int, fila_inicio: int, fila_fin: int) -> QRect:
        ancho = self._ancho_columna()
        return QRect(
            int(MARGEN_IZQ + columna * ancho) + 1,
            MARGEN_SUP + fila_inicio * ALTO_FILA,
            int(ancho) - 2,
            (fila_fin - fila_inicio) * ALTO_FILA,
        )

    def _pintar_en(self, columna: int, fila: int) -> None:
        dia = self.dias[columna]
        minuto = self.inicio + fila * PASO
        clave = (dia, minuto)
        if self.herramienta is None:
            if self.celdas.pop(clave, None) is None:
                return
        elif self.celdas.get(clave) == self.herramienta:
            return
        else:
            self.celdas[clave] = self.herramienta
        self.update()
        self.cambiado.emit()

    # ------------------------------------------------------------------ eventos

    def mousePressEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        celda = self._celda_en(evento.position().toPoint())
        if celda is not None:
            self.cursor = celda
            self._pintar_en(*celda)

    def mouseMoveEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        if evento.buttons() & Qt.MouseButton.LeftButton:
            celda = self._celda_en(evento.position().toPoint())
            if celda is not None:
                self.cursor = celda
                self._pintar_en(*celda)

    def keyPressEvent(self, evento: QKeyEvent) -> None:  # noqa: N802 - API de Qt
        columna, fila = self.cursor
        teclas = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if evento.key() in teclas:
            dx, dy = teclas[evento.key()]  # type: ignore[index]
            self.cursor = (
                min(max(columna + dx, 0), len(self.dias) - 1),
                min(max(fila + dy, 0), self.filas - 1),
            )
            if evento.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._pintar_en(*self.cursor)
            self.update()
        elif evento.key() == Qt.Key.Key_Space:
            self._pintar_en(*self.cursor)
        else:
            super().keyPressEvent(evento)

    def paintEvent(self, _evento: QPaintEvent) -> None:  # noqa: N802 - API de Qt
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().base())
        ancho = self._ancho_columna()
        texto = self.palette().text().color()
        # Bandas de referencia de las franjas de cada nivel.
        banda = QColor(100, 149, 237, 40)
        for franja in self.bandas:
            if franja.dia in self.dias:
                columna = self.dias.index(franja.dia)
                fi = (franja.inicio - self.inicio) // PASO
                ff = -(-(franja.fin - self.inicio) // PASO)
                p.fillRect(self._rect(columna, max(fi, 0), min(ff, self.filas)), banda)
        # Celdas marcadas.
        for (dia, minuto), tipo in self.celdas.items():
            if dia in self.dias and self.inicio <= minuto < self.fin:
                fila = (minuto - self.inicio) // PASO
                rect = self._rect(self.dias.index(dia), fila, fila + 1)
                p.fillRect(rect, QBrush(COLORES[tipo], PATRONES[tipo]))
        # Rejilla por hora y encabezados.
        p.setPen(QPen(texto))
        for j, dia in enumerate(self.dias):
            p.drawText(QRect(int(MARGEN_IZQ + j * ancho), 0, int(ancho), MARGEN_SUP),
                       Qt.AlignmentFlag.AlignCenter, dia)  # fmt: skip
        p.setPen(QPen(QColor(0, 0, 0, 60)))
        for fila in range(0, self.filas + 1):
            minuto = self.inicio + fila * PASO
            if minuto % 60 == 0:
                y = MARGEN_SUP + fila * ALTO_FILA
                p.drawLine(MARGEN_IZQ, y, self.width(), y)
                p.setPen(QPen(texto))
                p.drawText(QRect(0, y - 8, MARGEN_IZQ - 4, 16),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           a_hhmm(minuto))  # fmt: skip
                p.setPen(QPen(QColor(0, 0, 0, 60)))
        # Cursor del teclado.
        if self.hasFocus():
            p.setPen(QPen(texto, 2))
            columna, fila = self.cursor
            p.drawRect(self._rect(columna, fila, fila + 1))
        p.end()
