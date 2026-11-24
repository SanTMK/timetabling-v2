"""Creado con Claude.

Pantalla Espacios (§17): espacios especiales con su tipo y cantidad.
"""

from typing import Any

from PySide6.QtWidgets import QLineEdit, QSpinBox

from timetabling.dominio.modelos import Espacio
from timetabling.gui.pantallas.base import Formulario, PantallaListaFormulario


class PantallaEspacios(PantallaListaFormulario):
    clave = "espacios"
    titulo = "Espacios"
    tipo = Espacio
    nombre_singular = "espacio"

    def construir_formulario(self, formulario: Formulario) -> None:
        self.nombre = formulario.campo("nombre", "&Nombre", QLineEdit())
        self.tipo_espacio = formulario.campo("tipo", "&Tipo", QLineEdit())
        self.tipo_espacio.setPlaceholderText("laboratorio, taller, cancha…")
        self.cantidad = formulario.campo("cantidad", "&Cantidad", QSpinBox())
        self.cantidad.setRange(0, 99)
        self.vigilar(self.nombre, self.tipo_espacio, self.cantidad)

    def entidades(self) -> list[Any]:
        return list(self.sesion.datos.espacios)

    def texto(self, entidad: Espacio) -> str:
        return f"{entidad.nombre} ({entidad.tipo} × {entidad.cantidad})"

    def mostrar(self, entidad: Espacio | None) -> None:
        self.nombre.setText(entidad.nombre if entidad else "")
        self.tipo_espacio.setText(entidad.tipo if entidad else "")
        self.cantidad.setValue(entidad.cantidad if entidad else 1)

    def leer(self) -> Espacio:
        return Espacio.model_validate(
            {
                "id": getattr(self.actual, "id", None),
                "nombre": self.nombre.text(),
                "tipo": self.tipo_espacio.text(),
                "cantidad": self.cantidad.value(),
            }
        )
