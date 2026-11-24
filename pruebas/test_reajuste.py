"""Creado con Claude.

Reajuste y comparación (§13): reajustar el vigente conserva lo posible (B9), una base
desactualizada se mapea por traslape, el emparejamiento usa `clase_id` o asignatura + grupos, y
la comparación empareja ocurrencias con una asignación de costo mínimo. También el comando,
la hoja `Cambios`, la copia ajustada y la interfaz (Reajustar vigente, Resaltar cambios).
"""

import itertools
import random
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from typer.testing import CliRunner

from pruebas.escuelas import ANA, CARO, INGLES_A, MATE_A, escuela_minima, f, horario_valido
from timetabling.cli import app
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.comparacion import asignacion_minima, comparar
from timetabling.dominio.modelos import DatosEscuela, Disponibilidad, EstadoSolucion, Solucion
from timetabling.gui.app import VentanaPrincipal
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.edicion import nuevo_borrador
from timetabling.servicios.generacion import opciones_de
from timetabling.servicios.reajuste import ErrorReajuste, reajustar, reajustar_en_memoria
from timetabling.servicios.sesion import SesionProyecto
from timetabling.servicios.soluciones import a_colocaciones, a_solucion, mapear_solucion


def _vigente(datos: DatosEscuela, colocaciones: list[Colocacion] | None = None) -> Solucion:
    return a_solucion(datos, colocaciones or horario_valido(), nombre="Vigente",
                      estado=EstadoSolucion.OPTIMO, origen="generado").model_copy(
        update={"id": 1})  # fmt: skip


def _completa() -> DatosEscuela:
    """Escuela mínima que valida: se agrega Inglés de 1°B (clase 15)."""
    datos = escuela_minima()
    ingles = next(c for c in datos.clases if c.id == INGLES_A)
    datos.clases.append(ingles.model_copy(update={"id": 15, "destinatarios": [
        ingles.destinatarios[0].model_copy(update={"grupo_id": 2})]}))  # fmt: skip
    return datos


def _horario_completo() -> list[Colocacion]:
    return [*horario_valido(), Colocacion(15, f("M", 1), (CARO,))]


def _opciones(datos: DatosEscuela) -> Any:
    return opciones_de(datos, tiempo_limite_s=10, hilos=2)


# ---------------------------------------------------------------------------
# Comparación por asignación de costo mínimo
# ---------------------------------------------------------------------------


def test_comparacion_empareja_por_costo_minimo_y_no_en_orden() -> None:
    datos = escuela_minima()
    antes = _vigente(datos)
    # Mismas ocurrencias de Matemáticas 1°A en otro orden de inserción: no hay cambios.
    reordenado = list(reversed(horario_valido()))
    assert comparar(antes, _vigente(datos, reordenado)).sin_cambios
    # Una hora de Matemáticas 1°A pasa del lunes 8:50 al martes 8:50: un solo cambio de hora,
    # y la del lunes 8:00 se empareja consigo misma (no «en orden»).
    movido = [c if c != Colocacion(MATE_A, f("L", 1), (ANA,)) else c.en(f("M", 1))
              for c in horario_valido()]  # fmt: skip
    comparacion = comparar(antes, _vigente(datos, movido))
    assert [(c.tipo, c.antes.texto(), c.despues.texto()) for c in comparacion.cambios] == [  # type: ignore[union-attr]
        ("hora", "Lunes 08:50–09:40 (Ana)", "Martes 08:50–09:40 (Ana)")
    ]
    assert comparacion.clases_afectadas == 1 and comparacion.profesores_afectados == {"Ana"}
    assert comparacion.resumen() == "1 clases y 1 profesores afectados (1 cambios)."


def test_comparacion_tipos_de_cambio() -> None:
    datos = escuela_minima()
    antes = _vigente(datos)
    nuevo = [c for c in horario_valido() if c.clase_id != 13]  # quita Ed. Física 1°A
    nuevo = [Colocacion(c.clase_id, c.franja_id, (ANA,)) if c.clase_id == INGLES_A else c
             for c in nuevo]  # fmt: skip
    nuevo.append(Colocacion(MATE_A, f("M", 3), (ANA,)))  # agregada
    comparacion = comparar(antes, _vigente(datos, nuevo))
    tipos = sorted(c.tipo for c in comparacion.cambios)
    assert tipos == ["agregada", "profesor", "quitada"]
    assert comparacion.marcas() == {
        (c.despues.clase_id, c.despues.indice_franja)
        for c in comparacion.cambios if c.despues is not None
    }  # fmt: skip


def test_asignacion_minima_contra_fuerza_bruta() -> None:
    azar = random.Random(7)
    for _ in range(150):
        n, m = azar.randint(1, 5), azar.randint(1, 5)
        costos = [[float(azar.randint(0, 3)) for _ in range(m)] for _ in range(n)]
        parejas = asignacion_minima(costos)
        k = min(n, m)
        mejor = min(
            sum(costos[i][j] for i, j in zip(filas, columnas, strict=True))
            for filas in itertools.permutations(range(n), k)
            for columnas in itertools.permutations(range(m), k)
        )
        assert len(parejas) == k
        assert sum(costos[i][j] for i, j in parejas) == mejor


# ---------------------------------------------------------------------------
# Mapeo de la base
# ---------------------------------------------------------------------------


def test_mapeo_sin_cambios_y_por_texto() -> None:
    datos = escuela_minima()
    vigente = _vigente(datos)
    mapeo = mapear_solucion(vigente, datos)
    assert not mapeo.por_traslape and mapeo.sin_correspondencia == []
    assert mapeo.colocaciones == sorted(horario_valido())
    # Se borra la clase de Inglés y se crea otra igual con otro id: se empareja por texto.
    ingles = next(c for c in datos.clases if c.id == INGLES_A)
    datos.clases = [c for c in datos.clases if c.id != INGLES_A]
    datos.clases.append(ingles.model_copy(update={"id": 99}))
    mapeo = mapear_solucion(vigente, datos)
    assert Colocacion(99, f("M", 0), (CARO,)) in mapeo.colocaciones
    # Si además cambia de grupos, ya no hay correspondencia.
    datos.clases = [c for c in datos.clases if c.id != 99]
    mapeo = mapear_solucion(vigente, datos)
    assert mapeo.sin_correspondencia == ["Inglés · 1°A (Ma 08:00–08:50)"]


def test_mapeo_por_traslape_si_esta_desactualizada() -> None:
    datos = escuela_minima()
    vigente = _vigente(datos)
    datos.niveles[0].duracion_min = 45  # 8:00–8:45, 8:45–9:30, 10:00–10:45, 10:45–11:30
    mapeo = mapear_solucion(vigente, datos)
    assert mapeo.por_traslape and mapeo.sin_correspondencia == []
    assert [c.franja_id for c in mapeo.colocaciones if c.clase_id == MATE_A] == [
        f("L", 0), f("L", 1)
    ]  # fmt: skip
    # Sin el martes, las clases de ese día quedan sin correspondencia.
    datos.niveles[0].dias = ["L"]
    mapeo = mapear_solucion(vigente, datos)
    assert len(mapeo.sin_correspondencia) == 3
    assert all("(Ma " in texto for texto in mapeo.sin_correspondencia)


# ---------------------------------------------------------------------------
# Reajuste
# ---------------------------------------------------------------------------


def test_reajuste_sin_cambios_en_los_datos() -> None:
    datos = _completa()
    vigente = _vigente(datos, _horario_completo())
    resultado = reajustar_en_memoria(datos, vigente, _opciones(datos))
    assert resultado.comparacion is not None and resultado.comparacion.sin_cambios
    solucion = resultado.generacion.solucion
    assert solucion is not None and solucion.base_id == 1
    assert solucion.nombre == "Reajuste de «Vigente»"
    assert "Reajuste a partir de «Vigente» (id 1)." in solucion.nota
    assert solucion.penalizaciones["B9"] == 0


def test_reajuste_mueve_lo_minimo() -> None:
    """Ana deja de estar disponible el lunes de 8:00 a 8:50: solo Matemáticas de 1°A cambia."""
    datos = _completa()
    vigente = _vigente(datos, _horario_completo())
    datos.profesores[ANA - 1].disponibilidad = [
        Disponibilidad(dia="L", inicio=480, fin=530, tipo="no_disponible")
    ]
    resultado = reajustar_en_memoria(datos, vigente, _opciones(datos))
    comparacion = resultado.comparacion
    assert comparacion is not None and comparacion.clases_afectadas == 1
    assert {c.clase for c in comparacion.cambios} == {"Matemáticas · 1°A"}
    assert resultado.generacion.resolucion.estado is EstadoSolucion.OPTIMO
    solucion = resultado.generacion.solucion
    assert solucion is not None
    assert verificar(datos, a_colocaciones(solucion)).valida
    assert solucion.penalizaciones["B9"] == 2 * len(comparacion.cambios)


def test_reajuste_con_base_desactualizada() -> None:
    datos = _completa()
    vigente = _vigente(datos, _horario_completo())
    datos.niveles[0].duracion_min = 45
    resultado = reajustar_en_memoria(datos, vigente, _opciones(datos))
    assert resultado.mapeo.por_traslape
    solucion = resultado.generacion.solucion
    assert solucion is not None
    assert "se mapeó por traslape" in solucion.nota
    assert verificar(datos, a_colocaciones(solucion)).valida
    assert solucion.penalizaciones["B9"] == 0  # todo cabe en la franja de mayor traslape


def test_reajuste_nunca_es_infactible_por_la_base() -> None:
    datos = _completa()
    base = [*_horario_completo(), Colocacion(MATE_A, f("M", 3), (CARO,))]  # base imposible
    resultado = reajustar_en_memoria(datos, _vigente(datos, base), _opciones(datos))
    assert resultado.generacion.solucion is not None


# ---------------------------------------------------------------------------
# Proyecto, comando, Excel y copia ajustada
# ---------------------------------------------------------------------------


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    ruta = tmp_path / "minima.horario"
    datos = _completa()
    with Repositorio.crear(ruta, datos.configuracion) as repo:
        repo.reemplazar_datos(datos)
        guardada = repo.guardar_solucion(_vigente(datos, _horario_completo()).model_copy(
            update={"id": None}))  # fmt: skip
        repo.marcar_vigente(guardada.id)
    return ruta


def test_cli_reajustar(proyecto: Path, tmp_path: Path) -> None:
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        ana = datos.profesores[ANA - 1]
        repo.guardar(ana.model_copy(update={"disponibilidad": [
            Disponibilidad(dia="L", inicio=480, fin=530, tipo="no_disponible")]}))  # fmt: skip
    resultado = CliRunner().invoke(app, ["reajustar", str(proyecto), "--tiempo-limite", "10",
                                         "--hilos", "2"])  # fmt: skip
    assert resultado.exit_code == 0, resultado.output
    assert "Guardado como «Reajuste de «Vigente»»" in resultado.output
    assert "Cambios respecto al vigente: 1 clases y 1 profesores afectados" in resultado.output
    assert "Matemáticas · 1°A: Lunes 08:00–08:50 (Ana) →" in resultado.output
    sin_vigente = tmp_path / "otro.horario"
    with Repositorio.crear(sin_vigente) as repo:
        repo.reemplazar_datos(_completa())
    otro = CliRunner().invoke(app, ["reajustar", str(sin_vigente)])
    assert otro.exit_code == 2 and "No hay un horario vigente" in otro.output


def test_excel_con_hoja_de_cambios(proyecto: Path, tmp_path: Path) -> None:
    sesion = SesionProyecto.abrir(proyecto)
    try:
        vigente = sesion.cargar_solucion(sesion.vigente().id)  # type: ignore[union-attr]
        movido = [c if c.clase_id != INGLES_A else c.en(f("M", 3))
                  for c in a_colocaciones(vigente)]  # fmt: skip
        otra = sesion.guardar_solucion(a_solucion(sesion.datos, movido, nombre="Otra",
                                                  estado=EstadoSolucion.FACTIBLE,
                                                  origen="manual"))  # fmt: skip
        assert sesion.referencia_de(otra).id == vigente.id  # type: ignore[union-attr]
        ruta = sesion.exportar_excel(otra, tmp_path / "otra.xlsx")
        hoja = openpyxl.load_workbook(ruta)["Cambios"]
        assert [hoja.cell(2, j).value for j in range(1, 5)] == [
            "Inglés · 1°A", "Martes 08:00–08:50 (Caro)", "Martes 10:50–11:40 (Caro)",
            "Cambia la hora",
        ]  # fmt: skip
        assert "Cambios" not in openpyxl.load_workbook(
            sesion.exportar_excel(vigente, tmp_path / "v.xlsx")).sheetnames  # fmt: skip
    finally:
        sesion.cerrar()


def test_copia_ajustada_de_una_solucion_desactualizada(proyecto: Path) -> None:
    sesion = SesionProyecto.abrir(proyecto)
    try:
        vigente = sesion.vigente()
        nivel = sesion.datos.niveles[0]
        sesion.guardar(nivel.model_copy(update={"duracion_min": 45}))
        assert sesion.desactualizada(vigente)  # type: ignore[arg-type]
        copia = nuevo_borrador(sesion, copia_de=vigente.id)  # type: ignore[union-attr]
        assert copia.nombre == "Copia ajustada de Vigente"
        assert "ajustada por traslape" in copia.nota
        assert not sesion.desactualizada(copia)
        assert len(a_colocaciones(copia)) == 8
    finally:
        sesion.cerrar()


def test_reajustar_sin_vigente(tmp_path: Path) -> None:
    ruta = tmp_path / "v.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(_completa())
    with pytest.raises(ErrorReajuste):
        reajustar(ruta)


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------


def test_gui_reajustar_y_resaltar_cambios(
    ventana: VentanaPrincipal, proyecto: Path, qtbot: Any
) -> None:
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        repo.guardar(datos.profesores[ANA - 1].model_copy(update={"disponibilidad": [
            Disponibilidad(dia="L", inicio=480, fin=530, tipo="no_disponible")]}))  # fmt: skip
        repo.guardar_configuracion(datos.configuracion.model_copy(
            update={"tiempo_limite_s": 10, "hilos": 2}))  # fmt: skip
    ventana.abrir_proyecto(proyecto)
    generar: Any = ventana.ir_a("generar")
    assert generar.boton_reajustar.isEnabled()
    with qtbot.waitSignal(generar.termino, timeout=60_000):
        generar.reajustar()
    assert "Cambios respecto al vigente: 1 clases y 1 profesores afectados" in (
        generar.resultado.text()
    )
    generar.boton_ver.click()
    resultados: Any = ventana.pantalla_actual()
    assert resultados.solucion.nombre == "Reajuste de «Vigente»"
    assert "respecto a «Vigente»: 1 clases y 1 profesores afectados" in resultados.info.text()
    assert resultados.tabla_cambios.rowCount() == len(resultados.comparacion.cambios)
    assert resultados.tabla_cambios.item(0, 0).text() == "Matemáticas · 1°A"
    resultados.por_grupo.selector.setCurrentText("1°A")
    textos = [resultados.por_grupo.vista.texto(i, j) for i in range(5) for j in range(2)]
    assert not any(t.startswith("↻") for t in textos)
    resultados.boton_cambios.setChecked(True)
    textos = [resultados.por_grupo.vista.texto(i, j) for i in range(5) for j in range(2)]
    assert any(t.startswith("↻ Matemáticas") for t in textos)
