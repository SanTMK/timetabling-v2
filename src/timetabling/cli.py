"""Creado con Claude.

Línea de comandos (§18). En F0 solo existe `--version`; los subcomandos se agregan por fase.
"""

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
    version: bool = typer.Option(
        False,
        "--version",
        help="Muestra la versión y termina.",
        callback=_mostrar_version,
        is_eager=True,
    ),
) -> None:
    """Sin subcomando abre la interfaz gráfica (disponible a partir de F6)."""
    if ctx.invoked_subcommand is None:
        typer.echo("La interfaz gráfica todavía no está disponible (fase F6).")


def principal() -> None:
    """Punto de entrada del ejecutable `timetabling`."""
    app()


if __name__ == "__main__":
    principal()
