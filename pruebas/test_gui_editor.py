"""Creado con Claude.

Editor manual (§12, pytest-qt): arrastrar y soltar, colores de validez, intercambio,
«Colocar y reacomodar», modo estricto y flexible, bloquear, teclado (Supr, Alt+flechas),
deshacer y rehacer, panel «Por colocar», vista maestra, «Completar el resto», «Editar una
copia» y fijas para generar.
"""

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent

from pruebas.escuelas import (
    ANA,
    CARO,
    FISICA_A,
    INGLES_A,
    MATE_A,
    escuela_minima,
    f,
    horario_valido,
)
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import Destinatario, EstadoSolucion
from timetabling.gui.app import VentanaPrincipal
from timetabling.gui.widgets.rejilla_editor import mime_de
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.soluciones import a_solucion

ESPERA_MS = 60_000


def _proyecto(
    tmp_path: Path, colocaciones: list[Colocacion], ingles_b: bool = False
) -> tuple[Path, int]:
    ruta = tmp_path / "minima.horario"
    datos = escuela_minima()
    if ingles_b:  # Inglés de 1°B: sin esto, la escuela mínima no pasa la validación
        ingles = next(c for c in datos.clases if c.id == INGLES_A)
        datos.clases.append(
            ingles.model_copy(update={"id": 15, "destinatarios": [Destinatario(grupo_id=2)]})
        )
    with Repositorio.crear(ruta, datos.configuracion) as repo:
        repo.reemplazar_datos(datos)
        solucion = a_solucion(datos, colocaciones, nombre="Borrador de prueba",
                              estado=EstadoSolucion.BORRADOR, origen="manual")  # fmt: skip
        ident = repo.guardar_solucion(solucion).id or 0
    return ruta, ident


def _editor(
    ventana: VentanaPrincipal, tmp_path: Path, colocaciones: list[Colocacion],
    ingles_b: bool = False,
) -> Any:  # fmt: skip
    ruta, ident = _proyecto(tmp_path, colocaciones, ingles_b)
    ventana.abrir_proyecto(ruta)
    editor: Any = ventana.ir_a("editor")
    editor.abrir_borrador(ident)
    editor.combo_grupo.setCurrentText("1°A")
    return editor


def _texto(editor: Any, franja: str) -> str:
    fila, columna = editor.rejilla.posiciones[franja][0]
    return editor.rejilla.item(fila, columna).text()


def _soltar_con_raton(editor: Any, clase: int, origen: str | None, destino: str) -> None:
    """Simula soltar un arrastre (con los datos MIME reales) sobre la celda destino."""
    rejilla = editor.rejilla
    mime = mime_de(clase, Colocacion(clase, origen, ()) if origen else None)
    punto = QPointF(rejilla.centro_de(destino))
    evento = QDropEvent(punto, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)  # fmt: skip
    rejilla.dropEvent(evento)


def _clic(qtbot: Any, boton: Any) -> None:
    qtbot.mouseClick(boton, Qt.MouseButton.LeftButton)


def _colocacion(editor: Any, clase: int, franja: str) -> Colocacion | None:
    return editor.edicion.borrador.buscar(clase, franja)


def test_colores_al_tomar_una_clase(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    editor = _editor(ventana, tmp_path, horario_valido())
    editor.tomar(INGLES_A, f("M", 0))
    assert _texto(editor, f("M", 3)).startswith("✓")  # libre y válida
    assert _texto(editor, f("L", 2)).startswith("✗ Ed. Física")  # 1°A ya tiene Ed. Física
    fila, columna = editor.rejilla.posiciones[f("L", 2)][0]
    tooltip = editor.rejilla.item(fila, columna).toolTip()
    assert "1°A ya tiene Ed. Física · 1°A el lunes de 10:00–10:50." in tooltip
    color = editor.rejilla.item(fila, columna).background().color().name()
    assert color == "#ffcdd2"
    editor.soltar_toma()
    assert not _texto(editor, f("M", 3)).startswith("✓")


def test_arrastrar_y_deshacer(ventana: VentanaPrincipal, tmp_path: Path, qtbot: Any) -> None:
    editor = _editor(ventana, tmp_path, horario_valido())
    _soltar_con_raton(editor, INGLES_A, f("M", 0), f("M", 3))
    assert _colocacion(editor, INGLES_A, f("M", 3)) is not None
    assert _colocacion(editor, INGLES_A, f("M", 0)) is None
    assert "Inglés" in _texto(editor, f("M", 3))
    assert editor.boton_deshacer.isEnabled()
    _clic(qtbot, editor.boton_deshacer)
    assert _colocacion(editor, INGLES_A, f("M", 0)) is not None
    _clic(qtbot, editor.boton_rehacer)
    assert _colocacion(editor, INGLES_A, f("M", 3)) is not None
    # Se guardó al instante.
    with Repositorio.abrir(ventana.contexto.sesion.ruta, respaldo_diario=False) as repo:  # type: ignore[union-attr]
        guardada = repo.cargar_solucion(editor.edicion.solucion.id)
    lugares = {
        (guardada.franjas[a.franja].dia, guardada.franjas[a.franja].indice)
        for a in guardada.asignaciones
        if a.clase_id == INGLES_A
    }
    assert lugares == {("M", 3)}


def test_arrastrar_una_tarjeta_y_elegir_profesor(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    sin_ingles = [c for c in horario_valido() if c.clase_id != INGLES_A]
    editor = _editor(ventana, tmp_path, sin_ingles)
    assert [t.clase_id for t in editor.panel.visibles()] == [INGLES_A]
    assert "faltan 1 de 1" in editor.panel.lista.item(0).text()
    assert editor.etiqueta_pendientes.text() == "Pendientes: 1"
    ventana.dialogos.responder(CARO)  # type: ignore[attr-defined]
    _soltar_con_raton(editor, INGLES_A, None, f("M", 3))
    colocada = _colocacion(editor, INGLES_A, f("M", 3))
    assert colocada is not None and colocada.profesores == (CARO,)
    assert ventana.dialogos.mostrados[-1][0] == "Elegir profesor"  # type: ignore[attr-defined]
    assert editor.panel.lista.count() == 0
    assert editor.etiqueta_pendientes.text() == "Pendientes: 0"


def test_intercambiar(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    colocaciones = [c if c.clase_id != FISICA_A else c.en(f("M", 3)) for c in horario_valido()]
    editor = _editor(ventana, tmp_path, colocaciones)
    ventana.dialogos.responder(True)  # type: ignore[attr-defined]
    editor.tomar(INGLES_A, f("M", 0))
    editor.soltar(f("M", 3))
    assert ventana.dialogos.mostrados[-1][0] == "Intercambiar"  # type: ignore[attr-defined]
    assert _colocacion(editor, INGLES_A, f("M", 3)) is not None
    assert _colocacion(editor, FISICA_A, f("M", 0)) is not None
    editor.pila.undo()
    assert _colocacion(editor, INGLES_A, f("M", 0)) is not None
    assert _colocacion(editor, FISICA_A, f("M", 3)) is not None


def test_colocar_y_reacomodar(ventana: VentanaPrincipal, tmp_path: Path, qtbot: Any) -> None:
    sin_ingles = [c for c in horario_valido() if c.clase_id != INGLES_A]
    editor = _editor(ventana, tmp_path, sin_ingles)
    ventana.dialogos.responder(True, True)  # type: ignore[attr-defined]  # reacomodar y aplicar
    editor.tomar(INGLES_A)
    with qtbot.waitSignal(editor.tarea_terminada, timeout=ESPERA_MS):
        editor.soltar(f("L", 2))
    titulos = [t for t, _ in ventana.dialogos.mostrados]  # type: ignore[attr-defined]
    assert "Colocar y reacomodar lo mínimo" in titulos
    assert "Vista previa del reacomodo" in titulos
    vista_previa = dict(ventana.dialogos.mostrados)["Vista previa del reacomodo"]  # type: ignore[attr-defined]
    assert "Ed. Física · 1°A" in vista_previa
    assert _colocacion(editor, INGLES_A, f("L", 2)) is not None
    assert editor.etiqueta_conflictos.text() == "Conflictos: 0"
    editor.pila.undo()
    assert _colocacion(editor, INGLES_A, f("L", 2)) is None
    assert _colocacion(editor, FISICA_A, f("L", 2)) is not None


def test_estricto_y_flexible(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    sin_ingles = [c for c in horario_valido() if c.clase_id != INGLES_A]
    editor = _editor(ventana, tmp_path, sin_ingles)
    editor.tomar(INGLES_A)
    ventana.dialogos.responder(False)  # type: ignore[attr-defined]  # no reacomodar
    editor.soltar(f("L", 1))
    assert _colocacion(editor, INGLES_A, f("L", 1)) is None
    editor.flexible.setChecked(True)
    ventana.dialogos.responder(True, CARO)  # type: ignore[attr-defined]
    editor.tomar(INGLES_A)
    editor.soltar(f("L", 1))
    assert _colocacion(editor, INGLES_A, f("L", 1)) is not None
    assert editor.etiqueta_conflictos.text() != "Conflictos: 0"
    assert "⚠" in _texto(editor, f("L", 1))
    assert editor.lista_conflictos.count() >= 1


def test_bloquear_quitar_y_mover_con_teclado(
    ventana: VentanaPrincipal, tmp_path: Path, qtbot: Any
) -> None:
    editor = _editor(ventana, tmp_path, horario_valido())
    rejilla = editor.rejilla
    editor.tomar(INGLES_A, f("M", 0))
    editor.soltar_toma()
    editor.bloquear_seleccion()
    assert _texto(editor, f("M", 0)).startswith("📌 Inglés")
    assert _colocacion(editor, INGLES_A, f("M", 0)).bloqueada  # type: ignore[union-attr]
    editor.pila.undo()
    assert not _texto(editor, f("M", 0)).startswith("📌")
    # Alt+↓ mueve una franja abajo (de la 1.ª a la 2.ª del martes).
    rejilla.ir_a_franja(f("M", 0))
    editor.tomar(INGLES_A, f("M", 0))
    editor.soltar_toma()
    qtbot.keyClick(rejilla, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert _colocacion(editor, INGLES_A, f("M", 1)) is not None
    # Supr la devuelve al panel.
    rejilla.ir_a_franja(f("M", 1))
    qtbot.keyClick(rejilla, Qt.Key.Key_Delete)
    assert _colocacion(editor, INGLES_A, f("M", 1)) is None
    assert editor.etiqueta_pendientes.text() == "Pendientes: 1"


def test_cambiar_profesor_y_porque_no(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    editor = _editor(ventana, tmp_path, horario_valido())
    ventana.dialogos.responder(ANA)  # type: ignore[attr-defined]
    editor.cambiar_profesor(INGLES_A)
    assert _colocacion(editor, INGLES_A, f("M", 0)).profesores == (ANA,)  # type: ignore[union-attr]
    editor.tomar(INGLES_A, f("M", 0))
    assert "1°A ya tiene Matemáticas" in editor.porque_no(f("L", 1))
    assert editor.porque_no(f("M", 3)) == "Puede ir ahí sin problemas."


def test_panel_filtros_y_sugerir(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    editor = _editor(ventana, tmp_path, [])
    assert editor.panel.lista.count() == 5
    editor.panel.grupo.setCurrentText("1°B")
    assert {t.clase_id for t in editor.panel.visibles()} == {11, 14}
    editor.panel.grupo.setCurrentIndex(0)
    editor.panel.busqueda.setText("inglés")
    assert [t.clase_id for t in editor.panel.visibles()] == [INGLES_A]
    editor.panel.elegir(INGLES_A)
    editor.sugerir()
    assert len(editor.sugeridas) == 3
    estrellas = [franja for franja in editor.sugeridas if _texto(editor, franja).startswith("★")]
    assert len(estrellas) == 3


def test_vistas(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    editor = _editor(ventana, tmp_path, horario_valido())
    editor.pestanas.setCurrentIndex(3)  # vista maestra
    assert editor.rejilla.rowCount() == 2 and editor.rejilla.columnCount() == 8
    editor.pestanas.setCurrentIndex(1)
    editor.combo_profesor.setCurrentText("Caro")
    assert "Caro" in editor.etiqueta_carga.text()
    assert "Inglés" in _texto(editor, f("M", 0))
    editor.pestanas.setCurrentIndex(2)
    assert editor.combo_espacio.currentText().startswith("cancha")


def test_completar_el_resto(ventana: VentanaPrincipal, tmp_path: Path, qtbot: Any) -> None:
    bloqueada = Colocacion(MATE_A, f("M", 2), (ANA,), bloqueada=True)
    editor = _editor(ventana, tmp_path, [bloqueada])
    original = editor.edicion.solucion.id
    with qtbot.waitSignal(editor.tarea_terminada, timeout=ESPERA_MS):
        editor.completar()
    assert editor.edicion.solucion.id != original
    assert editor.selector.currentText().startswith("Borrador de prueba (completado)")
    assert editor.etiqueta_pendientes.text() == "Pendientes: 0"
    assert _colocacion(editor, MATE_A, f("M", 2)).bloqueada  # type: ignore[union-attr]
    assert (
        "↻" in _texto(editor, f("L", 0))
        or "↻" in _texto(editor, f("L", 1))
        or any("↻" in _texto(editor, franja) for franja in editor.rejilla.posiciones)
    )
    # Validar y guardar como definitivo.
    editor.validar_definitivo()
    assert "FACTIBLE" in ventana.dialogos.mostrados[-1][1]  # type: ignore[attr-defined]
    estados = {s.nombre: s.estado for s in ventana.contexto.sesion.soluciones()}  # type: ignore[union-attr]
    assert estados["Borrador de prueba (completado)"] is EstadoSolucion.FACTIBLE


def test_editar_una_copia_desde_resultados(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ruta = tmp_path / "minima.horario"
    datos = escuela_minima()
    with Repositorio.crear(ruta, datos.configuracion) as repo:
        repo.reemplazar_datos(datos)
        generado = a_solucion(
            datos, horario_valido(), nombre="Generado", estado=EstadoSolucion.OPTIMO,
            origen="generado",
        )  # fmt: skip
        repo.guardar_solucion(generado)
    ventana.abrir_proyecto(ruta)
    resultados: Any = ventana.ir_a("resultados")
    resultados.editar_copia()
    editor: Any = ventana.pantalla_actual()
    assert editor.clave == "editor"
    assert editor.selector.currentText().startswith("Copia de Generado")
    assert len(editor.edicion.borrador.colocaciones) == 7


def test_generar_usa_las_bloqueadas(ventana: VentanaPrincipal, tmp_path: Path, qtbot: Any) -> None:
    bloqueada = Colocacion(INGLES_A, f("M", 3), (CARO,), bloqueada=True)
    _editor(ventana, tmp_path, [bloqueada], ingles_b=True)
    generar: Any = ventana.ir_a("generar")
    assert generar.boton_generar.isEnabled(), generar.estado_datos.text()
    assert "1 clases bloqueadas en «Borrador de prueba»" in generar.fijas.text()
    with qtbot.waitSignal(generar.termino, timeout=ESPERA_MS) as senal:
        generar.generar()
    solucion = senal.args[0].solucion
    franjas = {i: s for i, s in enumerate(solucion.franjas)}
    assert any(a.clase_id == INGLES_A and franjas[a.franja].dia == "M"
               and franjas[a.franja].indice == 3 for a in solucion.asignaciones)  # fmt: skip


@pytest.mark.parametrize("vista", [0, 3])
def test_seleccion_resaltada(ventana: VentanaPrincipal, tmp_path: Path, vista: int) -> None:
    editor = _editor(ventana, tmp_path, horario_valido())
    editor.pestanas.setCurrentIndex(vista)
    editor.tomar(MATE_A, f("L", 0))
    fila, columna = editor.rejilla.posiciones[f("L", 0)][0]
    assert editor.rejilla.item(fila, columna).font().bold()
