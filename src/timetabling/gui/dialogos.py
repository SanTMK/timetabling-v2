"""Creado con Claude.

Diálogos de la interfaz reunidos en una clase intercambiable: las pruebas la sustituyen por
respuestas programadas, sin ventanas modales.
"""

from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

FILTRO = "Proyectos de horario (*.horario)"


class Respuesta(Enum):
    GUARDAR = "guardar"
    DESCARTAR = "descartar"
    CANCELAR = "cancelar"


class Dialogos:
    def __init__(self, padre: QWidget | None = None) -> None:
        self.padre = padre

    def guardar_descartar_cancelar(self, que: str) -> Respuesta:
        caja = QMessageBox(self.padre)
        caja.setIcon(QMessageBox.Icon.Warning)
        caja.setWindowTitle("Cambios sin guardar")
        caja.setText(f"Hay cambios sin guardar en {que}.")
        guardar = caja.addButton("Guardar", QMessageBox.ButtonRole.AcceptRole)
        descartar = caja.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caja.setDefaultButton(guardar)
        caja.exec()
        if caja.clickedButton() is guardar:
            return Respuesta.GUARDAR
        if caja.clickedButton() is descartar:
            return Respuesta.DESCARTAR
        return Respuesta.CANCELAR

    def confirmar(self, titulo: str, texto: str) -> bool:
        respuesta = QMessageBox.question(self.padre, titulo, texto)
        return respuesta == QMessageBox.StandardButton.Yes

    def informar(self, titulo: str, texto: str) -> None:
        QMessageBox.information(self.padre, titulo, texto)

    def error(self, titulo: str, texto: str) -> None:
        QMessageBox.warning(self.padre, titulo, texto)

    def ruta_nueva(self, titulo: str = "Nuevo proyecto") -> Path | None:
        ruta, _ = QFileDialog.getSaveFileName(self.padre, titulo, "", FILTRO)
        if not ruta:
            return None
        destino = Path(ruta)
        return destino if destino.suffix == ".horario" else destino.with_suffix(".horario")

    def ruta_existente(self, titulo: str = "Abrir proyecto") -> Path | None:
        ruta, _ = QFileDialog.getOpenFileName(self.padre, titulo, "", FILTRO)
        return Path(ruta) if ruta else None

    def ruta_guardar(self, titulo: str, filtro: str, sufijo: str) -> Path | None:
        ruta, _ = QFileDialog.getSaveFileName(self.padre, titulo, "", filtro)
        if not ruta:
            return None
        destino = Path(ruta)
        return destino if destino.suffix == sufijo else destino.with_suffix(sufijo)

    def texto(self, titulo: str, etiqueta: str, valor: str = "") -> str | None:
        texto, ok = QInputDialog.getText(self.padre, titulo, etiqueta, text=valor)
        return texto if ok else None

    def elegir_uno(self, titulo: str, texto: str, opciones: list[tuple[object, str]]) -> object:
        """Devuelve el valor elegido o `None`."""
        seleccion = self.elegir_varios(titulo, texto, opciones, [], uno=True)
        return seleccion[0] if seleccion else None

    def elegir_varios(
        self,
        titulo: str,
        texto: str,
        opciones: list[tuple[object, str]],
        marcados: list[object],
        uno: bool = False,
    ) -> list[object] | None:
        """Lista de opciones marcables. Devuelve los valores elegidos o `None` si se cancela."""
        dialogo = QDialog(self.padre)
        dialogo.setWindowTitle(titulo)
        capa = QVBoxLayout(dialogo)
        capa.addWidget(QLabel(texto))
        lista = QListWidget()
        for valor, etiqueta in opciones:
            item = QListWidgetItem(etiqueta)
            item.setData(Qt.ItemDataRole.UserRole, valor)
            if not uno:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if valor in marcados else Qt.CheckState.Unchecked
                )
            lista.addItem(item)
        if uno and lista.count():
            lista.setCurrentRow(0)
        capa.addWidget(lista)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(dialogo.accept)
        botones.rejected.connect(dialogo.reject)
        capa.addWidget(botones)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        if uno:
            actual = lista.currentItem()
            return [actual.data(Qt.ItemDataRole.UserRole)] if actual else None
        return [
            lista.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(lista.count())
            if lista.item(i).checkState() == Qt.CheckState.Checked
        ]
