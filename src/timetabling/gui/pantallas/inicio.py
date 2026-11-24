"""Creado con Claude.

Pantalla Inicio (§17): sin proyecto, accesos para crear o abrir uno; con proyecto, la lista de
verificación con enlaces, el horario vigente y accesos rápidos.
"""

from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from timetabling.gui.pantallas.base import Contexto, Pantalla


class PantallaInicio(Pantalla):
    clave = "inicio"
    titulo = "Inicio"
    requiere_proyecto = False

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.capa = QVBoxLayout(self)
        self.encabezado = QLabel()
        self.capa.addWidget(self.encabezado)
        self.sin_proyecto = QWidget()
        capa_sin = QVBoxLayout(self.sin_proyecto)
        capa_sin.addWidget(QLabel("Cree un proyecto nuevo o abra uno existente."))
        self.boton_nuevo = QPushButton("&Nuevo proyecto…")
        self.boton_abrir = QPushButton("&Abrir proyecto…")
        capa_sin.addWidget(self.boton_nuevo)
        capa_sin.addWidget(self.boton_abrir)
        capa_sin.addStretch()
        self.capa.addWidget(self.sin_proyecto)
        self.con_proyecto = QWidget()
        self.rejilla = QGridLayout(self.con_proyecto)
        self.capa.addWidget(self.con_proyecto)
        self.vigente = QLabel()
        self.capa.addWidget(self.vigente)
        self.capa.addStretch()
        self.botones_puntos: dict[str, QPushButton] = {}

    def recargar(self) -> None:
        sesion = self.contexto.sesion
        self.sin_proyecto.setVisible(sesion is None)
        self.con_proyecto.setVisible(sesion is not None)
        self.vigente.setVisible(sesion is not None)
        if sesion is None:
            self.encabezado.setText("<h2>Timetabling escolar</h2>")
            return
        self.encabezado.setText(
            f"<h2>{sesion.datos.configuracion.nombre_escuela}</h2><p>{sesion.ruta}</p>"
        )
        while self.rejilla.count():
            item = self.rejilla.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.botones_puntos = {}
        for i, punto in enumerate(sesion.puntos_de_control()):
            marca = QLabel("✔" if punto.ok else "✖")
            marca.setStyleSheet("color: #1B5E20;" if punto.ok else "color: #B00020;")
            marca.setAccessibleName("Listo" if punto.ok else "Pendiente")
            self.rejilla.addWidget(marca, i, 0)
            self.rejilla.addWidget(QLabel(punto.texto), i, 1)
            ir = QPushButton("Ir")
            ir.setAccessibleName(f"Ir a {punto.texto}")
            ir.clicked.connect(lambda _c=False, destino=punto.pantalla: self.contexto.ir_a(destino))
            self.rejilla.addWidget(ir, i, 2)
            self.botones_puntos[punto.clave] = ir
        vigente = sesion.vigente()
        self.vigente.setText(
            f"Horario vigente: <b>{vigente.nombre}</b> ({vigente.fecha:%d/%m/%Y})"
            if vigente
            else "Todavía no hay un horario vigente."
        )

    def puntos(self) -> dict[str, bool]:
        """`clave → ok` de la lista de verificación (para pruebas y accesibilidad)."""
        sesion = self.contexto.sesion
        return {p.clave: p.ok for p in sesion.puntos_de_control()} if sesion else {}
