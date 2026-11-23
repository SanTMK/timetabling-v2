"""Creado con Claude.

Restricciones blandas (§9): cada criterio B1–B10 en casos mínimos con óptimo conocido; B1 y D8
cruzando niveles; pesos, prioridades y coherencia entre el modelo y la evaluación sin solver.
"""

import pytest
from ortools.sat.python import cp_model

from pruebas.escuelas import (
    ANA,
    BETO,
    CARO,
    FISICA_A,
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
    Clase,
    Criterios,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    EstadoSolucion,
    Grado,
    Grupo,
    Nivel,
    RangoFranjas,
    ReglasAsignatura,
)
from timetabling.nucleo.modelo import ConstructorModelo
from timetabling.nucleo.objetivo import (
    ConstructorObjetivo,
    coeficiente,
    evaluar,
    pesos,
    total_ponderado,
)
from timetabling.nucleo.resolver import OpcionesResolucion, resolver
from timetabling.nucleo.verificador import verificar


def _solo(criterio: str) -> Criterios:
    return Criterios(perfil="personalizado", modo_avanzado=True, pesos_avanzados={criterio: 1.0})


def _ninguno() -> Criterios:
    criterios = Criterios(perfil="personalizado")
    for criterio in criterios.prioridades:
        criterios.prioridades[criterio] = "desactivado"
    return criterios


def _optimo(datos: DatosEscuela, criterio: str, base: list[Colocacion] | None = None) -> float:
    """Valor óptimo del criterio cuando es el único activo (B9 solo existe con base)."""
    criterios = _ninguno() if criterio == "B9" else _solo(criterio)
    resultado = resolver(
        datos,
        OpcionesResolucion(tiempo_limite_s=30, hilos=4, criterios=criterios, base=base),
    )
    assert resultado.estado is EstadoSolucion.OPTIMO
    assert verificar(datos, resultado.colocaciones).valida
    return resultado.penalizaciones[criterio]


def _fija(datos: DatosEscuela, clase: int, dia: str, indice: int, profesor: int | None = None
          ) -> None:  # fmt: skip
    datos.fijas.append(
        AsignacionFija(id=len(datos.fijas) + 1, clase_id=clase, profesor_id=profesor, dia=dia,  # type: ignore[arg-type]
                       indice_franja=indice)
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Pesos y prioridades
# ---------------------------------------------------------------------------


def test_pesos_por_perfil_y_avanzados() -> None:
    equilibrado = pesos(Criterios())
    assert equilibrado["B1"] == 16 and equilibrado["B5"] == 1 and "B9" not in equilibrado
    assert pesos(Criterios(), con_base=True)["B9"] == 64
    profesores = pesos(Criterios.de_perfil("profesores"))
    assert profesores["B1"] == 64
    desactivado = Criterios()
    desactivado.prioridades["B3"] = "desactivado"
    assert "B3" not in pesos(desactivado)
    assert pesos(_solo("B2")) == {"B2": 1.0}
    # B1 y B6 van por minuto: una unidad (50 min) pesa lo mismo que una unidad de conteo.
    assert coeficiente("B1", 1.0) * 50 == coeficiente("B2", 1.0)
    assert total_ponderado({"B1": 2.0, "B2": 1.0}, {"B1": 16, "B2": 16}) == 48


def test_criterios_desactivados_no_se_construyen() -> None:
    datos = escuela_minima()
    constructor = ConstructorModelo(datos)
    constructor.construir()
    nada = _ninguno()
    assert ConstructorObjetivo(constructor, nada).construir().vacio
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2, criterios=nada))
    assert resultado.estado is EstadoSolucion.OPTIMO and not resultado.penalizaciones_son_cota


# ---------------------------------------------------------------------------
# B1 y D8 (cruzando niveles)
# ---------------------------------------------------------------------------


def test_b1_optimo_sin_huecos() -> None:
    assert _optimo(escuela_minima(), "B1") == 0


def test_b1_hueco_inevitable() -> None:
    """Ana da Matemáticas 1°A a las 8:00 e Inglés 1°A a las 10:50 el lunes; la otra hora de
    Matemáticas va a las 8:50 y queda libre 10:00–10:50 (el receso de 9:40 no cuenta)."""
    datos = escuela_minima()
    next(c for c in datos.clases if c.id == MATE_A).profesores = [ANA]
    next(c for c in datos.clases if c.id == MATE_B).profesores = [BETO]
    next(c for c in datos.clases if c.id == INGLES_A).profesores = [ANA]
    _fija(datos, MATE_A, "L", 0)
    _fija(datos, INGLES_A, "L", 3)
    assert _optimo(datos, "B1") == 1.0


def _dos_niveles(inicio_secundaria: int) -> DatosEscuela:
    """Ana da Matemáticas en Primaria (8:00–9:40) y en Secundaria (una hora desde
    `inicio_secundaria`), solo el lunes."""
    datos = escuela_minima()
    datos.niveles[0].dias = ["L"]
    datos.niveles.append(
        Nivel(id=2, nombre="Secundaria", duracion_min=50, inicio_jornada=inicio_secundaria,
              fin_jornada=inicio_secundaria + 50, dias=["L"])
    )  # fmt: skip
    datos.grados.append(Grado(id=2, nivel_id=2, nombre="7°"))
    datos.grupos.append(Grupo(id=3, grado_id=2, seccion="A"))
    datos.profesores[ANA - 1].grados.append(2)
    datos.clases = [
        Clase(id=MATE_A, asignatura_id=MATE, destinatarios=[Destinatario(grupo_id=1)],
              horas_semanales=2, profesores=[ANA]),
        Clase(id=30, asignatura_id=MATE, destinatarios=[Destinatario(grupo_id=3)],
              horas_semanales=1, profesores=[ANA]),
    ]  # fmt: skip
    datos.plan = []
    datos.configuracion.margen_traslado_min = 0
    return datos


def test_b1_cruza_niveles() -> None:
    datos = _dos_niveles(inicio_secundaria=630)  # 10:30–11:20
    colocaciones = [
        Colocacion(MATE_A, f("L", 0), (ANA,)),
        Colocacion(MATE_A, f("L", 1), (ANA,)),
        Colocacion(30, "2:L:0", (ANA,)),
    ]
    # Libre de 9:40 a 10:30 (50 min), menos el receso de Primaria (9:40–10:00): 30 min.
    assert evaluar(datos, colocaciones)["B1"] == pytest.approx(30 / 50)


def test_d8_cruza_niveles() -> None:
    """Máximo 100 min seguidos con descanso de 10: tras 8:00–9:40 en Primaria, una clase de
    Secundaria a las 9:45 es imposible; a las 9:50, posible."""
    for inicio, factible in ((585, False), (590, True)):
        datos = _dos_niveles(inicio_secundaria=inicio)
        datos.niveles[0].recesos = []
        datos.profesores[ANA - 1].max_minutos_continuos = 100
        _fija(datos, MATE_A, "L", 0)
        _fija(datos, MATE_A, "L", 1)
        resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2))
        assert (resultado.estado is EstadoSolucion.OPTIMO) == factible, inicio
        manual = [
            Colocacion(MATE_A, f("L", 0), (ANA,)),
            Colocacion(MATE_A, f("L", 1), (ANA,)),
            Colocacion(30, "2:L:0", (ANA,)),
        ]
        violaciones = {v.restriccion for v in verificar(datos, manual).violaciones}
        assert ("D8" not in violaciones) == factible


# ---------------------------------------------------------------------------
# B2–B10
# ---------------------------------------------------------------------------


def test_b2_distribucion_semanal() -> None:
    datos = escuela_minima()
    datos.asignaturas[MATE - 1].reglas_por_defecto.max_horas_dia = 3
    mate = next(c for c in datos.clases if c.id == MATE_A)
    mate.horas_semanales = 3
    # 3 h en 2 días: ⌈3/2⌉ = 2 por día; lo mejor es 2 + 1 (penalización 0); 3 juntas, 1.
    assert _optimo(datos, "B2") == 0
    assert evaluar(datos, [Colocacion(MATE_A, f("L", i), (ANA,)) for i in range(3)])["B2"] == 1


def test_b3_fuera_de_preferidas() -> None:
    datos = escuela_minima()
    reglas = datos.asignaturas[MATE - 1].reglas_por_defecto
    reglas.max_horas_dia = 1
    reglas.franjas_preferidas = [RangoFranjas(dias=("L",), desde_indice=0, hasta_indice=0)]
    # Matemáticas de 1°A y 1°B: 4 h; solo la del lunes a primera hora de cada grupo es
    # preferida (los dos grupos pueden usarla a la vez).
    assert _optimo(datos, "B3") == 2


def test_b4_preferible_no() -> None:
    datos = escuela_minima()
    caro = datos.profesores[CARO - 1]
    caro.disponibilidad = [
        Disponibilidad(dia=d, inicio=480, fin=720, tipo="preferible_no") for d in ("L", "M")
    ]
    # Ed. Física solo la puede dar Caro: 2 h inevitables; Inglés la puede dar Ana.
    assert _optimo(datos, "B4") == 2


def test_b5_dias_con_clase() -> None:
    datos = escuela_minima()
    # Beto da las 4 h de Matemáticas el mismo día y Caro, Inglés y Ed. Física otro (o el mismo):
    # Ana queda sin clases. Mínimo: 2 días-profesor.
    assert _optimo(datos, "B5") == 2


def test_b6_desequilibrio() -> None:
    datos = escuela_minima()
    for clase in datos.clases:
        if clase.asignatura_id == INGLES:
            clase.profesores = [CARO]
    # Matemáticas: Ana y Beto, 2 clases de 2 h → una cada uno, desequilibrio 0.
    assert _optimo(datos, "B6") == 0
    todo_ana = [
        Colocacion(MATE_A, f("L", 0), (ANA,)),
        Colocacion(MATE_A, f("L", 1), (ANA,)),
        Colocacion(MATE_B, f("M", 0), (ANA,)),
        Colocacion(MATE_B, f("M", 1), (ANA,)),
    ]
    assert evaluar(datos, todo_ana)["B6"] == 4.0  # 200 min − 0 min = 4 unidades


def test_b7_titular() -> None:
    datos = escuela_minima()
    datos.niveles[0].preferir_titular = True
    datos.grupos[0].titular_id = ANA
    # 1°A: Matemáticas e Inglés los puede dar Ana; Ed. Física solo Caro (1 h inevitable).
    assert _optimo(datos, "B7") == 1


def test_b8_bloque_doble_preferido() -> None:
    datos = escuela_minima()
    datos.asignaturas[MATE - 1].reglas_por_defecto = ReglasAsignatura(bloque_doble="preferido")
    assert _optimo(datos, "B8") == 0
    separadas = [Colocacion(MATE_A, f("L", 0), (ANA,)), Colocacion(MATE_A, f("M", 0), (ANA,))]
    assert evaluar(datos, separadas)["B8"] == 2


def test_b9_cambios_respecto_a_la_base() -> None:
    datos = escuela_minima()
    base = horario_valido()
    assert _optimo(datos, "B9", base=base) == 0
    cambiado = [c for c in base if c.clase_id != FISICA_A]
    cambiado.append(Colocacion(FISICA_A, f("L", 3), (CARO,)))  # movida: 2
    cambiado = [
        Colocacion(c.clase_id, c.franja_id, (ANA,)) if c.clase_id == INGLES_A else c
        for c in cambiado
    ]  # solo cambia el profesor: 1
    assert evaluar(datos, cambiado, base=base)["B9"] == 3


def test_b9_base_imposible_no_vuelve_infactible() -> None:
    datos = escuela_minima()
    base = [Colocacion(MATE_A, f("L", 0), (CARO,)), Colocacion(999, f("L", 1), (ANA,))]
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2, base=base,
                                                   criterios=_solo("B1")))  # fmt: skip
    assert resultado.estado is EstadoSolucion.OPTIMO


def test_b10_huecos_de_alumnos() -> None:
    datos = escuela_minima()
    assert _optimo(datos, "B10") == 0
    con_hueco = [Colocacion(MATE_A, f("L", 0), (ANA,)), Colocacion(INGLES_A, f("L", 2), (CARO,))]
    assert evaluar(datos, con_hueco)["B10"] == 1
    datos.niveles[0].huecos_alumnos = "permitidos"
    assert evaluar(datos, con_hueco)["B10"] == 0


# ---------------------------------------------------------------------------
# Coherencia entre el modelo y la evaluación sin solver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["equilibrado", "profesores", "alumnos"])
def test_modelo_y_evaluacion_coinciden_en_el_optimo(perfil: str) -> None:
    datos = escuela_minima()
    datos.niveles[0].preferir_titular = True
    datos.grupos[0].titular_id = ANA
    datos.asignaturas[MATE - 1].reglas_por_defecto.franjas_preferidas = [
        RangoFranjas(desde=480, hasta=600)
    ]
    criterios = Criterios.de_perfil(perfil)  # type: ignore[arg-type]
    constructor = ConstructorModelo(datos)
    horario = constructor.construir()
    objetivo = ConstructorObjetivo(constructor, criterios).construir()
    horario.modelo.minimize(objetivo.expresion)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 4
    solver.parameters.max_time_in_seconds = 30
    assert solver.solve(horario.modelo) == cp_model.OPTIMAL
    del_modelo = objetivo.valores(solver)
    evaluados = evaluar(datos, horario.colocaciones(solver), constructor.calendario)
    for criterio, valor in del_modelo.items():
        assert valor == pytest.approx(evaluados[criterio]), criterio
