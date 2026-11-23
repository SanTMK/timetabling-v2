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


def principal() -> None:
    """Punto de entrada del ejecutable `timetabling`."""
    app()


if __name__ == "__main__":
    principal()
