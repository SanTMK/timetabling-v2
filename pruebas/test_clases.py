"""Creado con Claude.

Clases (§5.2): sincronización con el plan, cobertura, divisiones, clases conjuntas y huérfanas.
También cubre las reglas de validación de los modelos que usan las clases.
"""

import pytest
from pydantic import ValidationError

from timetabling.dominio.clases import (
    DiferenciaCobertura,
    clases_huerfanas,
    cobertura_del_plan,
    grupos_de_clase,
    sincronizar_con_plan,
    texto_destinatarios,
)
from timetabling.dominio.modelos import (
    Asignatura,
    Clase,
    DatosEscuela,
    Destinatario,
    Division,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    RangoFranjas,
    ReglasAsignatura,
    ReglasAsignaturaNivel,
)
from timetabling.ejemplo import ejemplo_mediano, ejemplo_pequeno

MATE, INGLES, ARTES = 1, 2, 3


def _escuela(clases: list[Clase] | None = None) -> DatosEscuela:
    """Un nivel, el grado 7° con 7°A y 7°B, plan: Matemáticas 5 e Inglés 4."""
    return DatosEscuela(
        niveles=[Nivel(id=1, nombre="Secundaria", inicio_jornada=420, fin_jornada=840)],
        grados=[Grado(id=1, nivel_id=1, nombre="7°")],
        grupos=[Grupo(id=1, grado_id=1, seccion="A"), Grupo(id=2, grado_id=1, seccion="B")],
        divisiones=[Division(id=1, grupo_id=1, partes=["Básico", "Avanzado"])],
        asignaturas=[
            Asignatura(id=MATE, nombre="Matemáticas"),
            Asignatura(id=INGLES, nombre="Inglés"),
            Asignatura(id=ARTES, nombre="Artes"),
        ],
        plan=[
            PlanEstudios(grado_id=1, asignatura_id=MATE, horas_semanales=5),
            PlanEstudios(grado_id=1, asignatura_id=INGLES, horas_semanales=4),
        ],
        clases=clases or [],
    )


def _clase(ident: int, asignatura: int, horas: int, *destinatarios: Destinatario) -> Clase:
    return Clase(
        id=ident, asignatura_id=asignatura, destinatarios=list(destinatarios), horas_semanales=horas
    )


A = Destinatario(grupo_id=1)
B = Destinatario(grupo_id=2)
A_BASICO = Destinatario(grupo_id=1, division_id=1, parte="Básico")
A_AVANZADO = Destinatario(grupo_id=1, division_id=1, parte="Avanzado")


# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------


def test_sincronizar_crea_las_faltantes() -> None:
    resultado = sincronizar_con_plan(_escuela())
    creadas = {(c.destinatarios[0].grupo_id, c.asignatura_id, c.horas_semanales)
               for c in resultado.nuevas}  # fmt: skip
    assert creadas == {(1, MATE, 5), (1, INGLES, 4), (2, MATE, 5), (2, INGLES, 4)}
    assert all(c.origen == "plan" and c.profesores == [] and c.id is None for c in resultado.nuevas)
    assert resultado.diferencias == []
    assert resultado.huerfanas == []


def test_sincronizar_no_toca_las_manuales() -> None:
    manual = _clase(10, MATE, 3, A)
    manual.profesores = [7]
    datos = _escuela([manual])
    resultado = sincronizar_con_plan(datos)
    assert all(not (c.asignatura_id == MATE and c.destinatarios == [A]) for c in resultado.nuevas)
    assert datos.clases == [manual]
    assert manual.horas_semanales == 3 and manual.profesores == [7]
    # Se informa que 7°A tiene 2 horas de menos.
    assert resultado.diferencias == [DiferenciaCobertura(1, MATE, 5, 3)]


def test_sincronizar_es_idempotente() -> None:
    datos = _escuela()
    datos.clases = [
        c.model_copy(update={"id": i}) for i, c in enumerate(sincronizar_con_plan(datos).nuevas, 1)
    ]
    assert sincronizar_con_plan(datos).nuevas == []


def test_clase_conjunta_cubre_ambos_grupos() -> None:
    datos = _escuela([_clase(1, MATE, 5, A, B)])
    resultado = sincronizar_con_plan(datos)
    assert all(c.asignatura_id != MATE for c in resultado.nuevas)
    assert resultado.diferencias == []
    assert grupos_de_clase(datos.clases[0]) == [1, 2]
    assert texto_destinatarios(datos, datos.clases[0]) == "7°A, 7°B"


# ---------------------------------------------------------------------------
# Cobertura
# ---------------------------------------------------------------------------


def test_cobertura_horas_de_mas_y_de_menos() -> None:
    datos = _escuela([_clase(1, MATE, 6, A), _clase(2, MATE, 4, B), _clase(3, INGLES, 4, A, B)])
    diferencias = cobertura_del_plan(datos)
    assert diferencias == [DiferenciaCobertura(1, MATE, 5, 6), DiferenciaCobertura(2, MATE, 5, 4)]
    assert [d.diferencia for d in diferencias] == [1, -1]


def test_cobertura_sin_clases() -> None:
    diferencias = cobertura_del_plan(_escuela())
    assert DiferenciaCobertura(1, INGLES, 4, 0) in diferencias
    assert len(diferencias) == 4


def test_cobertura_por_partes_de_division() -> None:
    clases = [
        _clase(1, MATE, 5, A, B),
        _clase(2, INGLES, 4, A_BASICO),
        _clase(3, INGLES, 3, A_AVANZADO),
        _clase(4, INGLES, 4, B),
    ]
    diferencias = cobertura_del_plan(_escuela(clases))
    assert diferencias == [DiferenciaCobertura(1, INGLES, 4, 3, 1, "Avanzado")]
    assert "7°A (Avanzado)" == texto_destinatarios(_escuela(clases), clases[2])


def test_cobertura_parte_sin_clase() -> None:
    clases = [_clase(1, MATE, 5, A, B), _clase(2, INGLES, 4, A_BASICO), _clase(3, INGLES, 4, B)]
    assert cobertura_del_plan(_escuela(clases)) == [
        DiferenciaCobertura(1, INGLES, 4, 0, 1, "Avanzado")
    ]


def test_cobertura_grupo_completo_cuenta_para_cada_parte() -> None:
    clases = [
        _clase(1, MATE, 5, A, B),
        _clase(2, INGLES, 2, A),
        _clase(3, INGLES, 2, A_BASICO),
        _clase(4, INGLES, 2, A_AVANZADO),
        _clase(5, INGLES, 4, B),
    ]
    assert cobertura_del_plan(_escuela(clases)) == []


def test_huerfanas() -> None:
    artes = _clase(9, ARTES, 2, A)
    datos = _escuela([_clase(1, MATE, 5, A, B), artes])
    assert clases_huerfanas(datos) == [artes]
    assert sincronizar_con_plan(datos).huerfanas == [artes]


def test_ejemplos_quedan_cubiertos() -> None:
    for datos in (ejemplo_pequeno(), ejemplo_mediano()):
        assert sincronizar_con_plan(datos).nuevas == []
        assert cobertura_del_plan(datos) == []
        assert clases_huerfanas(datos) == []


# ---------------------------------------------------------------------------
# Validación de modelos relacionados
# ---------------------------------------------------------------------------


def test_destinatario_parcial_requiere_division_y_parte() -> None:
    with pytest.raises(ValidationError, match="división y la parte"):
        Destinatario(grupo_id=1, parte="Básico")


def test_clase_requiere_destinatarios_sin_repetir() -> None:
    with pytest.raises(ValidationError):
        Clase(asignatura_id=1, destinatarios=[], horas_semanales=1)
    with pytest.raises(ValidationError, match="repetir destinatarios"):
        Clase(asignatura_id=1, destinatarios=[A, A], horas_semanales=1)
    with pytest.raises(ValidationError, match="repetir profesores"):
        Clase(asignatura_id=1, destinatarios=[A], profesores=[1, 1], horas_semanales=1)


def test_division_necesita_dos_partes_distintas() -> None:
    with pytest.raises(ValidationError):
        Division(grupo_id=1, partes=["Única"])
    with pytest.raises(ValidationError, match="repetirse"):
        Division(grupo_id=1, partes=["A", "A"])


def test_espacio_efectivo() -> None:
    asignatura = Asignatura(id=1, nombre="Tecnología", espacio_requerido="taller")
    clase = Clase(asignatura_id=1, destinatarios=[A], horas_semanales=2)
    assert clase.espacio_efectivo(asignatura) == "taller"
    clase.sobrescribe_espacio = True
    assert clase.espacio_efectivo(asignatura) is None
    clase.espacio_requerido = "laboratorio"
    assert clase.espacio_efectivo(asignatura) == "laboratorio"


def test_reglas_efectivas_por_nivel() -> None:
    prohibida = RangoFranjas(desde_indice=0, hasta_indice=0)
    asignatura = Asignatura(
        id=1,
        nombre="Ed. Física",
        reglas_por_defecto=ReglasAsignatura(max_horas_dia=1, franjas_prohibidas=[prohibida]),
        reglas_por_nivel=[
            ReglasAsignaturaNivel(nivel_id=2, max_horas_dia=2, franjas_prohibidas=[])
        ],
    )
    assert asignatura.reglas_efectivas(1) == asignatura.reglas_por_defecto
    efectivas = asignatura.reglas_efectivas(2)
    assert efectivas.max_horas_dia == 2 and efectivas.franjas_prohibidas == []
    assert efectivas.bloque_doble == "no"


def test_rango_franjas_por_indice_o_por_hora() -> None:
    with pytest.raises(ValidationError, match="no ambos"):
        RangoFranjas(desde_indice=0, hasta_indice=1, desde=420, hasta=480)
    with pytest.raises(ValidationError, match="no ambos"):
        RangoFranjas()
    with pytest.raises(ValidationError, match="mayor"):
        RangoFranjas(desde_indice=3, hasta_indice=1)
    rango = RangoFranjas(dias=("V", "L"), desde=420, hasta=660)
    assert rango.dias == ("L", "V") and rango.incluye_dia("L") and not rango.incluye_dia("M")
    assert RangoFranjas(desde_indice=0, hasta_indice=0).incluye_dia("X")


def test_validate_assignment_y_extra_forbid() -> None:
    grupo = Grupo(grado_id=1, seccion="A")
    with pytest.raises(ValidationError):
        grupo.estudiantes = -1
    with pytest.raises(ValidationError):
        Grupo(grado_id=1, seccion="A", desconocido=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="vacío"):
        Grupo(grado_id=1, seccion="  ")
    nivel = Nivel(nombre="X", inicio_jornada=420, fin_jornada=840, dias=["V", "L", "L"])
    assert nivel.dias == ["L", "V"]
    with pytest.raises(ValidationError, match="inicio debe ser anterior"):
        Nivel(nombre="X", inicio_jornada=840, fin_jornada=420)
