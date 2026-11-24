"""Creado con Claude.

Utilidades para las pruebas de interfaz: diálogos con respuestas programadas y una ventana con
preferencias en una carpeta temporal.
"""

from collections import deque
from pathlib import Path
from typing import Any

from timetabling.gui.dialogos import Dialogos, Respuesta


class DialogosFalsos(Dialogos):
    """Responde con lo programado en `respuestas` (en orden) y registra lo que se mostró."""

    def __init__(self) -> None:
        super().__init__(None)
        self.respuestas: deque[Any] = deque()
        self.mostrados: list[tuple[str, str]] = []

    def responder(self, *valores: Any) -> None:
        self.respuestas.extend(valores)

    def _siguiente(self, defecto: Any) -> Any:
        return self.respuestas.popleft() if self.respuestas else defecto

    def guardar_descartar_cancelar(self, que: str) -> Respuesta:
        self.mostrados.append(("cambios", que))
        return self._siguiente(Respuesta.CANCELAR)

    def confirmar(self, titulo: str, texto: str) -> bool:
        self.mostrados.append((titulo, texto))
        return bool(self._siguiente(True))

    def informar(self, titulo: str, texto: str) -> None:
        self.mostrados.append((titulo, texto))

    def error(self, titulo: str, texto: str) -> None:
        self.mostrados.append((titulo, texto))

    def ruta_nueva(self, titulo: str = "Nuevo proyecto") -> Path | None:
        return self._siguiente(None)

    def ruta_existente(self, titulo: str = "Abrir proyecto") -> Path | None:
        return self._siguiente(None)

    def ruta_guardar(self, titulo: str, filtro: str, sufijo: str) -> Path | None:
        self.mostrados.append((titulo, filtro))
        return self._siguiente(None)

    def texto(self, titulo: str, etiqueta: str, valor: str = "") -> str | None:
        self.mostrados.append((titulo, etiqueta))
        return self._siguiente(valor)

    def elegir_uno(self, titulo: str, texto: str, opciones: list[tuple[object, str]]) -> object:
        self.mostrados.append((titulo, texto))
        return self._siguiente(opciones[0][0] if opciones else None)

    def elegir_varios(
        self,
        titulo: str,
        texto: str,
        opciones: list[tuple[object, str]],
        marcados: list[object],
        uno: bool = False,
    ) -> list[object] | None:
        self.mostrados.append((titulo, texto))
        valor = self._siguiente(marcados)
        if isinstance(valor, list) and valor and isinstance(valor[0], str):
            por_texto = {t: v for v, t in opciones}
            return [por_texto[t] for t in valor]
        return valor
