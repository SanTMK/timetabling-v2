"""Creado con Claude.

Pantalla Suplencias (§14): calendario para elegir la fecha, registro de ausencias (de un día o
de un rango, completas o parciales), clases afectadas del vigente ese día con sus candidatos en
orden (§11.4) para cubrirlas con un clic o marcarlas «sin cubrir», conteo mensual y reporte
del día en Excel. Nada de esto modifica el horario vigente.
"""

from datetime import date

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import Ausencia, por_id
from timetabling.dominio.tiempo import texto_rango
from timetabling.exportacion.excel import texto_fecha
from timetabling.gui.pantallas.base import ESTILO_ERROR, Contexto, Pantalla
from timetabling.gui.widgets.campos import HoraEdit
from timetabling.nucleo.suplencias import Candidato
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.servicios.suplencias import ClaseAfectada, Suplencias

ROL = Qt.ItemDataRole.UserRole
ESPANOL = QLocale(QLocale.Language.Spanish, QLocale.Country.Mexico)
COLOR_ESTADO = {"Pendiente": "#B71C1C", "Sin cubrir": "#E65100", "Cubierta": "#1B5E20"}


def a_fecha(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def a_qdate(f: date) -> QDate:
    return QDate(f.year, f.month, f.day)


class PantallaSuplencias(Pantalla):
    clave = "suplencias"
    titulo = "Suplencias"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.servicio: Suplencias | None = None
        self.afectadas: list[ClaseAfectada] = []
        self.lista_candidatos: list[Candidato] = []

        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        capa.addWidget(self.aviso)
        divisor = QSplitter()
        capa.addWidget(divisor, 1)

        # ---------------------------------------------------------------- izquierda
        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        self.calendario = QCalendarWidget()
        self.calendario.setGridVisible(True)
        self.calendario.setLocale(ESPANOL)
        self.calendario.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.calendario.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendario.setAccessibleName("Fecha")
        self.calendario.selectionChanged.connect(self._fecha_cambiada)
        self.calendario.currentPageChanged.connect(lambda *_: self._marcar_ausencias())
        capa_izq.addWidget(self.calendario)

        caja = QGroupBox("Registrar ausencia")
        formulario = QFormLayout(caja)
        self.profesor = QComboBox()
        self.profesor.setAccessibleName("Profesor ausente")
        formulario.addRow("&Profesor:", self.profesor)
        self.fecha_inicio = QDateEdit()
        self.fecha_fin = QDateEdit()
        for campo, nombre in ((self.fecha_inicio, "Desde"), (self.fecha_fin, "Hasta")):
            campo.setCalendarPopup(True)
            campo.setLocale(ESPANOL)
            campo.setDisplayFormat("dd/MM/yyyy")
            campo.setAccessibleName(f"{nombre} (fecha)")
        self.fecha_inicio.dateChanged.connect(self._ajustar_fin)
        fechas = QHBoxLayout()
        fechas.addWidget(self.fecha_inicio)
        fechas.addWidget(QLabel("a"))
        fechas.addWidget(self.fecha_fin)
        formulario.addRow("Fechas:", fechas)
        self.parcial = QCheckBox("Solo de")
        self.desde = HoraEdit(480)
        self.hasta = HoraEdit(600)
        self.desde.setAccessibleName("Desde (hora)")
        self.hasta.setAccessibleName("Hasta (hora)")
        self.parcial.toggled.connect(self._parcial)
        horas = QHBoxLayout()
        horas.addWidget(self.parcial)
        horas.addWidget(self.desde)
        horas.addWidget(QLabel("a"))
        horas.addWidget(self.hasta)
        formulario.addRow("Horas:", horas)
        self.motivo = QLineEdit()
        self.motivo.setAccessibleName("Motivo")
        formulario.addRow("&Motivo:", self.motivo)
        self.error = QLabel()
        self.error.setStyleSheet(ESTILO_ERROR)
        self.error.setWordWrap(True)
        self.error.hide()
        formulario.addRow(self.error)
        self.boton_registrar = QPushButton("&Registrar ausencia")
        self.boton_registrar.clicked.connect(self.registrar)
        formulario.addRow(self.boton_registrar)
        capa_izq.addWidget(caja)

        capa_izq.addWidget(QLabel("Ausencias del día:"))
        self.ausencias = QListWidget()
        self.ausencias.setAccessibleName("Ausencias del día")
        self.ausencias.currentRowChanged.connect(lambda _f: self._botones())
        capa_izq.addWidget(self.ausencias, 1)
        self.boton_eliminar_ausencia = QPushButton("Eliminar ausencia")
        self.boton_eliminar_ausencia.clicked.connect(self.eliminar_ausencia)
        capa_izq.addWidget(self.boton_eliminar_ausencia)
        divisor.addWidget(izquierda)

        # ---------------------------------------------------------------- derecha
        self.pestanas = QTabWidget()
        dia = QWidget()
        capa_dia = QVBoxLayout(dia)
        self.titulo_dia = QLabel()
        capa_dia.addWidget(self.titulo_dia)
        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            ["Horario", "Asignatura", "Grupos", "Ausente", "Estado", "Suplente"]
        )
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setAccessibleName("Clases afectadas")
        self.tabla.verticalHeader().hide()
        self.tabla.itemSelectionChanged.connect(self._clase_elegida)
        capa_dia.addWidget(self.tabla, 3)

        self.titulo_candidatos = QLabel("Candidatos (clic en «Asignar» o doble clic):")
        self.titulo_candidatos.setWordWrap(True)
        capa_dia.addWidget(self.titulo_candidatos)
        self.candidatos = QListWidget()
        self.candidatos.setAccessibleName("Candidatos a suplente")
        self.candidatos.itemActivated.connect(lambda _i: self.asignar_elegido())
        self.candidatos.currentRowChanged.connect(lambda _f: self._botones())
        capa_dia.addWidget(self.candidatos, 2)
        acciones = QHBoxLayout()
        self.boton_asignar = QPushButton("&Asignar")
        self.boton_asignar.setToolTip("Asigna al candidato elegido como suplente.")
        self.boton_sin_cubrir = QPushButton("Sin &cubrir")
        self.boton_sin_cubrir.setToolTip("Registra que la clase quedó sin cubrir.")
        self.boton_quitar = QPushButton("&Quitar")
        self.boton_quitar.setToolTip("Quita el registro: la clase vuelve a «Pendiente».")
        self.boton_asignar.clicked.connect(self.asignar_elegido)
        self.boton_sin_cubrir.clicked.connect(self.marcar_sin_cubrir)
        self.boton_quitar.clicked.connect(self.quitar)
        acciones.addWidget(self.boton_asignar)
        acciones.addWidget(self.boton_sin_cubrir)
        acciones.addWidget(self.boton_quitar)
        acciones.addStretch()
        capa_dia.addLayout(acciones)
        exportar = QHBoxLayout()
        exportar.addStretch()
        self.boton_exportar = QPushButton("&Exportar el día a Excel…")
        self.boton_exportar.clicked.connect(self.exportar)
        exportar.addWidget(self.boton_exportar)
        capa_dia.addLayout(exportar)
        self.pestanas.addTab(dia, "Clases del día")

        mes = QWidget()
        capa_mes = QVBoxLayout(mes)
        self.titulo_mes = QLabel()
        capa_mes.addWidget(self.titulo_mes)
        self.conteo = QTableWidget(0, 4)
        self.conteo.setHorizontalHeaderLabels(
            ["Profesor", "Suplencias realizadas", "Sus clases cubiertas", "Sus clases sin cubrir"]
        )
        self.conteo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conteo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conteo.verticalHeader().hide()
        self.conteo.setAccessibleName("Conteo mensual")
        capa_mes.addWidget(self.conteo, 1)
        self.pestanas.addTab(mes, "Conteo del mes")
        divisor.addWidget(self.pestanas)
        divisor.setStretchFactor(1, 3)
        self._parcial(False)

    # ------------------------------------------------------------------ utilidades

    @property
    def fecha(self) -> date:
        return a_fecha(self.calendario.selectedDate())

    def _servicio(self) -> Suplencias:
        if self.servicio is None or self.servicio.repo is not self.sesion.repo:
            self.servicio = Suplencias(self.sesion.repo)
        return self.servicio

    def _parcial(self, activo: bool) -> None:
        self.desde.setEnabled(activo)
        self.hasta.setEnabled(activo)

    def _ajustar_fin(self, inicio: QDate) -> None:
        if self.fecha_fin.date() < inicio:
            self.fecha_fin.setDate(inicio)

    def actual(self) -> ClaseAfectada | None:
        fila = self.tabla.currentRow()
        return self.afectadas[fila] if 0 <= fila < len(self.afectadas) else None

    def _botones(self) -> None:
        clase = self.actual()
        hay = self.servicio is not None and self.servicio.vigente() is not None
        self.boton_asignar.setEnabled(clase is not None and self.candidatos.currentRow() >= 0)
        self.boton_sin_cubrir.setEnabled(clase is not None)
        self.boton_quitar.setEnabled(clase is not None and clase.suplencia is not None)
        self.boton_registrar.setEnabled(hay)
        self.boton_exportar.setEnabled(hay)
        self.boton_eliminar_ausencia.setEnabled(self.ausencias.currentRow() >= 0)

    # ------------------------------------------------------------------ carga

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        servicio = self._servicio()
        vigente = servicio.vigente()
        if vigente is None:
            self.aviso.setText(
                "⚠ No hay un horario vigente. Marque uno en Resultados para gestionar suplencias."
            )
        else:
            self.aviso.setText(
                f"Horario vigente: «{vigente.nombre}». Las suplencias no lo modifican."
            )
        actual = self.profesor.currentData()
        self.profesor.blockSignals(True)
        self.profesor.clear()
        for p in sorted(self.sesion.datos.profesores, key=lambda p: p.nombre):
            if p.activo and p.id is not None:
                self.profesor.addItem(p.nombre, p.id)
        indice = self.profesor.findData(actual)
        self.profesor.setCurrentIndex(max(indice, 0))
        self.profesor.blockSignals(False)
        self._marcar_ausencias()
        self._fecha_cambiada()

    def _marcar_ausencias(self) -> None:
        """Pone en negritas los días del mes visible con alguna ausencia."""
        if self.contexto.sesion is None:
            return
        self.calendario.setDateTextFormat(QDate(), QTextCharFormat())
        negrita = QTextCharFormat()
        negrita.setFontWeight(QFont.Weight.Bold)
        negrita.setForeground(Qt.GlobalColor.darkRed)
        anio, mes = self.calendario.yearShown(), self.calendario.monthShown()
        primero = date(anio, mes, 1)
        for a in self._servicio().ausencias():
            dia = max(a.fecha_inicio, primero)
            while dia <= a.fecha_fin and dia.month == mes:
                self.calendario.setDateTextFormat(a_qdate(dia), negrita)
                dia = date.fromordinal(dia.toordinal() + 1)

    def _fecha_cambiada(self) -> None:
        if self.contexto.sesion is None:
            return
        fecha = self.fecha
        self.fecha_inicio.setDate(a_qdate(fecha))
        self.fecha_fin.setDate(a_qdate(fecha))
        self.titulo_dia.setText(f"<b>Clases afectadas del {texto_fecha(fecha)}</b>")
        nombres = por_id(self.sesion.datos.profesores)
        self.ausencias.clear()
        for a in self._servicio().ausencias_de(fecha):
            nombre = nombres[a.profesor_id].nombre if a.profesor_id in nombres else "?"
            horas = "todo el día"
            if a.desde is not None and a.hasta is not None:
                horas = texto_rango(a.desde, a.hasta)
            texto = f"{nombre} · {horas}"
            if a.fecha_inicio != a.fecha_fin:
                texto += f" · {a.fecha_inicio:%d/%m} a {a.fecha_fin:%d/%m}"
            if a.motivo:
                texto += f" · {a.motivo}"
            item = QListWidgetItem(texto)
            item.setData(ROL, a)
            self.ausencias.addItem(item)
        self._llenar_tabla()
        self._llenar_conteo()

    def _llenar_tabla(self, seleccionar: int | None = None) -> None:
        servicio = self._servicio()
        self.afectadas = servicio.afectadas_del_dia(self.fecha)
        nombres = por_id(self.sesion.datos.profesores)
        self.tabla.blockSignals(True)
        self.tabla.setRowCount(len(self.afectadas))
        fila_elegida = -1
        for fila, c in enumerate(self.afectadas):
            suplente = ""
            if c.suplencia is not None and c.suplencia.suplente_id is not None:
                p = nombres.get(c.suplencia.suplente_id)
                suplente = p.nombre if p else "?"
            valores = [c.horas, c.asignatura, c.grupos, c.profesor_ausente, c.estado, suplente]
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if col == 4:
                    item.setForeground(Qt.GlobalColor.white)
                    item.setBackground(QColor(COLOR_ESTADO[c.estado]))
                self.tabla.setItem(fila, col, item)
            if c.asignacion_id == seleccionar:
                fila_elegida = fila
        self.tabla.blockSignals(False)
        if fila_elegida < 0 and self.afectadas:
            fila_elegida = 0
        if fila_elegida >= 0:
            self.tabla.setCurrentCell(fila_elegida, 0)
        self._clase_elegida()

    def _clase_elegida(self) -> None:
        self.candidatos.clear()
        self.lista_candidatos = []
        clase = self.actual()
        if clase is None:
            self.titulo_candidatos.setText(
                "No hay clases afectadas ese día."
                if not self.afectadas
                else "Elija una clase para ver sus candidatos."
            )
            self._botones()
            return
        try:
            self.lista_candidatos = self._servicio().candidatos(clase)
        except ErrorProyecto as error:
            self.titulo_candidatos.setText(str(error))
            self._botones()
            return
        actual = clase.suplencia.suplente_id if clase.suplencia else None
        for c in self.lista_candidatos:
            marca = "✔ " if c.profesor_id == actual else ""
            item = QListWidgetItem(f"{marca}{c.nombre} — {c.detalle}")
            item.setData(ROL, c.profesor_id)
            self.candidatos.addItem(item)
        if self.lista_candidatos:
            # El primero (el mejor según §11.4) queda elegido: se asigna con un clic.
            fila = next((i for i, c in enumerate(self.lista_candidatos)
                         if c.profesor_id == actual), 0)  # fmt: skip
            self.candidatos.setCurrentRow(fila)
        texto = f"Candidatos para {clase.asignatura} {clase.grupos} ({clase.horas})"
        if not self.lista_candidatos:
            texto += ": nadie disponible. Puede marcarla «sin cubrir»."
        else:
            texto += ", en orden (el primero es el recomendado):"
        self.titulo_candidatos.setText(texto)
        self._botones()

    def _llenar_conteo(self) -> None:
        fecha = self.fecha
        filas = self._servicio().conteo_mensual(fecha.year, fecha.month)
        mes = texto_fecha(fecha.replace(day=1)).split(" de ", 1)[1]
        self.titulo_mes.setText(f"<b>Suplencias de {mes}</b>")
        self.conteo.setRowCount(len(filas))
        for i, f in enumerate(filas):
            for j, valor in enumerate([f.nombre, f.realizadas, f.cubiertas, f.sin_cubrir]):
                item = QTableWidgetItem(str(valor))
                if j:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.conteo.setItem(i, j, item)

    # ------------------------------------------------------------------ acciones

    def registrar(self) -> None:
        self.error.hide()
        profesor_id = self.profesor.currentData()
        if profesor_id is None:
            self._error("Elija el profesor ausente.")
            return
        try:
            ausencia = Ausencia(
                profesor_id=profesor_id,
                fecha_inicio=a_fecha(self.fecha_inicio.date()),
                fecha_fin=a_fecha(self.fecha_fin.date()),
                desde=self.desde.minutos() if self.parcial.isChecked() else None,
                hasta=self.hasta.minutos() if self.parcial.isChecked() else None,
                motivo=self.motivo.text().strip(),
            )
        except ValueError as error:
            mensajes = getattr(error, "errors", None)
            texto = mensajes()[0]["msg"] if callable(mensajes) else str(error)
            self._error(texto.removeprefix("Value error, "))
            return
        _, afectadas = self._servicio().registrar_ausencia(ausencia)
        self.motivo.clear()
        if afectadas:
            renglones = [
                f"• {c.fecha:%d/%m} {c.horas} · {c.asignatura} · {c.grupos}" for c in afectadas
            ]
            self.dialogos.informar(
                "Ausencia registrada",
                f"{len(afectadas)} clases afectadas del horario vigente:\n" + "\n".join(renglones),
            )
        else:
            self.dialogos.informar(
                "Ausencia registrada", "El profesor no tiene clases en esas fechas y horas."
            )
        self.calendario.setSelectedDate(a_qdate(ausencia.fecha_inicio))
        self._marcar_ausencias()
        self._fecha_cambiada()

    def _error(self, texto: str) -> None:
        self.error.setText(f"⚠ {texto}")
        self.error.show()

    def eliminar_ausencia(self) -> None:
        item = self.ausencias.currentItem()
        if item is None:
            return
        ausencia: Ausencia = item.data(ROL)
        if ausencia.id is None or not self.dialogos.confirmar(
            "Eliminar ausencia",
            f"¿Eliminar la ausencia «{item.text()}»? Se quitarán las suplencias registradas "
            "para sus clases.",
        ):
            return
        self._servicio().eliminar_ausencia(ausencia.id)
        self._marcar_ausencias()
        self._fecha_cambiada()

    def asignar(self, profesor_id: int | None) -> None:
        clase = self.actual()
        if clase is None:
            return
        try:
            self._servicio().asignar(clase, profesor_id)
        except ErrorProyecto as error:
            self.dialogos.error("Suplencias", str(error))
            return
        self._llenar_tabla(seleccionar=clase.asignacion_id)
        self._llenar_conteo()

    def asignar_elegido(self) -> None:
        item = self.candidatos.currentItem()
        if item is not None:
            self.asignar(int(item.data(ROL)))

    def marcar_sin_cubrir(self) -> None:
        self.asignar(None)

    def quitar(self) -> None:
        clase = self.actual()
        if clase is None or clase.suplencia is None or clase.suplencia.id is None:
            return
        self._servicio().quitar(clase.suplencia.id)
        self._llenar_tabla(seleccionar=clase.asignacion_id)
        self._llenar_conteo()

    def exportar(self) -> None:
        ruta = self.dialogos.ruta_guardar(
            "Exportar suplencias del día", "Libro de Excel (*.xlsx)", ".xlsx"
        )
        if ruta is None:
            return
        try:
            self._servicio().exportar_reporte_del_dia(self.fecha, ruta)
        except OSError as error:
            self.dialogos.error("Exportar suplencias", str(error))
            return
        self.dialogos.informar("Exportar suplencias", f"Se exportó a «{ruta}».")

    def poner_fecha(self, fecha: date) -> None:
        self.calendario.setSelectedDate(a_qdate(fecha))
