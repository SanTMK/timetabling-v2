"""Creado con Claude.

Resolución en segundo plano (§17, Concurrencia): un `QThread` resuelve con una **copia** de los
datos para que la interfaz no se congele. La solución se guarda en el hilo de la interfaz, al
recibir la señal `terminado`.
"""

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal

from timetabling.dominio.modelos import DatosEscuela
from timetabling.nucleo.resolver import OpcionesResolucion, Progreso, Resolutor
from timetabling.servicios.generacion import ResultadoGeneracion, generar_en_memoria


class Trabajador(QObject):
    progreso = Signal(object)
    terminado = Signal(object)
    fallo = Signal(str)

    def __init__(
        self, datos: DatosEscuela, opciones: OpcionesResolucion, diagnostico_s: float = 30.0
    ) -> None:
        super().__init__()
        self.datos = datos.model_copy(deep=True)
        self.opciones = opciones
        self.diagnostico_s = diagnostico_s
        self.resolutor = Resolutor(self.datos, opciones, self._informar)
        self.resultado: ResultadoGeneracion | None = None
        self.error: str | None = None

    def _informar(self, progreso: Progreso) -> None:
        self.progreso.emit(progreso)

    def ejecutar(self) -> None:
        try:
            self.resultado = generar_en_memoria(
                self.datos, self.opciones, self._informar, self.resolutor, self.diagnostico_s
            )
        except Exception as error:  # noqa: BLE001 - se informa en la interfaz
            self.error = f"{type(error).__name__}: {error}"
            self.fallo.emit(self.error)
            return
        self.terminado.emit(self.resultado)

    def cancelar(self) -> None:
        self.resolutor.cancelar()


class Ejecucion:
    """Un trabajador corriendo en su propio hilo."""

    def __init__(self, trabajador: "Trabajador | TareaFondo") -> None:
        self.trabajador = trabajador
        self.hilo = QThread()
        trabajador.moveToThread(self.hilo)
        self.hilo.started.connect(trabajador.ejecutar)
        # Conexión directa: el hilo termina su ciclo aunque el hilo de la interfaz esté
        # bloqueado esperándolo (al cerrar la ventana); en cola sería un interbloqueo.
        trabajador.terminado.connect(self.hilo.quit, Qt.ConnectionType.DirectConnection)
        trabajador.fallo.connect(self.hilo.quit, Qt.ConnectionType.DirectConnection)

    def iniciar(self) -> None:
        self.hilo.start()

    @property
    def activa(self) -> bool:
        return self.hilo.isRunning()

    def cancelar_y_esperar(self, milisegundos: int = 60_000) -> bool:
        self.trabajador.cancelar()
        return self.hilo.wait(milisegundos)


class TareaFondo(QObject):
    """Ejecuta una función cualquiera en segundo plano (completar, reacomodar)."""

    terminado = Signal(object)
    fallo = Signal(str)

    def __init__(self, funcion: Callable[[], object], al_cancelar: Callable[[], None] | None = None
                 ) -> None:  # fmt: skip
        super().__init__()
        self.funcion = funcion
        self.al_cancelar = al_cancelar
        self.resultado: object = None

    def ejecutar(self) -> None:
        try:
            self.resultado = self.funcion()
        except Exception as error:  # noqa: BLE001 - se informa en la interfaz
            self.fallo.emit(f"{type(error).__name__}: {error}")
            return
        self.terminado.emit(self.resultado)

    def cancelar(self) -> None:
        if self.al_cancelar is not None:
            self.al_cancelar()
