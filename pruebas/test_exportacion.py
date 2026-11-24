"""Creado con Claude.

Exportación a Excel (§16.1) y disposición común de los horarios: hojas, celdas combinadas,
colores, impresión (verificados con openpyxl), nombres de hoja, carga docente y comandos.
El PDF (§16.2) se agrega en F12.
"""

from pathlib import Path

import openpyxl
import pytest
from typer.testing import CliRunner

from pruebas.escuelas import ANA, INGLES_A, MATE, MATE_A, escuela_minima, f, horario_valido
from timetabling.cli import app
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.colores import color_texto, contraste
from timetabling.dominio.cuadricula import Disposicion
from timetabling.dominio.estadisticas import carga_docente
from timetabling.dominio.modelos import (
    Clase,
    DatosEscuela,
    Destinatario,
    Division,
    EstadoSolucion,
    Grado,
    Grupo,
    Nivel,
    Solucion,
)
from timetabling.ejemplo import crear_ejemplo
from timetabling.exportacion.estilos import nombre_hoja
from timetabling.exportacion.excel import FilaCambio, exportar_excel
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.soluciones import a_solucion


def _solucion(datos: DatosEscuela, colocaciones: list[Colocacion], **campos: object) -> Solucion:
    valores: dict[str, object] = {"nombre": "Prueba", "estado": EstadoSolucion.OPTIMO,
                                  "origen": "generado"}  # fmt: skip
    valores.update(campos)
    return a_solucion(datos, colocaciones, **valores)  # type: ignore[arg-type]


def _dos_niveles() -> tuple[DatosEscuela, list[Colocacion]]:
    """Ana da en Primaria (50 min, 8:00) y en Secundaria (45 min, desde 9:00)."""
    datos = escuela_minima()
    datos.niveles.append(
        Nivel(id=2, nombre="Secundaria", duracion_min=45, inicio_jornada=540, fin_jornada=720,
              dias=["L", "M"])
    )  # fmt: skip
    datos.grados.append(Grado(id=2, nivel_id=2, nombre="7°"))
    datos.grupos.append(Grupo(id=3, grado_id=2, seccion="A"))
    datos.profesores[ANA - 1].grados.append(2)
    datos.clases.append(
        Clase(id=30, asignatura_id=MATE, destinatarios=[Destinatario(grupo_id=3)],
              horas_semanales=1, profesores=[ANA])
    )  # fmt: skip
    return datos, [*horario_valido(), Colocacion(30, "2:L:1", (ANA,))]


@pytest.fixture
def libro(tmp_path: Path) -> openpyxl.Workbook:
    datos, colocaciones = _dos_niveles()
    solucion = _solucion(datos, colocaciones, penalizaciones={"B1": 1.5, "total": 24.0},
                         penalizaciones_son_cota=True)  # fmt: skip
    cambios = [FilaCambio("Matemáticas · 1°A", "L 1", "M 2", "movida")]
    ruta = exportar_excel(datos, solucion, tmp_path / "h.xlsx", cambios=cambios)
    return openpyxl.load_workbook(ruta)


# ---------------------------------------------------------------------------
# Libro
# ---------------------------------------------------------------------------


def test_hojas(libro: openpyxl.Workbook) -> None:
    assert libro.sheetnames == [
        "Resumen", "1°A", "1°B", "7°A", "Ana", "Beto", "Caro", "cancha - Primaria",
        "CargaDocente", "Cambios", "Leyenda",
    ]  # fmt: skip


def test_resumen_marca_la_cota(libro: openpyxl.Workbook) -> None:
    hoja = libro["Resumen"]
    valores = {hoja.cell(i, 1).value: hoja.cell(i, 2).value for i in range(1, hoja.max_row + 1)}
    assert valores["Escuela"] == "Mínima"
    assert valores["Estado"] == "OPTIMO"
    assert valores["B1 Huecos de profesores (cota superior)"] == 1.5
    assert valores["Penalización total (cota superior)"] == 24.0


def test_hoja_de_grupo(libro: openpyxl.Workbook) -> None:
    hoja = libro["1°A"]
    assert [hoja.cell(2, j).value for j in range(1, 4)] == ["Hora", "Lunes", "Martes"]
    assert [hoja.cell(i, 1).value for i in range(3, 8)] == [
        "08:00–08:50", "08:50–09:40", "Receso", "10:00–10:50", "10:50–11:40"
    ]  # fmt: skip
    # Receso combinado en gris a lo ancho de los días.
    assert "B5:C5" in {str(r) for r in hoja.merged_cells.ranges}
    assert hoja["B5"].value == "Receso"
    assert hoja["B5"].fill.fgColor.rgb.endswith("D9D9D9")
    # Matemáticas de 1°A el lunes a primera hora, con su color y texto en contraste.
    assert hoja["B3"].value == "Matemáticas\nAna"
    assert hoja["B3"].fill.fgColor.rgb.endswith("9E9E9E")
    assert hoja["B3"].font.color.rgb.endswith("000000")
    assert hoja["B3"].alignment.wrap_text and hoja["B3"].border.left.style == "thin"
    assert hoja["C3"].value == "Inglés\nCaro"


def test_profesor_multinivel_en_rejilla(libro: openpyxl.Workbook) -> None:
    hoja = libro["Ana"]
    assert "rejilla de 5 min" in hoja["B1"].value
    combinadas = {str(r) for r in hoja.merged_cells.ranges}
    # Matemáticas 1°A 8:00–8:50 y 8:50–9:40 (10 filas de 5 min) y 7°A 9:45–10:30 (9 filas).
    assert {"B3:B12", "B13:B22", "B24:B32"} <= combinadas
    assert hoja["B24"].value == "Matemáticas\n7°A"
    assert hoja["A3"].value == "08:00"


def test_impresion(libro: openpyxl.Workbook) -> None:
    for nombre in ("1°A", "Ana", "CargaDocente"):
        hoja = libro[nombre]
        assert hoja.page_setup.orientation == "landscape"
        assert hoja.page_setup.paperSize == 1  # carta
        # 1 es el valor por defecto de OOXML: XlsxWriter no lo escribe y openpyxl lee None.
        assert hoja.page_setup.fitToWidth in (None, 1)
        assert hoja.page_setup.fitToHeight in (None, 1)
        assert hoja.sheet_properties.pageSetUpPr.fitToPage
        assert hoja.page_margins.left == pytest.approx(0.25)
        assert "Mínima" in hoja.oddHeader.left.text and hoja.oddHeader.right.text == "&A"
        assert hoja.oddFooter.right.text == "Página &P de &N"


def test_carga_docente_y_leyenda(libro: openpyxl.Workbook) -> None:
    carga = libro["CargaDocente"]
    filas = {carga.cell(i, 1).value: [carga.cell(i, j).value for j in range(2, 8)]
             for i in range(2, carga.max_row + 1)}  # fmt: skip
    assert filas["Ana"][:3] == [145, 0, 2400]
    assert filas["Ana"][4] == 1  # días con clase
    leyenda = libro["Leyenda"]
    assert {leyenda.cell(i, 1).value for i in range(2, 5)} == {
        "Matemáticas",
        "Inglés",
        "Ed. Física",
    }
    assert libro["Cambios"]["D2"].value == "movida"


def test_sin_cambios_no_hay_hoja(tmp_path: Path) -> None:
    datos = escuela_minima()
    ruta = exportar_excel(datos, _solucion(datos, horario_valido()), tmp_path / "h.xlsx")
    assert "Cambios" not in openpyxl.load_workbook(ruta).sheetnames


# ---------------------------------------------------------------------------
# Nombres de hoja y colores
# ---------------------------------------------------------------------------


def test_nombre_de_hoja() -> None:
    usados: set[str] = set()
    assert nombre_hoja("7°A [mañana]: grupo*?/\\", usados) == "7°A _mañana__ grupo____"
    largo = "Profesora con un nombre larguísimo que no cabe"
    assert nombre_hoja(largo, usados) == largo[:31]
    assert nombre_hoja(largo, usados) == largo[:27] + " (2)"
    assert nombre_hoja(largo.upper(), usados) == largo.upper()[:27] + " (3)"
    assert all(len(n) <= 31 for n in usados)


def test_color_de_texto_en_contraste() -> None:
    assert color_texto("#FFFF00") == "#000000"
    assert color_texto("#1A237E") == "#FFFFFF"
    for fondo in ("#E57373", "#64B5F6", "#81C784", "#9575CD", "#90A4AE"):
        assert contraste(fondo, color_texto(fondo)) >= 4.5


# ---------------------------------------------------------------------------
# Disposición común
# ---------------------------------------------------------------------------


def test_division_en_la_misma_celda() -> None:
    datos = escuela_minima()
    datos.divisiones.append(Division(id=1, grupo_id=1, partes=["Básico", "Avanzado"]))
    ingles = next(c for c in datos.clases if c.id == INGLES_A)
    ingles.destinatarios = [Destinatario(grupo_id=1, division_id=1, parte="Básico")]
    avanzado = [Destinatario(grupo_id=1, division_id=1, parte="Avanzado")]
    datos.clases.append(ingles.model_copy(update={"id": 20, "destinatarios": avanzado}))
    colocaciones = [*horario_valido(), Colocacion(20, f("M", 0), (ANA,))]
    cuadricula = Disposicion(_solucion(datos, colocaciones), datos).por_grupo("1°A")
    celda = cuadricula.celda(0, 1)
    assert celda is not None
    assert celda.lineas == ["Inglés (Avanzado) · Ana", "Inglés (Básico) · Caro"]


def test_marcas_y_solucion_desactualizada() -> None:
    datos = escuela_minima()
    colocaciones = horario_valido()
    colocaciones[0] = Colocacion(MATE_A, f("L", 0), (ANA,), bloqueada=True)
    solucion = _solucion(datos, colocaciones)
    # Los niveles cambian y la clase se borra: la solución sigue legible con lo guardado.
    datos.niveles[0].duracion_min = 45
    datos.clases = [c for c in datos.clases if c.id != MATE_A]
    disposicion = Disposicion(solucion, datos, cambiadas={(MATE_A, 1)})
    cuadricula = disposicion.por_grupo("1°A")
    assert cuadricula.filas[0].etiqueta == "08:00–08:50"
    primera = cuadricula.celda(0, 0)
    assert primera is not None and primera.texto == "📌 Matemáticas\nAna"
    segunda = cuadricula.celda(1, 0)
    assert segunda is not None and segunda.texto.startswith("↻ ")


def test_carga_docente_sin_recesos_en_los_huecos() -> None:
    datos = escuela_minima()
    colocaciones = [Colocacion(MATE_A, f("L", 1), (ANA,)), Colocacion(MATE_A, f("L", 2), (ANA,))]
    carga = carga_docente(_solucion(datos, colocaciones), datos)
    assert carga[0].nombre == "Ana" and carga[0].minutos == 100
    assert carga[0].minutos_hueco == 0  # 9:40–10:00 es receso de Primaria
    colocaciones[1] = Colocacion(MATE_A, f("L", 3), (ANA,))
    assert carga_docente(_solucion(datos, colocaciones), datos)[0].minutos_hueco == 50


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------


def test_cli_generar_y_exportar(tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "p.horario")
    corredor = CliRunner()
    resultado = corredor.invoke(app, ["generar", str(ruta), "--tiempo-limite", "5", "--hilos", "2",
                                      "--exportar", str(tmp_path / "a.xlsx")])  # fmt: skip
    assert resultado.exit_code == 0, resultado.output
    assert (tmp_path / "a.xlsx").exists()
    identificador = resultado.output.split("(id ")[1].split(")")[0]
    otra = corredor.invoke(app, ["exportar", str(ruta), "--solucion", identificador, "--salida",
                                 str(tmp_path / "b.xlsx")])  # fmt: skip
    assert otra.exit_code == 0, otra.output
    libro = openpyxl.load_workbook(tmp_path / "b.xlsx")
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        guardada = repo.cargar_solucion(int(identificador))
    con_clases = {a.profesor_nombre for a in guardada.asignaciones if a.profesor_nombre}
    # Resumen, 5 grupos, un profesor por hoja (solo los que tienen clases), carga y leyenda.
    assert len(libro.sheetnames) == 1 + 5 + len(con_clases) + 2
    assert con_clases <= set(libro.sheetnames)
    pdf = corredor.invoke(app, ["exportar", str(ruta), "--solucion", identificador, "--salida",
                                str(tmp_path / "b.pdf")])  # fmt: skip
    assert pdf.exit_code == 2 and "PDF" in pdf.output
    falta = corredor.invoke(app, ["exportar", str(ruta), "--solucion", "999", "--salida",
                                  str(tmp_path / "c.xlsx")])  # fmt: skip
    assert falta.exit_code == 2 and "No existe la solución 999" in falta.output
