"""Creado con Claude.

Bases de las pantallas (§17): contexto compartido, indicador de cambios sin guardar, errores
junto a cada campo y la pantalla genérica «lista + formulario».
"""

import sqlite3
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from timetabling.gui.dialogos import Dialogos, Respuesta
from timetabling.gui.errores import GENERAL, traducir
from timetabling.gui.widgets.campos import DiasSelector, ListaMarcable, TablaFilas
from timetabling.persistencia.repositorio import ErrorProfesorEnUso
from timetabling.servicios.sesion import SesionProyecto

ESTILO_ERROR = "color: #B00020;"


class Contexto(QObject):
    """Lo que comparten las pantallas: la sesión abierta, los diálogos y la navegación."""

    sesion_cambiada = Signal()
    navegar = Signal(str, str, object)  # pantalla, entidad, id
    solo_lectura_cambiada = Signal(bool)

    def __init__(self, dialogos: Dialogos) -> None:
        super().__init__()
        self.dialogos = dialogos
        self.sesion: SesionProyecto | None = None
        self.solo_lectura = False

    def poner_sesion(self, sesion: SesionProyecto | None) -> None:
        self.sesion = sesion
        if sesion is not None:
            sesion.suscribir(self.sesion_cambiada.emit)
        self.sesion_cambiada.emit()

    def poner_solo_lectura(self, solo_lectura: bool) -> None:
        """Mientras se resuelve, las pantallas de captura no se pueden editar (sí navegar)."""
        self.solo_lectura = solo_lectura
        self.solo_lectura_cambiada.emit(solo_lectura)

    def ir_a(self, pantalla: str, entidad: str = "", ident: object = None) -> None:
        self.navegar.emit(pantalla, entidad, ident)


class Pantalla(QWidget):
    """Una pantalla de la barra lateral."""

    clave = ""
    titulo = ""
    requiere_proyecto = True
    cambios = Signal(bool)

    def __init__(self, contexto: Contexto) -> None:
        super().__init__()
        self.contexto = contexto
        self._hay_cambios = False
        self._cargando = False
        self.setObjectName(f"pantalla_{self.clave}")

    @property
    def sesion(self) -> SesionProyecto:
        assert self.contexto.sesion is not None
        return self.contexto.sesion

    @property
    def dialogos(self) -> Dialogos:
        return self.contexto.dialogos

    # ------------------------------------------------------------------ cambios

    def hay_cambios(self) -> bool:
        return self._hay_cambios

    def marcar_cambio(self, *_args: object) -> None:
        if self._cargando or self._hay_cambios:
            return
        self._hay_cambios = True
        self.cambios.emit(True)

    def limpiar_cambios(self) -> None:
        if self._hay_cambios:
            self._hay_cambios = False
            self.cambios.emit(False)

    def vigilar(self, *widgets: QWidget) -> None:
        """Conecta la señal de cambio de cada widget con `marcar_cambio`."""
        for w in widgets:
            if isinstance(w, (DiasSelector, ListaMarcable, TablaFilas)):
                w.cambiado.connect(self.marcar_cambio)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self.marcar_cambio)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.valueChanged.connect(self.marcar_cambio)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.marcar_cambio)
            elif isinstance(w, QTimeEdit):
                w.timeChanged.connect(self.marcar_cambio)
            elif isinstance(w, QAbstractButton):
                w.toggled.connect(self.marcar_cambio)

    def confirmar_salida(self) -> bool:
        """Antes de cambiar de pantalla o cerrar: «Guardar / Descartar / Cancelar»."""
        if not self.hay_cambios():
            return True
        respuesta = self.dialogos.guardar_descartar_cancelar(self.titulo)
        if respuesta is Respuesta.GUARDAR:
            return self.guardar()
        if respuesta is Respuesta.DESCARTAR:
            self.descartar()
            return True
        return False

    # ------------------------------------------------------------------ ciclo

    def al_mostrar(self) -> None:
        """Se llama al entrar en la pantalla; recarga si no hay cambios pendientes."""
        if not self.hay_cambios():
            self.recargar()

    def recargar(self) -> None:
        pass

    def guardar(self) -> bool:
        self.limpiar_cambios()
        return True

    def descartar(self) -> None:
        self.limpiar_cambios()
        self.recargar()

    def seleccionar(self, entidad: str, ident: object) -> None:
        """Destino de una navegación (por ejemplo, desde Validación)."""

    def poner_solo_lectura(self, solo_lectura: bool) -> None:
        self.setEnabled(not solo_lectura or not self.requiere_proyecto)
        self.setToolTip("Solo lectura mientras se genera el horario." if solo_lectura else "")


class Formulario(QWidget):
    """Formulario con una etiqueta de error junto a cada campo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.capa = QFormLayout(self)
        self.errores: dict[str, QLabel] = {}
        self.error_general = QLabel()
        self.error_general.setStyleSheet(ESTILO_ERROR)
        self.error_general.setWordWrap(True)
        self.error_general.hide()
        self.capa.addRow(self.error_general)

    def campo(self, clave: str, etiqueta: str, widget: QWidget) -> QWidget:
        contenedor = QWidget()
        capa = QVBoxLayout(contenedor)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(widget)
        error = QLabel()
        error.setStyleSheet(ESTILO_ERROR)
        error.setWordWrap(True)
        error.hide()
        error.setObjectName(f"error_{clave}")
        capa.addWidget(error)
        self.errores[clave] = error
        rotulo = QLabel(etiqueta)
        rotulo.setBuddy(widget)
        self.capa.addRow(rotulo, contenedor)
        widget.setAccessibleName(etiqueta.replace("&", ""))
        return widget

    def limpiar_errores(self) -> None:
        for etiqueta in [*self.errores.values(), self.error_general]:
            etiqueta.clear()
            etiqueta.hide()

    def mostrar_errores(self, errores: dict[str, str]) -> None:
        self.limpiar_errores()
        sueltos: list[str] = []
        for campo, mensaje in errores.items():
            etiqueta = self.errores.get(campo)
            if etiqueta is None or campo == GENERAL:
                sueltos.append(mensaje)
            else:
                etiqueta.setText(f"⚠ {mensaje}")
                etiqueta.show()
        if sueltos:
            self.error_general.setText("⚠ " + " ".join(sueltos))
            self.error_general.show()

    def texto_errores(self) -> str:
        return " ".join(e.text() for e in [self.error_general, *self.errores.values()] if e.text())


def guardar_con_errores(formulario: Formulario, accion: Callable[[], Any]) -> tuple[bool, Any]:
    """Ejecuta `accion`; si falla por validación o unicidad, muestra el error en el formulario."""
    formulario.limpiar_errores()
    try:
        return True, accion()
    except ValidationError as error:
        formulario.mostrar_errores(traducir(error))
    except sqlite3.IntegrityError as error:
        texto = str(error)
        if "UNIQUE" in texto:
            formulario.mostrar_errores({GENERAL: "Ya existe otro registro con ese nombre."})
        else:
            formulario.mostrar_errores({GENERAL: f"No se pudo guardar: {texto}"})
    except ValueError as error:
        formulario.mostrar_errores({GENERAL: str(error)})
    return False, None


class PantallaListaFormulario(Pantalla):
    """Lista de entidades a la izquierda y formulario a la derecha, con Guardar/Descartar."""

    tipo: type[BaseModel]
    nombre_singular = "elemento"
    texto_nuevo = ""
    """Texto del botón de alta; por defecto «Nuevo <nombre_singular>»."""

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.actual: Any = None
        capa = QVBoxLayout(self)
        titulo = QLabel(f"<h2>{self.titulo}</h2>")
        capa.addWidget(titulo)
        divisor = QSplitter()
        capa.addWidget(divisor, 1)

        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        self.lista = QListWidget()
        self.lista.setAccessibleName(f"Lista de {self.titulo.lower()}")
        self.lista.currentItemChanged.connect(self._al_elegir)
        capa_izq.addWidget(self.lista)
        botones = QHBoxLayout()
        self.boton_nuevo = QPushButton(self.texto_nuevo or f"Nuevo {self.nombre_singular}")
        self.boton_eliminar = QPushButton("Eliminar")
        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_eliminar.clicked.connect(self.eliminar)
        botones.addWidget(self.boton_nuevo)
        botones.addWidget(self.boton_eliminar)
        capa_izq.addLayout(botones)
        divisor.addWidget(izquierda)

        derecha = QWidget()
        capa_der = QVBoxLayout(derecha)
        capa_der.setContentsMargins(0, 0, 0, 0)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        self.formulario = Formulario()
        desplazable.setWidget(self.formulario)
        capa_der.addWidget(desplazable, 1)
        acciones = QHBoxLayout()
        acciones.addStretch()
        self.boton_descartar = QPushButton("Descartar")
        self.boton_guardar = QPushButton("&Guardar")
        self.boton_guardar.setDefault(True)
        self.boton_descartar.clicked.connect(self.descartar)
        self.boton_guardar.clicked.connect(self.guardar)
        acciones.addWidget(self.boton_descartar)
        acciones.addWidget(self.boton_guardar)
        capa_der.addLayout(acciones)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 3)

        self._cargando = True
        self.construir_formulario(self.formulario)
        self._cargando = False

    # ------------------------------------------------------------------ a implementar

    def entidades(self) -> list[Any]:
        raise NotImplementedError

    def texto(self, entidad: Any) -> str:
        return str(getattr(entidad, "nombre", entidad))

    def construir_formulario(self, formulario: Formulario) -> None:
        raise NotImplementedError

    def mostrar(self, entidad: Any) -> None:
        """Llena el formulario con la entidad (o con valores por defecto si es `None`)."""
        raise NotImplementedError

    def leer(self) -> BaseModel:
        """Construye la entidad desde el formulario (puede lanzar `ValidationError`)."""
        raise NotImplementedError

    def guardar_entidad(self, entidad: BaseModel) -> BaseModel:
        return self.sesion.guardar(entidad)

    def atenuado(self, entidad: Any) -> bool:
        return False

    # ------------------------------------------------------------------ comportamiento

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        ident = getattr(self.actual, "id", None)
        self._cargando = True
        self.lista.blockSignals(True)
        self.lista.clear()
        fila_actual = -1
        for i, entidad in enumerate(self.entidades()):
            item = QListWidgetItem(self.texto(entidad))
            item.setData(Qt.ItemDataRole.UserRole, entidad)
            if self.atenuado(entidad):
                item.setForeground(Qt.GlobalColor.gray)
            self.lista.addItem(item)
            if ident is not None and getattr(entidad, "id", None) == ident:
                fila_actual = i
        self.lista.blockSignals(False)
        if fila_actual < 0 and self.lista.count():
            fila_actual = 0
        self.lista.setCurrentRow(fila_actual)
        if fila_actual < 0:
            self._poner(None)
        self._cargando = False

    def _poner(self, entidad: Any) -> None:
        self._cargando = True
        self.actual = entidad
        self.formulario.limpiar_errores()
        self.mostrar(entidad)
        self.boton_eliminar.setEnabled(entidad is not None)
        self._cargando = False
        self.limpiar_cambios()

    def _al_elegir(self, actual: QListWidgetItem | None, anterior: QListWidgetItem | None) -> None:
        if self._cargando:
            if actual is not None:
                self._poner(actual.data(Qt.ItemDataRole.UserRole))
            return
        if self.hay_cambios() and anterior is not None:
            if not self.confirmar_salida():
                self.lista.blockSignals(True)
                self.lista.setCurrentItem(anterior)
                self.lista.blockSignals(False)
                return
        self._poner(actual.data(Qt.ItemDataRole.UserRole) if actual else None)

    def nuevo(self) -> None:
        if not self.confirmar_salida():
            return
        self.lista.blockSignals(True)
        self.lista.clearSelection()
        self.lista.setCurrentRow(-1)
        self.lista.blockSignals(False)
        self._poner(None)
        self.marcar_cambio()

    def guardar(self) -> bool:
        ok, guardada = guardar_con_errores(
            self.formulario, lambda: self.guardar_entidad(self.leer())
        )
        if ok:
            self.actual = guardada
            self.limpiar_cambios()
            self.recargar()
        return ok

    def descartar(self) -> None:
        self.limpiar_cambios()
        self._poner(self.actual)

    def eliminar(self) -> None:
        if self.actual is None or getattr(self.actual, "id", None) is None:
            return
        ident = self.actual.id
        nombre = self.texto(self.actual)
        try:
            afectados = self.sesion.afectados(self.tipo, ident)
        except ErrorProfesorEnUso as error:
            if self.dialogos.confirmar("No se puede eliminar", f"{error}\n\n¿Desactivarlo?"):
                self.sesion.activar_profesor(ident, False)
                self.recargar()
            return
        detalle = "\n".join(f"• {n} {que}" for que, n in afectados.items())
        if not self.dialogos.confirmar(
            "Eliminar", f"¿Eliminar «{nombre}»? Se afectará:\n{detalle}"
        ):
            return
        self.sesion.eliminar(self.tipo, ident)
        self.actual = None
        self.limpiar_cambios()
        self.recargar()

    def seleccionar(self, entidad: str, ident: object) -> None:
        for i in range(self.lista.count()):
            dato = self.lista.item(i).data(Qt.ItemDataRole.UserRole)
            if getattr(dato, "id", None) == ident:
                self.lista.setCurrentRow(i)
                return

    def elegir(self, texto: str) -> None:
        """Selecciona por texto visible (útil para el teclado y las pruebas)."""
        for i in range(self.lista.count()):
            if self.lista.item(i).text() == texto:
                self.lista.setCurrentRow(i)
                return
        raise KeyError(texto)
