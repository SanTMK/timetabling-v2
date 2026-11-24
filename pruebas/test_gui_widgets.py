"""Creado con Claude.

Widgets de la interfaz: editor de disponibilidad (arrastrar, teclado, copiar día, aviso de
franjas parcialmente cubiertas), cuadrícula de franjas y tablas de filas.
"""

from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget

from timetabling.dominio.modelos import Disponibilidad, RangoFranjas
from timetabling.gui.widgets.campos import Columna, DiasSelector, HoraEdit, TablaFilas
from timetabling.gui.widgets.cuadricula_franjas import CuadriculaFranjas
from timetabling.gui.widgets.disponibilidad import (
    ALTO_FILA,
    MARGEN_IZQ,
    MARGEN_SUP,
    EditorDisponibilidad,
)
from timetabling.nucleo.franjas import Franja


def _editor(qtbot: Any) -> EditorDisponibilidad:
    editor = EditorDisponibilidad()
    qtbot.addWidget(editor)
    editor.resize(MARGEN_IZQ + 5 * 100, 400)
    editor.configurar(["L", "M", "X", "J", "V"], 7 * 60, 9 * 60, [])
    editor.show()
    return editor


def _punto(editor: EditorDisponibilidad, columna: int, minuto: int) -> QPoint:
    ancho = editor._ancho_columna()
    fila = (minuto - editor.inicio) // 5
    return QPoint(int(MARGEN_IZQ + columna * ancho + ancho / 2),
                  MARGEN_SUP + fila * ALTO_FILA + ALTO_FILA // 2)  # fmt: skip


def test_arrastrar_marca_un_rango(qtbot: Any) -> None:
    editor = _editor(qtbot)
    qtbot.mousePress(editor, Qt.MouseButton.LeftButton, pos=_punto(editor, 0, 420))
    for minuto in range(425, 480, 5):
        qtbot.mouseMove(editor, _punto(editor, 0, minuto))
    qtbot.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=_punto(editor, 0, 475))
    assert editor.leer() == [Disponibilidad(dia="L", inicio=420, fin=480)]


def test_herramientas_y_union_de_rangos(qtbot: Any) -> None:
    editor = _editor(qtbot)
    editor.marcar("M", 420, 480, "disponible")
    editor.marcar("M", 480, 500, "preferible_no")
    editor.marcar("M", 500, 540, "disponible")
    editor.herramienta = "no_disponible"
    qtbot.mouseClick(editor, Qt.MouseButton.LeftButton, pos=_punto(editor, 1, 425))
    assert editor.leer() == [
        Disponibilidad(dia="M", inicio=420, fin=425),
        Disponibilidad(dia="M", inicio=425, fin=430, tipo="no_disponible"),
        Disponibilidad(dia="M", inicio=430, fin=480),
        Disponibilidad(dia="M", inicio=480, fin=500, tipo="preferible_no"),
        Disponibilidad(dia="M", inicio=500, fin=540),
    ]
    editor.herramienta = None
    qtbot.mouseClick(editor, Qt.MouseButton.LeftButton, pos=_punto(editor, 1, 425))
    assert Disponibilidad(dia="M", inicio=425, fin=430, tipo="no_disponible") not in editor.leer()


def test_copiar_dia_y_limpiar(qtbot: Any) -> None:
    editor = _editor(qtbot)
    editor.poner([Disponibilidad(dia="L", inicio=450, fin=500)])
    editor.copiar_dia("L")
    assert {d.dia for d in editor.leer()} == {"L", "M", "X", "J", "V"}
    editor.limpiar()
    assert editor.leer() == []


def test_teclado(qtbot: Any) -> None:
    editor = _editor(qtbot)
    editor.setFocus()
    qtbot.keyClick(editor, Qt.Key.Key_Right)
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    qtbot.keyClick(editor, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert editor.leer() == [Disponibilidad(dia="M", inicio=420, fin=430)]


def test_aviso_de_franja_parcialmente_cubierta(ventana: Any, tmp_path: Any) -> None:
    from timetabling.ejemplo import crear_ejemplo

    ventana.abrir_proyecto(crear_ejemplo(tmp_path / "p.horario"))
    profesores: Any = ventana.ir_a("profesores")
    profesores.elegir("Ana López")
    profesores.toda_jornada.setChecked(False)
    profesores.editor.marcar("L", 450, 520, "disponible")  # 7:30–8:40 corta 7:30–8:20/8:20–9:10
    assert "L 08:20–09:10" in profesores.aviso.text()
    profesores.editor.marcar("L", 520, 550, "disponible")
    assert profesores.aviso.text() == ""


def test_cuadricula_de_franjas(qtbot: Any) -> None:
    cuadricula = CuadriculaFranjas()
    qtbot.addWidget(cuadricula)
    franjas = {d: [Franja(1, d, i, 450 + 50 * i, 500 + 50 * i) for i in range(4)] for d in "LM"}
    cuadricula.configurar(franjas)  # type: ignore[arg-type]
    por_hora = [RangoFranjas(desde=450, hasta=560)]
    cuadricula.poner([RangoFranjas(dias=("M",), desde_indice=3, hasta_indice=3)], por_hora)
    assert cuadricula.estados[("M", 3)] == "prohibida"
    assert cuadricula.estados[("L", 1)] == "preferida"
    # Sin tocarla, conserva los rangos originales (también los de hora).
    assert cuadricula.rangos()[1] == por_hora
    cuadricula.alternar(0, 0)  # L 1.ª: preferida → normal
    cuadricula.alternar(2, 0)  # L 3.ª: normal → prohibida
    prohibidas, preferidas = cuadricula.rangos()
    assert prohibidas == [
        RangoFranjas(dias=("L",), desde_indice=2, hasta_indice=2),
        RangoFranjas(dias=("M",), desde_indice=3, hasta_indice=3),
    ]
    assert preferidas == [
        RangoFranjas(dias=("L",), desde_indice=1, hasta_indice=1),
        RangoFranjas(dias=("M",), desde_indice=0, hasta_indice=1),
    ]
    cuadricula.setCurrentCell(3, 0)
    qtbot.keyClick(cuadricula, Qt.Key.Key_Space)
    assert cuadricula.estados[("L", 3)] == "prohibida"


def test_tabla_de_filas_y_dias(qtbot: Any) -> None:
    padre = QWidget()
    qtbot.addWidget(padre)
    tabla = TablaFilas(
        [Columna("nombre", "Nombre", "texto", "Receso"), Columna("inicio", "Inicio", "hora", 600),
         Columna("dia", "Día", "dia", "L"), Columna("n", "N", "entero", 3),
         Columna("si", "Sí", "booleano", True)],
        padre,
    )  # fmt: skip
    cambios: list[int] = []
    tabla.cambiado.connect(lambda: cambios.append(1))
    tabla.agregar()
    tabla.agregar({"nombre": "Comida", "inicio": 720, "dia": "X", "n": 5, "si": False})
    assert tabla.filas() == [
        {"nombre": "Receso", "inicio": 600, "dia": "L", "n": 3, "si": True},
        {"nombre": "Comida", "inicio": 720, "dia": "X", "n": 5, "si": False},
    ]
    tabla.tabla.setCurrentCell(0, 0)
    tabla.quitar_seleccionada()
    assert [f["nombre"] for f in tabla.filas()] == ["Comida"]
    assert cambios
    dias = DiasSelector()
    qtbot.addWidget(dias)
    dias.poner(["V", "L"])
    assert dias.dias() == ["L", "V"]
    hora = HoraEdit(615)
    qtbot.addWidget(hora)
    assert hora.minutos() == 615 and hora.text() == "10:15"
