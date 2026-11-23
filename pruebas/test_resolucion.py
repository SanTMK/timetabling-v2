"""Creado con Claude.

Resolución de punta a punta (§11.1). En F3 cubre la etapa de factibilidad: los ejemplos
resuelven y verifican; el mediano encuentra una solución en menos de 60 s (marca `lento`).
F4 agrega la optimización.
"""

import threading
import time

import pytest

from pruebas.escuelas import ANA, CARO, INGLES_A, MATE_A, escuela_minima, f
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import AsignacionFija, EstadoSolucion
from timetabling.ejemplo import ejemplo_mediano, ejemplo_pequeno
from timetabling.nucleo.resolver import OpcionesResolucion, Progreso, Resolutor, resolver
from timetabling.nucleo.verificador import verificar


def test_escuela_minima() -> None:
    datos = escuela_minima()
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2))
    assert resultado.estado is EstadoSolucion.FACTIBLE
    assert len(resultado.colocaciones) == 7
    assert verificar(datos, resultado.colocaciones).valida


def test_ejemplo_pequeno() -> None:
    datos = ejemplo_pequeno()
    progresos: list[Progreso] = []
    resultado = Resolutor(
        datos, OpcionesResolucion(tiempo_limite_s=30, hilos=4), progresos.append
    ).resolver()
    assert resultado.estado is EstadoSolucion.FACTIBLE
    assert len(resultado.colocaciones) == sum(c.horas_semanales for c in datos.clases)
    assert verificar(datos, resultado.colocaciones).valida
    assert progresos[0].fase == "construyendo"
    assert any(p.fase == "factibilidad" and p.soluciones >= 1 for p in progresos)


@pytest.mark.lento
def test_ejemplo_mediano_en_menos_de_60_s() -> None:
    datos = ejemplo_mediano()
    inicio = time.monotonic()
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=60, hilos=4))
    assert time.monotonic() - inicio < 60
    assert resultado.estado is EstadoSolucion.FACTIBLE
    verificacion = verificar(datos, resultado.colocaciones)
    assert verificacion.valida, [v.mensaje for v in verificacion.violaciones[:5]]
    # La clase conjunta ocurre una sola vez por franja para ambos grupos; las partes de la
    # división coinciden.
    conjunta = next(c for c in datos.clases if len(c.destinatarios) == 2)
    assert sum(1 for c in resultado.colocaciones if c.clase_id == conjunta.id) == 2


def test_infactible() -> None:
    datos = escuela_minima()
    datos.clases[0].horas_semanales = 9  # más horas que franjas
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2))
    assert resultado.estado is EstadoSolucion.INFACTIBLE
    assert resultado.colocaciones == []


def test_respeta_asignaciones_fijas() -> None:
    datos = escuela_minima()
    datos.fijas = [AsignacionFija(id=1, clase_id=INGLES_A, profesor_id=ANA, dia="M",
                                  indice_franja=3)]  # fmt: skip
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2))
    assert Colocacion(INGLES_A, f("M", 3), (ANA,)) in resultado.colocaciones


def test_vecindario_fija_lo_demas() -> None:
    datos = escuela_minima()
    base = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2)).colocaciones
    resultado = resolver(
        datos,
        OpcionesResolucion(tiempo_limite_s=10, hilos=2, base=base, vecindario={INGLES_A}),
    )
    assert {c for c in resultado.colocaciones if c.clase_id != INGLES_A} == {
        c for c in base if c.clase_id != INGLES_A
    }
    assert verificar(datos, resultado.colocaciones).valida


def test_fijar_colocaciones_extra() -> None:
    datos = escuela_minima()
    fijada = Colocacion(INGLES_A, f("L", 3), (CARO,))
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2, fijar=[fijada]))
    assert fijada in resultado.colocaciones


def test_cancelar_antes_de_resolver() -> None:
    resolutor = Resolutor(escuela_minima(), OpcionesResolucion(tiempo_limite_s=10, hilos=2))
    resolutor.cancelar()
    assert resolutor.resolver().estado is EstadoSolucion.CANCELADO


def test_cancelar_desde_otro_hilo() -> None:
    """Cancelar durante la búsqueda devuelve el control pronto y marca el resultado como
    CANCELADO (si para entonces ya había terminado, el resultado se conserva)."""
    datos = ejemplo_mediano()
    resolutor = Resolutor(datos, OpcionesResolucion(tiempo_limite_s=120, hilos=2))
    temporizador = threading.Timer(0.5, resolutor.cancelar)
    temporizador.start()
    inicio = time.monotonic()
    resultado = resolutor.resolver()
    temporizador.cancel()
    assert time.monotonic() - inicio < 30
    if resultado.estado is not EstadoSolucion.FACTIBLE:
        assert resultado.estado is EstadoSolucion.CANCELADO
        assert resolutor.cancelado


def test_pista_de_base_se_acepta() -> None:
    datos = escuela_minima()
    base = [Colocacion(MATE_A, f("M", 2), (ANA,)), Colocacion(MATE_A, f("M", 3), (ANA,))]
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2, base=base))
    assert resultado.estado is EstadoSolucion.FACTIBLE
