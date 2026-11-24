"""Creado con Claude.

Pantalla Plan de estudios (§17): matriz grados × asignaturas con las horas semanales; el total
por grado se pinta en rojo si no cabe en las franjas útiles de sus grupos.
"""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import PlanEstudios
from timetabling.gui.pantallas.base import Contexto, Pantalla

ROJO = QColor("#B00020")


class _DelegadoHoras(QStyledItemDelegate):
    def createEditor(  # noqa: N802 - API de Qt
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = QSpinBox(parent)
        editor.setRange(0, 60)
        return editor


class PantallaPlan(Pantalla):
    clave = "plan"
    titulo = "Plan de estudios"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addWidget(
            QLabel("Horas semanales (en horas-clase del nivel). 0 o vacío = no se imparte.")
        )
        self.tabla = QTableWidget()
        self.tabla.setItemDelegate(_DelegadoHoras(self.tabla))
        self.tabla.setAccessibleName("Matriz del plan de estudios")
        self.tabla.itemChanged.connect(self._celda_cambiada)
        capa.addWidget(self.tabla, 1)
        self.aviso = QLabel()
        self.aviso.setStyleSheet("color: #B00020;")
        capa.addWidget(self.aviso)
        acciones = QHBoxLayout()
        acciones.addStretch()
        descartar = QPushButton("Descartar")
        descartar.clicked.connect(self.descartar)
        self.boton_guardar = QPushButton("&Guardar")
        self.boton_guardar.clicked.connect(self.guardar)
        acciones.addWidget(descartar)
        acciones.addWidget(self.boton_guardar)
        capa.addLayout(acciones)
        self._grados: list[int] = []
        self._asignaturas: list[int] = []
        self._original: dict[tuple[int, int], int] = {}

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        datos = self.sesion.datos
        self._cargando = True
        self._grados = [g.id or 0 for g in datos.grados]
        self._asignaturas = [a.id or 0 for a in datos.asignaturas]
        self._original = {(f.grado_id, f.asignatura_id): f.horas_semanales for f in datos.plan}
        niveles = {n.id: n.nombre for n in datos.niveles}
        self.tabla.clear()
        self.tabla.setRowCount(len(self._grados))
        self.tabla.setColumnCount(len(self._asignaturas) + 1)
        self.tabla.setHorizontalHeaderLabels([a.nombre for a in datos.asignaturas] + ["Total"])
        self.tabla.setVerticalHeaderLabels(
            [f"{g.nombre} ({niveles.get(g.nivel_id, '?')})" for g in datos.grados]
        )
        for i, grado in enumerate(self._grados):
            for j, asignatura in enumerate(self._asignaturas):
                horas = self._original.get((grado, asignatura), 0)
                item = QTableWidgetItem(str(horas) if horas else "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tabla.setItem(i, j, item)
            total = QTableWidgetItem()
            total.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tabla.setItem(i, len(self._asignaturas), total)
        self._cargando = False
        self._totales()
        self.limpiar_cambios()

    def horas(self, fila: int, columna: int) -> int:
        item = self.tabla.item(fila, columna)
        texto = item.text().strip() if item else ""
        try:
            return max(0, int(texto)) if texto else 0
        except ValueError:
            return 0

    def poner_horas(self, grado_id: int, asignatura_id: int, horas: int) -> None:
        """Escribe una celda (equivale a teclearla)."""
        fila = self._grados.index(grado_id)
        columna = self._asignaturas.index(asignatura_id)
        self.tabla.item(fila, columna).setText(str(horas) if horas else "")

    def _celda_cambiada(self, item: QTableWidgetItem) -> None:
        if self._cargando or item.column() >= len(self._asignaturas):
            return
        self.marcar_cambio()
        self._totales()

    def _totales(self) -> None:
        if self.contexto.sesion is None:
            return
        datos = self.sesion.datos
        calendario = self.sesion.calendario
        self._cargando = True
        avisos = []
        for i, grado_id in enumerate(self._grados):
            total = sum(self.horas(i, j) for j in range(len(self._asignaturas)))
            grupos = [g.id for g in datos.grupos if g.grado_id == grado_id]
            capacidad = min(
                (len(calendario.utiles_grupo.get(g or 0, [])) for g in grupos), default=None
            )
            item = self.tabla.item(i, len(self._asignaturas))
            item.setText(str(total) if capacidad is None else f"{total} / {capacidad}")
            excede = capacidad is not None and total > capacidad
            item.setForeground(QBrush(ROJO if excede else self.palette().text().color()))
            item.setToolTip("No cabe en las franjas útiles de sus grupos" if excede else "")
            if excede:
                avisos.append(self.tabla.verticalHeaderItem(i).text())
        self.aviso.setText("⚠ No caben en sus franjas: " + ", ".join(avisos) if avisos else "")
        self._cargando = False

    def guardar(self) -> bool:
        filas = []
        for i, grado in enumerate(self._grados):
            for j, asignatura in enumerate(self._asignaturas):
                horas = self.horas(i, j)
                if horas != self._original.get((grado, asignatura), 0):
                    filas.append(
                        PlanEstudios(grado_id=grado, asignatura_id=asignatura,
                                     horas_semanales=horas)
                    )  # fmt: skip
        if filas:
            self.sesion.guardar_plan(filas)
        self.limpiar_cambios()
        self.recargar()
        return True
