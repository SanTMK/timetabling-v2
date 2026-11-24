"""Creado con Claude.

Punto de entrada del ejecutable empaquetado (§19): sin argumentos abre la interfaz; con
argumentos funciona como la línea de comandos.

El ejecutable no tiene consola. En Windows, para que los subcomandos escriban su salida:
1. si el proceso heredó una salida redirigida (archivo o tubería), se usa esa;
2. si no, se adjunta a la consola del proceso padre, si existe;
3. si tampoco, la salida se descarta.
La salida va siempre en UTF-8.
"""

import os
import sys


def _salida_windows() -> None:
    import ctypes
    import msvcrt

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GetStdHandle.restype = ctypes.c_void_p

    def abrir(numero: int, modo: str) -> object | None:
        manejador = kernel32.GetStdHandle(numero)
        if manejador in (None, 0, ctypes.c_void_p(-1).value):
            return None
        if kernel32.GetFileType(ctypes.c_void_p(manejador)) == 0:  # FILE_TYPE_UNKNOWN
            return None
        try:
            descriptor = msvcrt.open_osfhandle(manejador, os.O_TEXT)  # type: ignore[attr-defined]
            return os.fdopen(descriptor, modo, encoding="utf-8", errors="replace", buffering=1)
        except OSError:
            return None

    salida = sys.stdout if sys.stdout is not None else abrir(-11, "w")
    error = sys.stderr if sys.stderr is not None else abrir(-12, "w")
    # Siempre UTF-8 (si no, Python usa la página de códigos de Windows y los acentos se dañan).
    for flujo in (salida, error):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")
    if salida is None and kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        kernel32.SetConsoleOutputCP(65001)  # la consola interpreta UTF-8
        salida = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        error = error or salida
    nulo = open(os.devnull, "w")  # noqa: SIM115
    sys.stdout = salida or nulo  # type: ignore[assignment]
    sys.stderr = error or salida or nulo  # type: ignore[assignment]


def main() -> None:
    if os.name == "nt" and len(sys.argv) > 1:
        _salida_windows()
    elif sys.stdout is None or sys.stderr is None:
        nulo = open(os.devnull, "w")  # noqa: SIM115
        sys.stdout = sys.stdout or nulo
        sys.stderr = sys.stderr or nulo
    from timetabling.cli import principal

    principal()


if __name__ == "__main__":
    main()
