"""Creado con Claude.

Conflictos (§11.2): cada motivo con su texto, y el tiempo por celda en el ejemplo mediano
(menos de 2 ms).
"""

import time

import pytest

from pruebas.escuelas import (
    ANA,
    BETO,
    CARO,
    FISICA,
    FISICA_A,
    FISICA_B,
    INGLES_A,
    MATE,
    MATE_A,
    MATE_B,
    escuela_minima,
    f,
)
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import (
    BloqueoGrupo,
    Clase,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Evento,
    Grado,
    Grupo,
    Nivel,
    RangoFranjas,
)
from timetabling.ejemplo import ejemplo_mediano
from timetabling.nucleo.conflictos import Conflictos, Motivo, excede_continuo, motivos
from timetabling.nucleo.resolver import OpcionesResolucion, resolver


def _motivos(
    datos: DatosEscuela,
    colocadas: list[Colocacion],
    clase: int,
    franja: str,
    profesor: int | None = None,
) -> list[Motivo]:
    conflictos = Conflictos(datos).cargar(colocadas)
    return conflictos.motivos(clase, conflictos.calendario.franjas[franja], profesor)


def _duros(lista: list[Motivo]) -> dict[str, str]:
    return {m.restriccion: m.texto for m in lista if m.es_dura}


def _blandos(lista: list[Motivo]) -> dict[str, str]:
    return {m.restriccion: m.texto for m in lista if not m.es_dura}


def test_celda_libre_sin_motivos() -> None:
    assert _motivos(escuela_minima(), [], MATE_A, f("L", 0)) == []


def test_d1_horas_completas() -> None:
    colocadas = [Colocacion(INGLES_A, f("L", 0), (CARO,))]
    texto = _duros(_motivos(escuela_minima(), colocadas, INGLES_A, f("M", 0)))["D1"]
    assert texto == "Inglés · 1°A ya tiene sus 1 horas colocadas."


def test_d2_grupo_ocupado() -> None:
    colocadas = [Colocacion(MATE_A, f("L", 0), (ANA,))]
    duros = _duros(_motivos(escuela_minima(), colocadas, INGLES_A, f("L", 0)))
    assert duros["D2"] == "1°A ya tiene Matemáticas · 1°A el lunes de 08:00–08:50."


def test_d3_profesor_ocupado() -> None:
    colocadas = [Colocacion(MATE_A, f("L", 0), (ANA,))]
    duros = _duros(_motivos(escuela_minima(), colocadas, MATE_B, f("L", 0), profesor=ANA))
    assert duros["D3"] == "Ana ya da 1°A de 08:00–08:50."


def test_d3_tiempo_de_traslado_entre_niveles() -> None:
    """Secundaria empieza a las 8:55; con margen de 10 min, Ana no llega desde 8:00–8:50."""
    datos = escuela_minima()
    datos.configuracion.margen_traslado_min = 10
    datos.niveles.append(
        Nivel(id=2, nombre="Secundaria", duracion_min=50, inicio_jornada=535, fin_jornada=700,
              dias=["L"])
    )  # fmt: skip
    datos.grados.append(Grado(id=2, nivel_id=2, nombre="7°"))
    datos.grupos.append(Grupo(id=3, grado_id=2, seccion="A"))
    datos.profesores[ANA - 1].grados.append(2)
    datos.clases.append(
        Clase(id=30, asignatura_id=MATE, destinatarios=[Destinatario(grupo_id=3)],
              horas_semanales=1)
    )  # fmt: skip
    colocadas = [Colocacion(MATE_A, f("L", 0), (ANA,))]
    duros = _duros(_motivos(datos, colocadas, 30, "2:L:0", profesor=ANA))
    assert duros["D3"] == "Ana ya da 1°A de 08:00–08:50 (sin tiempo de traslado)."
    datos.configuracion.margen_traslado_min = 0
    assert "D3" not in _duros(_motivos(datos, colocadas, 30, "2:L:0", profesor=ANA))


def test_d4_no_habilitado() -> None:
    duros = _duros(_motivos(escuela_minima(), [], FISICA_A, f("L", 2), profesor=BETO))
    assert duros["D4"] == "Beto no está habilitado o activo para Ed. Física · 1°A."


def test_d5_no_disponible_y_b4_preferible_no() -> None:
    datos = escuela_minima()
    datos.profesores[ANA - 1].disponibilidad = [
        Disponibilidad(dia="L", inicio=480, fin=530, tipo="no_disponible"),
        Disponibilidad(dia="L", inicio=600, fin=610, tipo="preferible_no"),
    ]
    assert _duros(_motivos(datos, [], MATE_A, f("L", 0), ANA))["D5"] == (
        "Ana no está disponible de 08:00–08:50."
    )
    motivos_b4 = _motivos(datos, [], MATE_A, f("L", 2), ANA)
    assert _duros(motivos_b4) == {}
    assert _blandos(motivos_b4)["B4"] == "Ana prefiere no dar clase de 10:00–10:10."


def test_d6_ya_la_imparte_otro() -> None:
    colocadas = [Colocacion(MATE_A, f("L", 0), (BETO,))]
    duros = _duros(_motivos(escuela_minima(), colocadas, MATE_A, f("L", 1), profesor=ANA))
    assert duros["D6"] == "Matemáticas · 1°A ya la imparte Beto."
    # Sin profesor indicado, se usa el que ya la imparte.
    colocadas.append(Colocacion(MATE_B, f("L", 1), (BETO,)))
    assert (
        "Beto ya da 1°B" in _duros(_motivos(escuela_minima(), colocadas, MATE_A, f("L", 1)))["D3"]
    )


def test_d7_cargas() -> None:
    datos = escuela_minima()
    caro = datos.profesores[CARO - 1]
    caro.carga_max_semanal_min = 60
    caro.max_dias = 1
    colocadas = [Colocacion(FISICA_A, f("L", 2), (CARO,))]
    duros = [m.texto for m in _motivos(datos, colocadas, FISICA_B, f("M", 2)) if m.es_dura]
    assert "Caro pasaría de su carga máxima semanal (60 min)." in duros
    assert "Caro ya da clase 1 días (máximo 1)." in duros
    caro.carga_max_semanal_min = 2400
    caro.carga_max_diaria_min = 90
    caro.max_dias = None
    duros = [m.texto for m in _motivos(datos, colocadas, INGLES_A, f("L", 3), CARO) if m.es_dura]
    assert duros == ["Caro pasaría de su carga máxima diaria (90 min)."]


def test_d8_tiempo_continuo() -> None:
    datos = escuela_minima()
    datos.profesores[ANA - 1].max_minutos_continuos = 90
    colocadas = [Colocacion(MATE_A, f("L", 0), (ANA,))]
    assert _duros(_motivos(datos, colocadas, MATE_A, f("L", 1)))["D8"] == (
        "Ana pasaría de 90 min seguidos sin un descanso de 10 min."
    )
    assert excede_continuo([(0, 50), (50, 100)], 90, 10)
    assert not excede_continuo([(0, 50), (60, 110)], 90, 10)
    # La ventana que termina al final de un intervalo también cuenta.
    assert excede_continuo([(0, 40), (45, 100), (130, 150)], 90, 50)


def test_d9_espacio_ocupado() -> None:
    datos = escuela_minima()
    datos.profesores[ANA - 1].asignaturas.append(FISICA)
    colocadas = [Colocacion(FISICA_A, f("L", 2), (CARO,))]
    duros = _duros(_motivos(datos, colocadas, FISICA_B, f("L", 2), profesor=ANA))
    assert duros["D9"] == (
        "No hay espacio de tipo «cancha» libre el lunes de 10:00–10:50: lo usan Ed. Física · 1°A."
    )
    datos.espacios[0].cantidad = 2
    assert "D9" not in _duros(_motivos(datos, colocadas, FISICA_B, f("L", 2), profesor=ANA))


def test_d10_maximo_y_adyacencia() -> None:
    colocadas = [Colocacion(MATE_A, f("L", 0), (ANA,))]
    assert _duros(_motivos(escuela_minima(), colocadas, MATE_A, f("L", 2)))["D10"] == (
        "Las 2 h de Matemáticas de 1°A el lunes deben ir juntas."
    )
    assert "D10" not in _duros(_motivos(escuela_minima(), colocadas, MATE_A, f("L", 1)))
    colocadas = [Colocacion(FISICA_A, f("L", 2), (CARO,))]
    datos = escuela_minima()
    datos.clases.append(
        Clase(id=40, asignatura_id=FISICA, destinatarios=[Destinatario(grupo_id=1)],
              horas_semanales=1)
    )  # fmt: skip
    assert _duros(_motivos(datos, colocadas, 40, f("L", 3)))["D10"] == (
        "1°A ya tiene 1 h de Ed. Física el lunes (máximo 1)."
    )


def test_d14_evento_y_bloqueo() -> None:
    datos = escuela_minima()
    datos.niveles[0].eventos = [Evento(dia="L", inicio=480, fin=500)]
    datos.grupos[1].bloqueos = [BloqueoGrupo(dia="M", inicio=600, fin=650, nombre="Natación")]
    assert _duros(_motivos(datos, [], MATE_A, f("L", 0)))["D14"] == (
        "Primaria tiene «Hora cívica» el lunes de 08:00–08:50."
    )
    assert _duros(_motivos(datos, [], FISICA_B, f("M", 2)))["D14"] == (
        "1°B tiene «Natación» el martes de 10:00–10:50."
    )


def test_d15_y_b3() -> None:
    datos = escuela_minima()
    reglas = datos.asignaturas[MATE - 1].reglas_por_defecto
    reglas.franjas_prohibidas = [RangoFranjas(desde_indice=3, hasta_indice=3)]
    reglas.franjas_preferidas = [RangoFranjas(desde=480, hasta=580)]
    assert _duros(_motivos(datos, [], MATE_A, f("L", 3)))["D15"] == (
        "Matemáticas no puede ir el lunes de 10:50–11:40 (franja prohibida)."
    )
    assert _blandos(_motivos(datos, [], MATE_A, f("L", 2)))["B3"] == (
        "El lunes de 10:00–10:50 está fuera de las franjas preferidas de Matemáticas."
    )
    assert _motivos(datos, [], MATE_A, f("L", 1)) == []


def test_mejor_candidato() -> None:
    datos = escuela_minima()
    colocadas = [Colocacion(MATE_B, f("L", 0), (BETO,))]
    # Ana está libre: no hay motivos.
    assert _motivos(datos, colocadas, MATE_A, f("L", 0)) == []
    colocadas.append(Colocacion(INGLES_A, f("L", 0), (ANA,)))
    duros = _duros(_motivos(datos, colocadas, MATE_A, f("L", 0)))
    assert duros["D3"].startswith("Ningún profesor posible está libre: ")
    assert "Ana ya da 1°A" in duros["D3"] and "Beto ya da 1°B" in duros["D3"]


def test_quitar_libera_la_celda() -> None:
    datos = escuela_minima()
    conflictos = Conflictos(datos)
    colocacion = Colocacion(MATE_A, f("L", 0), (ANA,))
    conflictos.agregar(colocacion)
    franja = conflictos.calendario.franjas[f("L", 0)]
    assert _duros(conflictos.motivos(INGLES_A, franja))
    conflictos.quitar(colocacion)
    assert conflictos.motivos(INGLES_A, franja) == []


def test_atajo_motivos() -> None:
    datos = escuela_minima()
    conflictos = Conflictos(datos)
    franja = conflictos.calendario.franjas[f("L", 0)]
    assert motivos(datos, [Colocacion(MATE_A, f("L", 0), (ANA,))], INGLES_A, franja)


@pytest.fixture(scope="module")
def mediano_resuelto() -> tuple[DatosEscuela, list[Colocacion]]:
    datos = ejemplo_mediano()
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=60, hilos=8, optimizar=False))
    assert resultado.colocaciones
    return datos, resultado.colocaciones


def test_tiempo_por_celda_en_el_mediano(
    mediano_resuelto: tuple[DatosEscuela, list[Colocacion]],
) -> None:
    datos, colocaciones = mediano_resuelto
    conflictos = Conflictos(datos).cargar(colocaciones)
    celdas = [
        (clase.id or 0, franja)
        for clase in datos.clases[::4]
        for franja in conflictos.calendario.utiles_nivel[
            conflictos.info[clase.id or 0].nivel_id or 0
        ]
    ]
    inicio = time.perf_counter()
    for clase_id, franja in celdas:
        conflictos.motivos(clase_id, franja)
    promedio_ms = (time.perf_counter() - inicio) / len(celdas) * 1000
    assert len(celdas) > 1000
    assert promedio_ms < 2.0, f"{promedio_ms:.3f} ms por celda"
