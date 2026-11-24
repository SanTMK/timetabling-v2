"""Creado con Claude.

Pantalla Configuración (§17): datos generales, perfil y prioridades de los criterios (§9) y el
modo avanzado con pesos numéricos (oculto por defecto).
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import CRITERIOS, PERFILES, Configuracion, Criterios
from timetabling.gui.pantallas.base import Contexto, Formulario, Pantalla, guardar_con_errores
from timetabling.nucleo.objetivo import NOMBRES_CRITERIOS

PERFILES_TEXTO = {
    "equilibrado": "Equilibrado",
    "profesores": "Priorizar profesores",
    "alumnos": "Priorizar alumnos",
    "personalizado": "Personalizado",
}
PRIORIDADES_TEXTO = {
    "desactivado": "Desactivado",
    "baja": "Baja",
    "media": "Media",
    "alta": "Alta",
    "muy_alta": "Muy alta",
}


class PantallaConfiguracion(Pantalla):
    clave = "configuracion"
    titulo = "Configuración"

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        self.formulario = Formulario()
        desplazable.setWidget(self.formulario)
        capa.addWidget(desplazable, 1)
        f = self.formulario
        self.nombre = f.campo("nombre_escuela", "&Nombre de la escuela", QLineEdit())
        self.margen = f.campo("margen_traslado_min", "&Margen de traslado (min)", QSpinBox())
        self.margen.setRange(0, 120)
        self.descanso = f.campo("descanso_minimo_min", "&Descanso mínimo (min)", QSpinBox())
        self.descanso.setRange(0, 60)
        self.tiempo = f.campo("tiempo_limite_s", "&Tiempo límite (s)", QSpinBox())
        self.tiempo.setRange(1, 36000)
        self.hilos = f.campo("hilos", "&Hilos", QSpinBox())
        self.hilos.setRange(1, 64)
        self.respaldos = f.campo("respaldos_a_conservar", "&Respaldos a conservar", QSpinBox())
        self.respaldos.setRange(1, 999)
        self.perfil = f.campo("criterios", "&Perfil de prioridades", QComboBox())
        for clave, texto in PERFILES_TEXTO.items():
            self.perfil.addItem(texto, clave)
        self.prioridades: dict[str, QComboBox] = {}
        self.pesos: dict[str, QDoubleSpinBox] = {}
        for criterio in CRITERIOS:
            fila = QWidget()
            capa_fila = QHBoxLayout(fila)
            capa_fila.setContentsMargins(0, 0, 0, 0)
            combo = QComboBox()
            for clave, texto in PRIORIDADES_TEXTO.items():
                combo.addItem(texto, clave)
            combo.currentIndexChanged.connect(self._prioridad_cambiada)
            peso = QDoubleSpinBox()
            peso.setRange(0, 10000)
            peso.setDecimals(2)
            peso.setVisible(False)
            capa_fila.addWidget(combo)
            capa_fila.addWidget(peso)
            f.campo(f"criterio_{criterio}", f"{criterio} {NOMBRES_CRITERIOS[criterio]}", fila)
            combo.setAccessibleName(NOMBRES_CRITERIOS[criterio])
            self.prioridades[criterio] = combo
            self.pesos[criterio] = peso
            self.vigilar(combo, peso)
        self.avanzado = QCheckBox("Modo avanzado (pesos numéricos)")
        self.avanzado.toggled.connect(self._mostrar_pesos)
        f.capa.addRow(self.avanzado)
        self.perfil.currentIndexChanged.connect(self._perfil_cambiado)
        self.vigilar(
            self.nombre, self.margen, self.descanso, self.tiempo, self.hilos, self.respaldos,
            self.perfil, self.avanzado,
        )  # fmt: skip
        acciones = QHBoxLayout()
        acciones.addStretch()
        descartar = QPushButton("Descartar")
        descartar.clicked.connect(self.descartar)
        self.boton_guardar = QPushButton("&Guardar")
        self.boton_guardar.clicked.connect(self.guardar)
        acciones.addWidget(descartar)
        acciones.addWidget(self.boton_guardar)
        capa.addLayout(acciones)

    def _mostrar_pesos(self, visible: bool) -> None:
        for peso in self.pesos.values():
            peso.setVisible(visible)

    def _perfil_cambiado(self) -> None:
        perfil = self.perfil.currentData()
        if perfil in PERFILES and not self._cargando:
            self._cargando = True
            for criterio, prioridad in PERFILES[perfil].items():
                combo = self.prioridades[criterio]
                combo.setCurrentIndex(combo.findData(prioridad))
            self._cargando = False

    def _prioridad_cambiada(self) -> None:
        if self._cargando:
            return
        perfil = self.perfil.currentData()
        actuales = {c: self.prioridades[c].currentData() for c in CRITERIOS}
        if perfil in PERFILES and actuales != PERFILES[perfil]:
            self._cargando = True
            self.perfil.setCurrentIndex(self.perfil.findData("personalizado"))
            self._cargando = False

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        c = self.sesion.datos.configuracion
        self._cargando = True
        self.nombre.setText(c.nombre_escuela)
        self.margen.setValue(c.margen_traslado_min)
        self.descanso.setValue(c.descanso_minimo_min)
        self.tiempo.setValue(c.tiempo_limite_s)
        self.hilos.setValue(c.hilos)
        self.respaldos.setValue(c.respaldos_a_conservar)
        self.perfil.setCurrentIndex(self.perfil.findData(c.criterios.perfil))
        for criterio in CRITERIOS:
            combo = self.prioridades[criterio]
            combo.setCurrentIndex(combo.findData(c.criterios.prioridades[criterio]))
            self.pesos[criterio].setValue(c.criterios.pesos_avanzados.get(criterio, 0.0))
        self.avanzado.setChecked(c.criterios.modo_avanzado)
        self._cargando = False
        self.formulario.limpiar_errores()
        self.limpiar_cambios()

    def leer(self) -> Configuracion:
        criterios = Criterios(
            perfil=self.perfil.currentData(),
            prioridades={c: self.prioridades[c].currentData() for c in CRITERIOS},
            modo_avanzado=self.avanzado.isChecked(),
            pesos_avanzados=(
                {c: self.pesos[c].value() for c in CRITERIOS} if self.avanzado.isChecked() else {}
            ),
        )
        return Configuracion.model_validate(
            {
                "nombre_escuela": self.nombre.text(),
                "margen_traslado_min": self.margen.value(),
                "descanso_minimo_min": self.descanso.value(),
                "tiempo_limite_s": self.tiempo.value(),
                "hilos": self.hilos.value(),
                "respaldos_a_conservar": self.respaldos.value(),
                "criterios": criterios,
            }
        )

    def guardar(self) -> bool:
        ok, _ = guardar_con_errores(
            self.formulario, lambda: self.sesion.guardar_configuracion(self.leer())
        )
        if ok:
            self.limpiar_cambios()
        return ok
