"""Creado con Claude.

Editor manual de horarios (§12): borradores, panel «Por colocar», vistas por grupo, profesor y
espacio y vista maestra; al tomar una clase cada celda se pinta según su validez; soltar en una
celda libre coloca, en una ocupada ofrece intercambiar o «colocar y reacomodar lo mínimo»; modo
estricto o flexible; bloquear (📌), quitar (Supr), mover con Alt+flechas, cambiar profesor
(doble clic), deshacer y rehacer (Ctrl+Z / Ctrl+Y); barra de estado con pendientes, conflictos,
penalización en vivo y carga; «Completar el resto» y «Validar y guardar como definitivo».
"""

from collections import defaultdict
from dataclasses import replace

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.borrador import Colocacion, ErrorBorrador, Operacion
from timetabling.dominio.clases import grupos_de_clase
from timetabling.dominio.modelos import EstadoSolucion, por_id
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.gui.pantallas.base import Contexto, Pantalla
from timetabling.gui.trabajador import Ejecucion, TareaFondo
from timetabling.gui.widgets.panel_colocar import PanelPorColocar
from timetabling.gui.widgets.rejilla_editor import ContenidoCelda, RejillaEditor
from timetabling.nucleo.conflictos import EstadoCelda
from timetabling.nucleo.franjas import Franja
from timetabling.nucleo.reparacion import Propuesta
from timetabling.servicios.edicion import EdicionBorrador, ErrorEdicion, nuevo_borrador

ROL = Qt.ItemDataRole.UserRole
VISTAS = ("grupo", "profesor", "espacio", "maestra")


class ComandoOperacion(QUndoCommand):
    """Una operación del borrador en la pila de deshacer."""

    def __init__(self, editor: "PantallaEditor", operacion: Operacion) -> None:
        super().__init__(operacion.descripcion)
        self.editor = editor
        self.operacion = operacion

    def redo(self) -> None:
        self.editor._aplicar(self.operacion)

    def undo(self) -> None:
        self.editor._aplicar(self.operacion.inversa())


class _Vista(QWidget):
    def __init__(self, selectores: list[tuple[str, QComboBox]]) -> None:
        super().__init__()
        capa = QVBoxLayout(self)
        fila = QHBoxLayout()
        for etiqueta, combo in selectores:
            rotulo = QLabel(etiqueta)
            rotulo.setBuddy(combo)
            combo.setAccessibleName(etiqueta.replace("&", "").rstrip(":"))
            fila.addWidget(rotulo)
            fila.addWidget(combo, 1)
        capa.addLayout(fila)
        self.rejilla = RejillaEditor()
        capa.addWidget(self.rejilla, 1)


class PantallaEditor(Pantalla):
    clave = "editor"
    titulo = "Editor"
    tarea_terminada = Signal(object)

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.edicion: EdicionBorrador | None = None
        self.pila = QUndoStack(self)
        self.tomada: tuple[int, Colocacion | None] | None = None
        self.seleccion: tuple[int, str] | None = None
        self.previa: set[tuple[int, str]] = set()
        self.sugeridas: set[str] = set()
        self.ejecucion: Ejecucion | None = None
        self._al_terminar_tarea: object = None
        self.conflictivas: set[int] = set()
        self._construir()

    # ------------------------------------------------------------------ construcción

    def _construir(self) -> None:
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        superior = QHBoxLayout()
        rotulo = QLabel("&Borrador:")
        self.selector = QComboBox()
        self.selector.setAccessibleName("Borrador")
        rotulo.setBuddy(self.selector)
        self.selector.currentIndexChanged.connect(self._elegir_borrador)
        superior.addWidget(rotulo)
        superior.addWidget(self.selector, 1)
        self.boton_nuevo = QPushButton("&Nuevo borrador vacío")
        self.boton_nuevo.clicked.connect(self.nuevo_vacio)
        superior.addWidget(self.boton_nuevo)
        capa.addLayout(superior)

        acciones = QHBoxLayout()
        self.boton_deshacer = QPushButton("Deshacer")
        self.boton_rehacer = QPushButton("Rehacer")
        self.boton_deshacer.clicked.connect(self.pila.undo)
        self.boton_rehacer.clicked.connect(self.pila.redo)
        self.pila.canUndoChanged.connect(self.boton_deshacer.setEnabled)
        self.pila.canRedoChanged.connect(self.boton_rehacer.setEnabled)
        self.boton_deshacer.setEnabled(False)
        self.boton_rehacer.setEnabled(False)
        self.flexible = QCheckBox("Modo &flexible")
        self.flexible.setToolTip(
            "Estricto: no deja soltar en rojo. Flexible: lo deja y marca la clase con ⚠."
        )
        self.boton_sugerir = QPushButton("&Sugerir lugar")
        self.boton_completar = QPushButton("&Completar el resto")
        self.boton_definitivo = QPushButton("&Validar y guardar como definitivo")
        self.boton_sugerir.clicked.connect(self.sugerir)
        self.boton_completar.clicked.connect(self.completar)
        self.boton_definitivo.clicked.connect(self.validar_definitivo)
        for w in (self.boton_deshacer, self.boton_rehacer, self.flexible, self.boton_sugerir):
            acciones.addWidget(w)
        acciones.addStretch()
        capa.addLayout(acciones)
        asistencia = QHBoxLayout()
        asistencia.addWidget(self.boton_completar)
        asistencia.addWidget(self.boton_definitivo)
        asistencia.addStretch()
        capa.addLayout(asistencia)
        for texto, atajo, funcion in (
            ("Deshacer", QKeySequence.StandardKey.Undo, self.pila.undo),
            ("Rehacer", QKeySequence.StandardKey.Redo, self.pila.redo),
        ):
            accion = QAction(texto, self)
            accion.setShortcut(atajo)
            accion.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            accion.triggered.connect(funcion)
            self.addAction(accion)
        rehacer_y = QAction("Rehacer", self)
        rehacer_y.setShortcut(QKeySequence("Ctrl+Y"))
        rehacer_y.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        rehacer_y.triggered.connect(self.pila.redo)
        self.addAction(rehacer_y)
        bloquear = QAction("Bloquear", self)
        bloquear.setShortcut(QKeySequence("Ctrl+L"))
        bloquear.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        bloquear.triggered.connect(self.bloquear_seleccion)
        self.addAction(bloquear)

        divisor = QSplitter()
        capa.addWidget(divisor, 1)
        self.pestanas = QTabWidget()
        self.combo_grupo = QComboBox()
        self.combo_profesor = QComboBox()
        self.combo_nivel_profesor = QComboBox()
        self.combo_espacio = QComboBox()
        self.combo_nivel_maestra = QComboBox()
        self.combo_filas_maestra = QComboBox()
        self.combo_filas_maestra.addItem("Grupos", "grupos")
        self.combo_filas_maestra.addItem("Profesores", "profesores")
        self.vistas: dict[str, _Vista] = {
            "grupo": _Vista([("&Grupo:", self.combo_grupo)]),
            "profesor": _Vista([("&Profesor:", self.combo_profesor),
                                ("Ni&vel:", self.combo_nivel_profesor)]),
            "espacio": _Vista([("&Espacio:", self.combo_espacio)]),
            "maestra": _Vista([("Ni&vel:", self.combo_nivel_maestra),
                               ("&Filas:", self.combo_filas_maestra)]),
        }  # fmt: skip
        titulos = {"grupo": "Por grupo", "profesor": "Por profesor", "espacio": "Por espacio",
                   "maestra": "Vista maestra"}  # fmt: skip
        for clave, titulo in titulos.items():
            vista = self.vistas[clave]
            self.pestanas.addTab(vista, titulo)
            rejilla = vista.rejilla
            rejilla.celda_pulsada.connect(self._celda_pulsada)
            rejilla.soltado.connect(self._soltado)
            rejilla.doble_clic_en.connect(self._doble_clic)
            rejilla.menu_en.connect(self._menu)
            rejilla.tecla.connect(self._tecla)
        combos = (
            self.combo_grupo,
            self.combo_profesor,
            self.combo_nivel_profesor,
            self.combo_espacio,
            self.combo_nivel_maestra,
            self.combo_filas_maestra,
        )
        for combo in combos:
            combo.currentIndexChanged.connect(self._configurar_vista)
        self.combo_profesor.currentIndexChanged.connect(self._niveles_de_profesor)
        self.pestanas.currentChanged.connect(self._configurar_vista)
        divisor.addWidget(self.pestanas)

        derecha = QWidget()
        capa_der = QVBoxLayout(derecha)
        capa_der.setContentsMargins(0, 0, 0, 0)
        self.panel = PanelPorColocar()
        self.panel.tarjeta_elegida.connect(lambda c: self.tomar(c))
        capa_der.addWidget(self.panel, 3)
        self.caja_conflictos = QGroupBox("Conflictos")
        self.caja_conflictos.setCheckable(True)
        self.caja_conflictos.setChecked(True)
        capa_caja = QVBoxLayout(self.caja_conflictos)
        self.lista_conflictos = QListWidget()
        self.lista_conflictos.setWordWrap(True)
        self.lista_conflictos.setAccessibleName("Conflictos del borrador")
        self.lista_conflictos.itemClicked.connect(self._ir_a_conflicto)
        self.caja_conflictos.toggled.connect(self.lista_conflictos.setVisible)
        capa_caja.addWidget(self.lista_conflictos)
        capa_der.addWidget(self.caja_conflictos, 2)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(0, 3)

        estado = QHBoxLayout()
        self.etiqueta_pendientes = QLabel()
        self.etiqueta_conflictos = QLabel()
        self.etiqueta_penalizacion = QLabel()
        self.etiqueta_carga = QLabel()
        self.barra_carga = QProgressBar()
        self.barra_carga.setMaximumWidth(180)
        self.barra_carga.setAccessibleName("Carga")
        self.etiqueta_tarea = QLabel()
        for w in (self.etiqueta_pendientes, self.etiqueta_conflictos, self.etiqueta_penalizacion,
                  self.etiqueta_carga, self.barra_carga, self.etiqueta_tarea):  # fmt: skip
            estado.addWidget(w)
        estado.addStretch()
        capa.addLayout(estado)
        self._habilitar(False)

    def _habilitar(self, hay: bool) -> None:
        for w in (self.pestanas, self.panel, self.boton_sugerir, self.boton_completar,
                  self.boton_definitivo, self.flexible):  # fmt: skip
            w.setEnabled(hay)

    # ------------------------------------------------------------------ carga

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        actual = self.edicion.solucion.id if self.edicion else self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        for resumen in self.sesion.soluciones():
            if resumen.estado is EstadoSolucion.BORRADOR:
                aviso = " ⚠ desactualizado" if self.sesion.desactualizada(resumen) else ""
                self.selector.addItem(
                    f"{resumen.nombre} · {resumen.fecha:%d/%m/%Y %H:%M}{aviso}", resumen.id
                )
        indice = self.selector.findData(actual)
        self.selector.setCurrentIndex(indice if indice >= 0 else 0)
        self.selector.blockSignals(False)
        self._llenar_combos()
        self._elegir_borrador()

    def seleccionar(self, entidad: str, ident: object) -> None:
        if entidad == "solucion":
            indice = self.selector.findData(ident)
            if indice >= 0:
                self.selector.setCurrentIndex(indice)

    def abrir_borrador(self, solucion_id: int) -> None:
        self.recargar()
        indice = self.selector.findData(solucion_id)
        if indice < 0:
            raise KeyError(solucion_id)
        self.selector.setCurrentIndex(indice)
        self._elegir_borrador()

    def _elegir_borrador(self) -> None:
        ident = self.selector.currentData()
        if self.edicion is not None and self.edicion.solucion.id == ident:
            self._refrescar()
            return
        self.pila.clear()
        self.tomada = self.seleccion = None
        self.previa = set()
        self.sugeridas = set()
        self.edicion = None
        if ident is not None:
            try:
                self.edicion = EdicionBorrador(self.sesion, ident)
            except ErrorEdicion as error:
                self.etiqueta_tarea.setText(f"⚠ {error}")
        self._habilitar(self.edicion is not None)
        self._configurar_vista()

    def _llenar_combos(self) -> None:
        datos = self.sesion.datos
        espacios = sorted(
            {
                (c.espacio_efectivo(a), datos.nivel_de_grupo(c.destinatarios[0].grupo_id).id)
                for c in datos.clases
                if (a := por_id(datos.asignaturas).get(c.asignatura_id)) and c.espacio_efectivo(a)
            },
            key=str,
        )
        opciones = {
            self.combo_grupo: [(g.id, datos.nombre_grupo(g.id or 0)) for g in datos.grupos],
            self.combo_profesor: [(p.id, p.nombre) for p in datos.profesores if p.activo],
            self.combo_espacio: [
                (e, f"{e[0]} — {por_id(datos.niveles)[e[1]].nombre}") for e in espacios
            ],
            self.combo_nivel_maestra: [(n.id, n.nombre) for n in datos.niveles],
        }
        for combo, lista in opciones.items():
            actual = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for valor, texto in lista:
                combo.addItem(texto, valor)
            indice = combo.findData(actual)
            combo.setCurrentIndex(indice if indice >= 0 else 0)
            combo.blockSignals(False)
        self._niveles_de_profesor()

    def _niveles_de_profesor(self) -> None:
        datos = self.sesion.datos
        profesor = por_id(datos.profesores).get(self.combo_profesor.currentData())
        grados = por_id(datos.grados)
        niveles = (
            sorted({grados[g].nivel_id for g in profesor.grados if g in grados}) if profesor else []
        ) or [n.id for n in datos.niveles]
        nombres = {n.id: n.nombre for n in datos.niveles}
        actual = self.combo_nivel_profesor.currentData()
        self.combo_nivel_profesor.blockSignals(True)
        self.combo_nivel_profesor.clear()
        for n in niveles:
            self.combo_nivel_profesor.addItem(nombres.get(n, "?"), n)
        indice = self.combo_nivel_profesor.findData(actual)
        self.combo_nivel_profesor.setCurrentIndex(indice if indice >= 0 else 0)
        self.combo_nivel_profesor.blockSignals(False)

    # ------------------------------------------------------------------ vistas

    @property
    def vista_actual(self) -> str:
        return VISTAS[self.pestanas.currentIndex()]

    @property
    def rejilla(self) -> RejillaEditor:
        return self.vistas[self.vista_actual].rejilla

    def _nivel_vista(self) -> int | None:
        datos = self.sesion.datos
        vista = self.vista_actual
        if vista == "grupo" and self.combo_grupo.currentData() is not None:
            return datos.nivel_de_grupo(self.combo_grupo.currentData()).id
        if vista == "profesor":
            return self.combo_nivel_profesor.currentData()
        if vista == "espacio" and self.combo_espacio.currentData() is not None:
            return self.combo_espacio.currentData()[1]
        if vista == "maestra":
            return self.combo_nivel_maestra.currentData()
        return None

    def _franjas(self, nivel_id: int | None) -> tuple[list[str], list[int], dict[str, Franja]]:
        franjas = self.sesion.calendario.franjas_nivel.get(nivel_id or 0, [])
        dias = [d for d in ("L", "M", "X", "J", "V", "S", "D") if any(f.dia == d for f in franjas)]
        indices = sorted({f.indice for f in franjas})
        return dias, indices, {f.id: f for f in franjas}

    def _configurar_vista(self, *_args: object) -> None:
        if self.contexto.sesion is None:
            return
        nivel = self._nivel_vista()
        dias, indices, franjas = self._franjas(nivel)
        rejilla = self.rejilla
        if self.vista_actual == "maestra":
            filas = self._filas_maestra()
            columnas = [f"{d}{i + 1}" for d in dias for i in indices]
            mapa = {
                (r, c): f"{nivel}:{d}:{i}"
                for r in range(len(filas))
                for c, (d, i) in enumerate((d, i) for d in dias for i in indices)
                if f"{nivel}:{d}:{i}" in franjas
            }
            rejilla.configurar([t for _, t in filas], columnas, mapa, alto_fila=34)
        else:
            modelo = {f.indice: f for f in franjas.values() if dias and f.dia == dias[0]}
            etiquetas = [
                ("⏸ " if modelo[i].receso_antes else "")
                + f"{i + 1}. {texto_rango(modelo[i].inicio, modelo[i].fin)}"
                if i in modelo else f"{i + 1}"
                for i in indices
            ]  # fmt: skip
            mapa = {
                (r, c): f"{nivel}:{d}:{i}"
                for r, i in enumerate(indices)
                for c, d in enumerate(dias)
                if f"{nivel}:{d}:{i}" in franjas
            }
            rejilla.configurar(etiquetas, [NOMBRES_DIAS[d] for d in dias], mapa)
        self._refrescar()

    def _filas_maestra(self) -> list[tuple[int, str]]:
        datos = self.sesion.datos
        nivel = self.combo_nivel_maestra.currentData()
        if self.combo_filas_maestra.currentData() == "profesores":
            grados = {g.id for g in datos.grados if g.nivel_id == nivel}
            return [(p.id or 0, p.nombre) for p in datos.profesores
                    if p.activo and grados & set(p.grados)]  # fmt: skip
        return [
            (g.id or 0, datos.nombre_grupo(g.id or 0))
            for g in datos.grupos
            if datos.nivel_de_grupo(g.id or 0).id == nivel
        ]

    def _relevante(self, colocacion: Colocacion, fila: int | None = None) -> bool:
        """La colocación se ve en la vista actual (y en la fila, en la vista maestra)."""
        assert self.edicion is not None
        info = self.edicion.conflictos.info.get(colocacion.clase_id)
        if info is None:
            return False
        vista = self.vista_actual
        if vista == "grupo":
            return self.combo_grupo.currentData() in grupos_de_clase(info.clase)
        if vista == "profesor":
            return self.combo_profesor.currentData() in colocacion.profesores
        if vista == "espacio":
            espacio = self.combo_espacio.currentData()
            return espacio is not None and info.tipo_espacio == espacio[0]
        filas = self._filas_maestra()
        if fila is None or fila >= len(filas):
            return False
        ident = filas[fila][0]
        if self.combo_filas_maestra.currentData() == "profesores":
            return ident in colocacion.profesores
        return ident in grupos_de_clase(info.clase)

    def _lineas(self, colocacion: Colocacion, cambiadas: set[tuple[int, str]]) -> list[str]:
        assert self.edicion is not None
        info = self.edicion.conflictos.info[colocacion.clase_id]
        datos = self.sesion.datos
        marcas = "".join(
            m for m, si in (
                ("📌", colocacion.bloqueada),
                ("↻", (colocacion.clase_id, colocacion.franja_id) in cambiadas | self.previa),
                ("⚠", colocacion.clase_id in self.conflictivas),
            ) if si
        )  # fmt: skip
        titulo = (marcas + " " if marcas else "") + info.asignatura
        vista = self.vista_actual
        if vista == "maestra":
            return [titulo]
        if vista == "grupo":
            grupo = self.combo_grupo.currentData()
            partes = [d.parte for d in info.clase.destinatarios if d.grupo_id == grupo and d.parte]
            if partes:
                titulo += f" ({', '.join(partes)})"
            profesores = por_id(datos.profesores)
            return [titulo, ", ".join(profesores[p].nombre for p in colocacion.profesores
                                      if p in profesores)]  # fmt: skip
        return [titulo, info.texto.split(" · ", 1)[-1]]

    def _refrescar(self) -> None:
        if self.edicion is None:
            self.rejilla.pintar({})
            self.panel.poner([], [], [], [])
            self.lista_conflictos.clear()
            for etiqueta in (self.etiqueta_pendientes, self.etiqueta_conflictos,
                             self.etiqueta_penalizacion, self.etiqueta_carga):  # fmt: skip
                etiqueta.clear()
            return
        rejilla = self.rejilla
        cambiadas = self.edicion.cambiadas()
        contenidos: dict[tuple[int, int], ContenidoCelda] = defaultdict(ContenidoCelda)
        por_franja: dict[str, list[Colocacion]] = defaultdict(list)
        for c in self.edicion.borrador.colocaciones:
            por_franja[c.franja_id].append(c)
        for franja, posiciones in rejilla.posiciones.items():
            for fila, columna in posiciones:
                for c in por_franja.get(franja, []):
                    if self._relevante(c, fila):
                        celda = contenidos[(fila, columna)]
                        celda.colocaciones.append(c)
                        celda.lineas.extend(self._lineas(c, cambiadas))
                        if celda.color is None:
                            asignatura = self.edicion.conflictos.info[
                                c.clase_id
                            ].clase.asignatura_id
                            celda.color = por_id(self.sesion.datos.asignaturas)[asignatura].color
        rejilla.pintar(dict(contenidos), self._estados(), self.seleccion, self.sugeridas)
        self._actualizar_estado()

    def _estados(self) -> dict[str, tuple[EstadoCelda, str]]:
        if self.tomada is None or self.edicion is None:
            return {}
        clase_id, origen = self.tomada
        conflictos = self.edicion.conflictos
        info = conflictos.info.get(clase_id)
        estados: dict[str, tuple[EstadoCelda, str]] = {}
        with conflictos.sin(origen):
            for franja_id in self.rejilla.posiciones:
                franja = self.sesion.calendario.franjas[franja_id]
                if info is None or franja.nivel_id != info.nivel_id:
                    estados[franja_id] = ("invalida", "La clase no es de este nivel.")
                    continue
                estado, motivos = conflictos.estado(clase_id, franja)
                texto = "\n".join(("✗ " if m.es_dura else "~ ") + m.texto for m in motivos)
                estados[franja_id] = (estado, texto)
        return estados

    def _actualizar_estado(self) -> None:
        assert self.edicion is not None
        estado = self.edicion.estado()
        verificacion = self.edicion.verificacion()
        self.conflictivas = {v.clase_id for v in verificacion.violaciones if v.clase_id}
        self.etiqueta_pendientes.setText(f"Pendientes: {estado.pendientes}")
        self.etiqueta_conflictos.setText(f"Conflictos: {estado.conflictos}")
        self.etiqueta_penalizacion.setText(f"Penalización: {estado.penalizacion:.1f}")
        datos = self.sesion.datos
        tarjetas = self.edicion.borrador.tarjetas(datos)
        self.panel.poner(
            tarjetas,
            [(g.id or 0, datos.nombre_grupo(g.id or 0)) for g in datos.grupos],
            [(p.id or 0, p.nombre) for p in datos.profesores if p.activo],
            sorted({t.asignatura for t in tarjetas}),
        )
        self.lista_conflictos.clear()
        for violacion in verificacion.violaciones:
            item = QListWidgetItem(f"⚠ {violacion.mensaje}")
            item.setData(ROL, violacion.clase_id)
            self.lista_conflictos.addItem(item)
        self.caja_conflictos.setTitle(f"Conflictos ({len(verificacion.violaciones)})")
        self._carga()

    def _carga(self) -> None:
        assert self.edicion is not None
        datos = self.sesion.datos
        if self.vista_actual == "profesor" and self.combo_profesor.currentData() is not None:
            profesor = por_id(datos.profesores)[self.combo_profesor.currentData()]
            minutos = sum(
                self.sesion.calendario.franjas[c.franja_id].duracion
                for c in self.edicion.borrador.colocaciones
                if profesor.id in c.profesores
            )
            maximo = max(1, profesor.carga_max_semanal_min)
            self.etiqueta_carga.setText(f"Carga de {profesor.nombre}: {minutos}/{maximo} min")
            self.barra_carga.setRange(0, maximo)
            self.barra_carga.setValue(min(minutos, maximo))
        elif self.combo_grupo.currentData() is not None:
            grupo = self.combo_grupo.currentData()
            clases = [c for c in datos.clases if grupo in grupos_de_clase(c)]
            total = sum(c.horas_semanales for c in clases)
            colocadas = sum(
                1 for c in self.edicion.borrador.colocaciones
                if c.clase_id in {k.id for k in clases}
            )  # fmt: skip
            self.etiqueta_carga.setText(
                f"{datos.nombre_grupo(grupo)}: {colocadas}/{total} horas colocadas"
            )
            self.barra_carga.setRange(0, max(1, total))
            self.barra_carga.setValue(min(colocadas, total))

    # ------------------------------------------------------------------ tomar y soltar

    def tomar(self, clase_id: int, franja_id: str | None = None) -> None:
        """Toma una clase del panel (sin franja) o una colocada (con su franja)."""
        if self.edicion is None:
            return
        origen = self.edicion.borrador.buscar(clase_id, franja_id) if franja_id else None
        self.tomada = (clase_id, origen)
        self.seleccion = (clase_id, franja_id) if franja_id else None
        self.sugeridas = set()
        self._refrescar()

    def soltar_toma(self) -> None:
        self.tomada = None
        self.sugeridas = set()
        self._refrescar()

    def _celda_pulsada(self, franja_id: str) -> None:
        if self.edicion is None:
            return
        fila, columna = self.rejilla.currentRow(), self.rejilla.currentColumn()
        contenido = self.rejilla.contenidos.get((fila, columna))
        if self.tomada is not None and (
            self.tomada[1] is None or self.tomada[1].franja_id != franja_id
        ):
            self.soltar(franja_id)
            return
        if contenido and contenido.colocaciones:
            c = contenido.colocaciones[0]
            self.tomar(c.clase_id, c.franja_id)

    def _soltado(self, clase_id: int, origen: str | None, franja_id: str) -> None:
        self.tomar(clase_id, origen)
        self.soltar(franja_id)

    def _elegir_profesores(self, clase_id: int, franja: Franja, origen: Colocacion | None
                           ) -> tuple[int, ...] | None:  # fmt: skip
        """Profesores para colocar: los fijos, los de la clase o se elige un candidato (§11.4)."""
        assert self.edicion is not None
        conflictos = self.edicion.conflictos
        info = conflictos.info[clase_id]
        if info.clase.profesores:
            return tuple(info.clase.profesores)
        if origen is not None:
            return origen.profesores
        actuales = {p for c in self.edicion.borrador.de_clase(clase_id) for p in c.profesores}
        if actuales:
            return (min(actuales),)
        candidatos = conflictos.candidatos_validos(clase_id, franja)
        if not candidatos:
            sugerido = info.posibles[0] if info.posibles else None
            return (sugerido,) if sugerido is not None else ()
        if len(candidatos) == 1:
            return (candidatos[0][0],)
        nombres = por_id(self.sesion.datos.profesores)
        elegido = self.dialogos.elegir_uno(
            "Elegir profesor",
            "Profesores que pueden dar la clase en esa franja:",
            [(p, nombres[p].nombre + (" (prefiere no)" if motivos else ""))
             for p, motivos in candidatos],
        )  # fmt: skip
        return (int(elegido),) if elegido is not None else None  # type: ignore[call-overload]

    def soltar(self, franja_id: str) -> None:
        """Suelta la clase tomada en la franja (§12.2)."""
        if self.edicion is None or self.tomada is None:
            return
        clase_id, origen = self.tomada
        if origen is not None and origen.franja_id == franja_id:
            return
        if self.edicion.borrador.buscar(clase_id, franja_id) is not None:
            self.dialogos.informar("Editor", "La clase ya está en esa franja.")
            return
        franja = self.sesion.calendario.franjas[franja_id]
        conflictos = self.edicion.conflictos
        info = conflictos.info.get(clase_id)
        if info is None or franja.nivel_id != info.nivel_id:
            self.dialogos.informar("Editor", "La clase no es de este nivel.")
            return
        with conflictos.sin(origen):
            estado, motivos = conflictos.estado(clase_id, franja)
        if estado != "invalida":
            profesores = self._elegir_profesores(clase_id, franja, origen)
            if profesores is None:
                return
            self._colocar(clase_id, franja_id, profesores, origen)
            return
        # Celda ocupada o inválida: intercambiar, reacomodar o (en modo flexible) forzar.
        otras = {m.clase_id for m in motivos if m.es_dura and m.clase_id not in (None, clase_id)}
        ocupante = None
        if origen is not None and len(otras) == 1:
            ocupante = self.edicion.borrador.buscar(next(iter(otras)), franja_id)
        if (
            ocupante is not None
            and origen is not None
            and self._intercambio_valido(origen, ocupante)
        ):
            if self.dialogos.confirmar(
                "Intercambiar",
                f"¿Intercambiar {info.texto} con {conflictos.info[ocupante.clase_id].texto}?",
            ):
                self._ejecutar(self.edicion.borrador.intercambiar(origen, ocupante))
            return
        texto = "\n".join("• " + m.texto for m in motivos if m.es_dura)
        if self.flexible.isChecked():
            if self.dialogos.confirmar(
                "Colocar con conflictos",
                f"La celda no es válida:\n{texto}\n\n¿Colocarla de todos modos?",
            ):
                profesores = self._elegir_profesores(clase_id, franja, origen)
                if profesores is not None:
                    self._colocar(clase_id, franja_id, profesores, origen)
            return
        if self.dialogos.confirmar(
            "Colocar y reacomodar lo mínimo",
            f"No cabe directamente:\n{texto}\n\n¿Buscar el menor reacomodo posible?",
        ):
            profesores = conflictos.profesores_de(clase_id, franja)
            if origen is not None and not info.clase.profesores:
                profesores = origen.profesores
            nueva = Colocacion(
                clase_id, franja_id, profesores, origen.bloqueada if origen else False
            )
            self.reacomodar(nueva, origen)

    def _intercambio_valido(self, a: Colocacion, b: Colocacion) -> bool:
        assert self.edicion is not None
        conflictos = self.edicion.conflictos
        fa = self.sesion.calendario.franjas[a.franja_id]
        fb = self.sesion.calendario.franjas[b.franja_id]
        with conflictos.sin(a, b):
            primero = not any(m.es_dura for m in conflictos.motivos_colocacion(a.en(b.franja_id)))
            conflictos.agregar(a.en(b.franja_id))
            try:
                segundo = not any(
                    m.es_dura for m in conflictos.motivos_colocacion(b.en(a.franja_id))
                )
            finally:
                conflictos.quitar(a.en(b.franja_id))
        return primero and segundo and fa.nivel_id == fb.nivel_id

    def _colocar(self, clase_id: int, franja_id: str, profesores: tuple[int, ...],
                 origen: Colocacion | None) -> None:  # fmt: skip
        assert self.edicion is not None
        borrador = self.edicion.borrador
        if origen is not None:
            movida = replace(origen, franja_id=franja_id, profesores=profesores)
            self._ejecutar(Operacion((origen,), (movida,), "Mover"))
        else:
            self._ejecutar(borrador.colocar(Colocacion(clase_id, franja_id, profesores)))
        self.tomada = None
        self.seleccion = (clase_id, franja_id)
        self._refrescar()

    # ------------------------------------------------------------------ operaciones

    def _ejecutar(self, operacion: Operacion) -> None:
        if operacion.vacia:
            return
        self.pila.push(ComandoOperacion(self, operacion))

    def _aplicar(self, operacion: Operacion) -> None:
        assert self.edicion is not None
        try:
            self.edicion.aplicar(operacion)
        except ErrorBorrador as error:
            self.dialogos.error("Editor", str(error))
            return
        self.sugeridas = set()
        if self.seleccion and self.edicion.borrador.buscar(*self.seleccion) is None:
            self.seleccion = None
        if self.tomada and self.tomada[1] is not None and self.tomada[1] in operacion.quitar:
            self.tomada = None
        self._refrescar()

    def seleccionada(self) -> Colocacion | None:
        if self.edicion is None or self.seleccion is None:
            return None
        return self.edicion.borrador.buscar(*self.seleccion)

    def quitar_seleccion(self) -> None:
        colocacion = self.seleccionada()
        if colocacion is not None:
            self.tomada = None
            self._ejecutar(self.edicion.borrador.quitar(colocacion))  # type: ignore[union-attr]

    def bloquear_seleccion(self) -> None:
        colocacion = self.seleccionada()
        if colocacion is not None:
            operacion = self.edicion.borrador.bloquear(colocacion, not colocacion.bloqueada)  # type: ignore[union-attr]
            self._ejecutar(operacion)
            self.tomada = None
            self._refrescar()

    def cambiar_profesor(self, clase_id: int) -> None:
        if self.edicion is None:
            return
        info = self.edicion.conflictos.info.get(clase_id)
        if info is None:
            return
        if info.clase.profesores:
            self.dialogos.informar(
                "Cambiar profesor",
                "La clase tiene profesores fijos; cámbielos en la pantalla Clases.",
            )
            return
        nombres = por_id(self.sesion.datos.profesores)
        elegido = self.dialogos.elegir_uno(
            "Cambiar profesor", "Nuevo profesor de la clase:",
            [(p, nombres[p].nombre) for p in info.posibles],
        )  # fmt: skip
        if elegido is not None:
            self._ejecutar(self.edicion.borrador.cambiar_profesor(clase_id, [int(elegido)]))  # type: ignore[call-overload]

    def mover(self, direccion: str) -> None:
        colocacion = self.seleccionada()
        franja = self.rejilla.franja_actual()
        if colocacion is None or franja is None:
            return
        fila, columna = self.rejilla.posiciones[colocacion.franja_id][0]
        df, dc = {"arriba": (-1, 0), "abajo": (1, 0), "izquierda": (0, -1), "derecha": (0, 1)}[
            direccion
        ]
        destino = self.rejilla.mapa.get((fila + df, columna + dc))
        if destino is None:
            return
        self.tomar(colocacion.clase_id, colocacion.franja_id)
        self.soltar(destino)
        self.rejilla.ir_a_franja(destino)

    def _tecla(self, nombre: str, franja_id: str) -> None:
        if nombre == "suprimir":
            self.quitar_seleccion()
        elif nombre.startswith("mover_"):
            self.mover(nombre.removeprefix("mover_"))
        elif nombre == "soltar" and self.tomada is not None and franja_id:
            self.soltar(franja_id)
        elif nombre == "tomar" and franja_id:
            self._celda_pulsada(franja_id)
        elif nombre == "soltar_toma":
            self.soltar_toma()

    def _doble_clic(self, franja_id: str) -> None:
        contenido = self.rejilla.contenidos.get((self.rejilla.currentRow(),
                                                 self.rejilla.currentColumn()))  # fmt: skip
        if contenido and contenido.colocaciones:
            self.tomada = None
            self.cambiar_profesor(contenido.colocaciones[0].clase_id)

    def buscar_suplente(self, clase_id: int, franja_id: str) -> str:
        """Quién podría cubrir la clase en esa franja (§11.4), en orden."""
        if self.edicion is None:
            return ""
        lista = self.edicion.suplentes(clase_id, franja_id)
        franja = self.sesion.calendario.franjas[franja_id]
        encabezado = f"Pueden cubrir la clase {franja.texto()}:"
        if not lista:
            encabezado = f"Nadie puede cubrir la clase {franja.texto()}."
        renglones = [f"{i}. {c.nombre} ({c.detalle})" for i, c in enumerate(lista, start=1)]
        pie = "Para registrar una suplencia con fecha, use la pantalla Suplencias."
        return "\n".join([encabezado, *renglones, "", pie])

    def porque_no(self, franja_id: str) -> str:
        """«¿Por qué no puede ir en…?»: motivos de la clase tomada en esa franja."""
        if self.edicion is None or self.tomada is None:
            return "Tome primero una clase (del panel o de la rejilla)."
        clase_id, origen = self.tomada
        franja = self.sesion.calendario.franjas[franja_id]
        with self.edicion.conflictos.sin(origen):
            motivos = self.edicion.conflictos.motivos(clase_id, franja)
        if not motivos:
            return "Puede ir ahí sin problemas."
        return "\n".join(("✗ " if m.es_dura else "~ ") + m.texto for m in motivos)

    def _menu(self, franja_id: str, punto: QPoint) -> None:
        contenido = self.rejilla.contenidos.get((self.rejilla.currentRow(),
                                                 self.rejilla.currentColumn()))  # fmt: skip
        menu = QMenu(self)
        if contenido and contenido.colocaciones:
            c = contenido.colocaciones[0]
            self.seleccion = (c.clase_id, c.franja_id)
            menu.addAction("Desbloquear" if c.bloqueada else "📌 Bloquear", self.bloquear_seleccion)
            menu.addAction("Quitar (Supr)", self.quitar_seleccion)
            menu.addAction("Cambiar profesor…", lambda: self.cambiar_profesor(c.clase_id))
            menu.addAction(
                "Buscar suplente…",
                lambda: self.dialogos.informar(
                    "Buscar suplente", self.buscar_suplente(c.clase_id, c.franja_id)
                ),
            )
        franja = self.sesion.calendario.franjas[franja_id]
        menu.addAction(
            f"¿Por qué no puede ir en {franja.texto()}?",
            lambda: self.dialogos.informar("¿Por qué no?", self.porque_no(franja_id)),
        )
        menu.exec(punto)

    def _ir_a_conflicto(self, item: QListWidgetItem) -> None:
        clase_id = item.data(ROL)
        if clase_id is None or self.edicion is None:
            return
        info = self.edicion.conflictos.info.get(clase_id)
        colocaciones = self.edicion.borrador.de_clase(clase_id)
        if info is None or not colocaciones:
            return
        self.pestanas.setCurrentIndex(0)
        self.combo_grupo.setCurrentIndex(
            self.combo_grupo.findData(info.clase.destinatarios[0].grupo_id)
        )
        self.seleccion = (clase_id, colocaciones[0].franja_id)
        self.rejilla.ir_a_franja(colocaciones[0].franja_id)
        self._refrescar()

    # ------------------------------------------------------------------ asistencia

    def sugerir(self) -> None:
        """«Sugerir lugar» (§12.4): resalta las 3 mejores celdas para la clase tomada."""
        if self.edicion is None:
            return
        if self.tomada is None:
            self.dialogos.informar("Sugerir lugar", "Elija primero una tarjeta del panel.")
            return
        clase_id, origen = self.tomada
        with self.edicion.conflictos.sin(origen):
            sugerencias = self.edicion.sugerir(clase_id)
        self.sugeridas = {s.franja_id for s in sugerencias}
        if not sugerencias:
            self.dialogos.informar("Sugerir lugar", "No hay celdas válidas para esa clase.")
        self._refrescar()

    def _en_fondo(self, funcion: object, al_terminar: object, texto: str) -> None:
        """Ejecuta `funcion` en otro hilo; `al_terminar(resultado)` corre en el de la interfaz
        (las señales se conectan a métodos de esta pantalla, que es un QObject)."""
        self._al_terminar_tarea = al_terminar
        tarea = TareaFondo(funcion)  # type: ignore[arg-type]
        tarea.terminado.connect(self._tarea_ok)
        tarea.fallo.connect(self._tarea_fallo)
        self.ejecucion = Ejecucion(tarea)
        self.etiqueta_tarea.setText(texto)
        self.setEnabled(False)
        self.ejecucion.iniciar()

    def _tarea_ok(self, resultado: object) -> None:
        self._fin_tarea(resultado, self._al_terminar_tarea)

    def _tarea_fallo(self, mensaje: str) -> None:
        self._fin_tarea(None, None, mensaje)

    def _fin_tarea(self, resultado: object, al_terminar: object, error: str | None = None) -> None:
        if self.ejecucion is not None:
            self.ejecucion.hilo.wait(5000)
        self.setEnabled(True)
        self.etiqueta_tarea.setText("")
        if error:
            self.dialogos.error("Editor", error)
        elif al_terminar is not None:
            al_terminar(resultado)  # type: ignore[operator]
        self.tarea_terminada.emit(resultado)

    def reacomodar(self, nueva: Colocacion, origen: Colocacion | None) -> None:
        assert self.edicion is not None
        edicion = self.edicion
        self._en_fondo(lambda: edicion.reacomodar(nueva, origen), self._propuesta,
                       "Buscando el menor reacomodo…")  # fmt: skip

    def _propuesta(self, propuesta: Propuesta) -> None:
        assert self.edicion is not None
        if not propuesta.encontrada:
            self.dialogos.informar("Colocar y reacomodar", propuesta.mensaje)
            return
        self.previa = propuesta.cambiadas
        self._refrescar()
        lineas = "\n".join("• " + c.linea for c in propuesta.cambios) or "Sin cambios."
        aceptar = self.dialogos.confirmar(
            "Vista previa del reacomodo",
            f"Cambios ({propuesta.tiempo_s:.1f} s"
            + (", con la semana completa" if propuesta.ampliada else "")
            + f"):\n{lineas}\n\n¿Aplicar?",
        )
        self.previa = set()
        if aceptar:
            operacion = self.edicion.borrador.reemplazar(propuesta.colocaciones,
                                                         "Colocar y reacomodar")  # fmt: skip
            self.tomada = None
            self._ejecutar(operacion)
        self._refrescar()

    def completar(self) -> None:
        """«Completar el resto» (§12.3) en segundo plano; abre el nuevo borrador."""
        if self.edicion is None:
            return
        edicion = self.edicion
        resolutor = edicion.resolutor_completar()
        self._en_fondo(resolutor.resolver, self._completado, "Completando el horario…")

    def _completado(self, resultado: object) -> None:
        assert self.edicion is not None
        solucion = self.edicion.guardar_completado(resultado)  # type: ignore[arg-type]
        if solucion is None:
            self.dialogos.informar("Completar el resto", "No se encontró cómo completarlo.")
            return
        self.recargar()
        self.abrir_borrador(solucion.id)  # type: ignore[attr-defined]
        self.dialogos.informar(
            "Completar el resto",
            f"Se creó «{solucion.nombre}» (↻ marca lo que cambió). El borrador original no se "  # type: ignore[attr-defined]
            "tocó.",
        )

    def validar_definitivo(self) -> None:
        if self.edicion is None:
            return
        verificacion = self.edicion.validar_definitivo()
        if verificacion.valida:
            self.dialogos.informar(
                "Validar y guardar como definitivo",
                f"«{self.edicion.solucion.nombre}» es válido y quedó como FACTIBLE. Márquelo como "
                "vigente en Resultados.",
            )
            self.edicion = None
            self.recargar()
            return
        lineas = "\n".join("• " + v.mensaje for v in verificacion.violaciones[:15])
        self.dialogos.error(
            "Validar y guardar como definitivo",
            f"El borrador todavía no es válido ({len(verificacion.violaciones)} problemas):\n"
            f"{lineas}",
        )

    def nuevo_vacio(self) -> None:
        nombre = self.dialogos.texto("Nuevo borrador", "Nombre:", "Borrador")
        if not nombre:
            return
        solucion = nuevo_borrador(self.sesion, nombre)
        self.abrir_borrador(solucion.id or 0)
