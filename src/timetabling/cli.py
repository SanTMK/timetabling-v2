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
    """Sin subcomando abre la interfaz gráfica (disponible a partir de F6)."""
    if ctx.invoked_subcommand is None:
        typer.echo("La interfaz gráfica todavía no está disponible (fase F6).")


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
) -> None:
    """Genera un horario y lo guarda en el proyecto. Código 1 si no hay horario."""
    from timetabling.nucleo.objetivo import NOMBRES_CRITERIOS
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
    if solucion.violaciones:
        typer.echo(f"⚠ El verificador encontró {len(solucion.violaciones)} violaciones.")
        raise typer.Exit(1)


def principal() -> None:
    """Punto de entrada del ejecutable `timetabling`."""
    app()


if __name__ == "__main__":
    principal()
