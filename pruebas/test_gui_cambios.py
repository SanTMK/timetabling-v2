"""Creado con Claude.

Interfaz (§17): cambios sin guardar (Guardar / Descartar / Cancelar), errores de pydantic en
español junto al campo, borrados con confirmación, profesores en uso, navegación desde
Validación, avisos al abrir, proyectos recientes y geometría recordada.
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from PySide6.QtCore import Qt

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import EstadoSolucion, Nivel, Profesor
from timetabling.ejemplo import crear_ejemplo
from timetabling.gui.app import VentanaPrincipal
from timetabling.gui.dialogos import Respuesta
from timetabling.gui.errores import traducir
from timetabling.servicios.soluciones import a_solucion


@pytest.fixture
def con_pequeno(ventana: VentanaPrincipal, tmp_path: Path) -> VentanaPrincipal:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    ventana.abrir_proyecto(ruta)
    return ventana


def _clic(qtbot: Any, boton: Any) -> None:
    qtbot.mouseClick(boton, Qt.MouseButton.LeftButton)


# ---------------------------------------------------------------------------
# Cambios sin guardar
# ---------------------------------------------------------------------------


def test_cancelar_se_queda_en_la_pantalla(con_pequeno: VentanaPrincipal) -> None:
    niveles: Any = con_pequeno.ir_a("niveles")
    niveles.nombre.setText("Primaria matutina")
    assert niveles.hay_cambios()
    assert con_pequeno.windowTitle().endswith("•")
    assert con_pequeno.barra.item(2).text() == "Niveles •"
    con_pequeno.dialogos.responder(Respuesta.CANCELAR)  # type: ignore[attr-defined]
    con_pequeno.ir_a("espacios")
    assert con_pequeno.pantalla_actual() is niveles
    assert niveles.nombre.text() == "Primaria matutina"


def test_descartar_pierde_los_cambios(con_pequeno: VentanaPrincipal) -> None:
    niveles: Any = con_pequeno.ir_a("niveles")
    niveles.nombre.setText("Otro nombre")
    con_pequeno.dialogos.responder(Respuesta.DESCARTAR)  # type: ignore[attr-defined]
    con_pequeno.ir_a("espacios")
    assert con_pequeno.pantalla_actual().clave == "espacios"
    assert con_pequeno.contexto.sesion.datos.niveles[0].nombre == "Primaria"
    assert "•" not in con_pequeno.windowTitle()


def test_guardar_al_salir(con_pequeno: VentanaPrincipal) -> None:
    niveles: Any = con_pequeno.ir_a("niveles")
    niveles.nombre.setText("Primaria matutina")
    con_pequeno.dialogos.responder(Respuesta.GUARDAR)  # type: ignore[attr-defined]
    con_pequeno.ir_a("espacios")
    assert con_pequeno.contexto.sesion.datos.niveles[0].nombre == "Primaria matutina"


def test_guardar_con_error_no_sale(con_pequeno: VentanaPrincipal) -> None:
    niveles: Any = con_pequeno.ir_a("niveles")
    niveles.nombre.setText("")
    con_pequeno.dialogos.responder(Respuesta.GUARDAR)  # type: ignore[attr-defined]
    con_pequeno.ir_a("espacios")
    assert con_pequeno.pantalla_actual() is niveles
    assert "no puede quedar vacío" in niveles.formulario.errores["nombre"].text()


def test_cerrar_con_cambios_pregunta(con_pequeno: VentanaPrincipal) -> None:
    espacios: Any = con_pequeno.ir_a("espacios")
    _clic_nuevo = espacios.boton_nuevo
    _clic_nuevo.click()
    espacios.nombre.setText("Laboratorio")
    espacios.tipo_espacio.setText("laboratorio")
    con_pequeno.dialogos.responder(Respuesta.CANCELAR)  # type: ignore[attr-defined]
    assert not con_pequeno.close()
    con_pequeno.dialogos.responder(Respuesta.GUARDAR)  # type: ignore[attr-defined]
    sesion = con_pequeno.contexto.sesion
    assert con_pequeno.close()
    assert sesion is not None
    from timetabling.persistencia.repositorio import Repositorio

    with Repositorio.abrir(sesion.ruta, respaldo_diario=False) as repo:
        assert [e.nombre for e in repo.cargar_datos().espacios] == ["Laboratorio"]


def test_cambiar_de_elemento_con_cambios_pregunta(con_pequeno: VentanaPrincipal) -> None:
    profesores: Any = con_pequeno.ir_a("profesores")
    profesores.elegir("Ana López")
    profesores.carga_max.setValue(1000)
    con_pequeno.dialogos.responder(Respuesta.CANCELAR)  # type: ignore[attr-defined]
    profesores.elegir("Bruno Díaz")
    assert profesores.nombre.text() == "Ana López"


# ---------------------------------------------------------------------------
# Errores junto al campo
# ---------------------------------------------------------------------------


def test_errores_junto_al_campo(con_pequeno: VentanaPrincipal, qtbot: Any) -> None:
    niveles: Any = con_pequeno.ir_a("niveles")
    niveles.fin.poner(niveles.inicio.minutos() - 60)
    _clic(qtbot, niveles.boton_guardar)
    assert "el inicio debe ser anterior al fin" in niveles.formulario.error_general.text()
    assert niveles.hay_cambios()
    niveles.descartar()
    niveles.duracion.setValue(2)
    _clic(qtbot, niveles.boton_guardar)
    assert niveles.formulario.errores["duracion_min"].text() == "⚠ Debe ser mayor o igual que 5."


def test_nombre_repetido(con_pequeno: VentanaPrincipal, qtbot: Any) -> None:
    asignaturas: Any = con_pequeno.ir_a("asignaturas")
    _clic(qtbot, asignaturas.boton_nuevo)
    asignaturas.nombre.setText("Español")
    _clic(qtbot, asignaturas.boton_guardar)
    assert "Ya existe otro registro con ese nombre" in asignaturas.formulario.texto_errores()


def test_traducir_errores_de_pydantic() -> None:
    with pytest.raises(ValidationError) as error:
        Profesor(nombre=" ", carga_max_semanal_min=-1, max_dias=9)
    traducidos = traducir(error.value)
    assert traducidos["nombre"] == "El campo «nombre del profesor» no puede quedar vacío."
    assert traducidos["carga_max_semanal_min"] == "Debe ser mayor o igual que 0."
    assert traducidos["max_dias"] == "Debe ser menor o igual que 7."
    with pytest.raises(ValidationError) as error:
        Nivel(nombre="X", inicio_jornada=600, fin_jornada=500)
    assert "inicio debe ser anterior" in traducir(error.value)[""]


# ---------------------------------------------------------------------------
# Borrados y profesores en uso
# ---------------------------------------------------------------------------


def test_eliminar_muestra_lo_afectado(con_pequeno: VentanaPrincipal) -> None:
    asignaturas: Any = con_pequeno.ir_a("asignaturas")
    asignaturas.elegir("Artes")
    con_pequeno.dialogos.responder(False)  # type: ignore[attr-defined]
    asignaturas.eliminar()
    titulo, texto = con_pequeno.dialogos.mostrados[-1]  # type: ignore[attr-defined]
    assert titulo == "Eliminar" and "5 clases" in texto and "5 filas del plan" in texto
    assert any(a.nombre == "Artes" for a in con_pequeno.contexto.sesion.datos.asignaturas)
    con_pequeno.dialogos.responder(True)  # type: ignore[attr-defined]
    asignaturas.elegir("Artes")
    asignaturas.eliminar()
    assert not any(a.nombre == "Artes" for a in con_pequeno.contexto.sesion.datos.asignaturas)


def test_profesor_en_uso_se_desactiva(con_pequeno: VentanaPrincipal) -> None:
    sesion = con_pequeno.contexto.sesion
    assert sesion is not None
    datos = sesion.datos
    ana = next(p for p in datos.profesores if p.nombre == "Ana López")
    clase = next(c for c in datos.clases if c.asignatura_id in ana.asignaturas)
    solucion = a_solucion(
        datos, [Colocacion(clase.id or 0, "1:L:0", (ana.id or 0,))], nombre="X",
        estado=EstadoSolucion.BORRADOR, origen="manual",
    )  # fmt: skip
    sesion.repo.guardar_solucion(solucion)
    profesores: Any = con_pequeno.ir_a("profesores")
    profesores.elegir("Ana López")
    con_pequeno.dialogos.responder(True)  # type: ignore[attr-defined]
    profesores.eliminar()
    assert "aparece en un horario guardado" in con_pequeno.dialogos.mostrados[-1][1]  # type: ignore[attr-defined]
    ana = next(p for p in sesion.datos.profesores if p.nombre == "Ana López")
    assert not ana.activo
    textos = [profesores.lista.item(i).text() for i in range(profesores.lista.count())]
    assert "Ana López (inactivo)" in textos


# ---------------------------------------------------------------------------
# Navegación, avisos, recientes y geometría
# ---------------------------------------------------------------------------


def test_doble_clic_en_validacion_navega(con_pequeno: VentanaPrincipal, qtbot: Any) -> None:
    profesores: Any = con_pequeno.ir_a("profesores")
    profesores.elegir("Irene Castro")
    profesores.carga_min.setValue(900)
    _clic(qtbot, profesores.boton_guardar)
    validacion: Any = con_pequeno.ir_a("validacion")
    fila = next(i for i, p in enumerate(validacion.problemas) if "Irene Castro" in p.mensaje)
    # Doble clic real (con el clic previo que registra la celda pulsada en Qt 6).
    centro = validacion.tabla.visualItemRect(validacion.tabla.item(fila, 1)).center()
    vista = validacion.tabla.viewport()
    qtbot.mouseClick(vista, Qt.MouseButton.LeftButton, pos=centro)
    qtbot.mouseDClick(vista, Qt.MouseButton.LeftButton, pos=centro)
    assert con_pequeno.pantalla_actual() is profesores
    assert profesores.nombre.text() == "Irene Castro"
    inicio: Any = con_pequeno.ir_a("inicio")
    assert inicio.puntos()["validacion"] is False


def test_clases_desde_validacion_y_matriz(con_pequeno: VentanaPrincipal) -> None:
    clases: Any = con_pequeno.ir_a("clases")
    clases.elegir_grupo("3°A")
    clases.elegir_clase("Inglés")
    con_pequeno.dialogos.responder(["Gabriela Sosa"])  # type: ignore[attr-defined]
    clases.asignar_profesor()
    fila = next(i for i in range(clases.tabla.rowCount())
                if clases.tabla.item(i, 0).text() == "Inglés")  # fmt: skip
    assert clases.tabla.item(fila, 2).text() == "Gabriela Sosa"
    sesion = con_pequeno.contexto.sesion
    assert sesion is not None
    ingles = next(
        c for c in sesion.datos.clases
        if sesion.datos.nombre_grupo(c.destinatarios[0].grupo_id) == "3°A"
        and next(a.nombre for a in sesion.datos.asignaturas if a.id == c.asignatura_id) == "Inglés"
    )  # fmt: skip
    gabriela = next(p for p in sesion.datos.profesores if p.nombre == "Gabriela Sosa")
    assert ingles.profesores == [gabriela.id]
    textos = [
        clases.matriz.item(i, j).text()
        for i in range(clases.matriz.rowCount())
        for j in range(clases.matriz.columnCount())
    ]
    assert "Gabriela Sosa" in textos


def test_juntar_y_dividir_clases(con_pequeno: VentanaPrincipal, qtbot: Any) -> None:
    sesion = con_pequeno.contexto.sesion
    assert sesion is not None
    clases: Any = con_pequeno.ir_a("clases")
    clases.elegir_grupo("1°A")
    clases.elegir_clase("Artes")
    con_pequeno.dialogos.responder(["2°A"])  # type: ignore[attr-defined]
    clases.juntar()
    artes = [c for c in sesion.datos.clases if len(c.destinatarios) == 2]
    assert len(artes) == 1
    destinatarios = [clases.tabla.item(i, 1).text() for i in range(clases.tabla.rowCount())]
    assert "1°A, 2°A" in destinatarios
    # Dividir: primero una división en Grados y grupos.
    grados: Any = con_pequeno.ir_a("grados")
    grados.elegir("4°A")
    grados.grupo_divisiones.agregar({"nombre": "Inglés por nivel", "partes": "Básico, Avanzado",
                                     "simultanea": True})  # fmt: skip
    _clic(qtbot, grados.boton_guardar)
    assert len(sesion.datos.divisiones) == 1
    clases = con_pequeno.ir_a("clases")
    clases.elegir_grupo("4°A")  # type: ignore[attr-defined]
    clases.elegir_clase("Inglés")  # type: ignore[attr-defined]
    clases.dividir()  # type: ignore[attr-defined]
    partes = [
        d.parte for c in sesion.datos.clases for d in c.destinatarios if d.division_id is not None
    ]
    assert sorted(partes) == ["Avanzado", "Básico"]
    assert clases.tabla.rowCount() == 8  # type: ignore[attr-defined]
    assert sesion.problemas() == []


def test_avisos_al_abrir(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "Dropbox" / "p.horario")
    ventana.abrir_proyecto(ruta)
    assert not ventana.aviso.isHidden()
    assert "Dropbox" in ventana.texto_aviso.text()


def test_recientes_y_geometria(
    ventana: VentanaPrincipal, tmp_path: Path, qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    ventana.abrir_proyecto(ruta)
    assert ventana.recientes()[0] == str(ruta)
    # El tamaño mínimo depende de las fuentes de cada sistema: se pide uno por encima del mínimo
    # (si no, cada sistema lo recorta distinto al restaurar) y se compara con el tamaño real.
    # Además debe caber en la pantalla (la de macOS en CI es baja).
    minimo = ventana.minimumSizeHint().expandedTo(ventana.minimumSize())
    libre = ventana.screen().availableGeometry()
    ancho_libre = libre.width() - (ventana.frameGeometry().width() - ventana.width()) - 10
    alto_libre = libre.height() - (ventana.frameGeometry().height() - ventana.height()) - 10
    assert minimo.width() <= ancho_libre and minimo.height() <= alto_libre
    ventana.resize(min(max(780, minimo.width() + 40), ancho_libre),
                   min(max(520, minimo.height() + 40), alto_libre))  # fmt: skip
    tamano = (ventana.width(), ventana.height())
    assert ventana.close()
    from pruebas.gui_utiles import DialogosFalsos

    otra = VentanaPrincipal(dialogos=DialogosFalsos())
    qtbot.addWidget(otra)
    assert otra.recientes()[0] == str(ruta)
    assert otra.menu_recientes.actions()[0].text() == str(ruta)
    assert (otra.width(), otra.height()) == tamano


def test_proyecto_v6_ofrece_importar(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    import sqlite3

    ruta = tmp_path / "viejo.horario"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE esquema_version (version INTEGER)")
    con.commit()
    con.close()
    ventana.dialogos.responder(False)  # type: ignore[attr-defined]
    assert ventana.abrir_proyecto(ruta) is None
    titulo, texto = ventana.dialogos.mostrados[-1]  # type: ignore[attr-defined]
    assert titulo == "Proyecto de la versión anterior" and "¿Importarlo ahora?" in texto


def test_sin_proyecto_las_pantallas_estan_desactivadas(ventana: VentanaPrincipal) -> None:
    habilitadas = [
        bool(ventana.barra.item(i).flags() & Qt.ItemFlag.ItemIsEnabled)
        for i in range(ventana.barra.count())
    ]
    assert habilitadas[0] and not any(habilitadas[1:])
    assert not ventana.pantallas["inicio"].sin_proyecto.isHidden()  # type: ignore[attr-defined]


def test_restaurar_respaldo(con_pequeno: VentanaPrincipal) -> None:
    sesion = con_pequeno.contexto.sesion
    assert sesion is not None
    sesion.repo.crear_respaldo()
    nombre = sesion.datos.niveles[0].nombre
    niveles: Any = con_pequeno.ir_a("niveles")
    niveles.nombre.setText("Cambiado")
    niveles.guardar()
    assert sesion.datos.niveles[0].nombre == "Cambiado"
    con_pequeno.restaurar_respaldo()
    assert sesion.datos.niveles[0].nombre == nombre


def test_ancho_minimo_de_la_ventana(ventana: VentanaPrincipal) -> None:
    """La ventana cabe en una laptop pequeña (1024 px); en macOS las fuentes la ensanchan."""
    assert ventana.minimumSizeHint().width() <= 1024
