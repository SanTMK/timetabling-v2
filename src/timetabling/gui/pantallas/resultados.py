"""Creado con Claude.

Pantalla Resultados (§17): selector de solución (★ vigente, estado, origen, ⚠ desactualizada);
Marcar vigente, Eliminar, Editar una copia y Resaltar cambios; pestañas por grupo, profesor y
espacio, Penalizaciones, Cambios y Carga docente; exportar a Excel o PDF.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.cuadricula import Disposicion
from timetabling.dominio.estadisticas import carga_docente
from timetabling.dominio.modelos import NOMBRES_CRITERIOS, Solucion
from timetabling.gui.pantallas.base import Contexto, Pantalla
from timetabling.gui.widgets.vista_horario import VistaHorario
from timetabling.nucleo.objetivo import pesos
from timetabling.persistencia.repositorio import ErrorSolucion

ROL = Qt.ItemDataRole.UserRole


class _PestanaVista(QWidget):
    """Selector (grupo, profesor o espacio) más la vista de horario."""

    def __init__(self, etiqueta: str) -> None:
        super().__init__()
        capa = QVBoxLayout(self)
        fila = QHBoxLayout()
        rotulo = QLabel(etiqueta)
        self.selector = QComboBox()
        self.selector.setAccessibleName(etiqueta)
        rotulo.setBuddy(self.selector)
        fila.addWidget(rotulo)
        fila.addWidget(self.selector, 1)
        self.subtitulo = QLabel()
        fila.addWidget(self.subtitulo)
        capa.addLayout(fila)
        self.vista = VistaHorario()
        capa.addWidget(self.vista, 1)


def _tabla(columnas: list[str]) -> QTableWidget:
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return tabla


class PantallaResultados(Pantalla):
    clave = "resultados"
    titulo = "Resultados"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.solucion: Solucion | None = None
        self.disposicion: Disposicion | None = None
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        superior = QHBoxLayout()
        rotulo = QLabel("&Solución:")
        self.selector = QComboBox()
        self.selector.setAccessibleName("Solución")
        rotulo.setBuddy(self.selector)
        self.selector.currentIndexChanged.connect(self._elegir)
        superior.addWidget(rotulo)
        superior.addWidget(self.selector, 1)
        capa.addLayout(superior)
        botones = QHBoxLayout()
        self.boton_vigente = QPushButton("Marcar &vigente")
        self.boton_eliminar = QPushButton("&Eliminar")
        self.boton_copia = QPushButton("Editar una &copia")
        self.boton_copia.setEnabled(False)
        self.boton_copia.setToolTip("Disponible con el editor manual (F8).")
        self.boton_cambios = QPushButton("Resaltar ca&mbios")
        self.boton_cambios.setEnabled(False)
        self.boton_cambios.setToolTip("Disponible con el reajuste (F9).")
        self.boton_excel = QPushButton("Exportar a E&xcel…")
        self.boton_pdf = QPushButton("Exportar a &PDF…")
        self.boton_pdf.setEnabled(False)
        self.boton_pdf.setToolTip("Disponible en una próxima versión (F12).")
        self.boton_vigente.clicked.connect(self.marcar_vigente)
        self.boton_eliminar.clicked.connect(self.eliminar)
        self.boton_excel.clicked.connect(lambda: self.exportar_excel())
        for b in (self.boton_vigente, self.boton_eliminar, self.boton_copia, self.boton_cambios):
            botones.addWidget(b)
        botones.addStretch()
        capa.addLayout(botones)
        exportar = QHBoxLayout()
        exportar.addWidget(self.boton_excel)
        exportar.addWidget(self.boton_pdf)
        exportar.addStretch()
        capa.addLayout(exportar)
        self.info = QLabel()
        self.info.setWordWrap(True)
        capa.addWidget(self.info)

        self.pestanas = QTabWidget()
        self.por_grupo = _PestanaVista("&Grupo:")
        self.por_profesor = _PestanaVista("&Profesor:")
        self.por_espacio = _PestanaVista("&Espacio:")
        self.penalizaciones = _tabla(["Criterio", "Valor", "Peso", "Ponderado"])
        self.carga = _tabla(["Profesor", "Minutos", "Mínimo", "Máximo", "% del máximo", "Días",
                             "Minutos de hueco"])  # fmt: skip
        cambios = QLabel("La comparación con el horario vigente llega con el reajuste (F9).")
        self.pestanas.addTab(self.por_grupo, "Por grupo")
        self.pestanas.addTab(self.por_profesor, "Por profesor")
        self.pestanas.addTab(self.por_espacio, "Por espacio")
        self.pestanas.addTab(self.penalizaciones, "Penalizaciones")
        self.pestanas.addTab(cambios, "Cambios")
        self.pestanas.addTab(self.carga, "Carga docente")
        capa.addWidget(self.pestanas, 1)
        self.por_grupo.selector.currentIndexChanged.connect(self._ver_grupo)
        self.por_profesor.selector.currentIndexChanged.connect(self._ver_profesor)
        self.por_espacio.selector.currentIndexChanged.connect(self._ver_espacio)

    # ------------------------------------------------------------------ carga

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        actual = self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        for resumen in self.sesion.soluciones():
            desactualizada = " ⚠ desactualizada" if self.sesion.desactualizada(resumen) else ""
            texto = (
                f"{'★ ' if resumen.vigente else ''}{resumen.nombre} — {resumen.estado.value} · "
                f"{resumen.origen} · {resumen.fecha:%d/%m/%Y %H:%M}{desactualizada}"
            )
            self.selector.addItem(texto, resumen.id)
        indice = self.selector.findData(actual)
        self.selector.setCurrentIndex(indice if indice >= 0 else 0)
        self.selector.blockSignals(False)
        self._elegir()

    def seleccionar(self, entidad: str, ident: object) -> None:
        indice = self.selector.findData(ident)
        if indice >= 0:
            self.selector.setCurrentIndex(indice)

    def _elegir(self) -> None:
        ident = self.selector.currentData()
        self.solucion = self.sesion.cargar_solucion(ident) if ident is not None else None
        hay = self.solucion is not None
        for b in (self.boton_vigente, self.boton_eliminar, self.boton_excel):
            b.setEnabled(hay)
        if self.solucion is None:
            self.disposicion = None
            self.info.setText("Todavía no hay soluciones: genere un horario en «Generar».")
            for pestana in (self.por_grupo, self.por_profesor, self.por_espacio):
                pestana.selector.clear()
                pestana.vista.mostrar(None)
            self.penalizaciones.setRowCount(0)
            self.carga.setRowCount(0)
            return
        s = self.solucion
        self.disposicion = Disposicion(s, self.sesion.datos)
        partes = [
            f"<b>{s.estado.value}</b> · {s.origen} · {s.tiempo_s:.1f} s",
            f"{len({(a.clase_id, a.franja) for a in s.asignaciones})} clases colocadas",
        ]
        if "total" in s.penalizaciones:
            cota = " (cota superior)" if s.penalizaciones_son_cota else ""
            partes.append(f"penalización total{cota}: {s.penalizaciones['total']:.1f}")
        if s.vigente:
            partes.append("★ vigente")
        if self.sesion.desactualizada(s):
            partes.append(
                "⚠ desactualizada: los niveles cambiaron; se ve con sus franjas guardadas"
            )
        if s.violaciones:
            partes.append(f"⚠ {len(s.violaciones)} violaciones")
        self.info.setText(" · ".join(partes))
        self._llenar_selector(self.por_grupo, [(g, g) for g in self.disposicion.grupos()])
        self._llenar_selector(self.por_profesor, [(p, p) for p in self.disposicion.profesores()])
        self._llenar_selector(
            self.por_espacio,
            [((t, n), f"{t} — {self.disposicion.nombre_nivel(n)}") for t, n in
             self.disposicion.espacios()],
        )  # fmt: skip
        self._llenar_penalizaciones(s)
        self._llenar_carga(s)

    def _llenar_selector(self, pestana: _PestanaVista, opciones: list[tuple[object, str]]) -> None:
        actual = pestana.selector.currentText()
        pestana.selector.blockSignals(True)
        pestana.selector.clear()
        for valor, texto in opciones:
            pestana.selector.addItem(texto, valor)
        indice = pestana.selector.findText(actual)
        pestana.selector.setCurrentIndex(indice if indice >= 0 else 0)
        pestana.selector.blockSignals(False)
        if pestana is self.por_grupo:
            self._ver_grupo()
        elif pestana is self.por_profesor:
            self._ver_profesor()
        else:
            self._ver_espacio()

    def _ver(self, pestana: _PestanaVista, cuadricula: object) -> None:
        pestana.vista.mostrar(cuadricula)  # type: ignore[arg-type]
        pestana.subtitulo.setText(getattr(cuadricula, "subtitulo", ""))

    def _ver_grupo(self) -> None:
        valor = self.por_grupo.selector.currentData()
        if self.disposicion is not None and valor is not None:
            self._ver(self.por_grupo, self.disposicion.por_grupo(valor))

    def _ver_profesor(self) -> None:
        valor = self.por_profesor.selector.currentData()
        if self.disposicion is not None and valor is not None:
            self._ver(self.por_profesor, self.disposicion.por_profesor(valor))

    def _ver_espacio(self) -> None:
        valor = self.por_espacio.selector.currentData()
        if self.disposicion is not None and valor is not None:
            self._ver(self.por_espacio, self.disposicion.por_espacio(*valor))

    def _llenar_penalizaciones(self, s: Solucion) -> None:
        tabla_pesos = pesos(self.sesion.datos.configuracion.criterios, con_base="B9" in
                            s.penalizaciones)  # fmt: skip
        filas = [(c, n) for c, n in NOMBRES_CRITERIOS.items() if c in s.penalizaciones]
        self.penalizaciones.setRowCount(len(filas))
        for i, (criterio, nombre) in enumerate(filas):
            valor = s.penalizaciones[criterio]
            peso = tabla_pesos.get(criterio, 0.0)
            textos = [f"{criterio} {nombre}", f"{valor:g}", f"{peso:g}", f"{valor * peso:g}"]
            for j, texto in enumerate(textos):
                self.penalizaciones.setItem(i, j, QTableWidgetItem(texto))

    def _llenar_carga(self, s: Solucion) -> None:
        cargas = carga_docente(s, self.sesion.datos)
        self.carga.setRowCount(len(cargas))
        for i, c in enumerate(cargas):
            valores = [c.nombre, c.minutos, c.minimo, c.maximo, f"{c.porcentaje:.1f}", c.dias,
                       c.minutos_hueco]  # fmt: skip
            for j, valor in enumerate(valores):
                self.carga.setItem(i, j, QTableWidgetItem(str(valor)))

    # ------------------------------------------------------------------ acciones

    def marcar_vigente(self) -> None:
        if self.solucion is None or self.solucion.id is None:
            return
        try:
            self.sesion.marcar_vigente(self.solucion.id)
        except ErrorSolucion as error:
            self.dialogos.error("Marcar vigente", str(error))
            return
        self.recargar()

    def eliminar(self) -> None:
        if self.solucion is None or self.solucion.id is None:
            return
        if self.dialogos.confirmar(
            "Eliminar solución",
            f"¿Eliminar «{self.solucion.nombre}»? Antes se hará un respaldo del proyecto.",
        ):
            self.sesion.eliminar_solucion(self.solucion.id)
            self.recargar()

    def exportar_excel(self) -> None:
        if self.solucion is None:
            return
        ruta = self.dialogos.ruta_guardar("Exportar a Excel", "Libro de Excel (*.xlsx)", ".xlsx")
        if ruta is None:
            return
        try:
            self.sesion.exportar_excel(self.solucion, ruta)
        except OSError as error:
            self.dialogos.error("Exportar a Excel", str(error))
            return
        self.dialogos.informar("Exportar a Excel", f"Se exportó a «{ruta}».")

    def poner_solo_lectura(self, solo_lectura: bool) -> None:
        """Resultados sigue activa mientras se resuelve."""
