"""Creado con Claude.

Panel «Por colocar» (§12.2): tarjetas derivadas de `borrador.tarjetas()` («Matemáticas · 7°A ·
López · faltan 3 de 5»), con filtros por grupo, profesor y asignatura y búsqueda por texto. Las
tarjetas se arrastran a la rejilla.
"""

from collections.abc import Sequence

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.borrador import Tarjeta
from timetabling.gui.widgets.rejilla_editor import mime_de

ROL = Qt.ItemDataRole.UserRole


class _ListaTarjetas(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setWordWrap(True)
        self.setAccessibleName("Clases por colocar")

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:  # noqa: N802 - API de Qt
        tarjeta: Tarjeta = items[0].data(ROL)
        return mime_de(tarjeta.clase_id, None)

    def mimeTypes(self) -> list[str]:  # noqa: N802 - API de Qt
        from timetabling.gui.widgets.rejilla_editor import TIPO_MIME

        return [TIPO_MIME]


class PanelPorColocar(QWidget):
    tarjeta_elegida = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        self.titulo = QLabel("<b>Por colocar</b>")
        capa.addWidget(self.titulo)
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar…")
        self.busqueda.setAccessibleName("Buscar clases por colocar")
        capa.addWidget(self.busqueda)
        self.grupo = QComboBox()
        self.profesor = QComboBox()
        self.asignatura = QComboBox()
        for combo, nombre in ((self.grupo, "Grupo"), (self.profesor, "Profesor"),
                              (self.asignatura, "Asignatura")):  # fmt: skip
            combo.setAccessibleName(f"Filtrar por {nombre.lower()}")
            capa.addWidget(combo)
            combo.currentIndexChanged.connect(self._filtrar)
        self.busqueda.textChanged.connect(self._filtrar)
        self.lista = _ListaTarjetas()
        self.lista.currentItemChanged.connect(self._elegida)
        capa.addWidget(self.lista, 1)
        self.tarjetas: list[Tarjeta] = []

    def poner(
        self,
        tarjetas: list[Tarjeta],
        grupos: list[tuple[int, str]],
        profesores: list[tuple[int, str]],
        asignaturas: list[str],
    ) -> None:
        self.tarjetas = tarjetas
        for combo, opciones, todos in (
            (self.grupo, grupos, "Todos los grupos"),
            (self.profesor, profesores, "Todos los profesores"),
            (self.asignatura, [(a, a) for a in asignaturas], "Todas las asignaturas"),
        ):
            actual = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(todos, None)
            for valor, texto in opciones:
                combo.addItem(texto, valor)
            indice = combo.findData(actual)
            combo.setCurrentIndex(indice if indice >= 0 else 0)
            combo.blockSignals(False)
        self._filtrar()

    def _filtrar(self) -> None:
        texto = self.busqueda.text().strip().lower()
        grupo = self.grupo.currentData()
        profesor = self.profesor.currentData()
        asignatura = self.asignatura.currentData()
        actual = self.lista.currentItem().data(ROL).clase_id if self.lista.currentItem() else None
        self.lista.blockSignals(True)
        self.lista.clear()
        visibles = [
            t
            for t in self.tarjetas
            if (not texto or texto in t.texto.lower())
            and (grupo is None or grupo in t.grupos)
            and (profesor is None or profesor in t.profesores)
            and (asignatura is None or asignatura == t.asignatura)
        ]
        for tarjeta in visibles:
            item = QListWidgetItem(("▮▮ " if tarjeta.franjas == 2 else "") + tarjeta.texto)
            item.setData(ROL, tarjeta)
            item.setToolTip("Arrástrela a la rejilla o elíjala y pulse una celda.")
            self.lista.addItem(item)
            if tarjeta.clase_id == actual:
                self.lista.setCurrentItem(item)
        self.lista.blockSignals(False)
        faltan = sum(t.faltan for t in self.tarjetas)
        self.titulo.setText(f"<b>Por colocar</b> ({faltan} horas)")

    def _elegida(self, actual: QListWidgetItem | None, _anterior: QListWidgetItem | None) -> None:
        if actual is not None:
            self.tarjeta_elegida.emit(actual.data(ROL).clase_id)

    def elegir(self, clase_id: int) -> None:
        for i in range(self.lista.count()):
            if self.lista.item(i).data(ROL).clase_id == clase_id:
                self.lista.setCurrentRow(i)
                return
        raise KeyError(clase_id)

    def visibles(self) -> list[Tarjeta]:
        return [self.lista.item(i).data(ROL) for i in range(self.lista.count())]
