"""Creado con Claude.

Línea de comandos (§18). Los subcomandos se agregan fase por fase.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from timetabling import __version__

app = typer.Typer(
    name="timetabling",
    help="Generador y editor de horarios escolares sin conexión.",
    no_args_is_help=False,
    add_completion=False,
)


def _mostrar_version(valor: bool) -> None:
    if valor:
        typer.echo(f"timetabling {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def raiz(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Muestra la versión y termina.",
            callback=_mostrar_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Sin subcomando abre la interfaz gráfica."""
    if ctx.invoked_subcommand is None:
        from timetabling.gui.app import ejecutar

        raise typer.Exit(ejecutar())


class TamanoEjemplo(StrEnum):
    pequeno = "pequeno"
    mediano = "mediano"


@app.command()
def ejemplo(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario que se creará.")],
    tamano: Annotated[
        TamanoEjemplo, typer.Option("--tamano", help="Tamaño del ejemplo.")
    ] = TamanoEjemplo.pequeno,
    sobrescribir: Annotated[
        bool,
        typer.Option(
            "--sobrescribir", help="Reemplaza el archivo si existe (con respaldo previo)."
        ),
    ] = False,
) -> None:
    """Crea un proyecto de ejemplo (pequeño: 5 grupos; mediano: 30 grupos)."""
    from timetabling.ejemplo import crear_ejemplo

    try:
        ruta = crear_ejemplo(proyecto, tamano.value, sobrescribir)  # type: ignore[arg-type]
    except FileExistsError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Proyecto de ejemplo ({tamano.value}) creado en «{ruta}».")


@app.command()
def validar(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario que se validará.")],
) -> None:
    """Revisa los datos del proyecto (§10). Termina con código 1 si hay errores."""
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.servicios.proyecto import validar_proyecto

    try:
        problemas = validar_proyecto(proyecto)
    except (ErrorProyecto, FileNotFoundError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    errores = [p for p in problemas if p.es_error]
    advertencias = [p for p in problemas if not p.es_error]
    for problema in problemas:
        marca = "✖ Error" if problema.es_error else "⚠ Advertencia"
        typer.echo(f"{marca}: {problema.mensaje}")
        typer.echo(f"    → {problema.accion}")
    e, a = len(errores), len(advertencias)
    typer.echo(
        f"{e} {'error' if e == 1 else 'errores'}, "
        f"{a} {'advertencia' if a == 1 else 'advertencias'}."
    )
    if errores:
        raise typer.Exit(1)


@app.command()
def generar(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario.")],
    tiempo_limite: Annotated[
        int | None,
        typer.Option("--tiempo-limite", help="Segundos (por defecto, los del proyecto)."),
    ] = None,
    hilos: Annotated[int | None, typer.Option("--hilos", help="Hilos del solver.")] = None,
    exportar_a: Annotated[
        Path | None, typer.Option("--exportar", help="Exporta el horario (.xlsx).")
    ] = None,
) -> None:
    """Genera un horario y lo guarda en el proyecto. Código 1 si no hay horario."""
    from timetabling.dominio.modelos import NOMBRES_CRITERIOS
    from timetabling.nucleo.resolver import Progreso
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.servicios.generacion import ErrorValidacion
    from timetabling.servicios.generacion import generar as generar_horario

    ultimo = {"fase": ""}

    def informar(progreso: Progreso) -> None:
        if progreso.fase != ultimo["fase"]:
            ultimo["fase"] = progreso.fase
            typer.echo(f"[{progreso.tiempo_s:6.1f} s] Fase: {progreso.fase}")
        if progreso.mejor_objetivo is not None:
            typer.echo(
                f"[{progreso.tiempo_s:6.1f} s] Solución {progreso.soluciones}: "
                f"penalización {progreso.mejor_objetivo:.1f} (cota {progreso.cota:.1f})"
            )

    try:
        resultado = generar_horario(proyecto, tiempo_limite, hilos, informar)
    except ErrorValidacion as error:
        typer.echo(str(error), err=True)
        for problema in error.problemas:
            if problema.es_error:
                typer.echo(f"✖ {problema.mensaje}", err=True)
        raise typer.Exit(1) from error
    except (ErrorProyecto, FileNotFoundError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    r = resultado.resolucion
    typer.echo(f"Estado: {r.estado.value} en {r.tiempo_s:.1f} s.")
    if resultado.solucion is None:
        typer.echo(r.mensaje or "No se generó ningún horario.")
        if resultado.diagnostico is not None:
            typer.echo(f"Diagnóstico: {resultado.diagnostico.mensaje}")
            for enlace in resultado.diagnostico.enlaces:
                typer.echo(f"  → {enlace.entidad}: {enlace.texto}")
        raise typer.Exit(1)
    solucion = resultado.solucion
    cota = " (cota superior)" if solucion.penalizaciones_son_cota else ""
    typer.echo(f"Guardado como «{solucion.nombre}» (id {solucion.id}).")
    typer.echo(f"Penalización total{cota}: {solucion.penalizaciones.get('total', 0):.1f}")
    for criterio, nombre in NOMBRES_CRITERIOS.items():
        if criterio in solucion.penalizaciones:
            typer.echo(f"  {criterio} {nombre}: {solucion.penalizaciones[criterio]:g}")
    if exportar_a is not None and solucion.id is not None:
        _exportar(proyecto, solucion.id, exportar_a)
    if solucion.violaciones:
        typer.echo(f"⚠ El verificador encontró {len(solucion.violaciones)} violaciones.")
        raise typer.Exit(1)


@app.command()
def reajustar(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario.")],
    tiempo_limite: Annotated[
        int | None,
        typer.Option("--tiempo-limite", help="Segundos (por defecto, los del proyecto)."),
    ] = None,
    hilos: Annotated[int | None, typer.Option("--hilos", help="Hilos del solver.")] = None,
) -> None:
    """Reajusta el horario vigente con cambios mínimos y guarda el resultado (§13)."""
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.servicios.generacion import ErrorValidacion
    from timetabling.servicios.reajuste import reajustar as reajustar_vigente

    try:
        resultado = reajustar_vigente(proyecto, tiempo_limite, hilos)
    except ErrorValidacion as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    except (ErrorProyecto, FileNotFoundError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    r = resultado.generacion.resolucion
    typer.echo(f"Estado: {r.estado.value} en {r.tiempo_s:.1f} s.")
    if resultado.mapeo.por_traslape:
        typer.echo("El vigente estaba desactualizado: se mapeó por traslape.")
    if resultado.mapeo.sin_correspondencia:
        typer.echo(f"{len(resultado.mapeo.sin_correspondencia)} clases sin correspondencia.")
    solucion = resultado.generacion.solucion
    if solucion is None:
        typer.echo(r.mensaje or "No se encontró un reajuste.")
        raise typer.Exit(1)
    typer.echo(f"Guardado como «{solucion.nombre}» (id {solucion.id}).")
    if resultado.comparacion is not None:
        typer.echo(f"Cambios respecto al vigente: {resultado.comparacion.resumen()}")
        for cambio in resultado.comparacion.cambios[:20]:
            antes = cambio.antes.texto() if cambio.antes else "—"
            despues = cambio.despues.texto() if cambio.despues else "—"
            typer.echo(f"  {cambio.clase}: {antes} → {despues} ({cambio.descripcion})")


def _exportar(proyecto: Path, solucion_id: int, salida: Path) -> None:
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.servicios.exportacion import exportar as exportar_solucion

    try:
        ruta = exportar_solucion(proyecto, solucion_id, salida)
    except (ErrorProyecto, FileNotFoundError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(f"Exportado a «{ruta}».")


@app.command()
def exportar(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario.")],
    solucion: Annotated[int, typer.Option("--solucion", help="Id de la solución.")],
    salida: Annotated[Path, typer.Option("--salida", help="Archivo .xlsx de salida.")],
) -> None:
    """Exporta una solución guardada a Excel."""
    _exportar(proyecto, solucion, salida)


@app.command("importar-excel")
def importar_excel(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario.")],
    cuadro: Annotated[Path, typer.Argument(help="Cuadro de horarios por grado (.xlsx).")],
    mapeo: Annotated[
        Path | None,
        typer.Option("--mapeo", help="Mapeo en JSON (hojas → grados, textos → asignaturas)."),
    ] = None,
    guardar_mapeo: Annotated[
        Path | None,
        typer.Option("--guardar-mapeo", help="Escribe el mapeo sugerido en JSON y termina."),
    ] = None,
) -> None:
    """Importa asignaturas, grupos y plan desde el cuadro de horarios (§15.1)."""
    from timetabling.importacion.horarios_excel import MapeoHorarios, mapeo_inicial
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.persistencia.repositorio import Repositorio
    from timetabling.servicios.importacion import importar_horarios, leer_horarios

    try:
        hojas = leer_horarios(cuadro)
        with Repositorio.abrir(proyecto) as repo:
            elegido = (MapeoHorarios.de_json(mapeo.read_text("utf-8")) if mapeo
                       else mapeo_inicial(repo.cargar_datos(), hojas))  # fmt: skip
            if guardar_mapeo is not None:
                guardar_mapeo.write_text(elegido.a_json(), "utf-8")
                typer.echo(f"Mapeo sugerido escrito en «{guardar_mapeo}».")
                return
            resultado = importar_horarios(repo, hojas, elegido)
    except (ErrorProyecto, FileNotFoundError, OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(resultado.texto())


@app.command("importar-maestros")
def importar_maestros(
    proyecto: Annotated[Path, typer.Argument(help="Archivo .horario.")],
    cuadro: Annotated[Path, typer.Argument(help="Cuadro de maestros (.xlsx).")],
    con_horarios: Annotated[
        bool, typer.Option("--con-horarios", help="Importa también los horarios como borrador.")
    ] = False,
) -> None:
    """Importa profesores y su asignación por grupo desde el cuadro de maestros (§15.2)."""
    from timetabling.importacion.maestros_excel import mapeo_inicial
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.persistencia.repositorio import Repositorio
    from timetabling.servicios.importacion import importar_maestros as importar
    from timetabling.servicios.importacion import leer_maestros

    try:
        bloques = leer_maestros(cuadro)
        with Repositorio.abrir(proyecto) as repo:
            elegido = mapeo_inicial(repo.cargar_datos(), bloques)
            elegido.con_horarios = con_horarios
            resultado, borrador = importar(repo, bloques, elegido)
    except (ErrorProyecto, FileNotFoundError, OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(resultado.texto())
    if borrador is not None:
        typer.echo(f"Borrador guardado como «{borrador.nombre}» (id {borrador.id}).")


@app.command("importar-v6")
def importar_v6(
    anterior: Annotated[Path, typer.Argument(help="Proyecto de la versión anterior (.horario).")],
    nuevo: Annotated[Path, typer.Argument(help="Proyecto nuevo que se creará (.horario).")],
) -> None:
    """Convierte un proyecto de la versión anterior (esquema v6) en uno nuevo (§15.3)."""
    from timetabling.persistencia.migraciones import ErrorProyecto
    from timetabling.servicios.importacion import importar_v6 as importar

    try:
        informe = importar(anterior, nuevo)
    except (ErrorProyecto, FileNotFoundError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(informe.texto())


def principal() -> None:
    """Punto de entrada del ejecutable `timetabling`."""
    app()


if __name__ == "__main__":
    principal()
