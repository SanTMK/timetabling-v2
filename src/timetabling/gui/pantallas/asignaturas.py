"""Creado con Claude.

Pantalla Asignaturas (§17): color, espacio, reglas por defecto y pestañas por nivel para
sobrescribirlas; editor de franjas prohibidas y preferidas sobre la cuadrícula del nivel.
"""

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import Asignatura, ReglasAsignatura, ReglasAsignaturaNivel
from timetabling.dominio.tiempo import DIAS, Dia
from timetabling.gui.pantallas.base import Formulario, PantallaListaFormulario
from timetabling.gui.widgets.cuadricula_franjas import CuadriculaFranjas
from timetabling.nucleo.franjas import Franja

BLOQUE = {"no": "No", "preferido": "Preferido", "obligatorio": "Obligatorio"}


class EditorReglas(QWidget):
    """Máximo diario, bloque doble y cuadrícula de franjas."""

    def __init__(self, con_activar: bool = False) -> None:
        super().__init__()
        capa = QVBoxLayout(self)
        self.activar = QCheckBox("Usar reglas propias en este nivel")
        self.activar.setVisible(con_activar)
        self.activar.toggled.connect(self._activar)
        capa.addWidget(self.activar)
        self.cuerpo = QWidget()
        forma = QFormLayout(self.cuerpo)
        self.max_horas = QSpinBox()
        self.max_horas.setRange(1, 24)
        self.max_horas.setAccessibleName("Máximo de horas por día")
        forma.addRow("Máximo de horas por día", self.max_horas)
        self.bloque = QComboBox()
        for clave, texto in BLOQUE.items():
            self.bloque.addItem(texto, clave)
        self.bloque.setAccessibleName("Bloque doble")
        forma.addRow("Bloque doble", self.bloque)
        self.cuadricula = CuadriculaFranjas()
        forma.addRow(QLabel("Franjas — clic o espacio: 🚫 prohibida → ★ preferida → normal"))
        forma.addRow(self.cuadricula)
        capa.addWidget(self.cuerpo)
        self._activar(not con_activar)

    def _activar(self, activo: bool) -> None:
        self.cuerpo.setEnabled(activo)

    def poner(self, reglas: ReglasAsignatura) -> None:
        self.max_horas.setValue(reglas.max_horas_dia)
        self.bloque.setCurrentIndex(self.bloque.findData(reglas.bloque_doble))
        self.cuadricula.poner(reglas.franjas_prohibidas, reglas.franjas_preferidas)

    def leer(self) -> ReglasAsignatura:
        prohibidas, preferidas = self.cuadricula.rangos()
        return ReglasAsignatura(
            max_horas_dia=self.max_horas.value(),
            bloque_doble=self.bloque.currentData(),
            franjas_prohibidas=prohibidas,
            franjas_preferidas=preferidas,
        )


class PantallaAsignaturas(PantallaListaFormulario):
    clave = "asignaturas"
    titulo = "Asignaturas"
    tipo = Asignatura
    nombre_singular = "asignatura"
    texto_nuevo = "Nueva asignatura"

    def construir_formulario(self, formulario: Formulario) -> None:
        f = formulario
        self.nombre = f.campo("nombre", "&Nombre", QLineEdit())
        fila_color = QWidget()
        capa_color = QHBoxLayout(fila_color)
        capa_color.setContentsMargins(0, 0, 0, 0)
        self.color = QLineEdit("#9E9E9E")
        self.color.setAccessibleName("Color")
        self.boton_color = QPushButton("Elegir…")
        self.boton_color.clicked.connect(self._elegir_color)
        self.color.textChanged.connect(self._pintar_color)
        capa_color.addWidget(self.color)
        capa_color.addWidget(self.boton_color)
        f.campo("color", "&Color", fila_color)
        self.espacio = f.campo("espacio_requerido", "&Espacio requerido", QComboBox())
        self.espacio.setEditable(True)
        self.pestanas = QTabWidget()
        f.campo("reglas_por_defecto", "&Reglas", self.pestanas)
        self.reglas_defecto = EditorReglas()
        self.reglas_nivel: dict[int, EditorReglas] = {}
        self.vigilar(self.nombre, self.color, self.espacio)
        self._vigilar_reglas(self.reglas_defecto)

    def _vigilar_reglas(self, editor: EditorReglas) -> None:
        self.vigilar(editor.activar, editor.max_horas, editor.bloque)
        editor.cuadricula.cambiado.connect(self.marcar_cambio)

    def _elegir_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color.text()), self, "Color de la asignatura")
        if color.isValid():
            self.color.setText(color.name().upper())

    def _pintar_color(self, texto: str) -> None:
        color = QColor(texto)
        if color.isValid():
            texto_contraste = "#000000" if color.lightness() > 140 else "#FFFFFF"
            self.boton_color.setStyleSheet(
                f"background-color: {color.name()}; color: {texto_contraste};"
            )

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        self._preparar_pestanas()
        super().recargar()

    def _preparar_pestanas(self) -> None:
        datos = self.sesion.datos
        calendario = self.sesion.calendario
        self.pestanas.clear()
        # Por defecto: cuadrícula genérica de índices (vale para todos los niveles).
        horas = max((len(v) for v in calendario.franjas_nivel.values()), default=0)
        dias = [d for d in DIAS if any(d in n.dias for n in datos.niveles)] or list(DIAS[:5])
        genericas: dict[Dia, list[Franja]] = {
            d: [Franja(0, d, i, 0, 1) for i in range(horas)] for d in dias
        }
        self.reglas_defecto.cuadricula.configurar(genericas, etiquetas=False)
        self.pestanas.addTab(self.reglas_defecto, "Por defecto")
        for editor in self.reglas_nivel.values():
            editor.deleteLater()
        self.reglas_nivel = {}
        for nivel in datos.niveles:
            assert nivel.id is not None
            editor = EditorReglas(con_activar=True)
            por_dia: dict[Dia, list[Franja]] = {d: [] for d in nivel.dias}
            for franja in calendario.franjas_nivel.get(nivel.id, []):
                por_dia[franja.dia].append(franja)
            editor.cuadricula.configurar(por_dia)
            self._vigilar_reglas(editor)
            self.reglas_nivel[nivel.id] = editor
            self.pestanas.addTab(editor, nivel.nombre)
        self.espacio.blockSignals(True)
        self.espacio.clear()
        self.espacio.addItem("")
        for tipo in sorted({e.tipo for e in datos.espacios}):
            self.espacio.addItem(tipo)
        self.espacio.blockSignals(False)

    def entidades(self) -> list[Any]:
        return list(self.sesion.datos.asignaturas)

    def mostrar(self, entidad: Asignatura | None) -> None:
        a = entidad
        self.nombre.setText(a.nombre if a else "")
        self.color.setText(a.color if a else "#9E9E9E")
        self.espacio.setCurrentText(a.espacio_requerido or "" if a else "")
        defecto = a.reglas_por_defecto if a else ReglasAsignatura()
        self.reglas_defecto.poner(defecto)
        propias = {r.nivel_id: r for r in a.reglas_por_nivel} if a else {}
        for nivel_id, editor in self.reglas_nivel.items():
            editor.activar.setChecked(nivel_id in propias)
            editor.poner(a.reglas_efectivas(nivel_id) if a else defecto)

    def leer(self) -> Asignatura:
        por_nivel = []
        for nivel_id, editor in self.reglas_nivel.items():
            if editor.activar.isChecked():
                reglas = editor.leer()
                por_nivel.append(ReglasAsignaturaNivel(nivel_id=nivel_id, **reglas.model_dump()))
        return Asignatura.model_validate(
            {
                "id": getattr(self.actual, "id", None),
                "nombre": self.nombre.text(),
                "color": self.color.text(),
                "espacio_requerido": self.espacio.currentText() or None,
                "reglas_por_defecto": self.reglas_defecto.leer(),
                "reglas_por_nivel": por_nivel,
            }
        )
