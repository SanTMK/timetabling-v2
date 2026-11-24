"""Creado con Claude.

Pantalla Generar (§17): Generar horario · Reajustar vigente · Cancelar; fase, mejor penalización,
soluciones y tiempo; diagnóstico con enlaces si el problema es infactible. Mientras se resuelve,
las pantallas de captura quedan en solo lectura.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import EstadoSolucion
from timetabling.gui.pantallas.base import Contexto, Pantalla
from timetabling.gui.pantallas.validacion import DESTINOS
from timetabling.gui.trabajador import Ejecucion, Trabajador
from timetabling.nucleo.resolver import Progreso
from timetabling.servicios.generacion import ResultadoGeneracion, opciones_de

FASES = {
    "construyendo": "Construyendo el modelo…",
    "factibilidad": "Buscando una primera solución…",
    "optimizacion": "Mejorando el horario…",
    "diagnostico": "Buscando la causa del conflicto…",
}
DIAGNOSTICO_S = 30.0


class PantallaGenerar(Pantalla):
    clave = "generar"
    titulo = "Generar"
    termino = Signal(object)

    def __init__(self, contexto: Contexto) -> None:
        super().__init__(contexto)
        self.ejecucion: Ejecucion | None = None
        self.ultimo: ResultadoGeneracion | None = None
        self.solucion_guardada_id: int | None = None
        self._tiempo_limite = 1.0
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        self.estado_datos = QLabel()
        self.estado_datos.setWordWrap(True)
        capa.addWidget(self.estado_datos)
        self.fijas = QLabel()
        capa.addWidget(self.fijas)
        botones = QHBoxLayout()
        self.boton_generar = QPushButton("&Generar horario")
        self.boton_reajustar = QPushButton("&Reajustar vigente")
        self.boton_reajustar.setEnabled(False)
        self.boton_reajustar.setToolTip("Disponible en una próxima versión (F9).")
        self.boton_cancelar = QPushButton("&Cancelar")
        self.boton_cancelar.setEnabled(False)
        self.boton_generar.clicked.connect(self.generar)
        self.boton_cancelar.clicked.connect(self.cancelar)
        for b in (self.boton_generar, self.boton_reajustar, self.boton_cancelar):
            botones.addWidget(b)
        botones.addStretch()
        capa.addLayout(botones)

        datos = QGridLayout()
        self.fase = QLabel("—")
        self.mejor = QLabel("—")
        self.soluciones = QLabel("—")
        self.tiempo = QLabel("—")
        for i, (texto, etiqueta) in enumerate(
            (("Fase", self.fase), ("Mejor penalización", self.mejor),
             ("Soluciones", self.soluciones), ("Tiempo", self.tiempo))
        ):  # fmt: skip
            datos.addWidget(QLabel(f"<b>{texto}:</b>"), i, 0)
            datos.addWidget(etiqueta, i, 1)
            etiqueta.setAccessibleName(texto)
        capa.addLayout(datos)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        capa.addWidget(self.barra)

        self.resultado = QLabel()
        self.resultado.setWordWrap(True)
        capa.addWidget(self.resultado)
        self.enlaces = QWidget()
        self.capa_enlaces = QHBoxLayout(self.enlaces)
        self.capa_enlaces.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self.enlaces)
        self.boton_ver = QPushButton("Ver en &Resultados")
        self.boton_ver.hide()
        self.boton_ver.clicked.connect(
            lambda: self.contexto.ir_a("resultados", "solucion", self.solucion_guardada_id)
        )
        capa.addWidget(self.boton_ver)
        capa.addStretch()
        self._reloj = QTimer(self)
        self._reloj.setInterval(250)
        self._reloj.timeout.connect(self._avanzar_barra)
        self._transcurrido = 0.0
        self._en_curso = False

    # ------------------------------------------------------------------ estado

    @property
    def trabajando(self) -> bool:
        """Desde que se pulsa Generar hasta que se procesa el resultado."""
        return self._en_curso

    def recargar(self) -> None:
        if self.contexto.sesion is None:
            return
        errores = [p for p in self.sesion.problemas() if p.es_error]
        config = self.sesion.datos.configuracion
        if errores:
            self.estado_datos.setText(
                f"✖ Hay {len(errores)} errores de validación: corríjalos en Validación antes de "
                "generar."
            )
        else:
            self.estado_datos.setText(
                f"✔ Datos listos. Tiempo límite: {config.tiempo_limite_s} s · {config.hilos} hilos."
            )
        self.fijas.setText(self.sesion.origen_fijas())
        self.boton_generar.setEnabled(not errores and not self.trabajando)

    # ------------------------------------------------------------------ acciones

    def generar(self) -> None:
        if self.trabajando or self.contexto.sesion is None:
            return
        if any(p.es_error for p in self.sesion.problemas()):
            self.dialogos.informar("Generar", "Corrija los errores de validación antes de generar.")
            return
        datos = self.sesion.datos
        opciones = opciones_de(datos)
        self._tiempo_limite = opciones.tiempo_limite_s
        trabajador = Trabajador(datos, opciones, DIAGNOSTICO_S)
        trabajador.progreso.connect(self._al_progresar)
        trabajador.terminado.connect(self._al_terminar)
        trabajador.fallo.connect(self._al_fallar)
        self.ejecucion = Ejecucion(trabajador)
        self.ultimo = None
        self.solucion_guardada_id = None
        self._limpiar_enlaces()
        self.boton_ver.hide()
        self.resultado.setText("")
        self.fase.setText(FASES["construyendo"])
        self.mejor.setText("—")
        self.soluciones.setText("0")
        self._transcurrido = 0.0
        self.barra.setValue(0)
        self.boton_generar.setEnabled(False)
        self.boton_cancelar.setEnabled(True)
        self._en_curso = True
        self.contexto.poner_solo_lectura(True)
        self._reloj.start()
        self.ejecucion.iniciar()

    def cancelar(self) -> None:
        if self.ejecucion is not None:
            self.fase.setText("Cancelando…")
            self.ejecucion.trabajador.cancelar()

    def detener_y_guardar(self) -> None:
        """Al cerrar la ventana: cancela, espera y guarda la mejor solución como CANCELADO."""
        ejecucion = self.ejecucion
        if ejecucion is None or not self._en_curso:
            return
        ejecucion.cancelar_y_esperar()
        if ejecucion.trabajador.resultado is not None and self.ultimo is None:
            self._al_terminar(ejecucion.trabajador.resultado)

    # ------------------------------------------------------------------ señales

    def _avanzar_barra(self) -> None:
        self._transcurrido += self._reloj.interval() / 1000
        self.tiempo.setText(f"{self._transcurrido:.1f} s")
        self.barra.setValue(int(1000 * min(1.0, self._transcurrido / self._tiempo_limite)))

    def _al_progresar(self, progreso: Progreso) -> None:
        self.fase.setText(FASES.get(progreso.fase, progreso.fase))
        self.soluciones.setText(str(progreso.soluciones))
        self.tiempo.setText(f"{progreso.tiempo_s:.1f} s")
        self._transcurrido = progreso.tiempo_s
        if progreso.mejor_objetivo is not None:
            cota = f" (cota inferior {progreso.cota:.1f})" if progreso.cota is not None else ""
            self.mejor.setText(f"{progreso.mejor_objetivo:.1f}{cota}")

    def _terminar_ui(self) -> None:
        self._en_curso = False
        self._reloj.stop()
        self.boton_cancelar.setEnabled(False)
        self.contexto.poner_solo_lectura(False)
        self.recargar()

    def _al_terminar(self, resultado: ResultadoGeneracion) -> None:
        if self.ultimo is resultado:
            return
        self.ultimo = resultado
        r = resultado.resolucion
        self.fase.setText("Terminado")
        self.barra.setValue(1000)
        self.tiempo.setText(f"{r.tiempo_s:.1f} s")
        if resultado.solucion is not None and self.contexto.sesion is not None:
            if r.estado is EstadoSolucion.CANCELADO:
                resultado.solucion.estado = EstadoSolucion.CANCELADO
            guardada = self.sesion.guardar_solucion(resultado.solucion)
            self.solucion_guardada_id = guardada.id
            total = guardada.penalizaciones.get("total", 0.0)
            cota = " (cota superior)" if guardada.penalizaciones_son_cota else ""
            aviso = (
                f" ⚠ El verificador encontró {len(guardada.violaciones)} violaciones."
                if guardada.violaciones
                else ""
            )
            self.resultado.setText(
                f"✔ {guardada.estado.value}: guardado como «{guardada.nombre}». Penalización "
                f"total{cota}: {total:.1f}.{aviso}"
            )
            self.boton_ver.show()
        elif resultado.diagnostico is not None:
            self.resultado.setText(f"✖ Sin solución posible. {resultado.diagnostico.mensaje}")
            for enlace in resultado.diagnostico.enlaces:
                destino = DESTINOS.get(enlace.entidad)
                if destino is None:
                    continue
                boton = QPushButton(f"→ {enlace.texto}")
                boton.clicked.connect(
                    lambda _c=False, d=destino, e=enlace: self.contexto.ir_a(d, e.entidad, e.id)
                )
                self.capa_enlaces.addWidget(boton)
        else:
            self.resultado.setText(f"✖ {r.estado.value}: {r.mensaje or 'sin horario.'}")
        self._terminar_ui()
        self.termino.emit(resultado)

    def _al_fallar(self, mensaje: str) -> None:
        self.resultado.setText(f"✖ Error al generar: {mensaje}")
        self._terminar_ui()
        self.termino.emit(None)

    def _limpiar_enlaces(self) -> None:
        while self.capa_enlaces.count():
            item = self.capa_enlaces.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def poner_solo_lectura(self, solo_lectura: bool) -> None:
        """Esta pantalla sigue activa mientras se resuelve."""
