"""Creado con Claude.

Pantalla Profesores (§17): activo, datos generales, habilitaciones, eventos, «Puede suplir»,
cargas y editor de disponibilidad con aviso de franjas parcialmente cubiertas.
"""

from typing import Any

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import EventoProfesor, Profesor
from timetabling.gui.pantallas.base import Formulario, PantallaListaFormulario
from timetabling.gui.widgets.campos import Columna, ListaMarcable, TablaFilas
from timetabling.gui.widgets.disponibilidad import NOMBRES, EditorDisponibilidad
from timetabling.nucleo.franjas import franjas_parcialmente_cubiertas


class PantallaProfesores(PantallaListaFormulario):
    clave = "profesores"
    titulo = "Profesores"
    tipo = Profesor
    nombre_singular = "profesor"

    def construir_formulario(self, formulario: Formulario) -> None:
        f = formulario
        self.nombre = f.campo("nombre", "&Nombre", QLineEdit())
        self.activo = f.campo("activo", "&Activo", QCheckBox())
        self.asignaturas = f.campo("asignaturas", "A&signaturas que imparte", ListaMarcable())
        self.grados = f.campo("grados", "&Grados que atiende", ListaMarcable())
        self.supl_asignaturas = f.campo(
            "suplencia_asignaturas", "Puede suplir: asignaturas", ListaMarcable()
        )
        self.supl_grados = f.campo("suplencia_grados", "Puede suplir: grados", ListaMarcable())
        self.carga_max = f.campo("carga_max_semanal_min", "Carga máxima semanal (min)", QSpinBox())
        self.carga_max.setRange(0, 10080)
        self.carga_dia = f.campo("carga_max_diaria_min", "Carga máxima diaria (min)", QSpinBox())
        self.carga_dia.setRange(0, 1440)
        self.carga_min = f.campo("carga_min_semanal_min", "Carga mínima semanal (min)", QSpinBox())
        self.carga_min.setRange(0, 10080)
        self.max_dias = f.campo("max_dias", "Máximo de días con clase", QSpinBox())
        self.max_dias.setRange(0, 7)
        self.max_dias.setSpecialValueText("Sin límite")
        self.continuo = f.campo("max_minutos_continuos", "Máximo de minutos seguidos", QSpinBox())
        self.continuo.setRange(5, 1440)
        self.eventos = f.campo(
            "eventos",
            "&Eventos propios",
            TablaFilas(
                [
                    Columna("nombre", "Nombre", "texto", "Junta"),
                    Columna("dia", "Día", "dia", "L"),
                    Columna("inicio", "Inicio", "hora", 840),
                    Columna("fin", "Fin", "hora", 900),
                ]
            ),
        )
        self.toda_jornada = f.campo(
            "disponible_toda_la_jornada",
            "Disponible &toda la jornada",
            QCheckBox("salvo lo marcado como «no disponible»"),
        )
        caja = QWidget()
        capa = QVBoxLayout(caja)
        capa.setContentsMargins(0, 0, 0, 0)
        herramientas = QHBoxLayout()
        self.grupo_herramientas = QButtonGroup(self)
        for i, (clave, texto) in enumerate([*NOMBRES.items(), (None, "Borrar")]):
            boton = QRadioButton(texto)
            boton.setProperty("herramienta", clave)
            self.grupo_herramientas.addButton(boton, i)
            herramientas.addWidget(boton)
            if i == 0:
                boton.setChecked(True)
        self.grupo_herramientas.buttonClicked.connect(
            lambda b: setattr(self.editor, "herramienta", b.property("herramienta"))
        )
        self.boton_copiar = QPushButton("Copiar día a toda la semana")
        self.boton_limpiar = QPushButton("Limpiar")
        capa.addLayout(herramientas)
        acciones = QHBoxLayout()
        acciones.addWidget(self.boton_copiar)
        acciones.addWidget(self.boton_limpiar)
        acciones.addStretch()
        capa.addLayout(acciones)
        self.editor = EditorDisponibilidad()
        capa.addWidget(self.editor)
        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet("color: #8A5A00;")
        capa.addWidget(self.aviso)
        self.boton_copiar.clicked.connect(lambda: self.editor.copiar_dia(self.editor.dia_actual))
        self.boton_limpiar.clicked.connect(self.editor.limpiar)
        f.campo("disponibilidad", "&Disponibilidad", caja)
        self.vigilar(
            self.nombre, self.activo, self.asignaturas, self.grados, self.supl_asignaturas,
            self.supl_grados, self.carga_max, self.carga_dia, self.carga_min, self.max_dias,
            self.continuo, self.eventos, self.toda_jornada,
        )  # fmt: skip
        self.editor.cambiado.connect(self.marcar_cambio)
        self.editor.cambiado.connect(self._avisar)
        self.toda_jornada.toggled.connect(self._avisar)
        self.grados.cambiado.connect(self._configurar_editor)

    def entidades(self) -> list[Any]:
        return list(self.sesion.datos.profesores)

    def texto(self, entidad: Profesor) -> str:
        return entidad.nombre if entidad.activo else f"{entidad.nombre} (inactivo)"

    def atenuado(self, entidad: Profesor) -> bool:
        return not entidad.activo

    def _configurar_editor(self) -> None:
        datos = self.sesion.datos
        grados = {g.id: g for g in datos.grados}
        niveles_ids = {grados[g].nivel_id for g in self.grados.marcados() if g in grados}
        niveles = [n for n in datos.niveles if n.id in niveles_ids] or list(datos.niveles)
        if not niveles:
            return
        dias = [d for d in ("L", "M", "X", "J", "V", "S", "D") if any(d in n.dias for n in niveles)]
        inicio = min(n.inicio_jornada for n in niveles)
        fin = max(n.fin_jornada for n in niveles)
        bandas = [
            f for n in niveles for f in self.sesion.calendario.utiles_nivel.get(n.id or 0, [])
        ]
        self.editor.configurar(dias, inicio, fin, bandas)  # type: ignore[arg-type]
        self._avisar()

    def _avisar(self) -> None:
        if self.contexto.sesion is None:
            return
        try:
            profesor = Profesor(
                nombre="x",
                disponibilidad=self.editor.leer(),
                disponible_toda_la_jornada=self.toda_jornada.isChecked(),
            )
        except ValueError:
            return
        parciales = franjas_parcialmente_cubiertas(profesor, self.editor.bandas)
        self.aviso.setText(
            "⚠ Estas franjas quedan cubiertas solo en parte y no se podrán usar: "
            + ", ".join(sorted({f.texto() for f in parciales}))
            if parciales
            else ""
        )

    def mostrar(self, entidad: Profesor | None) -> None:
        datos = self.sesion.datos
        p = entidad
        niveles = {n.id: n.nombre for n in datos.niveles}
        opciones_asig = [(a.id or 0, a.nombre) for a in datos.asignaturas]
        opciones_grados = [
            (g.id or 0, f"{g.nombre} ({niveles.get(g.nivel_id, '?')})") for g in datos.grados
        ]
        self.nombre.setText(p.nombre if p else "")
        self.activo.setChecked(p.activo if p else True)
        self.asignaturas.poner(opciones_asig, p.asignaturas if p else [])
        self.grados.poner(opciones_grados, p.grados if p else [])
        self.supl_asignaturas.poner(opciones_asig, p.suplencia_asignaturas if p else [])
        self.supl_grados.poner(opciones_grados, p.suplencia_grados if p else [])
        self.carga_max.setValue(p.carga_max_semanal_min if p else 2400)
        self.carga_dia.setValue(p.carga_max_diaria_min if p else 480)
        self.carga_min.setValue(p.carga_min_semanal_min if p else 0)
        self.max_dias.setValue(p.max_dias or 0 if p else 0)
        self.continuo.setValue(p.max_minutos_continuos if p else 200)
        self.eventos.poner([e.model_dump() for e in p.eventos] if p else [])
        self.toda_jornada.setChecked(p.disponible_toda_la_jornada if p else True)
        self._configurar_editor()
        self.editor.poner(p.disponibilidad if p else [])
        self._avisar()

    def leer(self) -> Profesor:
        return Profesor.model_validate(
            {
                "id": getattr(self.actual, "id", None),
                "nombre": self.nombre.text(),
                "activo": self.activo.isChecked(),
                "asignaturas": self.asignaturas.marcados(),
                "grados": self.grados.marcados(),
                "suplencia_asignaturas": self.supl_asignaturas.marcados(),
                "suplencia_grados": self.supl_grados.marcados(),
                "carga_max_semanal_min": self.carga_max.value(),
                "carga_max_diaria_min": self.carga_dia.value(),
                "carga_min_semanal_min": self.carga_min.value(),
                "max_dias": self.max_dias.value() or None,
                "max_minutos_continuos": self.continuo.value(),
                "eventos": [EventoProfesor.model_validate(e) for e in self.eventos.filas()],
                "disponible_toda_la_jornada": self.toda_jornada.isChecked(),
                "disponibilidad": self.editor.leer(),
            }
        )
