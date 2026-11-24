"""Creado con Claude.

Criterio de aceptación de F6: se captura el ejemplo pequeño desde cero solo con la interfaz
(pytest-qt), y el resultado coincide con `ejemplo_pequeno()`, valida sin problemas y se puede
resolver.
"""

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt

from timetabling.dominio.modelos import DatosEscuela, EstadoSolucion, RangoFranjas
from timetabling.dominio.tiempo import a_minutos
from timetabling.ejemplo import ejemplo_pequeno
from timetabling.gui.app import VentanaPrincipal
from timetabling.nucleo.resolver import OpcionesResolucion, resolver
from timetabling.nucleo.validacion import validar

ASIGNATURAS = [
    "Español", "Matemáticas", "Ciencias", "Inglés", "Ed. Física", "Artes", "Formación Cívica",
]  # fmt: skip
PROFESORES = {
    "Ana López": ["Español"],
    "Bruno Díaz": ["Español"],
    "Carla Méndez": ["Matemáticas"],
    "Diego Ruiz": ["Matemáticas"],
    "Elena Torres": ["Ciencias"],
    "Fernando Gil": ["Ciencias", "Formación Cívica"],
    "Gabriela Sosa": ["Inglés"],
    "Héctor Vega": ["Inglés"],
    "Irene Castro": ["Ed. Física"],
    "Jorge Peña": ["Artes"],
    "Karla Ríos": ["Español", "Matemáticas", "Formación Cívica"],
    "Luis Navarro": ["Artes", "Ed. Física"],
}


def _clic(qtbot: Any, boton: Any) -> None:
    qtbot.mouseClick(boton, Qt.MouseButton.LeftButton)


def _ids(lista: Any, textos: list[str]) -> list[int]:
    """Ids de una ListaMarcable cuyas etiquetas empiezan con alguno de los textos."""
    resultado = []
    for i in range(lista.count()):
        item = lista.item(i)
        if any(item.text().startswith(t) for t in textos):
            resultado.append(int(item.data(Qt.ItemDataRole.UserRole)))
    return resultado


def _por_nombre(datos: DatosEscuela) -> dict[str, Any]:
    """Resumen comparable por nombres (sin ids)."""
    asignaturas = {a.id: a.nombre for a in datos.asignaturas}
    grados = {g.id: g.nombre for g in datos.grados}
    return {
        "niveles": [(n.nombre, n.duracion_min, n.inicio_jornada, n.fin_jornada, n.dias,
                     [(r.inicio, r.fin) for r in n.recesos]) for n in datos.niveles],
        "grupos": sorted(datos.nombre_grupo(g.id or 0) for g in datos.grupos),
        "asignaturas": sorted(
            (a.nombre, a.reglas_por_defecto.max_horas_dia) for a in datos.asignaturas
        ),
        "plan": sorted((grados[f.grado_id], asignaturas[f.asignatura_id], f.horas_semanales)
                       for f in datos.plan),
        "profesores": sorted(
            (p.nombre, tuple(sorted(asignaturas[a] for a in p.asignaturas)),
             tuple(sorted(grados[g] for g in p.grados)))
            for p in datos.profesores
        ),
        "clases": sorted(
            (asignaturas[c.asignatura_id], datos.nombre_grupo(c.destinatarios[0].grupo_id),
             c.horas_semanales)
            for c in datos.clases
        ),
    }  # fmt: skip


def test_capturar_el_ejemplo_pequeno_desde_cero(
    ventana: VentanaPrincipal, qtbot: Any, tmp_path: Path
) -> None:
    dialogos = ventana.dialogos
    # Inicio → Nuevo proyecto.
    dialogos.responder(tmp_path / "pequeno.horario")  # type: ignore[attr-defined]
    _clic(qtbot, ventana.pantallas["inicio"].boton_nuevo)  # type: ignore[attr-defined]
    assert ventana.contexto.sesion is not None

    # Configuración.
    config = ventana.ir_a("configuracion")
    config.nombre.setText("Escuela de ejemplo (pequeña)")  # type: ignore[attr-defined]
    _clic(qtbot, config.boton_guardar)  # type: ignore[attr-defined]
    assert not config.hay_cambios()

    # Niveles.
    niveles: Any = ventana.ir_a("niveles")
    _clic(qtbot, niveles.boton_nuevo)
    niveles.nombre.setText("Primaria")
    niveles.duracion.setValue(50)
    niveles.inicio.poner(a_minutos("07:30"))
    niveles.fin.poner(a_minutos("14:00"))
    niveles.recesos.agregar({"nombre": "Recreo", "inicio": 600, "fin": 630})
    assert "35 franjas útiles" in niveles.aviso_vista.text()
    _clic(qtbot, niveles.boton_guardar)
    assert niveles.formulario.texto_errores() == ""

    # Grados y grupos.
    grados: Any = ventana.ir_a("grados")
    for n in range(1, 6):
        _clic(qtbot, grados.boton_grado)
        grados.grado_nombre.setText(f"{n}°")
        _clic(qtbot, grados.boton_guardar)
        grados.elegir(f"Grado {n}°")
        _clic(qtbot, grados.boton_grupo)
        assert grados.grupo_grado.currentText().startswith(f"{n}°")
        grados.grupo_seccion.setText("A")
        _clic(qtbot, grados.boton_guardar)
    assert [g for g in ventana.contexto.sesion.datos.grupos if g.seccion == "A"].__len__() == 5

    # Asignaturas (Ed. Física: máximo 1 por día y nunca en la primera hora).
    asignaturas: Any = ventana.ir_a("asignaturas")
    for nombre in ASIGNATURAS:
        _clic(qtbot, asignaturas.boton_nuevo)
        asignaturas.nombre.setText(nombre)
        if nombre in ("Ed. Física", "Formación Cívica"):
            asignaturas.reglas_defecto.max_horas.setValue(1)
        if nombre == "Ed. Física":
            cuadricula = asignaturas.reglas_defecto.cuadricula
            for columna in range(cuadricula.columnCount()):
                cuadricula.alternar(0, columna)  # normal → prohibida
        _clic(qtbot, asignaturas.boton_guardar)
        assert asignaturas.formulario.texto_errores() == "", nombre

    # Plan de estudios.
    plan: Any = ventana.ir_a("plan")
    datos = ventana.contexto.sesion.datos
    horas = {"Español": 6, "Matemáticas": 6, "Ciencias": 4, "Inglés": 4, "Ed. Física": 2,
             "Artes": 2, "Formación Cívica": 1}  # fmt: skip
    for grado in datos.grados:
        for asignatura in datos.asignaturas:
            plan.poner_horas(grado.id, asignatura.id, horas[asignatura.nombre])
    assert plan.hay_cambios()
    _clic(qtbot, plan.boton_guardar)
    assert plan.tabla.item(0, len(ASIGNATURAS)).text() == "25 / 35"

    # Profesores.
    profesores: Any = ventana.ir_a("profesores")
    for nombre, suyas in PROFESORES.items():
        _clic(qtbot, profesores.boton_nuevo)
        profesores.nombre.setText(nombre)
        profesores.asignaturas.marcar(_ids(profesores.asignaturas, suyas))
        profesores.grados.marcar(_ids(profesores.grados, [f"{n}°" for n in range(1, 6)]))
        _clic(qtbot, profesores.boton_guardar)
        assert profesores.formulario.texto_errores() == "", nombre

    # Clases: sincronizar con el plan.
    clases: Any = ventana.ir_a("clases")
    _clic(qtbot, clases.boton_sincronizar)
    assert ("Sincronizar con el plan", "Se crearon 35 clases nuevas.") in dialogos.mostrados  # type: ignore[attr-defined]
    assert clases.tabla.rowCount() == 7

    # Validación y lista de verificación.
    validacion: Any = ventana.ir_a("validacion")
    assert validacion.problemas == []
    assert "Sin problemas" in validacion.resumen.text()
    inicio: Any = ventana.ir_a("inicio")
    assert all(inicio.puntos().values()), inicio.puntos()

    # Lo capturado coincide con el ejemplo pequeño y se puede resolver.
    capturado = ventana.contexto.sesion.datos
    esperado = ejemplo_pequeno()
    assert _por_nombre(capturado) == _por_nombre(esperado)
    fisica = next(a for a in capturado.asignaturas if a.nombre == "Ed. Física")
    assert fisica.reglas_por_defecto.franjas_prohibidas == [
        RangoFranjas(dias=(d,), desde_indice=0, hasta_indice=0) for d in "LMXJV"
    ]
    assert validar(capturado) == []
    resultado = resolver(capturado, OpcionesResolucion(tiempo_limite_s=10, hilos=2,
                                                       optimizar=False))  # fmt: skip
    assert resultado.estado is EstadoSolucion.OPTIMO
    assert "•" not in ventana.windowTitle()
