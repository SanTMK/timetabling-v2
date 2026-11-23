"""Creado con Claude.

Tiempo (§7): generación de franjas, recesos, duraciones especiales, eventos, bloqueos, rejilla
Δ, traslapes entre niveles, cliques y disponibilidad con los tres tipos.
"""

from timetabling.dominio.modelos import (
    BloqueoGrupo,
    Configuracion,
    DatosEscuela,
    Disponibilidad,
    Evento,
    EventoProfesor,
    Grado,
    Grupo,
    Nivel,
    Profesor,
    RangoFranjas,
    Receso,
    ReglasAsignatura,
)
from timetabling.dominio.tiempo import a_hhmm, a_minutos
from timetabling.ejemplo import ejemplo_mediano
from timetabling.nucleo.franjas import (
    Calendario,
    Franja,
    adyacentes,
    calcular_rejilla,
    cliques_de_traslape,
    cliques_maximales,
    en_rango,
    evaluar_franja,
    franjas_parcialmente_cubiertas,
    franjas_utiles_grupo,
    franjas_utiles_nivel,
    fusionar,
    generar_franjas,
    generar_franjas_dia,
    preferida,
    prohibida,
    se_traslapan_franjas,
)


def _nivel(**campos: object) -> Nivel:
    valores: dict[str, object] = {
        "id": 1,
        "nombre": "Primaria",
        "duracion_min": 50,
        "inicio_jornada": a_minutos("07:30"),
        "fin_jornada": a_minutos("12:00"),
        "recesos": [Receso(inicio=a_minutos("10:00"), fin=a_minutos("10:30"))],
    }
    valores.update(campos)
    return Nivel(**valores)  # type: ignore[arg-type]


def _horas(franjas: list[Franja]) -> list[str]:
    return [f"{a_hhmm(f.inicio)}-{a_hhmm(f.fin)}" for f in franjas]


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------


def test_generacion_con_receso() -> None:
    franjas = generar_franjas_dia(_nivel(), "L")
    # 11:20–12:10 ya no cabe antes de las 12:00.
    assert _horas(franjas) == ["07:30-08:20", "08:20-09:10", "09:10-10:00", "10:30-11:20"]
    assert [f.receso_antes for f in franjas] == [False, False, False, True]
    assert [f.indice for f in franjas] == [0, 1, 2, 3]
    assert franjas[0].id == "1:L:0"


def test_franja_que_cruzaria_el_receso_se_mueve() -> None:
    """Con horas de 40 min, la 3.ª (8:50–9:30) cabe; la 4.ª (9:30–10:10) choca y se mueve."""
    nivel = _nivel(duracion_min=40, inicio_jornada=a_minutos("08:10"))
    assert _horas(generar_franjas_dia(nivel, "L")) == [
        "08:10-08:50",
        "08:50-09:30",
        "10:30-11:10",
        "11:10-11:50",
    ]


def test_se_detiene_cuando_no_cabe() -> None:
    nivel = _nivel(fin_jornada=a_minutos("11:19"))
    assert len(generar_franjas_dia(nivel, "L")) == 3
    nivel = _nivel(fin_jornada=a_minutos("11:20"))
    assert len(generar_franjas_dia(nivel, "L")) == 4


def test_duraciones_especiales() -> None:
    nivel = _nivel(duraciones_especiales={0: 30, 3: 20})
    assert _horas(generar_franjas_dia(nivel, "L")) == [
        "07:30-08:00",
        "08:00-08:50",
        "08:50-09:40",
        "09:40-10:00",  # la hora especial de 20 min cabe justo antes del receso
        "10:30-11:20",
    ]


def test_dias_del_nivel() -> None:
    nivel = _nivel(dias=["L", "X"])
    assert {f.dia for f in generar_franjas(nivel)} == {"L", "X"}
    assert len(generar_franjas(nivel)) == 8


def test_eventos_quitan_franjas_y_conservan_indices() -> None:
    nivel = _nivel(
        eventos=[Evento(dia="L", inicio=a_minutos("07:30"), fin=a_minutos("08:00"))], dias=["L"]
    )
    utiles = franjas_utiles_nivel(nivel)
    assert [f.indice for f in utiles] == [1, 2, 3]


def test_bloqueos_de_grupo() -> None:
    nivel = _nivel(dias=["L", "M"])
    grupo = Grupo(
        id=1,
        grado_id=1,
        seccion="A",
        bloqueos=[BloqueoGrupo(dia="M", inicio=a_minutos("10:30"), fin=a_minutos("12:00"))],
    )
    utiles = franjas_utiles_grupo(franjas_utiles_nivel(nivel), grupo)
    assert [(f.dia, f.indice) for f in utiles] == [
        ("L", 0), ("L", 1), ("L", 2), ("L", 3), ("M", 0), ("M", 1), ("M", 2)
    ]  # fmt: skip


def test_bloqueo_que_solo_roza_no_quita() -> None:
    nivel = _nivel(dias=["L"])
    grupo = Grupo(
        id=1,
        grado_id=1,
        seccion="A",
        bloqueos=[BloqueoGrupo(dia="L", inicio=a_minutos("10:00"), fin=a_minutos("10:30"))],
    )
    assert len(franjas_utiles_grupo(franjas_utiles_nivel(nivel), grupo)) == 4


# ---------------------------------------------------------------------------
# Adyacencia, traslapes y cliques
# ---------------------------------------------------------------------------


def test_adyacencia() -> None:
    f = generar_franjas_dia(_nivel(), "L")
    assert adyacentes(f[0], f[1]) and adyacentes(f[1], f[0])
    assert not adyacentes(f[0], f[2])
    assert not adyacentes(f[2], f[3])  # receso entre ellas
    otra = generar_franjas_dia(_nivel(), "M")
    assert not adyacentes(f[0], otra[1])
    otro_nivel = generar_franjas_dia(_nivel(id=2, nombre="Otro"), "L")
    assert not adyacentes(f[0], otro_nivel[1])


def test_traslape_con_margen_solo_entre_niveles() -> None:
    a = Franja(1, "L", 0, 480, 530)
    b = Franja(1, "L", 1, 530, 580)
    c = Franja(2, "L", 0, 535, 580)
    assert not se_traslapan_franjas(a, b, margen=10)
    assert se_traslapan_franjas(a, c, margen=10)
    assert not se_traslapan_franjas(a, c, margen=0)
    assert not se_traslapan_franjas(a, Franja(2, "M", 0, 480, 530), margen=10)


def test_cliques_maximales() -> None:
    vecinos = {
        "a": {"b", "c"},
        "b": {"a", "c"},
        "c": {"a", "b", "d"},
        "d": {"c"},
        "e": set(),
    }
    assert set(cliques_maximales(vecinos)) == {
        frozenset("abc"),
        frozenset("cd"),
        frozenset("e"),
    }


def test_cliques_entre_niveles() -> None:
    """Secundaria de 50 min desde 7:00 y preescolar de 45 desde 8:00, margen 10."""
    sec = [Franja(1, "L", i, 420 + 50 * i, 470 + 50 * i) for i in range(4)]
    pre = [Franja(2, "L", i, 480 + 45 * i, 525 + 45 * i) for i in range(3)]
    aislada = Franja(3, "M", 0, 420, 470)
    cliques = cliques_de_traslape([*sec, *pre, aislada], margen=10)
    ids = {frozenset(c) for c in cliques}
    assert frozenset({"3:M:0"}) in ids
    # 7:50–8:40 de secundaria choca con 8:00–8:45 de preescolar.
    assert frozenset({"1:L:1", "2:L:0"}) in ids
    for clique in cliques:
        miembros = [f for f in [*sec, *pre, aislada] if f.id in clique]
        for i, x in enumerate(miembros):
            for y in miembros[i + 1 :]:
                assert se_traslapan_franjas(x, y, 10)
    # Cada franja está en algún clique.
    assert set().union(*cliques) == {f.id for f in [*sec, *pre, aislada]}


# ---------------------------------------------------------------------------
# Rejilla Δ
# ---------------------------------------------------------------------------


def test_rejilla_mcd_y_minimo() -> None:
    assert calcular_rejilla([480, 510, 540, 600]).delta == 30
    assert calcular_rejilla([480, 525, 10]).delta == 5
    assert calcular_rejilla([421, 470]).delta == 5
    assert calcular_rejilla([]).delta == 5


def test_rejilla_ticks() -> None:
    rejilla = calcular_rejilla([30])
    assert list(rejilla.ticks(480, 540)) == [16, 17]
    rejilla5 = calcular_rejilla([421, 470])
    assert list(rejilla5.ticks(421, 431)) == [84, 85, 86]


def test_calendario_del_mediano() -> None:
    datos = ejemplo_mediano()
    calendario = Calendario.de(datos)
    assert calendario.rejilla.delta == 5
    utiles = {n.nombre: len(calendario.utiles_nivel[n.id or 0]) for n in datos.niveles}
    assert utiles == {"Preescolar": 25, "Primaria": 34, "Secundaria": 40}
    seis_b = next(g for g in datos.grupos if datos.nombre_grupo(g.id or 0) == "6°B")
    assert len(calendario.utiles_grupo[seis_b.id or 0]) == 33
    assert calendario.franja(1, "L", 3) is not None and calendario.franja(1, "L", 9) is None
    assert any(len(c) > 1 for c in calendario.cliques)


def test_utiles_comunes() -> None:
    datos = DatosEscuela(
        configuracion=Configuracion(),
        niveles=[_nivel(dias=["L"])],
        grados=[Grado(id=1, nivel_id=1, nombre="1°")],
        grupos=[
            Grupo(id=1, grado_id=1, seccion="A"),
            Grupo(
                id=2,
                grado_id=1,
                seccion="B",
                bloqueos=[BloqueoGrupo(dia="L", inicio=450, fin=500)],
            ),
        ],
    )
    calendario = Calendario.de(datos)
    assert [f.indice for f in calendario.utiles_comunes([1, 2])] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------

F = Franja(1, "L", 1, a_minutos("08:20"), a_minutos("09:10"))


def test_toda_la_jornada_salvo_no_disponible() -> None:
    profesor = Profesor(nombre="Ana")
    assert evaluar_franja(profesor, F).validez == "valida"
    profesor.disponibilidad = [
        Disponibilidad(dia="L", inicio=a_minutos("09:00"), fin=a_minutos("10:00"),
                       tipo="no_disponible")
    ]  # fmt: skip
    evaluacion = evaluar_franja(profesor, F)
    assert evaluacion.validez == "invalida" and "09:00–10:00" in evaluacion.motivo


def test_solo_rangos_disponibles_fusionados() -> None:
    profesor = Profesor(
        nombre="Beto",
        disponible_toda_la_jornada=False,
        disponibilidad=[
            Disponibilidad(dia="L", inicio=a_minutos("08:00"), fin=a_minutos("08:45")),
            Disponibilidad(dia="L", inicio=a_minutos("08:45"), fin=a_minutos("09:30")),
        ],
    )
    assert evaluar_franja(profesor, F).validez == "valida"
    assert fusionar([(480, 525), (525, 570), (600, 610)]) == [(480, 570), (600, 610)]
    corto = profesor.model_copy(
        update={
            "disponibilidad": [
                Disponibilidad(dia="L", inicio=a_minutos("08:00"), fin=a_minutos("09:00"))
            ]
        }
    )
    assert evaluar_franja(corto, F).validez == "invalida"
    assert franjas_parcialmente_cubiertas(corto, [F]) == [F]
    assert franjas_parcialmente_cubiertas(profesor, [F]) == []
    otro_dia = Franja(1, "M", 1, F.inicio, F.fin)
    assert evaluar_franja(profesor, otro_dia).validez == "invalida"
    assert franjas_parcialmente_cubiertas(corto, [otro_dia]) == []


def test_preferible_no() -> None:
    profesor = Profesor(
        nombre="Caro",
        disponibilidad=[
            Disponibilidad(dia="L", inicio=a_minutos("09:00"), fin=a_minutos("09:30"),
                           tipo="preferible_no")
        ],
    )  # fmt: skip
    evaluacion = evaluar_franja(profesor, F)
    assert evaluacion.validez == "preferible_no" and evaluacion.valida
    # Sin toda la jornada, un rango preferible_no también permite dar clase.
    restringido = profesor.model_copy(
        update={
            "disponible_toda_la_jornada": False,
            "disponibilidad": [
                Disponibilidad(dia="L", inicio=a_minutos("08:00"), fin=a_minutos("09:00")),
                Disponibilidad(dia="L", inicio=a_minutos("09:00"), fin=a_minutos("10:00"),
                               tipo="preferible_no"),
            ],
        }
    )  # fmt: skip
    assert evaluar_franja(restringido, F).validez == "preferible_no"


def test_evento_del_profesor() -> None:
    profesor = Profesor(
        nombre="Dani",
        eventos=[EventoProfesor(nombre="Junta", dia="L", inicio=a_minutos("09:00"),
                                fin=a_minutos("10:00"))],
    )  # fmt: skip
    evaluacion = evaluar_franja(profesor, F)
    assert evaluacion.validez == "invalida" and "Junta" in evaluacion.motivo


# ---------------------------------------------------------------------------
# Rangos de franjas (prohibidas y preferidas)
# ---------------------------------------------------------------------------


def test_rangos_por_indice_y_por_hora() -> None:
    primera = Franja(1, "L", 0, a_minutos("07:30"), a_minutos("08:20"))
    once = Franja(1, "L", 4, a_minutos("10:30"), a_minutos("11:20"))
    reglas = ReglasAsignatura(
        franjas_prohibidas=[RangoFranjas(desde_indice=0, hasta_indice=0)],
        franjas_preferidas=[RangoFranjas(desde=a_minutos("07:00"), hasta=a_minutos("11:00"))],
    )
    assert prohibida(reglas, primera) and not prohibida(reglas, once)
    assert preferida(reglas, primera) and not preferida(reglas, once)
    assert preferida(ReglasAsignatura(), once)
    solo_lunes = RangoFranjas(dias=("M",), desde_indice=0, hasta_indice=9)
    assert not en_rango(solo_lunes, primera, completa=False)
    tarde = RangoFranjas(desde=a_minutos("11:00"), hasta=a_minutos("14:00"))
    assert en_rango(tarde, once, completa=False) and not en_rango(tarde, once, completa=True)
