"""Creado con Claude.

Resolución de punta a punta (§11.1): factibilidad y optimización, estados, cotas, cancelación,
pistas, vecindario y el caso de uso «generar» (servicio y línea de comandos). El mediano se
resuelve con la marca `lento`.
"""

import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pruebas.escuelas import ANA, CARO, INGLES_A, MATE_A, escuela_minima, f
from timetabling.cli import app
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import AsignacionFija, EstadoSolucion, Violacion
from timetabling.ejemplo import crear_ejemplo, ejemplo_mediano, ejemplo_pequeno
from timetabling.nucleo.resolver import OpcionesResolucion, Progreso, Resolutor, resolver
from timetabling.nucleo.verificador import ResultadoVerificacion, verificar
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.generacion import ErrorValidacion, generar
from timetabling.servicios.soluciones import a_colocaciones


def test_escuela_minima_optima() -> None:
    datos = escuela_minima()
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=20, hilos=2))
    assert resultado.estado is EstadoSolucion.OPTIMO
    assert not resultado.penalizaciones_son_cota
    assert len(resultado.colocaciones) == 7
    assert verificar(datos, resultado.colocaciones).valida
    assert set(resultado.penalizaciones) >= {"B1", "B5", "B10"}
    assert resultado.tiempo_primera_s is not None
    assert resultado.tiempo_primera_s <= resultado.tiempo_s


def test_solo_factibilidad() -> None:
    resultado = resolver(
        escuela_minima(), OpcionesResolucion(tiempo_limite_s=10, hilos=2, optimizar=False)
    )
    assert resultado.estado is EstadoSolucion.OPTIMO  # sin objetivo, la primera es óptima


def test_ejemplo_pequeno() -> None:
    datos = ejemplo_pequeno()
    progresos: list[Progreso] = []
    resultado = Resolutor(
        datos, OpcionesResolucion(tiempo_limite_s=6, hilos=4), progresos.append
    ).resolver()
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert resultado.penalizaciones_son_cota == (resultado.estado is EstadoSolucion.FACTIBLE)
    assert len(resultado.colocaciones) == sum(c.horas_semanales for c in datos.clases)
    assert verificar(datos, resultado.colocaciones).valida
    assert progresos[0].fase == "construyendo"
    assert any(p.fase == "factibilidad" and p.soluciones >= 1 for p in progresos)
    optimizacion = [p for p in progresos if p.fase == "optimizacion"]
    assert optimizacion and optimizacion[-1].mejor_objetivo is not None
    assert all(p.cota is not None and p.cota <= p.mejor_objetivo + 1e-6 for p in optimizacion)


@pytest.mark.lento
def test_ejemplo_mediano_en_menos_de_60_s() -> None:
    datos = ejemplo_mediano()
    inicio = time.monotonic()
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=60, hilos=4))
    assert time.monotonic() - inicio < 70
    assert resultado.tiempo_primera_s is not None and resultado.tiempo_primera_s < 60
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
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


def test_cancelar_durante_la_optimizacion_conserva_la_mejor() -> None:
    datos = ejemplo_pequeno()
    progresos: list[Progreso] = []
    resolutor = Resolutor(datos, OpcionesResolucion(tiempo_limite_s=120, hilos=2))

    def al_progresar(progreso: Progreso) -> None:
        progresos.append(progreso)
        if progreso.fase == "optimizacion" and progreso.soluciones == 2:
            threading.Thread(target=resolutor.cancelar).start()

    resolutor.al_progresar = al_progresar
    inicio = time.monotonic()
    resultado = resolutor.resolver()
    assert time.monotonic() - inicio < 30
    assert resultado.estado is EstadoSolucion.CANCELADO
    assert resultado.penalizaciones_son_cota
    assert verificar(datos, resultado.colocaciones).valida


def test_cancelar_desde_otro_hilo() -> None:
    """Cancelar en cualquier momento devuelve el control pronto."""
    datos = ejemplo_mediano()
    resolutor = Resolutor(datos, OpcionesResolucion(tiempo_limite_s=120, hilos=2))
    temporizador = threading.Timer(0.5, resolutor.cancelar)
    temporizador.start()
    inicio = time.monotonic()
    resultado = resolutor.resolver()
    temporizador.cancel()
    assert time.monotonic() - inicio < 30
    assert resultado.estado is EstadoSolucion.CANCELADO
    if resultado.colocaciones:
        assert verificar(datos, resultado.colocaciones).valida


def test_pista_de_base_se_acepta() -> None:
    datos = escuela_minima()
    base = [Colocacion(MATE_A, f("M", 2), (ANA,)), Colocacion(MATE_A, f("M", 3), (ANA,))]
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2, base=base))
    assert resultado.estado is EstadoSolucion.OPTIMO


# ---------------------------------------------------------------------------
# Caso de uso «generar»
# ---------------------------------------------------------------------------


def test_generar_guarda_la_solucion(tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    resultado = generar(ruta, tiempo_limite_s=5, hilos=2)
    solucion = resultado.solucion
    assert solucion is not None and solucion.id is not None
    assert solucion.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert solucion.origen == "generado"
    assert "total" in solucion.penalizaciones
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        guardada = repo.cargar_solucion(solucion.id)
    assert guardada.huella_niveles == datos.huella_niveles()
    assert len(guardada.asignaciones) == sum(c.horas_semanales for c in datos.clases)
    assert all(a.asignatura_nombre and a.grupos_texto and a.profesor_nombre
               for a in guardada.asignaciones)  # fmt: skip
    # Ida y vuelta a colocaciones: el horario guardado sigue siendo válido.
    assert verificar(datos, a_colocaciones(guardada)).valida


def test_generar_con_errores_de_validacion(tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        repo.guardar(datos.clases[0].model_copy(update={"horas_semanales": 1}))
    with pytest.raises(ErrorValidacion) as error:
        generar(ruta, tiempo_limite_s=5)
    assert any("recibe 1 h" in p.mensaje for p in error.value.problemas)


def test_generar_solucion_invalida_se_guarda_como_tal(monkeypatch: pytest.MonkeyPatch) -> None:
    from timetabling.servicios import generacion

    datos = escuela_minima()

    def verificador_estricto(*_args: object, **_kwargs: object) -> ResultadoVerificacion:
        return ResultadoVerificacion(violaciones=[Violacion(restriccion="D3", mensaje="x")])

    monkeypatch.setattr(generacion, "verificar", verificador_estricto)
    _, solucion = generacion.resolver_y_armar(datos, OpcionesResolucion(tiempo_limite_s=5,
                                                                         hilos=2))  # fmt: skip
    assert solucion is not None
    assert solucion.estado is EstadoSolucion.INVALIDA
    assert solucion.violaciones[0].restriccion == "D3"


def test_cli_generar(tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    resultado = CliRunner().invoke(app, ["generar", str(ruta), "--tiempo-limite", "5",
                                         "--hilos", "2"])  # fmt: skip
    assert resultado.exit_code == 0, resultado.output
    assert "Fase: factibilidad" in resultado.output
    assert "Guardado como «Generado" in resultado.output
    assert "B5 Días con clase por profesor" in resultado.output
