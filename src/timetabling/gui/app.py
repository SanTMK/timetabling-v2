"""Creado con Claude.

Ventana principal (§17): barra lateral con las pantallas, menú Archivo, avisos no bloqueantes,
proyectos recientes, indicador de cambios sin guardar y tamaño y posición recordados.
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling import __version__
from timetabling.gui.dialogos import Dialogos
from timetabling.gui.pantallas.asignaturas import PantallaAsignaturas
from timetabling.gui.pantallas.base import Contexto, Pantalla
from timetabling.gui.pantallas.clases import PantallaClases
from timetabling.gui.pantallas.configuracion import PantallaConfiguracion
from timetabling.gui.pantallas.espacios import PantallaEspacios
from timetabling.gui.pantallas.generar import PantallaGenerar
from timetabling.gui.pantallas.grados import PantallaGrados
from timetabling.gui.pantallas.inicio import PantallaInicio
from timetabling.gui.pantallas.niveles import PantallaNiveles
from timetabling.gui.pantallas.plan import PantallaPlan
from timetabling.gui.pantallas.profesores import PantallaProfesores
from timetabling.gui.pantallas.resultados import PantallaResultados
from timetabling.gui.pantallas.validacion import PantallaValidacion
from timetabling.persistencia.migraciones import ErrorProyecto, ErrorProyectoAnterior
from timetabling.servicios.sesion import SesionProyecto

MAX_RECIENTES = 8
PANTALLAS: tuple[type[Pantalla], ...] = (
    PantallaInicio,
    PantallaConfiguracion,
    PantallaNiveles,
    PantallaGrados,
    PantallaAsignaturas,
    PantallaPlan,
    PantallaClases,
    PantallaProfesores,
    PantallaEspacios,
    PantallaValidacion,
    PantallaGenerar,
    PantallaResultados,
)


def ajustes() -> QSettings:
    """Preferencias de la aplicación. `TIMETABLING_CONFIG` permite usar otra carpeta (pruebas)."""
    carpeta = os.environ.get("TIMETABLING_CONFIG")
    if carpeta:
        return QSettings(str(Path(carpeta) / "timetabling.ini"), QSettings.Format.IniFormat)
    return QSettings("Timetabling", "timetabling-v2")


class VentanaPrincipal(QMainWindow):
    def __init__(
        self, dialogos: Dialogos | None = None, preferencias: QSettings | None = None
    ) -> None:
        super().__init__()
        self.dialogos = dialogos or Dialogos(self)
        self.preferencias = preferencias or ajustes()
        self.contexto = Contexto(self.dialogos)
        self.resize(1280, 800)

        central = QWidget()
        capa = QVBoxLayout(central)
        self.aviso = QWidget()
        capa_aviso = QHBoxLayout(self.aviso)
        self.texto_aviso = QLabel()
        self.texto_aviso.setWordWrap(True)
        cerrar_aviso = QPushButton("Entendido")
        cerrar_aviso.clicked.connect(self.aviso.hide)
        capa_aviso.addWidget(self.texto_aviso, 1)
        capa_aviso.addWidget(cerrar_aviso)
        self.aviso.setStyleSheet("background: #FFF4CE; color: #3D2E00;")
        self.aviso.hide()
        capa.addWidget(self.aviso)
        cuerpo = QHBoxLayout()
        self.barra = QListWidget()
        self.barra.setMaximumWidth(220)
        self.barra.setAccessibleName("Pantallas")
        self.pila = QStackedWidget()
        cuerpo.addWidget(self.barra)
        cuerpo.addWidget(self.pila, 1)
        capa.addLayout(cuerpo, 1)
        self.setCentralWidget(central)

        self.pantallas: dict[str, Pantalla] = {}
        for clase in PANTALLAS:
            pantalla = clase(self.contexto)
            self.pantallas[pantalla.clave] = pantalla
            self.pila.addWidget(pantalla)
            item = QListWidgetItem(pantalla.titulo)
            item.setData(Qt.ItemDataRole.UserRole, pantalla.clave)
            self.barra.addItem(item)
            pantalla.cambios.connect(self._actualizar_titulo)
        self._indice_actual = 0
        self.barra.currentRowChanged.connect(self._cambiar_pantalla)
        self.contexto.navegar.connect(self.ir_a)
        self.contexto.solo_lectura_cambiada.connect(self._solo_lectura)
        self.contexto.sesion_cambiada.connect(self._sesion_cambiada)
        inicio = self.pantallas["inicio"]
        assert isinstance(inicio, PantallaInicio)
        inicio.boton_nuevo.clicked.connect(lambda: self.nuevo_proyecto())
        inicio.boton_abrir.clicked.connect(lambda: self.abrir_proyecto())

        self._menu()
        self._restaurar_geometria()
        self.barra.setCurrentRow(0)
        self._sesion_cambiada()

    # ------------------------------------------------------------------ menú

    def _menu(self) -> None:
        archivo = self.menuBar().addMenu("&Archivo")
        acciones = [
            ("&Nuevo proyecto…", QKeySequence.StandardKey.New, self.nuevo_proyecto),
            ("&Abrir…", QKeySequence.StandardKey.Open, self.abrir_proyecto),
        ]
        for texto, atajo, funcion in acciones:
            accion = QAction(texto, self)
            accion.setShortcut(atajo)
            accion.triggered.connect(lambda _c=False, f=funcion: f())
            archivo.addAction(accion)
        self.accion_importar = QAction("&Importar proyecto anterior…", self)
        self.accion_importar.setEnabled(False)
        self.accion_importar.setToolTip("Disponible en una próxima versión (F11).")
        archivo.addAction(self.accion_importar)
        self.accion_guardar_como = QAction("&Guardar como…", self)
        self.accion_guardar_como.triggered.connect(lambda: self.guardar_como())
        archivo.addAction(self.accion_guardar_como)
        self.accion_restaurar = QAction("&Restaurar respaldo…", self)
        self.accion_restaurar.triggered.connect(self.restaurar_respaldo)
        archivo.addAction(self.accion_restaurar)
        self.menu_recientes = archivo.addMenu("Proyectos &recientes")
        archivo.addSeparator()
        salir = QAction("&Salir", self)
        salir.setShortcut(QKeySequence.StandardKey.Quit)
        salir.triggered.connect(self.close)
        archivo.addAction(salir)
        guardar = QAction("Guardar", self)
        guardar.setShortcut(QKeySequence.StandardKey.Save)
        guardar.triggered.connect(lambda: self.pantalla_actual().guardar())
        self.addAction(guardar)
        self._llenar_recientes()

    def recientes(self) -> list[str]:
        valor = self.preferencias.value("recientes", [])
        if isinstance(valor, str):
            return [valor]
        return [str(v) for v in (valor or [])]

    def _agregar_reciente(self, ruta: Path) -> None:
        lista = [str(ruta)] + [r for r in self.recientes() if r != str(ruta)]
        self.preferencias.setValue("recientes", lista[:MAX_RECIENTES])
        self._llenar_recientes()

    def _llenar_recientes(self) -> None:
        self.menu_recientes.clear()
        for ruta in self.recientes():
            accion = QAction(ruta, self)
            accion.triggered.connect(lambda _c=False, r=ruta: self.abrir_proyecto(Path(r)))
            self.menu_recientes.addAction(accion)
        self.menu_recientes.setEnabled(bool(self.recientes()))

    # ------------------------------------------------------------------ proyecto

    def _confirmar_cambios(self) -> bool:
        return all(p.confirmar_salida() for p in self.pantallas.values() if p.hay_cambios())

    def _poner_sesion(self, sesion: SesionProyecto | None) -> None:
        anterior = self.contexto.sesion
        if anterior is not None:
            anterior.cerrar()
        self.contexto.poner_sesion(sesion)
        if sesion is not None:
            self._agregar_reciente(sesion.ruta)
            if sesion.avisos:
                self.texto_aviso.setText("⚠ " + "\n".join(a.mensaje for a in sesion.avisos))
                self.aviso.show()
            else:
                self.aviso.hide()

    def _ocupado(self) -> bool:
        if self.generando:
            self.dialogos.informar("Generando", "Espere a que termine la generación o cancélela.")
            return True
        return False

    def nuevo_proyecto(self, ruta: Path | None = None) -> SesionProyecto | None:
        if self._ocupado() or not self._confirmar_cambios():
            return None
        ruta = ruta or self.dialogos.ruta_nueva()
        if ruta is None:
            return None
        try:
            sesion = SesionProyecto.nuevo(ruta)
        except (OSError, ErrorProyecto) as error:
            self.dialogos.error("Nuevo proyecto", str(error))
            return None
        self._poner_sesion(sesion)
        self.ir_a("configuracion")
        return sesion

    def abrir_proyecto(self, ruta: Path | None = None) -> SesionProyecto | None:
        if self._ocupado() or not self._confirmar_cambios():
            return None
        ruta = ruta or self.dialogos.ruta_existente()
        if ruta is None:
            return None
        try:
            sesion = SesionProyecto.abrir(ruta)
        except ErrorProyectoAnterior as error:
            self.dialogos.informar("Proyecto de la versión anterior", str(error))
            return None
        except (OSError, ErrorProyecto) as error:
            self.dialogos.error("Abrir proyecto", str(error))
            return None
        self._poner_sesion(sesion)
        self.ir_a("inicio")
        return sesion

    def guardar_como(self, ruta: Path | None = None) -> None:
        sesion = self.contexto.sesion
        if sesion is None or not self._confirmar_cambios():
            return
        ruta = ruta or self.dialogos.ruta_nueva("Guardar como")
        if ruta is None:
            return
        try:
            sesion.guardar_como(ruta)
        except (OSError, ErrorProyecto) as error:
            self.dialogos.error("Guardar como", str(error))
            return
        self._poner_sesion(SesionProyecto.abrir(ruta))

    def restaurar_respaldo(self) -> None:
        sesion = self.contexto.sesion
        if sesion is None or not self._confirmar_cambios():
            return
        respaldos = sesion.listar_respaldos()
        if not respaldos:
            self.dialogos.informar("Restaurar respaldo", "Este proyecto no tiene respaldos.")
            return
        elegido = self.dialogos.elegir_uno(
            "Restaurar respaldo",
            "Respaldo a restaurar (el estado actual se respalda antes):",
            [(r.ruta, f"{r.fecha:%d/%m/%Y %H:%M:%S}") for r in respaldos],
        )
        if elegido is not None and self.dialogos.confirmar(
            "Restaurar respaldo", "Se reemplazarán los datos actuales. ¿Continuar?"
        ):
            sesion.restaurar_respaldo(elegido)  # type: ignore[arg-type]

    def _sesion_cambiada(self) -> None:
        abierta = self.contexto.sesion is not None
        for i in range(self.barra.count()):
            clave = self.barra.item(i).data(Qt.ItemDataRole.UserRole)
            item = self.barra.item(i)
            habilitada = abierta or not self.pantallas[clave].requiere_proyecto
            flags = item.flags()
            item.setFlags(
                flags | Qt.ItemFlag.ItemIsEnabled
                if habilitada
                else flags & ~Qt.ItemFlag.ItemIsEnabled
            )
        self.accion_guardar_como.setEnabled(abierta)
        self.accion_restaurar.setEnabled(abierta)
        actual = self.pantalla_actual()
        if not actual.hay_cambios():
            actual.recargar()
        self._actualizar_titulo()

    # ------------------------------------------------------------------ navegación

    def pantalla_actual(self) -> Pantalla:
        widget = self.pila.currentWidget()
        assert isinstance(widget, Pantalla)
        return widget

    def _cambiar_pantalla(self, fila: int) -> None:
        if fila == self._indice_actual and self.pila.currentIndex() == fila:
            return
        actual = self.pantalla_actual()
        if not actual.confirmar_salida():
            self.barra.blockSignals(True)
            self.barra.setCurrentRow(self._indice_actual)
            self.barra.blockSignals(False)
            return
        self._indice_actual = fila
        self.pila.setCurrentIndex(fila)
        self.pantalla_actual().al_mostrar()
        self._actualizar_titulo()

    def ir_a(self, clave: str, entidad: str = "", ident: object = None) -> Pantalla:
        fila = list(self.pantallas).index(clave)
        self.barra.setCurrentRow(fila)
        pantalla = self.pantallas[clave]
        if self.pantalla_actual() is pantalla and entidad:
            pantalla.seleccionar(entidad, ident)
        return pantalla

    def _solo_lectura(self, solo_lectura: bool) -> None:
        for pantalla in self.pantallas.values():
            pantalla.poner_solo_lectura(solo_lectura)
        for accion in (self.accion_guardar_como, self.accion_restaurar):
            accion.setEnabled(not solo_lectura and self.contexto.sesion is not None)

    @property
    def generando(self) -> bool:
        generar = self.pantallas["generar"]
        assert isinstance(generar, PantallaGenerar)
        return generar.trabajando

    def _actualizar_titulo(self, *_args: object) -> None:
        sesion = self.contexto.sesion
        cambios = any(p.hay_cambios() for p in self.pantallas.values())
        nombre = sesion.ruta.name if sesion else "sin proyecto"
        self.setWindowTitle(f"Timetabling {__version__} — {nombre}{' •' if cambios else ''}")
        for i in range(self.barra.count()):
            item = self.barra.item(i)
            pantalla = self.pantallas[item.data(Qt.ItemDataRole.UserRole)]
            item.setText(pantalla.titulo + (" •" if pantalla.hay_cambios() else ""))

    # ------------------------------------------------------------------ cierre

    def _restaurar_geometria(self) -> None:
        geometria = self.preferencias.value("geometria")
        if geometria is not None:
            self.restoreGeometry(geometria)  # type: ignore[arg-type]

    def closeEvent(self, evento: QCloseEvent) -> None:  # noqa: N802 - API de Qt
        if not self._confirmar_cambios():
            evento.ignore()
            return
        generar = self.pantallas["generar"]
        assert isinstance(generar, PantallaGenerar)
        generar.detener_y_guardar()  # cancela, espera y guarda la mejor como CANCELADO
        self.preferencias.setValue("geometria", self.saveGeometry())
        self.preferencias.sync()
        if self.contexto.sesion is not None:
            self.contexto.sesion.cerrar()
            self.contexto.sesion = None
        evento.accept()


def ejecutar(ruta: Path | None = None) -> int:
    """Abre la interfaz (y el proyecto indicado, si lo hay)."""
    aplicacion = QApplication.instance() or QApplication(sys.argv)
    aplicacion.setApplicationName("Timetabling")
    aplicacion.setOrganizationName("Timetabling")
    ventana = VentanaPrincipal()
    ventana.show()
    if ruta is not None:
        ventana.abrir_proyecto(ruta)
    return aplicacion.exec()  # type: ignore[union-attr]
