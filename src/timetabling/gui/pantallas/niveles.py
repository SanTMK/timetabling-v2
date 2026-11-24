"""Creado con Claude.

Pantalla Niveles (§17): datos del nivel, recesos, eventos, duraciones especiales, huecos de
alumnos, preferir titular y vista previa de franjas en vivo.
"""

from typing import Any

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)

from timetabling.dominio.modelos import Evento, Nivel, Receso
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.gui.pantallas.base import Contexto, Formulario, PantallaListaFormulario
from timetabling.gui.widgets.campos import Columna, DiasSelector, HoraEdit, TablaFilas
from timetabling.nucleo.franjas import generar_franjas_dia, tocada_por_evento

HUECOS = {"permitidos": "Permitidos", "penalizar": "Penalizar", "prohibidos": "Prohibidos"}


class PantallaNiveles(PantallaListaFormulario):
    clave = "niveles"
    titulo = "Niveles"
    tipo = Nivel
    nombre_singular = "nivel"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)

    def construir_formulario(self, formulario: Formulario) -> None:
        f = formulario
        self.nombre = f.campo("nombre", "&Nombre", QLineEdit())
        self.duracion = f.campo("duracion_min", "&Duración de la hora (min)", QSpinBox())
        self.duracion.setRange(1, 300)
        self.inicio = f.campo("inicio_jornada", "&Inicio de la jornada", HoraEdit(480))
        self.fin = f.campo("fin_jornada", "&Fin de la jornada", HoraEdit(840))
        self.dias = f.campo("dias", "Dí&as", DiasSelector())
        self.recesos = f.campo(
            "recesos",
            "&Recesos",
            TablaFilas(
                [
                    Columna("nombre", "Nombre", "texto", "Receso"),
                    Columna("inicio", "Inicio", "hora", 600),
                    Columna("fin", "Fin", "hora", 630),
                ]
            ),
        )
        self.eventos = f.campo(
            "eventos",
            "&Eventos",
            TablaFilas(
                [
                    Columna("nombre", "Nombre", "texto", "Hora cívica"),
                    Columna("dia", "Día", "dia", "L"),
                    Columna("inicio", "Inicio", "hora", 480),
                    Columna("fin", "Fin", "hora", 530),
                ]
            ),
        )
        self.especiales = f.campo(
            "duraciones_especiales",
            "Duraciones e&speciales",
            TablaFilas(
                [
                    Columna("hora", "Hora (1, 2…)", "entero", 1, minimo=1, maximo=30),
                    Columna("minutos", "Minutos", "entero", 50, minimo=1, maximo=300),
                ]
            ),
        )
        self.huecos = f.campo("huecos_alumnos", "&Huecos de alumnos", QComboBox())
        for clave, texto in HUECOS.items():
            self.huecos.addItem(texto, clave)
        self.titular = f.campo("preferir_titular", "Preferir &titular", QCheckBox())
        self.vista = QTableWidget()
        self.vista.setMinimumHeight(200)
        self.vista.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.aviso_vista = QLabel()
        f.capa.addRow(QLabel("<b>Vista previa de franjas</b>"))
        f.capa.addRow(self.aviso_vista)
        f.capa.addRow(self.vista)
        widgets = (
            self.nombre, self.duracion, self.inicio, self.fin, self.dias, self.recesos,
            self.eventos, self.especiales, self.huecos, self.titular,
        )  # fmt: skip
        self.vigilar(*widgets)
        for w in widgets:
            señal = getattr(w, "cambiado", None) or getattr(w, "textChanged", None)
            if señal is None:
                señal = (
                    getattr(w, "valueChanged", None)
                    or getattr(w, "timeChanged", None)
                    or getattr(w, "currentIndexChanged", None)
                    or w.toggled  # type: ignore[attr-defined]
                )
            señal.connect(self.actualizar_vista)

    def entidades(self) -> list[Any]:
        return list(self.sesion.datos.niveles)

    def mostrar(self, entidad: Nivel | None) -> None:
        n = entidad
        self.nombre.setText(n.nombre if n else "")
        self.duracion.setValue(n.duracion_min if n else 50)
        self.inicio.poner(n.inicio_jornada if n else 480)
        self.fin.poner(n.fin_jornada if n else 840)
        self.dias.poner(n.dias if n else ["L", "M", "X", "J", "V"])
        self.recesos.poner([r.model_dump() for r in n.recesos] if n else [])
        self.eventos.poner([e.model_dump() for e in n.eventos] if n else [])
        self.especiales.poner(
            [{"hora": i + 1, "minutos": m} for i, m in n.duraciones_especiales.items()] if n else []
        )
        self.huecos.setCurrentIndex(self.huecos.findData(n.huecos_alumnos if n else "penalizar"))
        self.titular.setChecked(n.preferir_titular if n else False)
        self.actualizar_vista()

    def leer(self) -> Nivel:
        return Nivel.model_validate(
            {
                "id": getattr(self.actual, "id", None),
                "nombre": self.nombre.text(),
                "duracion_min": self.duracion.value(),
                "inicio_jornada": self.inicio.minutos(),
                "fin_jornada": self.fin.minutos(),
                "dias": self.dias.dias(),
                "recesos": [Receso.model_validate(r) for r in self.recesos.filas()],
                "eventos": [Evento.model_validate(e) for e in self.eventos.filas()],
                "duraciones_especiales": {
                    int(d["hora"]) - 1: int(d["minutos"]) for d in self.especiales.filas()
                },
                "huecos_alumnos": self.huecos.currentData(),
                "preferir_titular": self.titular.isChecked(),
            }
        )

    def actualizar_vista(self) -> None:
        try:
            nivel = self.leer()
        except (ValidationError, ValueError) as error:
            self.vista.setRowCount(0)
            self.aviso_vista.setText(f"⚠ No se puede calcular: {str(error).splitlines()[0]}")
            return
        if nivel.id is None:
            nivel = nivel.model_copy(update={"id": 0})
        columnas = {d: generar_franjas_dia(nivel, d) for d in nivel.dias}
        filas = max((len(v) for v in columnas.values()), default=0)
        self.vista.setColumnCount(len(columnas))
        self.vista.setRowCount(filas)
        self.vista.setHorizontalHeaderLabels([NOMBRES_DIAS[d] for d in columnas])
        self.vista.setVerticalHeaderLabels([f"{i + 1}" for i in range(filas)])
        utiles = 0
        for j, franjas in enumerate(columnas.values()):
            for franja in franjas:
                evento = tocada_por_evento(franja, nivel)
                texto = texto_rango(franja.inicio, franja.fin)
                if franja.receso_antes:
                    texto = "⏸ " + texto
                if evento:
                    texto += " (evento)"
                else:
                    utiles += 1
                item = QTableWidgetItem(texto)
                if evento:
                    item.setForeground(self.palette().mid())
                self.vista.setItem(franja.indice, j, item)
        self.aviso_vista.setText(f"{utiles} franjas útiles a la semana. ⏸ = después de un receso.")
