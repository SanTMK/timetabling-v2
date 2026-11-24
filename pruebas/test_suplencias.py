"""Creado con Claude.

Suplencias (§11.4, §14): candidatos y su orden, ausencias parciales, choque con otra suplencia,
asignar o marcar «sin cubrir», conteo mensual, reporte del día en Excel y que el vigente no
cambie. También la pantalla Suplencias y «Buscar suplente…» del editor.
"""

from datetime import date
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from pruebas.escuelas import (
    ANA,
    BETO,
    CARO,
    FISICA_A,
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
    Ausencia,
    DatosEscuela,
    Disponibilidad,
    EstadoSolucion,
    EventoProfesor,
    Solucion,
)
from timetabling.nucleo.suplencias import candidatos, dia_de
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.edicion import nuevo_borrador
from timetabling.servicios.soluciones import a_solucion
from timetabling.servicios.suplencias import ClaseAfectada, ErrorSuplencias, Suplencias

LUNES = date(2026, 11, 23)
MARTES = date(2026, 11, 24)


def _completa() -> DatosEscuela:
    """Escuela mínima válida (con Inglés de 1°B, clase 15); Caro puede suplir Matemáticas."""
    datos = escuela_minima()
    ingles = next(c for c in datos.clases if c.id == INGLES_A)
    datos.clases.append(ingles.model_copy(update={"id": 15, "destinatarios": [
        ingles.destinatarios[0].model_copy(update={"grupo_id": 2})]}))  # fmt: skip
    caro = next(p for p in datos.profesores if p.id == CARO)
    caro.suplencia_asignaturas = [MATE]
    caro.suplencia_grados = [1]
    return datos


def _horario() -> list[Colocacion]:
    # L0: Mate A (Ana), Mate B (Beto) · L1: Mate A (Ana) · L2: Ed. Física A (Caro)
    # M0: Mate B (Beto), Inglés A (Caro) · M1: Inglés B (Caro) · M2: Ed. Física B (Caro)
    return [*horario_valido(), Colocacion(15, f("M", 1), (CARO,))]


def _solucion(datos: DatosEscuela) -> Solucion:
    solucion = a_solucion(datos, _horario(), nombre="Vigente", estado=EstadoSolucion.OPTIMO,
                          origen="generado")  # fmt: skip
    # Ids de asignación estables para las pruebas del núcleo.
    asignaciones = [
        a.model_copy(update={"id": i}) for i, a in enumerate(solucion.asignaciones, start=1)
    ]
    return solucion.model_copy(update={"asignaciones": asignaciones})


def _id_de(solucion: Solucion, clase_id: int, dia: str, indice: int) -> int:
    for a in solucion.asignaciones:
        franja = solucion.franjas[a.franja]
        if a.clase_id == clase_id and franja.dia == dia and franja.indice == indice:
            assert a.id is not None
            return a.id
    raise AssertionError("asignación no encontrada")


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    ruta = tmp_path / "suplencias.horario"
    datos = _completa()
    with Repositorio.crear(ruta, datos.configuracion) as repo:
        repo.reemplazar_datos(datos)
        solucion = _solucion(datos)
        sin_ids = [a.model_copy(update={"id": None}) for a in solucion.asignaciones]
        guardada = repo.guardar_solucion(solucion.model_copy(update={"asignaciones": sin_ids}))
        repo.marcar_vigente(guardada.id)
    return ruta


@pytest.fixture
def servicio(proyecto: Path):  # type: ignore[no-untyped-def]
    with Repositorio.abrir(proyecto) as repo:
        yield Suplencias(repo)


def _afectada(afectadas: list[ClaseAfectada], clase: str, horas: str) -> ClaseAfectada:
    return next(c for c in afectadas if c.asignatura == clase and c.horas == horas)


# ---------------------------------------------------------------------------
# Núcleo: candidatos
# ---------------------------------------------------------------------------


def test_dia_de_la_fecha() -> None:
    assert dia_de(LUNES) == "L"
    assert dia_de(MARTES) == "M"


def test_candidatos_titular_primero_y_sin_quien_choca() -> None:
    datos = _completa()
    solucion = _solucion(datos)
    # Mate 1°A del lunes 8:50: Beto (titular) está libre; Caro solo como suplente.
    nombres = [c.nombre for c in candidatos(datos, solucion, _id_de(solucion, MATE_A, "L", 1))]
    assert nombres == ["Beto", "Caro"]
    lista = candidatos(datos, solucion, _id_de(solucion, MATE_A, "L", 1))
    assert lista[0].titular and not lista[1].titular
    # Lunes 8:00: Beto da Mate 1°B a esa hora, así que solo queda Caro.
    nombres = [c.nombre for c in candidatos(datos, solucion, _id_de(solucion, MATE_A, "L", 0))]
    assert nombres == ["Caro"]


def test_inhabilitados_inactivos_y_el_ausente_no_son_candidatos() -> None:
    datos = _completa()
    solucion = _solucion(datos)
    ident = _id_de(solucion, MATE_A, "L", 1)
    caro = next(p for p in datos.profesores if p.id == CARO)
    caro.suplencia_grados = []  # habilitada para la asignatura pero no para el grado
    beto = next(p for p in datos.profesores if p.id == BETO)
    beto.activo = False
    assert candidatos(datos, solucion, ident) == []
    # Ana es la ausente: nunca aparece aunque esté habilitada.
    assert ANA not in [c.profesor_id for c in candidatos(_completa(), solucion, ident)]


def test_disponibilidad_y_eventos_del_profesor() -> None:
    datos = _completa()
    solucion = _solucion(datos)
    ident = _id_de(solucion, MATE_A, "L", 1)
    beto = next(p for p in datos.profesores if p.id == BETO)
    beto.eventos = [EventoProfesor(nombre="Junta", dia="L", inicio=530, fin=560)]
    assert [c.nombre for c in candidatos(datos, solucion, ident)] == ["Caro"]
    beto.eventos = []
    beto.disponibilidad = [Disponibilidad(dia="L", inicio=530, fin=580, tipo="no_disponible")]
    assert [c.nombre for c in candidatos(datos, solucion, ident)] == ["Caro"]


def test_orden_preferible_no_carga_y_mes() -> None:
    datos = _completa()
    solucion = _solucion(datos)
    # Inglés 1°A del martes 8:00 (Caro ausente): Ana es titular y está libre.
    ident = _id_de(solucion, INGLES_A, "M", 0)
    assert [c.nombre for c in candidatos(datos, solucion, ident)] == ["Ana"]
    # Con dos suplentes no titulares de Mate 1°A el lunes 8:50: Caro y una nueva, Dora.
    from timetabling.dominio.modelos import Profesor

    datos.profesores.append(
        Profesor(id=4, nombre="Dora", suplencia_asignaturas=[MATE], suplencia_grados=[1])
    )
    ident = _id_de(solucion, MATE_A, "L", 1)
    # Caro ya da Ed. Física el lunes (1 clase), Dora ninguna: Dora va antes de Caro.
    assert [c.nombre for c in candidatos(datos, solucion, ident)] == ["Beto", "Dora", "Caro"]
    # Si Dora «preferiría no» a esa hora, pasa detrás de Caro.
    dora = datos.profesores[-1]
    dora.disponibilidad = [Disponibilidad(dia="L", inicio=530, fin=580, tipo="preferible_no")]
    lista = candidatos(datos, solucion, ident)
    assert [c.nombre for c in lista] == ["Beto", "Caro", "Dora"]
    assert "prefiere no" in lista[-1].detalle


def test_suplencias_del_mes_desempatan() -> None:
    from timetabling.dominio.modelos import Profesor, Suplencia

    datos = _completa()
    caro = next(p for p in datos.profesores if p.id == CARO)
    caro.suplencia_asignaturas = []
    for ident, nombre in ((4, "Dora"), (5, "Eli")):
        datos.profesores.append(Profesor(id=ident, nombre=nombre, suplencia_asignaturas=[MATE],
                                         suplencia_grados=[1]))  # fmt: skip
    solucion = _solucion(datos)
    ident = _id_de(solucion, MATE_A, "L", 1)
    previa = [Suplencia(fecha=date(2026, 11, 2), profesor_ausente_id=ANA, suplente_id=4,
                        asignacion_id=None)]  # fmt: skip
    nombres = [c.nombre for c in candidatos(datos, solucion, ident, LUNES, previa)]
    assert nombres == ["Beto", "Eli", "Dora"]
    # Una suplencia de otro mes no cuenta.
    previa = [previa[0].model_copy(update={"fecha": date(2026, 10, 30)})]
    nombres = [c.nombre for c in candidatos(datos, solucion, ident, LUNES, previa)]
    assert nombres == ["Beto", "Dora", "Eli"]


def test_choque_con_otra_suplencia_del_dia() -> None:
    from timetabling.dominio.modelos import Suplencia

    datos = _completa()
    solucion = _solucion(datos)
    mate_a = _id_de(solucion, MATE_A, "L", 0)
    mate_b = _id_de(solucion, MATE_B, "L", 0)
    ausencias = [Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES),
                 Ausencia(profesor_id=BETO, fecha_inicio=LUNES, fecha_fin=LUNES)]  # fmt: skip
    # Sin suplencias, Caro puede cubrir Mate 1°B a las 8:00.
    assert [c.nombre for c in candidatos(datos, solucion, mate_b, LUNES, (), ausencias)] == ["Caro"]
    # Si ya cubre Mate 1°A a esa hora, deja de ser candidata.
    hecha = [Suplencia(fecha=LUNES, asignacion_id=mate_a, profesor_ausente_id=ANA,
                       suplente_id=CARO)]  # fmt: skip
    assert candidatos(datos, solucion, mate_b, LUNES, hecha, ausencias) == []
    # La suplencia de otra fecha no choca.
    otra = [hecha[0].model_copy(update={"fecha": date(2026, 11, 30)})]
    assert len(candidatos(datos, solucion, mate_b, LUNES, otra, ausencias)) == 1


def test_profesor_ausente_esa_fecha_no_es_candidato_y_su_clase_no_lo_ocupa() -> None:
    datos = _completa()
    solucion = _solucion(datos)
    ident = _id_de(solucion, MATE_A, "L", 1)
    ausencias = [Ausencia(profesor_id=BETO, fecha_inicio=LUNES, fecha_fin=LUNES)]
    assert [c.nombre for c in candidatos(datos, solucion, ident, LUNES, (), ausencias)] == ["Caro"]
    # Ausencia parcial de Beto solo de 8:00 a 8:50: a las 8:50 sí está.
    parcial = [Ausencia(profesor_id=BETO, fecha_inicio=LUNES, fecha_fin=LUNES, desde=480,
                        hasta=530)]  # fmt: skip
    assert [c.nombre for c in candidatos(datos, solucion, ident, LUNES, (), parcial)] == [
        "Beto", "Caro"
    ]  # fmt: skip
    # Y, ausente a las 8:00, su Mate 1°B no lo ocupa: su carga del día baja a 0.
    lista = candidatos(datos, solucion, ident, LUNES, (), parcial)
    assert lista[0].carga_del_dia == 0


# ---------------------------------------------------------------------------
# Servicio: ausencias, clases afectadas, asignación, conteo y reporte
# ---------------------------------------------------------------------------


def test_clases_afectadas_por_ausencia(servicio: Suplencias) -> None:
    _, afectadas = servicio.registrar_ausencia(
        Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=MARTES, motivo="Médico")
    )
    # Ana solo da clase el lunes: Mate 1°A a las 8:00 y a las 8:50.
    assert [(c.fecha, c.horas, c.asignatura) for c in afectadas] == [
        (LUNES, "08:00–08:50", "Matemáticas"),
        (LUNES, "08:50–09:40", "Matemáticas"),
    ]
    assert all(c.estado == "Pendiente" for c in afectadas)
    assert servicio.afectadas_del_dia(MARTES) == []


def test_ausencia_parcial_filtra_por_hora(servicio: Suplencias) -> None:
    _, afectadas = servicio.registrar_ausencia(
        Ausencia(profesor_id=CARO, fecha_inicio=MARTES, fecha_fin=MARTES, desde=530, hasta=650)
    )
    # Caro el martes: Inglés A 8:00 (fuera), Inglés B 8:50 y Ed. Física B 10:00 (dentro).
    assert [(c.horas, c.grupos) for c in afectadas] == [
        ("08:50–09:40", "1°B"),
        ("10:00–10:50", "1°B"),
    ]


def test_asignar_sin_cubrir_y_quitar(servicio: Suplencias) -> None:
    _, afectadas = servicio.registrar_ausencia(
        Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES)
    )
    a_las_8 = _afectada(afectadas, "Matemáticas", "08:00–08:50")
    a_las_850 = _afectada(afectadas, "Matemáticas", "08:50–09:40")
    assert [c.nombre for c in servicio.candidatos(a_las_850)] == ["Beto", "Caro"]
    servicio.asignar(a_las_850, BETO)
    # Reasignar la misma clase reemplaza el registro (no duplica).
    servicio.asignar(a_las_850, CARO, nota="Cambio")
    servicio.asignar(a_las_8, None)
    del_dia = servicio.suplencias_del_dia(LUNES)
    assert len(del_dia) == 2
    estados = {c.horas: c.estado for c in servicio.afectadas_del_dia(LUNES)}
    assert estados == {"08:00–08:50": "Sin cubrir", "08:50–09:40": "Cubierta"}
    # Con Caro ocupada a las 8:50, ya no es candidata... para otra clase a esa hora; y la
    # propia clase sigue listándola (su suplencia no choca consigo misma).
    assert "Caro" in [c.nombre for c in servicio.candidatos(a_las_850)]
    with pytest.raises(ErrorSuplencias):
        servicio.asignar(a_las_8, ANA)
    cubierta = next(s for s in del_dia if s.suplente_id == CARO)
    assert cubierta.id is not None and cubierta.nota == "Cambio"
    servicio.quitar(cubierta.id)
    assert len(servicio.suplencias_del_dia(LUNES)) == 1


def test_conteo_mensual(servicio: Suplencias) -> None:
    servicio.registrar_ausencia(Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES))
    servicio.registrar_ausencia(
        Ausencia(profesor_id=CARO, fecha_inicio=MARTES, fecha_fin=MARTES, desde=600, hasta=650)
    )
    lunes = servicio.afectadas_del_dia(LUNES)
    servicio.asignar(_afectada(lunes, "Matemáticas", "08:50–09:40"), BETO)
    servicio.asignar(_afectada(lunes, "Matemáticas", "08:00–08:50"), CARO)
    martes = servicio.afectadas_del_dia(MARTES)
    servicio.asignar(martes[0], None)
    conteo = {f.nombre: (f.realizadas, f.cubiertas, f.sin_cubrir)
              for f in servicio.conteo_mensual(2026, 11)}  # fmt: skip
    assert conteo == {"Ana": (0, 2, 0), "Beto": (1, 0, 0), "Caro": (1, 0, 1)}
    assert servicio.conteo_mensual(2026, 12) == []


def test_suplencias_no_modifican_el_vigente(proyecto: Path) -> None:
    with Repositorio.abrir(proyecto) as repo:
        ident = repo.solucion_vigente_id()
        assert ident is not None
        antes = repo.cargar_solucion(ident)
        servicio = Suplencias(repo)
        _, afectadas = servicio.registrar_ausencia(
            Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES)
        )
        for c in afectadas:
            servicio.asignar(c, CARO if c.horas.startswith("08:00") else BETO)
        assert repo.cargar_solucion(ident) == antes
        assert repo.solucion_vigente_id() == ident


def test_eliminar_ausencia_quita_sus_suplencias(servicio: Suplencias) -> None:
    ausencia, afectadas = servicio.registrar_ausencia(
        Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES)
    )
    for c in afectadas:
        servicio.asignar(c, None)
    assert ausencia.id is not None
    assert servicio.eliminar_ausencia(ausencia.id) == 2
    assert servicio.suplencias_del_dia(LUNES) == []
    assert servicio.afectadas_del_dia(LUNES) == []


def test_sin_vigente(tmp_path: Path) -> None:
    ruta = tmp_path / "vacio.horario"
    with Repositorio.crear(ruta) as repo:
        servicio = Suplencias(repo)
        assert servicio.afectadas_del_dia(LUNES) == []
        with pytest.raises(ErrorSuplencias):
            servicio.candidatos(ClaseAfectada(LUNES, 1, 1, 1, "Ana", 480, 530, "Mate", "1°A"))


def test_reporte_del_dia_en_excel(servicio: Suplencias, tmp_path: Path) -> None:
    servicio.registrar_ausencia(
        Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES, motivo="Médico")
    )
    lunes = servicio.afectadas_del_dia(LUNES)
    servicio.asignar(_afectada(lunes, "Matemáticas", "08:50–09:40"), BETO, nota="Aula 3")
    ruta = servicio.exportar_reporte_del_dia(LUNES, tmp_path / "suplencias.xlsx")
    libro = openpyxl.load_workbook(ruta)
    assert libro.sheetnames == ["Suplencias del día"]
    hoja = libro.active
    assert hoja is not None
    textos = [[c for c in fila if c is not None] for fila in hoja.iter_rows(values_only=True)]
    assert textos[0] == ["Suplencias del lunes 23 de noviembre de 2026"]
    assert textos[1] == ["Ausente: Ana (todo el día) — Médico"]
    assert ["08:00–08:50", "Matemáticas", "1°A", "Ana", "—", "Pendiente"] in textos
    assert ["08:50–09:40", "Matemáticas", "1°A", "Ana", "Beto", "Cubierta", "Aula 3"] in textos
    # Una página imprimible: carta horizontal ajustada a 1×1.
    assert hoja.page_setup.orientation == "landscape"
    assert hoja.sheet_properties.pageSetUpPr.fitToPage
    # XlsxWriter omite el 1 por defecto: openpyxl lo lee como None.
    assert hoja.page_setup.fitToWidth in (None, 1)
    assert hoja.page_setup.fitToHeight in (None, 1)
    assert hoja.page_setup.paperSize in (None, 1)


def test_reporte_vacio(servicio: Suplencias, tmp_path: Path) -> None:
    ruta = servicio.exportar_reporte_del_dia(MARTES, tmp_path / "vacio.xlsx")
    hoja = openpyxl.load_workbook(ruta).active
    assert hoja is not None
    valores = [c for fila in hoja.iter_rows(values_only=True) for c in fila if c]
    assert "No hay clases afectadas en esta fecha." in valores


def test_clase_de_otra_franja_no_afecta(servicio: Suplencias) -> None:
    # Ed. Física 1°A es de Caro el lunes 10:00; una ausencia de Caro de 8:00 a 9:00 no la toca.
    _, afectadas = servicio.registrar_ausencia(
        Ausencia(profesor_id=CARO, fecha_inicio=LUNES, fecha_fin=LUNES, desde=480, hasta=540)
    )
    assert afectadas == []
    assert FISICA_A  # la clase existe en el horario


# ---------------------------------------------------------------------------
# Interfaz: pantalla Suplencias y «Buscar suplente…» del editor
# ---------------------------------------------------------------------------


def test_pantalla_suplencias_flujo(ventana: Any, proyecto: Path, tmp_path: Path) -> None:
    ventana.abrir_proyecto(proyecto)
    pantalla: Any = ventana.ir_a("suplencias")
    assert "Horario vigente" in pantalla.aviso.text()
    pantalla.poner_fecha(LUNES)
    assert pantalla.tabla.rowCount() == 0
    # Registrar la ausencia de Ana el lunes desde el formulario.
    pantalla.profesor.setCurrentIndex(pantalla.profesor.findText("Ana"))
    pantalla.motivo.setText("Médico")
    pantalla.boton_registrar.click()
    titulo, texto = ventana.dialogos.mostrados[-1]
    assert titulo == "Ausencia registrada" and "2 clases afectadas" in texto
    assert pantalla.ausencias.count() == 1 and "Médico" in pantalla.ausencias.item(0).text()
    assert pantalla.tabla.rowCount() == 2
    assert pantalla.tabla.item(0, 4).text() == "Pendiente"
    # 8:00: solo Caro puede (Beto da clase). 8:50: Beto (titular) y Caro.
    assert [c.nombre for c in pantalla.lista_candidatos] == ["Caro"]
    pantalla.tabla.selectRow(1)
    assert [c.nombre for c in pantalla.lista_candidatos] == ["Beto", "Caro"]
    pantalla.candidatos.setCurrentRow(0)
    pantalla.boton_asignar.click()
    assert pantalla.tabla.item(1, 4).text() == "Cubierta"
    assert pantalla.tabla.item(1, 5).text() == "Beto"
    assert pantalla.candidatos.item(0).text().startswith("✔ Beto")
    pantalla.tabla.selectRow(0)
    pantalla.boton_sin_cubrir.click()
    assert pantalla.tabla.item(0, 4).text() == "Sin cubrir"
    # Conteo del mes.
    filas = {pantalla.conteo.item(i, 0).text(): [pantalla.conteo.item(i, j).text()
             for j in (1, 2, 3)] for i in range(pantalla.conteo.rowCount())}  # fmt: skip
    assert filas == {"Ana": ["0", "1", "1"], "Beto": ["1", "0", "0"]}
    # Quitar el registro vuelve la clase a «Pendiente».
    pantalla.tabla.selectRow(0)
    pantalla.boton_quitar.click()
    assert pantalla.tabla.item(0, 4).text() == "Pendiente"
    # Reporte del día.
    destino = tmp_path / "dia.xlsx"
    ventana.dialogos.responder(destino)
    pantalla.boton_exportar.click()
    assert destino.exists()
    assert ventana.dialogos.mostrados[-1][0] == "Exportar suplencias"
    # Otro día sin ausencias: tabla vacía.
    pantalla.poner_fecha(MARTES)
    assert pantalla.tabla.rowCount() == 0 and pantalla.ausencias.count() == 0
    # Eliminar la ausencia quita sus suplencias.
    pantalla.poner_fecha(LUNES)
    pantalla.ausencias.setCurrentRow(0)
    ventana.dialogos.responder(True)
    pantalla.boton_eliminar_ausencia.click()
    assert pantalla.tabla.rowCount() == 0 and pantalla.conteo.rowCount() == 0


def test_pantalla_suplencias_ausencia_parcial_y_error(ventana: Any, proyecto: Path) -> None:
    ventana.abrir_proyecto(proyecto)
    pantalla: Any = ventana.ir_a("suplencias")
    pantalla.poner_fecha(MARTES)
    pantalla.profesor.setCurrentIndex(pantalla.profesor.findText("Caro"))
    pantalla.parcial.setChecked(True)
    pantalla.desde.poner(600)
    pantalla.hasta.poner(560)
    pantalla.boton_registrar.click()
    assert pantalla.error.isVisibleTo(pantalla)
    assert pantalla.ausencias.count() == 0
    pantalla.hasta.poner(650)
    pantalla.boton_registrar.click()
    assert not pantalla.error.isVisibleTo(pantalla)
    assert pantalla.tabla.rowCount() == 1
    assert pantalla.tabla.item(0, 0).text() == "10:00–10:50"


def test_pantalla_suplencias_sin_vigente(ventana: Any, tmp_path: Path) -> None:
    ruta = tmp_path / "vacio.horario"
    Repositorio.crear(ruta).cerrar()
    ventana.abrir_proyecto(ruta)
    pantalla: Any = ventana.ir_a("suplencias")
    assert "No hay un horario vigente" in pantalla.aviso.text()
    assert not pantalla.boton_registrar.isEnabled()
    assert not pantalla.boton_exportar.isEnabled()


def test_editor_buscar_suplente(ventana: Any, proyecto: Path) -> None:
    ventana.abrir_proyecto(proyecto)
    editor: Any = ventana.ir_a("editor")
    sesion = ventana.contexto.sesion
    copia = nuevo_borrador(sesion, "Copia", copia_de=sesion.vigente().id)
    editor.abrir_borrador(copia.id)
    texto = editor.buscar_suplente(MATE_A, f("L", 1))
    assert "Pueden cubrir la clase" in texto
    assert "1. Beto (titular" in texto and "2. Caro (suplente" in texto
    # Mate 1°B del lunes 8:00: Ana da Mate 1°A a esa hora; queda Caro.
    texto = editor.buscar_suplente(MATE_B, f("L", 0))
    assert "1. Caro" in texto and "Ana" not in texto
    # Ed. Física 1°A: nadie más está habilitado.
    assert "Nadie puede cubrir" in editor.buscar_suplente(FISICA_A, f("L", 2))


def test_reporte_del_dia_en_pdf(servicio: Suplencias, tmp_path: Path) -> None:
    import re

    servicio.registrar_ausencia(Ausencia(profesor_id=ANA, fecha_inicio=LUNES, fecha_fin=LUNES))
    ruta = servicio.exportar_reporte_del_dia(LUNES, tmp_path / "dia.pdf")
    contenido = ruta.read_bytes()
    assert contenido.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page(?![s\w])", contenido)) == 1
