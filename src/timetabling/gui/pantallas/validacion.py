"""Creado con Claude.

Pantalla Validación (§17): problemas con su acción sugerida; doble clic navega al elemento.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from timetabling.gui.pantallas.base import Contexto, Pantalla
from timetabling.nucleo.validacion import Problema

DESTINOS = {
    "clase": "clases",
    "fija": "clases",
    "grupo": "grados",
    "grado": "grados",
    "division": "grados",
    "profesor": "profesores",
    "asignatura": "asignaturas",
    "nivel": "niveles",
    "espacio": "espacios",
}


class PantallaValidacion(Pantalla):
    clave = "validacion"
    titulo = "Validación"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        superior = QHBoxLayout()
        self.resumen = QLabel()
        superior.addWidget(self.resumen, 1)
        actualizar = QPushButton("&Actualizar")
        actualizar.clicked.connect(self.recargar)
        superior.addWidget(actualizar)
        capa.addLayout(superior)
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["", "Problema", "Acción sugerida"])
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setWordWrap(True)
        self.tabla.setAccessibleName("Problemas de validación")
        self.tabla.cellDoubleClicked.connect(lambda fila, _c: self.navegar(fila))
        capa.addWidget(self.tabla, 1)
        self.problemas: list[Problema] = []

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        self.problemas = self.sesion.problemas()
        errores = sum(p.es_error for p in self.problemas)
        advertencias = len(self.problemas) - errores
        self.resumen.setText(
            "✔ Sin problemas: se puede generar el horario."
            if not self.problemas
            else f"✖ {errores} errores · ⚠ {advertencias} advertencias. Doble clic para ir al "
            "elemento."
        )
        self.tabla.setRowCount(len(self.problemas))
        for i, problema in enumerate(self.problemas):
            icono = QTableWidgetItem("✖ Error" if problema.es_error else "⚠ Aviso")
            icono.setForeground(
                Qt.GlobalColor.darkRed if problema.es_error else Qt.GlobalColor.darkYellow
            )
            self.tabla.setItem(i, 0, icono)
            self.tabla.setItem(i, 1, QTableWidgetItem(problema.mensaje))
            self.tabla.setItem(i, 2, QTableWidgetItem(problema.accion))
        self.tabla.resizeRowsToContents()

    def poner_solo_lectura(self, solo_lectura: bool) -> None:
        """Validación sigue activa mientras se resuelve."""

    def navegar(self, fila: int) -> None:
        if not 0 <= fila < len(self.problemas):
            return
        problema = self.problemas[fila]
        destino = DESTINOS.get(problema.entidad)
        if destino:
            self.contexto.ir_a(destino, problema.entidad, problema.id)
