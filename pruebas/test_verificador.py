"""Creado con Claude.

Verificador (§11.2): horarios hechos a mano que violan cada restricción D1–D16, referencias y
modo parcial. Usa la escuela mínima de `escuelas.py`.
"""

from collections.abc import Callable

import pytest

from pruebas.escuelas import (
    ANA,
    BETO,
    CARO,
    FISICA,
    FISICA_A,
    FISICA_B,
    INGLES,
    INGLES_A,
    MATE,
    MATE_A,
    MATE_B,
    escuela_minima,
    f,
    horario_valido,
)
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import (
    AsignacionFija,
    BloqueoGrupo,
    Clase,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Division,
    Evento,
    EventoProfesor,
    RangoFranjas,
    ReglasAsignatura,
)
from timetabling.nucleo.verificador import ResultadoVerificacion, minutos_disponibles, verificar

Cambio = Callable[[DatosEscuela, list[Colocacion]], None]


def _verificar(cambio: Cambio | None = None, parcial: bool = False) -> ResultadoVerificacion:
    datos = escuela_minima()
    horario = horario_valido()
    if cambio:
        cambio(datos, horario)
    return verificar(datos, horario, parcial=parcial)


def _codigos(resultado: ResultadoVerificacion) -> set[str]:
    return {v.restriccion for v in resultado.violaciones}


def _mensajes(resultado: ResultadoVerificacion) -> str:
    return "\n".join(v.mensaje for v in resultado.violaciones)


def _reemplazar(horario: list[Colocacion], viejo: Colocacion, nuevo: Colocacion) -> None:
    horario[horario.index(viejo)] = nuevo


def test_horario_valido() -> None:
    resultado = _verificar()
    assert resultado.valida, _mensajes(resultado)
    assert resultado.pendientes == {}


# ---------------------------------------------------------------------------
# D1 y modo parcial
# ---------------------------------------------------------------------------


def test_d1_faltan_horas() -> None:
    resultado = _verificar(lambda d, h: h.pop(0))
    assert _codigos(resultado) == {"D1"}
    assert "Matemáticas · 1°A tiene 1 de 2 horas" in _mensajes(resultado)


def test_d1_parcial_son_pendientes() -> None:
    resultado = _verificar(lambda d, h: h.pop(0), parcial=True)
    assert resultado.valida
    assert resultado.pendientes == {MATE_A: 1}


def test_d1_horas_de_mas() -> None:
    resultado = _verificar(lambda d, h: h.append(Colocacion(INGLES_A, f("L", 3), (CARO,))))
    assert _codigos(resultado) == {"D1"}
    assert "ya tiene sus 1 horas colocadas" in _mensajes(resultado)


def test_parcial_no_revisa_carga_minima_ni_huecos() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.profesores[0].carga_min_semanal_min = 1000
        h.pop(0)

    assert _codigos(_verificar(cambio)) == {"D1", "D7"}
    assert _verificar(cambio, parcial=True).valida


# ---------------------------------------------------------------------------
# D2–D10
# ---------------------------------------------------------------------------


def test_d2_grupo_en_dos_clases() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(INGLES_A, f("M", 0), (CARO,)),
                    Colocacion(INGLES_A, f("L", 1), (CARO,)))  # fmt: skip

    resultado = _verificar(cambio)
    assert "D2" in _codigos(resultado)
    assert "1°A ya tiene Matemáticas · 1°A el lunes de 08:50–09:40" in _mensajes(resultado)


def _con_division(simultanea: bool = True) -> Cambio:
    """Inglés de 1°A se divide en Básico (Ana) y Avanzado (Caro), 1 h cada parte."""

    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.divisiones.append(Division(id=1, grupo_id=1, partes=["Básico", "Avanzado"],
                                     simultanea=simultanea))  # fmt: skip
        ingles = next(c for c in d.clases if c.id == INGLES_A)
        ingles.destinatarios = [Destinatario(grupo_id=1, division_id=1, parte="Básico")]
        ingles.profesores = [ANA]
        d.clases.append(
            Clase(id=20, asignatura_id=INGLES, profesores=[CARO], horas_semanales=1,
                  destinatarios=[Destinatario(grupo_id=1, division_id=1, parte="Avanzado")])
        )  # fmt: skip
        _reemplazar(h, Colocacion(INGLES_A, f("M", 0), (CARO,)),
                    Colocacion(INGLES_A, f("M", 1), (ANA,)))  # fmt: skip
        h.append(Colocacion(20, f("M", 1), (CARO,)))

    return cambio


def test_d2_partes_de_division_simultanea_pueden_coincidir() -> None:
    resultado = _verificar(_con_division())
    assert resultado.valida, _mensajes(resultado)


def test_d2_division_no_simultanea_no_coincide() -> None:
    assert "D2" in _codigos(_verificar(_con_division(simultanea=False)))


def test_d2_misma_parte_no_coincide() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _con_division()(d, h)
        otra = next(c for c in d.clases if c.id == 20)
        otra.destinatarios = [Destinatario(grupo_id=1, division_id=1, parte="Básico")]

    resultado = _verificar(cambio)
    assert "D2" in _codigos(resultado)
    assert "1°A (Básico) ya tiene" in _mensajes(resultado)


def test_d3_profesor_en_dos_lugares() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(MATE_B, f("L", 0), (BETO,)),
                    Colocacion(MATE_B, f("L", 0), (ANA,)))  # fmt: skip
        _reemplazar(h, Colocacion(MATE_B, f("M", 0), (BETO,)),
                    Colocacion(MATE_B, f("M", 1), (ANA,)))  # fmt: skip

    resultado = _verificar(cambio)
    assert "D3" in _codigos(resultado)
    assert "Ana ya da 1°A de 08:00–08:50" in _mensajes(resultado) or "Ana ya da 1°B" in _mensajes(
        resultado
    )


def test_d4_profesor_no_habilitado() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(FISICA_A, f("L", 2), (CARO,)),
                    Colocacion(FISICA_A, f("L", 2), (BETO,)))  # fmt: skip

    resultado = _verificar(cambio)
    assert "D4" in _codigos(resultado)
    assert "Beto no está habilitado o activo para Ed. Física · 1°A" in _mensajes(resultado)


def test_d4_profesor_inactivo() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.profesores[BETO - 1].activo = False

    assert "D4" in _codigos(_verificar(cambio))


def test_d5_minuto_a_minuto() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        ana = d.profesores[ANA - 1]
        ana.disponible_toda_la_jornada = False
        ana.disponibilidad = [Disponibilidad(dia="L", inicio=480, fin=569)]

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D5"}
    assert "Ana no está disponible el lunes a las 09:29" in _mensajes(resultado)


def test_d5_evento_del_profesor() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.profesores[BETO - 1].eventos = [EventoProfesor(nombre="Junta", dia="M", inicio=490,
                                                         fin=500)]  # fmt: skip

    assert _codigos(_verificar(cambio)) == {"D5"}


def test_minutos_disponibles() -> None:
    datos = escuela_minima()
    ana = datos.profesores[0]
    ana.disponibilidad = [Disponibilidad(dia="L", inicio=500, fin=510, tipo="no_disponible")]
    libres = minutos_disponibles(ana, "L", 480, 530)
    assert len(libres) == 40 and 505 not in libres


def test_d6_continuidad() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(MATE_B, f("M", 0), (BETO,)),
                    Colocacion(MATE_B, f("M", 0), (ANA,)))  # fmt: skip

    resultado = _verificar(cambio)
    assert "D6" in _codigos(resultado)
    assert "Matemáticas · 1°B ya la imparte Beto" in _mensajes(resultado)


def test_d6_profesores_fijos_y_uno_solo() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        next(c for c in d.clases if c.id == MATE_A).profesores = [ANA, BETO]

    resultado = _verificar(cambio)
    assert "debe impartirse por todos sus profesores fijos" in _mensajes(resultado)

    def dos(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(INGLES_A, f("M", 0), (CARO,)),
                    Colocacion(INGLES_A, f("M", 0), (CARO, ANA)))  # fmt: skip

    assert "debe tener un solo profesor" in _mensajes(_verificar(dos))


@pytest.mark.parametrize(
    ("campo", "valor", "texto"),
    [
        ("carga_max_semanal_min", 120, "carga máxima semanal (120 min)"),
        ("carga_max_diaria_min", 60, "carga máxima diaria (60 min)"),
        ("max_dias", 1, "ya da clase 1 días (máximo 1)"),
        ("carga_min_semanal_min", 300, "su carga mínima es de 300 min"),
    ],
)
def test_d7_cargas(campo: str, valor: int, texto: str) -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        setattr(d.profesores[CARO - 1], campo, valor)

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D7"}
    assert texto in _mensajes(resultado)


def test_d8_tiempo_continuo() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.profesores[ANA - 1].max_minutos_continuos = 60

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D8"}
    assert "Ana pasaría de 60 min seguidos sin un descanso de 10 min" in _mensajes(resultado)


def test_d8_el_receso_cuenta_como_descanso() -> None:
    """Ana da 8:50–9:40 y 10:00–10:50 con máximo 50 y descanso 20: el receso basta."""

    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.configuracion.descanso_minimo_min = 20
        d.profesores[ANA - 1].max_minutos_continuos = 50
        _reemplazar(h, Colocacion(MATE_A, f("L", 0), (ANA,)),
                    Colocacion(MATE_A, f("L", 2), (ANA,)))  # fmt: skip
        _reemplazar(h, Colocacion(FISICA_A, f("L", 2), (CARO,)),
                    Colocacion(FISICA_A, f("L", 3), (CARO,)))  # fmt: skip

    resultado = _verificar(cambio)
    assert "D8" not in _codigos(resultado), _mensajes(resultado)
    assert "D10" in _codigos(resultado)  # las 2 h de Matemáticas ya no son adyacentes


def test_d9_espacio_fisico() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(FISICA_B, f("M", 2), (CARO,)),
                    Colocacion(FISICA_B, f("L", 2), (CARO,)))  # fmt: skip
        d.profesores[ANA - 1].asignaturas.append(FISICA)
        next(c for c in d.clases if c.id == FISICA_B).profesores = [ANA]
        h[-1] = Colocacion(FISICA_B, f("L", 2), (ANA,))

    resultado = _verificar(cambio)
    assert "D9" in _codigos(resultado)
    assert "No hay espacio de tipo «cancha» libre el lunes de 10:00–10:50" in _mensajes(resultado)


def test_d10_maximo_diario_y_adyacencia() -> None:
    def maximo(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.asignaturas[MATE - 1].reglas_por_defecto.max_horas_dia = 1

    resultado = _verificar(maximo)
    assert _codigos(resultado) == {"D10"}
    assert "1°A ya tiene 1 h de Matemáticas el lunes (máximo 1)" in _mensajes(resultado)

    def separadas(d: DatosEscuela, h: list[Colocacion]) -> None:
        _reemplazar(h, Colocacion(MATE_A, f("L", 1), (ANA,)),
                    Colocacion(MATE_A, f("L", 3), (ANA,)))  # fmt: skip

    resultado = _verificar(separadas)
    assert _codigos(resultado) == {"D10"}
    assert "deben ir juntas" in _mensajes(resultado)


def test_d11_bloque_doble_obligatorio() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.asignaturas[MATE - 1].reglas_por_defecto = ReglasAsignatura(bloque_doble="obligatorio")

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D11"}
    assert "Matemáticas · 1°B debe darse en bloques dobles y tiene 2 horas sueltas" in _mensajes(
        resultado
    )


def test_d12_sin_huecos() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.niveles[0].huecos_alumnos = "prohibidos"

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D12"}
    assert "1°B tiene huecos el martes (prohibidos en Primaria)" in _mensajes(resultado)


def test_d13_fija_no_respetada() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.fijas.append(AsignacionFija(id=1, clase_id=INGLES_A, dia="M", indice_franja=1))

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D13"}
    assert "Inglés · 1°A no respeta su asignación fija del martes, hora 2" in _mensajes(resultado)

    def respetada(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.fijas.append(AsignacionFija(id=1, clase_id=INGLES_A, profesor_id=CARO, dia="M",
                                      indice_franja=0))  # fmt: skip

    assert _verificar(respetada).valida


@pytest.mark.parametrize(
    "cambio_datos",
    [
        lambda d: setattr(d.niveles[0], "eventos", [Evento(dia="M", inicio=480, fin=530)]),
        lambda d: setattr(d.grupos[0], "bloqueos", [BloqueoGrupo(dia="M", inicio=480, fin=500,
                                                                  nombre="Natación")]),
    ],
    ids=["evento", "bloqueo"],
)  # fmt: skip
def test_d14_eventos_y_bloqueos(cambio_datos: Callable[[DatosEscuela], None]) -> None:
    resultado = _verificar(lambda d, h: cambio_datos(d))
    assert "D14" in _codigos(resultado)
    assert "el martes de 08:00–08:50" in _mensajes(resultado)


def test_d15_franja_prohibida() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        d.asignaturas[FISICA - 1].reglas_por_defecto.franjas_prohibidas = [
            RangoFranjas(dias=("L",), desde_indice=2, hasta_indice=3)
        ]

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D15"}
    assert "Ed. Física no puede ir el lunes de 10:00–10:50 (franja prohibida)" in _mensajes(
        resultado
    )


def test_d16_division_simultanea() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        _con_division()(d, h)
        _reemplazar(h, Colocacion(20, f("M", 1), (CARO,)), Colocacion(20, f("M", 3), (CARO,)))

    resultado = _verificar(cambio)
    assert _codigos(resultado) == {"D16"}
    assert "Las partes de «Inglés por nivel» de 1°A no tienen Inglés en las mismas franjas" in (
        _mensajes(resultado)
    )


def test_referencias() -> None:
    def cambio(d: DatosEscuela, h: list[Colocacion]) -> None:
        h.append(Colocacion(999, f("L", 0), (ANA,)))
        h.append(Colocacion(INGLES_A, "1:L:9", (CARO,)))
        h.append(Colocacion(MATE_B, f("M", 3), (77,)))

    resultado = _verificar(cambio)
    mensajes = _mensajes(resultado)
    assert "La clase 999 no existe" in mensajes
    assert "está en la franja 1:L:9, que no existe" in mensajes
    assert "tiene un profesor que no existe" in mensajes
