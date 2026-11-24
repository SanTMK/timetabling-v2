"""Creado con Claude.

Pantalla Clases (§17): por grupo, lista de clases (asignatura, destinatarios, profesores, horas,
origen). Botones Sincronizar con el plan, Nueva clase, Juntar grupos, Dividir, Asignar profesor,
Cambiar horas y Eliminar; la matriz grupos × asignaturas es la vista alternativa. Cada acción se
guarda al instante.
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

from timetabling.dominio.clases import grupos_de_clase, texto_destinatarios
from timetabling.dominio.modelos import Clase, Destinatario, por_id
from timetabling.gui.pantallas.base import Contexto, Pantalla

ROL = Qt.ItemDataRole.UserRole


class PantallaClases(Pantalla):
    clave = "clases"
    titulo = "Clases"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        superior = QHBoxLayout()
        superior.addWidget(QLabel("&Grupo:"))
        self.grupo = QComboBox()
        self.grupo.setAccessibleName("Grupo")
        superior.itemAt(0).widget().setBuddy(self.grupo)  # type: ignore[union-attr]
        self.grupo.currentIndexChanged.connect(self._llenar_tabla)
        superior.addWidget(self.grupo, 1)
        self.boton_sincronizar = QPushButton("&Sincronizar con el plan")
        self.boton_sincronizar.clicked.connect(self.sincronizar)
        superior.addWidget(self.boton_sincronizar)
        capa.addLayout(superior)

        self.pestanas = QTabWidget()
        capa.addWidget(self.pestanas, 1)
        por_grupo = QWidget()
        capa_grupo = QVBoxLayout(por_grupo)
        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(
            ["Asignatura", "Destinatarios", "Profesores", "Horas", "Origen"]
        )
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAccessibleName("Clases del grupo")
        self.tabla.cellDoubleClicked.connect(lambda *_: self.asignar_profesor())
        capa_grupo.addWidget(self.tabla)
        botones = QHBoxLayout()
        self.boton_nueva = QPushButton("&Nueva clase")
        self.boton_juntar = QPushButton("&Juntar grupos")
        self.boton_dividir = QPushButton("&Dividir")
        self.boton_profesor = QPushButton("Asignar &profesor")
        self.boton_horas = QPushButton("Cambiar &horas")
        self.boton_eliminar = QPushButton("&Eliminar")
        for boton, accion in (
            (self.boton_nueva, self.nueva_clase),
            (self.boton_juntar, self.juntar),
            (self.boton_dividir, self.dividir),
            (self.boton_profesor, self.asignar_profesor),
            (self.boton_horas, self.cambiar_horas),
            (self.boton_eliminar, self.eliminar),
        ):
            boton.clicked.connect(accion)
            botones.addWidget(boton)
        capa_grupo.addLayout(botones)
        self.pestanas.addTab(por_grupo, "Por grupo")

        self.matriz = QTableWidget()
        self.matriz.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matriz.setAccessibleName("Matriz grupos por asignaturas")
        self.matriz.cellDoubleClicked.connect(self._matriz_doble_clic)
        self.pestanas.addTab(self.matriz, "Matriz grupos × asignaturas")

    # ------------------------------------------------------------------ carga

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        datos = self.sesion.datos
        actual = self.grupo.currentData()
        self.grupo.blockSignals(True)
        self.grupo.clear()
        for grupo in datos.grupos:
            self.grupo.addItem(datos.nombre_grupo(grupo.id or 0), grupo.id)
        indice = self.grupo.findData(actual)
        self.grupo.setCurrentIndex(indice if indice >= 0 else 0)
        self.grupo.blockSignals(False)
        self._llenar_tabla()
        self._llenar_matriz()

    def _texto_profesores(self, clase: Clase) -> str:
        if not clase.profesores:
            return "(lo elige el generador)"
        profesores = por_id(self.sesion.datos.profesores)
        return ", ".join(profesores[p].nombre for p in clase.profesores if p in profesores)

    def clases_del_grupo(self) -> list[Clase]:
        grupo = self.grupo.currentData()
        return [c for c in self.sesion.datos.clases if grupo in grupos_de_clase(c)]

    def _llenar_tabla(self) -> None:
        if self.contexto.sesion is None:
            return
        datos = self.sesion.datos
        asignaturas = por_id(datos.asignaturas)
        clases = self.clases_del_grupo()
        self.tabla.setRowCount(len(clases))
        for i, clase in enumerate(clases):
            valores = [
                asignaturas[clase.asignatura_id].nombre,
                texto_destinatarios(datos, clase),
                self._texto_profesores(clase),
                str(clase.horas_semanales),
                "Plan" if clase.origen == "plan" else "Manual",
            ]
            for j, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(ROL, clase.id)
                self.tabla.setItem(i, j, item)

    def _llenar_matriz(self) -> None:
        datos = self.sesion.datos
        self.matriz.clear()
        self.matriz.setRowCount(len(datos.grupos))
        self.matriz.setColumnCount(len(datos.asignaturas))
        self.matriz.setHorizontalHeaderLabels([a.nombre for a in datos.asignaturas])
        self.matriz.setVerticalHeaderLabels([datos.nombre_grupo(g.id or 0) for g in datos.grupos])
        for i, grupo in enumerate(datos.grupos):
            for j, asignatura in enumerate(datos.asignaturas):
                clases = [
                    c for c in datos.clases
                    if c.asignatura_id == asignatura.id and grupo.id in grupos_de_clase(c)
                ]  # fmt: skip
                texto = " / ".join(self._texto_profesores(c) for c in clases)
                item = QTableWidgetItem(texto)
                item.setData(ROL, [c.id for c in clases])
                self.matriz.setItem(i, j, item)

    # ------------------------------------------------------------------ selección

    def clase_seleccionada(self) -> Clase | None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return None
        ident = self.tabla.item(fila, 0).data(ROL)
        return por_id(self.sesion.datos.clases).get(ident)

    def elegir_clase(self, asignatura: str) -> None:
        """Selecciona la fila de la asignatura en el grupo actual."""
        for i in range(self.tabla.rowCount()):
            if self.tabla.item(i, 0).text() == asignatura:
                self.tabla.setCurrentCell(i, 0)
                return
        raise KeyError(asignatura)

    def elegir_grupo(self, nombre: str) -> None:
        indice = self.grupo.findText(nombre)
        if indice < 0:
            raise KeyError(nombre)
        self.grupo.setCurrentIndex(indice)

    def _requiere_clase(self) -> Clase | None:
        clase = self.clase_seleccionada()
        if clase is None:
            self.dialogos.informar("Clases", "Elija primero una clase de la lista.")
        return clase

    # ------------------------------------------------------------------ acciones

    def sincronizar(self) -> None:
        resultado = self.sesion.sincronizar_clases()
        datos = self.sesion.datos
        asignaturas = por_id(datos.asignaturas)
        lineas = [f"Se crearon {len(resultado.nuevas)} clases nuevas."]
        for d in resultado.diferencias:
            grupo = datos.nombre_grupo(d.grupo_id) + (f" ({d.parte})" if d.parte else "")
            signo = "de más" if d.diferencia > 0 else "de menos"
            lineas.append(
                f"• {grupo}: {abs(d.diferencia)} h {signo} de {asignaturas[d.asignatura_id].nombre}"
            )
        for clase in resultado.huerfanas:
            lineas.append(
                f"• Clase huérfana: {asignaturas[clase.asignatura_id].nombre} · "
                f"{texto_destinatarios(datos, clase)}"
            )
        self.dialogos.informar("Sincronizar con el plan", "\n".join(lineas))
        self.recargar()

    def nueva_clase(self) -> None:
        grupo = self.grupo.currentData()
        if grupo is None:
            return
        datos = self.sesion.datos
        asignatura = self.dialogos.elegir_uno(
            "Nueva clase", "Asignatura:", [(a.id, a.nombre) for a in datos.asignaturas]
        )
        if asignatura is None:
            return
        horas = self._pedir_horas(1)
        if horas is None:
            return
        self.sesion.guardar(
            Clase(asignatura_id=int(asignatura),  # type: ignore[call-overload]
                  destinatarios=[Destinatario(grupo_id=grupo)], horas_semanales=horas)
        )  # fmt: skip
        self.recargar()

    def _pedir_horas(self, actuales: int) -> int | None:
        texto = self.dialogos.texto("Horas semanales", "Horas semanales:", str(actuales))
        if texto is None:
            return None
        try:
            horas = int(texto)
        except ValueError:
            self.dialogos.error("Horas semanales", "Escriba un número entero.")
            return None
        if horas < 1:
            self.dialogos.error("Horas semanales", "Debe ser al menos 1.")
            return None
        return horas

    def cambiar_horas(self) -> None:
        clase = self._requiere_clase()
        if clase is None:
            return
        horas = self._pedir_horas(clase.horas_semanales)
        if horas is not None:
            self.sesion.guardar(clase.model_copy(update={"horas_semanales": horas,
                                                         "origen": "manual"}))  # fmt: skip
            self.recargar()

    def asignar_profesor(self, clase: Clase | None = None) -> None:
        clase = clase or self._requiere_clase()
        if clase is None:
            return
        candidatos = self.sesion.candidatos(clase)
        elegidos = self.dialogos.elegir_varios(
            "Asignar profesor",
            "Profesores que imparten la clase (ninguno = lo elige el generador):",
            [(p.id, p.nombre) for p in candidatos],
            list(clase.profesores),
        )
        if elegidos is None:
            return
        self.sesion.guardar(clase.model_copy(update={"profesores": [int(p) for p in elegidos]}))  # type: ignore[call-overload]
        self.recargar()

    def juntar(self) -> None:
        clase = self._requiere_clase()
        if clase is None:
            return
        datos = self.sesion.datos
        nivel = datos.nivel_de_grupo(clase.destinatarios[0].grupo_id).id
        propias = set(grupos_de_clase(clase))
        opciones = [
            (c.id, texto_destinatarios(datos, c))
            for c in datos.clases
            if c.id != clase.id
            and c.asignatura_id == clase.asignatura_id
            and not propias & set(grupos_de_clase(c))
            and datos.nivel_de_grupo(c.destinatarios[0].grupo_id).id == nivel
        ]
        if not opciones:
            self.dialogos.informar("Juntar grupos", "No hay otros grupos del nivel con esa clase.")
            return
        elegidas = self.dialogos.elegir_varios(
            "Juntar grupos", "Grupos que toman la clase juntos:", opciones, []
        )
        if elegidas:
            self.sesion.juntar_clases([clase.id or 0, *[int(c) for c in elegidas]])  # type: ignore[call-overload]
            self.recargar()

    def dividir(self) -> None:
        clase = self._requiere_clase()
        if clase is None:
            return
        grupo = clase.destinatarios[0].grupo_id
        divisiones = [d for d in self.sesion.datos.divisiones if d.grupo_id == grupo]
        if len(clase.destinatarios) != 1 or not divisiones:
            self.dialogos.informar(
                "Dividir",
                "Solo se divide una clase de un grupo que tenga divisiones (créelas en Grados "
                "y grupos).",
            )
            return
        division = self.dialogos.elegir_uno(
            "Dividir",
            "División:",
            [(d.id, f"{d.nombre}: {', '.join(d.partes)}") for d in divisiones],
        )
        if division is not None:
            self.sesion.dividir_clase(clase.id or 0, int(division))  # type: ignore[call-overload]
            self.recargar()

    def eliminar(self) -> None:
        clase = self._requiere_clase()
        if clase is None or clase.id is None:
            return
        afectados = self.sesion.afectados(Clase, clase.id)
        detalle = "\n".join(f"• {n} {que}" for que, n in afectados.items())
        if self.dialogos.confirmar(
            "Eliminar clase", f"¿Eliminar la clase? Se afectará:\n{detalle}"
        ):
            self.sesion.eliminar(Clase, clase.id)
            self.recargar()

    def _matriz_doble_clic(self, fila: int, columna: int) -> None:
        ids = self.matriz.item(fila, columna).data(ROL) or []
        if len(ids) == 1:
            self.asignar_profesor(por_id(self.sesion.datos.clases)[ids[0]])

    def seleccionar(self, entidad: str, ident: object) -> None:
        clases = por_id(self.sesion.datos.clases)
        fija = next((f for f in self.sesion.datos.fijas if f.id == ident), None)
        if entidad == "fija" and fija is not None:
            ident = fija.clase_id
        if entidad == "grupo":
            self.grupo.setCurrentIndex(max(0, self.grupo.findData(ident)))
            return
        clase = clases.get(ident)  # type: ignore[arg-type]
        if clase is None:
            return
        self.grupo.setCurrentIndex(max(0, self.grupo.findData(clase.destinatarios[0].grupo_id)))
        for i in range(self.tabla.rowCount()):
            if self.tabla.item(i, 0).data(ROL) == clase.id:
                self.tabla.setCurrentCell(i, 0)
