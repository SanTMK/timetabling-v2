"""Creado con Claude.

Rejilla del editor manual (§12.2). Cada celda corresponde a una franja; se puede arrastrar una
clase colocada o una tarjeta del panel y soltarla en una celda. Al tomar una clase, cada celda
se pinta según su validez (🟩 válida · 🟨 con penalización · 🟥 inválida) y lleva además un
ícono (✓ · ~ · ✗) para quien no distingue colores; el tooltip lista los motivos.
"""

import json
from dataclasses import dataclass, field

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QKeyEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.colores import color_texto
from timetabling.nucleo.conflictos import EstadoCelda

TIPO_MIME = "application/x-timetabling-clase"
COLORES_ESTADO: dict[EstadoCelda, str] = {
    "valida": "#C8E6C9",
    "penalizada": "#FFF59D",
    "invalida": "#FFCDD2",
}
ICONOS_ESTADO: dict[EstadoCelda, str] = {"valida": "✓", "penalizada": "~", "invalida": "✗"}


def mime_de(clase_id: int, colocacion: Colocacion | None) -> QMimeData:
    mime = QMimeData()
    datos = {"clase": clase_id, "franja": colocacion.franja_id if colocacion else None}
    mime.setData(TIPO_MIME, json.dumps(datos).encode("utf-8"))
    return mime


def leer_mime(mime: QMimeData) -> tuple[int, str | None] | None:
    if not mime.hasFormat(TIPO_MIME):
        return None
    datos = json.loads(bytes(mime.data(TIPO_MIME).data()).decode("utf-8"))
    return int(datos["clase"]), datos["franja"]


@dataclass
class ContenidoCelda:
    """Lo que hay en una celda: colocaciones con sus textos."""

    colocaciones: list[Colocacion] = field(default_factory=list)
    lineas: list[str] = field(default_factory=list)
    color: str | None = None


class RejillaEditor(QTableWidget):
    """Tabla cuyas celdas son franjas. Emite señales; la pantalla decide qué hacer."""

    celda_pulsada = Signal(str)  # franja_id
    soltado = Signal(int, object, str)  # clase_id, franja de origen (o None), franja destino
    doble_clic_en = Signal(str)
    menu_en = Signal(str, QPoint)
    tecla = Signal(str, str)  # nombre de la tecla, franja actual

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mapa: dict[tuple[int, int], str] = {}
        self.posiciones: dict[str, list[tuple[int, int]]] = {}
        self.contenidos: dict[tuple[int, int], ContenidoCelda] = {}
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setWordWrap(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.cellClicked.connect(lambda f, c: self._emitir(self.celda_pulsada, f, c))
        self.cellDoubleClicked.connect(lambda f, c: self._emitir(self.doble_clic_en, f, c))
        self._presion: QPoint | None = None

    def _emitir(self, senal: Signal, fila: int, columna: int) -> None:  # type: ignore[type-arg]
        franja = self.mapa.get((fila, columna))
        if franja is not None:
            senal.emit(franja)

    def _menu(self, punto: QPoint) -> None:
        indice = self.indexAt(punto)
        franja = self.mapa.get((indice.row(), indice.column()))
        if franja is not None:
            self.menu_en.emit(franja, self.viewport().mapToGlobal(punto))

    # ------------------------------------------------------------------ forma

    def configurar(
        self,
        filas: list[str],
        columnas: list[str],
        mapa: dict[tuple[int, int], str],
        alto_fila: int = 46,
    ) -> None:
        self.clearSpans()
        self.clear()
        self.setRowCount(len(filas))
        self.setColumnCount(len(columnas))
        self.setVerticalHeaderLabels(filas)
        self.setHorizontalHeaderLabels(columnas)
        for i in range(len(filas)):
            self.setRowHeight(i, alto_fila)
        self.mapa = dict(mapa)
        self.posiciones = {}
        for posicion, franja in self.mapa.items():
            self.posiciones.setdefault(franja, []).append(posicion)
        self.contenidos = {}

    def pintar(
        self,
        contenidos: dict[tuple[int, int], ContenidoCelda],
        estados: dict[str, tuple[EstadoCelda, str]] | None = None,
        seleccion: tuple[int, str] | None = None,
        sugeridas: set[str] | None = None,
    ) -> None:
        """Llena las celdas. Con `estados` (al tomar una clase) cada celda lleva el color y el
        ícono de su validez y el tooltip con los motivos."""
        self.contenidos = contenidos
        estados = estados or {}
        sugeridas = sugeridas or set()
        for (fila, columna), franja in self.mapa.items():
            contenido = contenidos.get((fila, columna), ContenidoCelda())
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            lineas = list(contenido.lineas)
            fondo = contenido.color
            tooltip = "\n".join(lineas)
            if franja in estados:
                estado, motivos = estados[franja]
                fondo = COLORES_ESTADO[estado]
                icono = ICONOS_ESTADO[estado]
                if franja in sugeridas:
                    icono = "★ " + icono
                lineas = [f"{icono} {lineas[0]}", *lineas[1:]] if lineas else [icono]
                tooltip = (tooltip + "\n\n" if tooltip else "") + (motivos or "Sin problemas.")
            if fondo:
                item.setBackground(QBrush(QColor(fondo)))
                item.setForeground(QBrush(QColor(color_texto(fondo))))
            item.setText("\n".join(lineas))
            item.setToolTip(tooltip)
            if seleccion is not None and any(
                c.clase_id == seleccion[0] and c.franja_id == seleccion[1]
                for c in contenido.colocaciones
            ):
                fuente = QFont(item.font())
                fuente.setBold(True)
                fuente.setUnderline(True)
                item.setFont(fuente)
            self.setItem(fila, columna, item)

    def franja_actual(self) -> str | None:
        return self.mapa.get((self.currentRow(), self.currentColumn()))

    def ir_a_franja(self, franja_id: str) -> None:
        posiciones = self.posiciones.get(franja_id)
        if posiciones:
            self.setCurrentCell(*posiciones[0])

    def centro_de(self, franja_id: str) -> QPoint:
        fila, columna = self.posiciones[franja_id][0]
        return self.visualItemRect(self.item(fila, columna)).center()

    # ------------------------------------------------------------------ arrastrar

    def mousePressEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        self._presion = evento.position().toPoint()
        super().mousePressEvent(evento)

    def mouseMoveEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        if self._presion is None or not evento.buttons() & Qt.MouseButton.LeftButton:
            return
        if (evento.position().toPoint() - self._presion).manhattanLength() < 8:
            return
        indice = self.indexAt(self._presion)
        contenido = self.contenidos.get((indice.row(), indice.column()))
        self._presion = None
        if contenido is None or not contenido.colocaciones:
            return
        colocacion = contenido.colocaciones[0]
        arrastre = QDrag(self)
        arrastre.setMimeData(mime_de(colocacion.clase_id, colocacion))
        arrastre.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        self._presion = None
        super().mouseReleaseEvent(evento)

    def dragEnterEvent(self, evento: QDragEnterEvent) -> None:  # noqa: N802 - API de Qt
        if evento.mimeData().hasFormat(TIPO_MIME):
            evento.acceptProposedAction()
        else:
            evento.ignore()

    def dragMoveEvent(self, evento: QDragMoveEvent) -> None:  # noqa: N802 - API de Qt
        if evento.mimeData().hasFormat(TIPO_MIME):
            evento.acceptProposedAction()
        else:
            evento.ignore()

    def dropEvent(self, evento: QDropEvent) -> None:  # noqa: N802 - API de Qt
        datos = leer_mime(evento.mimeData())
        indice = self.indexAt(evento.position().toPoint())
        franja = self.mapa.get((indice.row(), indice.column()))
        if datos is None or franja is None:
            evento.ignore()
            return
        evento.setDropAction(Qt.DropAction.MoveAction)
        evento.accept()
        self.soltado.emit(datos[0], datos[1], franja)

    # ------------------------------------------------------------------ teclado

    def keyPressEvent(self, evento: QKeyEvent) -> None:  # noqa: N802 - API de Qt
        franja = self.franja_actual() or ""
        modificadores = evento.modifiers()
        nombres = {
            Qt.Key.Key_Delete: "suprimir",
            Qt.Key.Key_Backspace: "suprimir",
            Qt.Key.Key_Return: "soltar",
            Qt.Key.Key_Enter: "soltar",
            Qt.Key.Key_Space: "tomar",
            Qt.Key.Key_Escape: "soltar_toma",
        }
        if modificadores & Qt.KeyboardModifier.AltModifier and evento.key() in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
        ):  # fmt: skip
            direccion = {
                Qt.Key.Key_Left: "izquierda", Qt.Key.Key_Right: "derecha",
                Qt.Key.Key_Up: "arriba", Qt.Key.Key_Down: "abajo",
            }[evento.key()]  # type: ignore[index]  # fmt: skip
            self.tecla.emit(f"mover_{direccion}", franja)
            return
        if evento.key() in nombres:
            self.tecla.emit(nombres[evento.key()], franja)  # type: ignore[index]
            return
        super().keyPressEvent(evento)
