"""Creado con Claude.

Diagnóstico (§11.3): en casos infactibles conocidos, el mensaje nombra al profesor y al grupo
correctos; el núcleo es mínimo; también desde «generar» y la línea de comandos.
"""

from pathlib import Path

from ortools.sat.python import cp_model
from typer.testing import CliRunner

from pruebas.escuelas import ANA, FISICA, MATE_A, MATE_B, escuela_minima
from timetabling.cli import app
from timetabling.dominio.modelos import DatosEscuela, Disponibilidad, RangoFranjas
from timetabling.ejemplo import crear_ejemplo
from timetabling.nucleo.diagnostico import Diagnostico, Enlace, diagnosticar
from timetabling.nucleo.modelo import ConstructorModelo
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.generacion import generar


def _ana_sobrecargada() -> DatosEscuela:
    """Ana imparte las 4 h de Matemáticas (1°A y 1°B), solo puede de 8:00 a 9:40 y a lo más
    50 min al día: en dos días caben 2 h."""
    datos = escuela_minima()
    for clase in datos.clases:
        if clase.id in (MATE_A, MATE_B):
            clase.profesores = [ANA]
    ana = datos.profesores[ANA - 1]
    ana.disponible_toda_la_jornada = False
    ana.disponibilidad = [Disponibilidad(dia=d, inicio=480, fin=580) for d in ("L", "M")]
    ana.carga_max_diaria_min = 50
    return datos


def _es_minimo(datos: DatosEscuela, diagnostico: Diagnostico) -> bool:
    """Con todo el núcleo es infactible; quitando cualquier elemento, factible."""
    familias = {e.familia for e in diagnostico.elementos}
    horario = ConstructorModelo(datos, modo="entidad", refinar=familias).construir()
    claves = [(e.familia, e.entidad) for e in diagnostico.elementos]

    def estado(supuestas: list[tuple[str, str]]) -> int:
        horario.modelo.clear_assumptions()
        horario.modelo.add_assumptions([horario.suposiciones[k] for k in supuestas])
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.max_time_in_seconds = 10
        return solver.solve(horario.modelo)

    if estado(claves) != cp_model.INFEASIBLE:
        return False
    return all(
        estado(claves[:i] + claves[i + 1 :]) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        for i in range(len(claves))
    )


def test_nombra_al_profesor_y_a_los_grupos() -> None:
    datos = _ana_sobrecargada()
    diagnostico = diagnosticar(datos)
    assert not diagnostico.factible and not diagnostico.estructural
    assert diagnostico.minimo
    assert diagnostico.familias == ["carga", "curricular"]
    assert diagnostico.mensaje == (
        "El conflicto involucra los límites de carga de Ana (máximos y tiempo continuo), las 2 "
        "horas de Matemáticas de 1°A y las 2 horas de Matemáticas de 1°B."
    )
    assert Enlace("profesor", ANA, "Ana") in diagnostico.enlaces
    assert Enlace("clase", MATE_A, "Matemáticas · 1°A") in diagnostico.enlaces
    assert _es_minimo(datos, diagnostico)


def test_disponibilidad_en_el_nucleo() -> None:
    """Ana solo puede el lunes de 8:00 a 8:50 y es la profesora fija de las 2 h de 1°A."""
    datos = escuela_minima()
    next(c for c in datos.clases if c.id == MATE_A).profesores = [ANA]
    ana = datos.profesores[ANA - 1]
    ana.disponible_toda_la_jornada = False
    ana.disponibilidad = [Disponibilidad(dia="L", inicio=480, fin=530)]
    diagnostico = diagnosticar(datos)
    assert "la disponibilidad de Ana" in diagnostico.mensaje
    assert "las 2 horas de Matemáticas de 1°A" in diagnostico.mensaje
    assert _es_minimo(datos, diagnostico)


def test_espacio_y_franjas_prohibidas() -> None:
    """Ed. Física solo puede el lunes a primera hora y hay una sola cancha para 1°A y 1°B."""
    datos = escuela_minima()
    datos.asignaturas[FISICA - 1].reglas_por_defecto.franjas_prohibidas = [
        RangoFranjas(dias=("M",), desde_indice=0, hasta_indice=3),
        RangoFranjas(dias=("L",), desde_indice=1, hasta_indice=3),
    ]
    datos.profesores[ANA - 1].asignaturas.append(FISICA)
    diagnostico = diagnosticar(datos)
    assert "la capacidad de los espacios de tipo «cancha»" in diagnostico.mensaje
    assert "las franjas prohibidas de Ed. Física" in diagnostico.mensaje
    assert Enlace("espacio", "cancha", "cancha") in diagnostico.enlaces
    assert _es_minimo(datos, diagnostico)


def test_problema_factible() -> None:
    diagnostico = diagnosticar(escuela_minima())
    assert diagnostico.factible
    assert "tiene solución" in diagnostico.mensaje


def test_presupuesto_agotado() -> None:
    diagnostico = diagnosticar(_ana_sobrecargada(), total_s=0.01, por_intento_s=0.01)
    assert not diagnostico.minimo or diagnostico.tiene_nucleo


def _pequeno_infactible(ruta: Path) -> Path:
    """Ed. Física (10 h en la semana) con sus dos profesores a una hora por día en 2 días."""
    crear_ejemplo(ruta)
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        for profesor in datos.profesores:
            if profesor.nombre in ("Irene Castro", "Luis Navarro"):
                profesor.max_dias = 2
                profesor.carga_max_diaria_min = 50
                repo.guardar(profesor)
    return ruta


def test_generar_adjunta_el_diagnostico(tmp_path: Path) -> None:
    ruta = _pequeno_infactible(tmp_path / "p.horario")
    resultado = generar(ruta, tiempo_limite_s=20, hilos=2, diagnostico_s=30)
    assert resultado.solucion is None
    assert resultado.diagnostico is not None
    mensaje = resultado.diagnostico.mensaje
    assert "Irene Castro" in mensaje and "Luis Navarro" in mensaje
    assert "Ed. Física" in mensaje


def test_cli_generar_muestra_el_diagnostico(tmp_path: Path) -> None:
    ruta = _pequeno_infactible(tmp_path / "p.horario")
    resultado = CliRunner().invoke(app, ["generar", str(ruta), "--tiempo-limite", "20"])
    assert resultado.exit_code == 1
    assert "Estado: INFACTIBLE" in resultado.output
    assert "Diagnóstico: El conflicto involucra" in resultado.output
    assert "→ profesor: Irene Castro" in resultado.output
