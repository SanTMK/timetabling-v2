"""Creado con Claude.

Reparación local (§12.4): «Colocar y reacomodar lo mínimo» da un resultado válido con el mínimo
de cambios (B9), amplía el vecindario si hace falta y tarda menos de 3 s en el ejemplo mediano;
«Sugerir lugar» ordena las celdas por penalización marginal.
"""

import time

import pytest

from pruebas.escuelas import (
    CARO,
    FISICA_A,
    INGLES_A,
    escuela_minima,
    f,
    horario_valido,
)
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.clases import grupos_de_clase
from timetabling.dominio.modelos import DatosEscuela, RangoFranjas
from timetabling.ejemplo import ejemplo_mediano
from timetabling.nucleo.conflictos import Conflictos
from timetabling.nucleo.objetivo import evaluar
from timetabling.nucleo.reparacion import colocar_y_reacomodar, sugerir_lugares
from timetabling.nucleo.resolver import OpcionesResolucion, resolver
from timetabling.nucleo.verificador import verificar


def test_mover_a_una_celda_ocupada_reacomoda_lo_minimo() -> None:
    """Inglés de 1°A pasa del martes a primera hora al lunes a la tercera, donde está
    Ed. Física: lo mínimo es mover Ed. Física (2 cambios de B9)."""
    datos = escuela_minima()
    base = horario_valido()
    origen = next(c for c in base if c.clase_id == INGLES_A)
    nueva = origen.en(f("L", 2))
    propuesta = colocar_y_reacomodar(datos, base, nueva, quitar=origen, hilos=2)
    assert propuesta.encontrada and not propuesta.ampliada
    assert nueva in propuesta.colocaciones
    assert verificar(datos, propuesta.colocaciones).valida
    cambios = evaluar(datos, propuesta.colocaciones, base=[c for c in base if c != origen])["B9"]
    assert cambios == 2  # solo Ed. Física de 1°A se mueve
    assert [c.clase_id for c in propuesta.cambios] == [INGLES_A, FISICA_A]
    assert propuesta.cambios[0].linea.startswith("Inglés · 1°A: Ma 08:00–08:50 (Caro) → Lu")
    assert (FISICA_A, f("L", 2)) not in {(c.clase_id, c.franja_id) for c in propuesta.colocaciones}
    assert (INGLES_A, f("L", 2)) in propuesta.cambiadas


def test_colocar_una_hora_pendiente() -> None:
    datos = escuela_minima()
    base = [c for c in horario_valido() if c.clase_id != INGLES_A]
    propuesta = colocar_y_reacomodar(datos, base, Colocacion(INGLES_A, f("L", 0), (CARO,)),
                                     hilos=2)  # fmt: skip
    assert propuesta.encontrada
    assert verificar(datos, propuesta.colocaciones).valida
    assert len(propuesta.colocaciones) == len(base) + 1


def test_las_bloqueadas_no_se_mueven() -> None:
    datos = escuela_minima()
    base = [
        Colocacion(c.clase_id, c.franja_id, c.profesores, bloqueada=c.clase_id == FISICA_A)
        for c in horario_valido()
    ]
    origen = next(c for c in base if c.clase_id == INGLES_A)
    propuesta = colocar_y_reacomodar(datos, base, origen.en(f("L", 2)), quitar=origen, hilos=2)
    assert not propuesta.encontrada
    assert "No se encontró" in propuesta.mensaje


def test_se_amplia_a_toda_la_semana(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si con el vecindario del día no hay solución, se amplía a la semana de esos grupos y
    profesores. Se fuerza un vecindario del día insuficiente (solo la clase movida)."""
    from timetabling.nucleo import reparacion

    monkeypatch.setattr(reparacion, "_vecindario_del_dia", lambda *a, **k: {INGLES_A})
    datos = escuela_minima()
    base = horario_valido()
    origen = next(c for c in base if c.clase_id == INGLES_A)
    propuesta = colocar_y_reacomodar(datos, base, origen.en(f("L", 2)), quitar=origen, hilos=2)
    assert propuesta.encontrada and propuesta.ampliada
    assert verificar(datos, propuesta.colocaciones).valida


def test_sugerir_lugar_ordena_por_penalizacion() -> None:
    datos = escuela_minima()
    datos.asignaturas[1].reglas_por_defecto.franjas_preferidas = [
        RangoFranjas(dias=("M",), desde_indice=3, hasta_indice=3)
    ]
    base = [c for c in horario_valido() if c.clase_id != INGLES_A]
    sugerencias = sugerir_lugares(datos, base, INGLES_A)
    assert len(sugerencias) == 3
    assert sugerencias[0].franja_id == f("M", 3)  # la única preferida
    assert sugerencias == sorted(sugerencias, key=lambda s: (s.penalizacion, s.franja_id))
    conflictos = Conflictos(datos).cargar(base)
    for sugerencia in sugerencias:
        franja = conflictos.calendario.franjas[sugerencia.franja_id]
        assert conflictos.estado(INGLES_A, franja)[0] != "invalida"


@pytest.fixture(scope="module")
def mediano() -> tuple[DatosEscuela, list[Colocacion]]:
    datos = ejemplo_mediano()
    base = resolver(datos, OpcionesResolucion(tiempo_limite_s=30, hilos=4, optimizar=False))
    assert base.colocaciones
    return datos, base.colocaciones


def test_mediano_en_menos_de_3_s(mediano: tuple[DatosEscuela, list[Colocacion]]) -> None:
    datos, base = mediano
    grupo = datos.grupos[20].id  # un grupo de secundaria
    del_grupo = [c for c in base if grupo in grupos_de_clase(datos.clases[c.clase_id - 1])]
    origen = del_grupo[0]
    ocupadas = {c.franja_id for c in del_grupo}
    destino = next(
        c.franja_id for c in del_grupo if c.dia != origen.dia and c.clase_id != origen.clase_id
        and c.franja_id not in {x.franja_id for x in base if x.clase_id == origen.clase_id}
    )  # fmt: skip
    assert destino in ocupadas
    inicio = time.monotonic()
    propuesta = colocar_y_reacomodar(datos, base, origen.en(destino), quitar=origen, hilos=4)
    transcurrido = time.monotonic() - inicio
    assert propuesta.encontrada
    assert transcurrido < 3.0, f"{transcurrido:.2f} s"
    assert verificar(datos, propuesta.colocaciones).valida
    assert origen.en(destino) in propuesta.colocaciones
    assert 1 <= len(propuesta.cambios) <= 10
