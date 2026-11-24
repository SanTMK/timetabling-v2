"""Creado con Claude.

Pantalla Grados y grupos (§17): árbol nivel → grado → grupos; titular, bloqueos y divisiones
del grupo.
"""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import BloqueoGrupo, Division, Grado, Grupo
from timetabling.gui.pantallas.base import Contexto, Formulario, Pantalla, guardar_con_errores
from timetabling.gui.widgets.campos import Columna, TablaFilas
from timetabling.persistencia.repositorio import ErrorProfesorEnUso

ROL = Qt.ItemDataRole.UserRole


class PantallaGrados(Pantalla):
    clave = "grados"
    titulo = "Grados y grupos"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.actual: Grado | Grupo | None = None
        self._nuevo_tipo: type[Grado] | type[Grupo] | None = None
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        divisor = QSplitter()
        capa.addWidget(divisor, 1)

        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setAccessibleName("Árbol de niveles, grados y grupos")
        self.arbol.currentItemChanged.connect(self._al_elegir)
        capa_izq.addWidget(self.arbol)
        botones = QHBoxLayout()
        self.boton_grado = QPushButton("Nuevo grado")
        self.boton_grupo = QPushButton("Nuevo grupo")
        self.boton_eliminar = QPushButton("Eliminar")
        self.boton_grado.clicked.connect(lambda: self.nuevo(Grado))
        self.boton_grupo.clicked.connect(lambda: self.nuevo(Grupo))
        self.boton_eliminar.clicked.connect(self.eliminar)
        for b in (self.boton_grado, self.boton_grupo, self.boton_eliminar):
            botones.addWidget(b)
        capa_izq.addLayout(botones)
        divisor.addWidget(izquierda)

        derecha = QWidget()
        capa_der = QVBoxLayout(derecha)
        capa_der.setContentsMargins(0, 0, 0, 0)
        self.pila = QStackedWidget()
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(self.pila)
        capa_der.addWidget(desplazable, 1)
        self.vacio = QLabel("Elija un grado o un grupo, o cree uno nuevo.")
        self.pila.addWidget(self.vacio)

        self.form_grado = Formulario()
        self.grado_nivel = self.form_grado.campo("nivel_id", "&Nivel", QComboBox())
        self.grado_nombre = self.form_grado.campo("nombre", "N&ombre", QLineEdit())
        self.grado_nombre.setPlaceholderText("1°, 7°, K2…")
        self.pila.addWidget(self.form_grado)

        self.form_grupo = Formulario()
        self.grupo_grado = self.form_grupo.campo("grado_id", "&Grado", QComboBox())
        self.grupo_seccion = self.form_grupo.campo("seccion", "&Sección", QLineEdit())
        self.grupo_estudiantes = self.form_grupo.campo(
            "estudiantes", "&Estudiantes (informativo)", QSpinBox()
        )
        self.grupo_estudiantes.setRange(0, 999)
        self.grupo_titular = self.form_grupo.campo("titular_id", "&Titular", QComboBox())
        self.grupo_bloqueos = self.form_grupo.campo(
            "bloqueos",
            "&Bloqueos",
            TablaFilas(
                [
                    Columna("nombre", "Nombre", "texto", "Bloqueo"),
                    Columna("dia", "Día", "dia", "V"),
                    Columna("inicio", "Inicio", "hora", 780),
                    Columna("fin", "Fin", "hora", 840),
                ]
            ),
        )
        self.grupo_divisiones = self.form_grupo.campo(
            "divisiones",
            "&Divisiones",
            TablaFilas(
                [
                    Columna("nombre", "Nombre", "texto", "Inglés por nivel"),
                    Columna("partes", "Partes (separadas por coma)", "texto", "Básico, Avanzado"),
                    Columna("simultanea", "Simultánea", "booleano", True),
                ]
            ),
        )
        self.pila.addWidget(self.form_grupo)
        self.vigilar(
            self.grado_nivel, self.grado_nombre, self.grupo_grado, self.grupo_seccion,
            self.grupo_estudiantes, self.grupo_titular, self.grupo_bloqueos,
            self.grupo_divisiones,
        )  # fmt: skip

        acciones = QHBoxLayout()
        acciones.addStretch()
        descartar = QPushButton("Descartar")
        descartar.clicked.connect(self.descartar)
        self.boton_guardar = QPushButton("&Guardar")
        self.boton_guardar.clicked.connect(self.guardar)
        acciones.addWidget(descartar)
        acciones.addWidget(self.boton_guardar)
        capa_der.addLayout(acciones)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 3)

    # ------------------------------------------------------------------ carga

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        datos = self.sesion.datos
        clave_actual = self._clave(self.actual)
        self._cargando = True
        self.arbol.blockSignals(True)
        self.arbol.clear()
        elegido: QTreeWidgetItem | None = None
        for nivel in datos.niveles:
            item_nivel = QTreeWidgetItem([nivel.nombre])
            item_nivel.setData(0, ROL, None)
            self.arbol.addTopLevelItem(item_nivel)
            for grado in [g for g in datos.grados if g.nivel_id == nivel.id]:
                item_grado = QTreeWidgetItem([f"Grado {grado.nombre}"])
                item_grado.setData(0, ROL, grado)
                item_nivel.addChild(item_grado)
                if self._clave(grado) == clave_actual:
                    elegido = item_grado
                for grupo in [g for g in datos.grupos if g.grado_id == grado.id]:
                    item_grupo = QTreeWidgetItem([datos.nombre_grupo(grupo.id or 0)])
                    item_grupo.setData(0, ROL, grupo)
                    item_grado.addChild(item_grupo)
                    if self._clave(grupo) == clave_actual:
                        elegido = item_grupo
        self.arbol.expandAll()
        self.arbol.blockSignals(False)
        self._llenar_combos()
        if elegido is not None:
            self.arbol.setCurrentItem(elegido)
            self._poner(elegido.data(0, ROL))
        else:
            self._poner(None)
        self._cargando = False

    @staticmethod
    def _clave(entidad: Any) -> tuple[str, int | None] | None:
        if entidad is None:
            return None
        return (type(entidad).__name__, getattr(entidad, "id", None))

    def _llenar_combos(self) -> None:
        datos = self.sesion.datos
        self.grado_nivel.blockSignals(True)
        self.grado_nivel.clear()
        for nivel in datos.niveles:
            self.grado_nivel.addItem(nivel.nombre, nivel.id)
        self.grado_nivel.blockSignals(False)
        self.grupo_grado.blockSignals(True)
        self.grupo_grado.clear()
        niveles = {n.id: n.nombre for n in datos.niveles}
        for grado in datos.grados:
            self.grupo_grado.addItem(f"{grado.nombre} ({niveles.get(grado.nivel_id, '?')})",
                                     grado.id)  # fmt: skip
        self.grupo_grado.blockSignals(False)
        self.grupo_titular.blockSignals(True)
        self.grupo_titular.clear()
        self.grupo_titular.addItem("(sin titular)", None)
        for profesor in datos.profesores:
            if profesor.activo:
                self.grupo_titular.addItem(profesor.nombre, profesor.id)
        self.grupo_titular.blockSignals(False)

    def _poner(self, entidad: Any) -> None:
        self._cargando = True
        self.actual = entidad
        self.form_grado.limpiar_errores()
        self.form_grupo.limpiar_errores()
        if isinstance(entidad, Grado) or (entidad is None and self._nuevo_tipo is Grado):
            self.pila.setCurrentWidget(self.form_grado)
            self.grado_nivel.setCurrentIndex(
                max(0, self.grado_nivel.findData(entidad.nivel_id if entidad else None))
            )
            self.grado_nombre.setText(entidad.nombre if entidad else "")
        elif isinstance(entidad, Grupo) or (entidad is None and self._nuevo_tipo is Grupo):
            self.pila.setCurrentWidget(self.form_grupo)
            g = entidad
            if g is not None:
                self.grupo_grado.setCurrentIndex(max(0, self.grupo_grado.findData(g.grado_id)))
            self.grupo_seccion.setText(g.seccion if g else "")
            self.grupo_estudiantes.setValue(g.estudiantes if g else 0)
            self.grupo_titular.setCurrentIndex(
                max(0, self.grupo_titular.findData(g.titular_id if g else None))
            )
            self.grupo_bloqueos.poner([b.model_dump() for b in g.bloqueos] if g else [])
            divisiones = (
                [d for d in self.sesion.datos.divisiones if d.grupo_id == g.id] if g else []
            )
            self._divisiones_originales = divisiones
            self.grupo_divisiones.poner(
                [
                    {"nombre": d.nombre, "partes": ", ".join(d.partes),
                     "simultanea": d.simultanea}
                    for d in divisiones
                ]
            )  # fmt: skip
        else:
            self.pila.setCurrentWidget(self.vacio)
        self.boton_eliminar.setEnabled(entidad is not None)
        self._cargando = False
        self.limpiar_cambios()

    def _al_elegir(self, actual: QTreeWidgetItem | None, anterior: QTreeWidgetItem | None) -> None:
        if self._cargando:
            return
        if self.hay_cambios() and anterior is not None and not self.confirmar_salida():
            self.arbol.blockSignals(True)
            self.arbol.setCurrentItem(anterior)
            self.arbol.blockSignals(False)
            return
        self._nuevo_tipo = None
        self._poner(actual.data(0, ROL) if actual is not None else None)

    # ------------------------------------------------------------------ acciones

    def nuevo(self, tipo: type[Grado] | type[Grupo]) -> None:
        if not self.confirmar_salida():
            return
        elegido = self.actual
        self._nuevo_tipo = tipo
        self.arbol.blockSignals(True)
        self.arbol.setCurrentItem(None)  # type: ignore[arg-type]
        self.arbol.blockSignals(False)
        self._poner(None)
        # Sugerencias según lo elegido en el árbol.
        if tipo is Grupo and isinstance(elegido, (Grado, Grupo)):
            grado_id = elegido.id if isinstance(elegido, Grado) else elegido.grado_id
            self.grupo_grado.setCurrentIndex(max(0, self.grupo_grado.findData(grado_id)))
        if tipo is Grado and isinstance(elegido, Grado):
            self.grado_nivel.setCurrentIndex(max(0, self.grado_nivel.findData(elegido.nivel_id)))
        self.marcar_cambio()

    def leer(self) -> Grado | Grupo:
        if self.pila.currentWidget() is self.form_grado:
            return Grado.model_validate(
                {
                    "id": getattr(self.actual, "id", None),
                    "nivel_id": self.grado_nivel.currentData(),
                    "nombre": self.grado_nombre.text(),
                }
            )
        return Grupo.model_validate(
            {
                "id": getattr(self.actual, "id", None),
                "grado_id": self.grupo_grado.currentData(),
                "seccion": self.grupo_seccion.text(),
                "estudiantes": self.grupo_estudiantes.value(),
                "titular_id": self.grupo_titular.currentData(),
                "bloqueos": [BloqueoGrupo.model_validate(b) for b in self.grupo_bloqueos.filas()],
            }
        )

    def _divisiones(self, grupo_id: int) -> tuple[list[Division], list[int]]:
        originales = getattr(self, "_divisiones_originales", [])
        nuevas: list[Division] = []
        for i, fila in enumerate(self.grupo_divisiones.filas()):
            partes = [p.strip() for p in str(fila["partes"]).split(",") if p.strip()]
            ident = originales[i].id if i < len(originales) else None
            nuevas.append(
                Division.model_validate(
                    {"id": ident, "grupo_id": grupo_id, "nombre": fila["nombre"],
                     "partes": partes, "simultanea": bool(fila["simultanea"])}
                )
            )  # fmt: skip
        quitar = [d.id for d in originales[len(nuevas) :] if d.id is not None]
        return nuevas, quitar

    def guardar(self) -> bool:
        formulario = (
            self.form_grado if self.pila.currentWidget() is self.form_grado else (self.form_grupo)
        )
        if self.pila.currentWidget() is self.vacio:
            self.limpiar_cambios()
            return True

        def accion() -> Grado | Grupo:
            entidad = self.leer()
            if isinstance(entidad, Grupo):
                divisiones, quitar = self._divisiones(entidad.id or 0)
                return self.sesion.guardar_grupo(entidad, divisiones, quitar)
            return self.sesion.guardar(entidad)

        ok, guardada = guardar_con_errores(formulario, accion)
        if ok:
            self.actual = guardada
            self._nuevo_tipo = None
            self.limpiar_cambios()
            self.recargar()
        return ok

    def descartar(self) -> None:
        self.limpiar_cambios()
        self._poner(self.actual)

    def eliminar(self) -> None:
        entidad = self.actual
        if entidad is None or entidad.id is None:
            return
        tipo = type(entidad)
        try:
            afectados = self.sesion.afectados(tipo, entidad.id)
        except ErrorProfesorEnUso as error:  # pragma: no cover - no aplica a grados
            self.dialogos.error("No se puede eliminar", str(error))
            return
        nombre = (
            self.sesion.datos.nombre_grupo(entidad.id) if isinstance(entidad, Grupo)
            else f"Grado {entidad.nombre}"
        )  # fmt: skip
        detalle = "\n".join(f"• {n} {que}" for que, n in afectados.items())
        if self.dialogos.confirmar("Eliminar", f"¿Eliminar «{nombre}»? Se afectará:\n{detalle}"):
            self.sesion.eliminar(tipo, entidad.id)
            self.actual = None
            self.limpiar_cambios()
            self.recargar()

    def seleccionar(self, entidad: str, ident: object) -> None:
        tipo = {"grado": Grado, "grupo": Grupo}.get(entidad)
        if tipo is None and entidad == "division":
            division = next((d for d in self.sesion.datos.divisiones if d.id == ident), None)
            tipo, ident = (Grupo, division.grupo_id) if division else (None, None)
        iterador = [self.arbol.topLevelItem(i) for i in range(self.arbol.topLevelItemCount())]
        while iterador:
            item = iterador.pop()
            dato = item.data(0, ROL)
            if tipo is not None and isinstance(dato, tipo) and dato.id == ident:
                self.arbol.setCurrentItem(item)
                return
            iterador.extend(item.child(i) for i in range(item.childCount()))

    def elegir(self, texto: str) -> None:
        items = self.arbol.findItems(texto, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
        if not items:
            raise KeyError(texto)
        self.arbol.setCurrentItem(items[0])
