"""Creado con Claude.

Criterio de aceptación de F7 (pytest-qt): «abrir mediano → generar → marcar vigente →
exportar». También: solo lectura mientras se resuelve, cancelar, diagnóstico con enlaces y
cierre de la ventana durante la generación.
"""

from pathlib import Path
from typing import Any

import openpyxl
from PySide6.QtCore import Qt

from timetabling.dominio.modelos import EstadoSolucion
from timetabling.ejemplo import crear_ejemplo
from timetabling.gui.app import VentanaPrincipal
from timetabling.persistencia.repositorio import Repositorio

ESPERA_MS = 120_000


def _clic(qtbot: Any, boton: Any) -> None:
    qtbot.mouseClick(boton, Qt.MouseButton.LeftButton)


def _tiempo_limite(ventana: VentanaPrincipal, qtbot: Any, segundos: int) -> None:
    config: Any = ventana.ir_a("configuracion")
    config.tiempo.setValue(segundos)
    config.hilos.setValue(2)
    _clic(qtbot, config.boton_guardar)


def _generar(ventana: VentanaPrincipal, qtbot: Any) -> Any:
    generar: Any = ventana.ir_a("generar")
    with qtbot.waitSignal(generar.termino, timeout=ESPERA_MS) as senal:
        _clic(qtbot, generar.boton_generar)
        assert ventana.generando
    return senal.args[0]


def test_abrir_mediano_generar_marcar_vigente_y_exportar(
    ventana: VentanaPrincipal, qtbot: Any, tmp_path: Path
) -> None:
    ruta = crear_ejemplo(tmp_path / "mediano.horario", "mediano")
    ventana.dialogos.responder(ruta)  # type: ignore[attr-defined]
    _clic(qtbot, ventana.pantallas["inicio"].boton_abrir)  # type: ignore[attr-defined]
    _tiempo_limite(ventana, qtbot, 8)

    resultado = _generar(ventana, qtbot)
    generar: Any = ventana.pantallas["generar"]
    assert resultado.solucion is not None
    assert generar.resultado.text().startswith("✔ ")
    assert not ventana.generando

    _clic(qtbot, generar.boton_ver)
    resultados: Any = ventana.pantalla_actual()
    assert resultados.clave == "resultados"
    assert (
        resultados.solucion is not None and resultados.solucion.id == generar.solucion_guardada_id
    )
    assert resultados.solucion.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert resultados.por_grupo.selector.count() == 30
    assert resultados.por_profesor.selector.count() == 42
    assert resultados.por_grupo.vista.rowCount() > 0
    assert resultados.penalizaciones.rowCount() >= 9
    assert resultados.carga.rowCount() == 42

    _clic(qtbot, resultados.boton_vigente)
    assert resultados.selector.currentText().startswith("★ ")
    assert "★ vigente" in resultados.info.text()
    inicio: Any = ventana.ir_a("inicio")
    assert "Horario vigente" in inicio.vigente.text()

    resultados = ventana.ir_a("resultados")
    salida = tmp_path / "mediano.xlsx"
    ventana.dialogos.responder(salida)  # type: ignore[attr-defined]
    _clic(qtbot, resultados.boton_excel)  # type: ignore[attr-defined]
    libro = openpyxl.load_workbook(salida)
    assert libro.sheetnames[0] == "Resumen" and "CargaDocente" in libro.sheetnames
    assert "8°A" in libro.sheetnames and "Sara Kim" in libro.sheetnames
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        assert repo.solucion_vigente_id() == generar.solucion_guardada_id


def test_solo_lectura_mientras_se_genera_y_cancelar(
    ventana: VentanaPrincipal, qtbot: Any, tmp_path: Path
) -> None:
    ventana.abrir_proyecto(crear_ejemplo(tmp_path / "m.horario", "mediano"))
    _tiempo_limite(ventana, qtbot, 120)
    generar: Any = ventana.ir_a("generar")
    with qtbot.waitSignal(generar.termino, timeout=ESPERA_MS) as senal:
        _clic(qtbot, generar.boton_generar)
        assert not ventana.pantallas["niveles"].isEnabled()
        assert ventana.pantallas["validacion"].isEnabled()
        assert ventana.pantallas["resultados"].isEnabled()
        assert generar.boton_cancelar.isEnabled() and not generar.boton_generar.isEnabled()
        ventana.ir_a("niveles")  # se puede navegar
        qtbot.waitUntil(lambda: generar.soluciones.text() not in ("—", "0"), timeout=ESPERA_MS)
        _clic(qtbot, generar.boton_cancelar)
    resultado = senal.args[0]
    assert resultado.resolucion.estado is EstadoSolucion.CANCELADO
    assert resultado.solucion is not None and resultado.solucion.estado is EstadoSolucion.CANCELADO
    assert ventana.pantallas["niveles"].isEnabled()
    assert "CANCELADO" in generar.resultado.text()


def test_infactible_muestra_el_diagnostico_con_enlaces(
    ventana: VentanaPrincipal, qtbot: Any, tmp_path: Path
) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        for profesor in repo.cargar_datos().profesores:
            if profesor.nombre in ("Irene Castro", "Luis Navarro"):
                repo.guardar(profesor.model_copy(update={"max_dias": 2,
                                                         "carga_max_diaria_min": 50}))  # fmt: skip
    ventana.abrir_proyecto(ruta)
    _tiempo_limite(ventana, qtbot, 20)
    resultado = _generar(ventana, qtbot)
    generar: Any = ventana.pantallas["generar"]
    assert resultado.solucion is None and resultado.diagnostico is not None
    assert "El conflicto involucra" in generar.resultado.text()
    enlaces = [generar.capa_enlaces.itemAt(i).widget() for i in range(generar.capa_enlaces.count())]
    irene = next(b for b in enlaces if "Irene Castro" in b.text())
    _clic(qtbot, irene)
    assert ventana.pantalla_actual().clave == "profesores"
    assert ventana.pantalla_actual().nombre.text() == "Irene Castro"  # type: ignore[attr-defined]


def test_cerrar_durante_la_generacion_guarda_cancelado(
    ventana: VentanaPrincipal, qtbot: Any, tmp_path: Path
) -> None:
    ruta = crear_ejemplo(tmp_path / "m.horario", "mediano")
    ventana.abrir_proyecto(ruta)
    _tiempo_limite(ventana, qtbot, 120)
    generar: Any = ventana.ir_a("generar")
    _clic(qtbot, generar.boton_generar)
    qtbot.waitUntil(lambda: generar.soluciones.text() not in ("—", "0"), timeout=ESPERA_MS)
    assert ventana.close()
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        estados = [s.estado for s in repo.listar_soluciones()]
    assert estados == [EstadoSolucion.CANCELADO]


def test_generar_con_errores_no_arranca(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        clase = repo.cargar_datos().clases[0]
        repo.guardar(clase.model_copy(update={"horas_semanales": 1}))
    ventana.abrir_proyecto(ruta)
    generar: Any = ventana.ir_a("generar")
    assert not generar.boton_generar.isEnabled()
    assert "errores de validación" in generar.estado_datos.text()


def test_resultados_sin_soluciones(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ventana.abrir_proyecto(crear_ejemplo(tmp_path / "p.horario"))
    resultados: Any = ventana.ir_a("resultados")
    assert "Todavía no hay soluciones" in resultados.info.text()
    assert not resultados.boton_vigente.isEnabled()
