"""Creado con Claude.

Construcción del ejecutable (§19):

1. genera el ícono dibujado con Qt (`.icns` en macOS, `.ico` en Windows);
2. ejecuta PyInstaller en modo **onedir**, sin consola, con `collect_all("ortools")`, los datos
   del paquete (`esquema.sql`) y sus metadatos (para `--version`);
3. deja un `.zip` en `dist/` («timetabling-<versión>-<sistema>-<arquitectura>.zip»).

Con `--humo` corre además la prueba de humo sobre el ejecutable empaquetado:
`--version`, `ejemplo t.horario --tamano pequeno`, `generar t.horario --tiempo-limite 30` y,
como extra, la exportación a PDF (comprueba Qt dentro del paquete).

    uv run python empaquetado/construir.py [--humo] [--sin-zip]
"""

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
BUILD = RAIZ / "build"
NOMBRE = "timetabling"


def sistema() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def arquitectura() -> str:
    maquina = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        maquina, maquina
    )


def generar_icono() -> Path | None:
    """Ícono para PyInstaller dibujado con Qt; `None` en Linux (no lo usa)."""
    from PySide6.QtGui import QGuiApplication

    from timetabling.gui.icono import dibujar

    _app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    carpeta = BUILD / "icono"
    carpeta.mkdir(parents=True, exist_ok=True)
    dibujar(1024).save(str(carpeta / "icono.png"))
    if sys.platform == "darwin":
        destino = carpeta / "icono.icns"
        if not dibujar(1024).save(str(destino), "ICNS"):
            # Respaldo: iconutil con un conjunto de tamaños.
            conjunto = carpeta / "icono.iconset"
            conjunto.mkdir(exist_ok=True)
            for t in (16, 32, 128, 256, 512):
                dibujar(t).save(str(conjunto / f"icon_{t}x{t}.png"))
                dibujar(t * 2).save(str(conjunto / f"icon_{t}x{t}@2x.png"))
            subprocess.run(["iconutil", "-c", "icns", str(conjunto), "-o", str(destino)],
                           check=True)  # fmt: skip
        return destino
    if sys.platform == "win32":
        destino = carpeta / "icono.ico"
        if not dibujar(256).save(str(destino), "ICO"):
            raise RuntimeError("Qt no pudo escribir el ícono .ico.")
        return destino
    return None


def pyinstaller(icono: Path | None) -> Path:
    import PyInstaller.__main__

    argumentos = [
        str(RAIZ / "empaquetado" / "lanzador.py"),
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", NOMBRE,
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--collect-all", "ortools",
        "--collect-data", "timetabling",
        "--copy-metadata", "timetabling",
        "--exclude-module", "pytest",
        "--exclude-module", "hypothesis",
    ]  # fmt: skip
    if icono is not None:
        argumentos += ["--icon", str(icono)]
    if sys.platform == "darwin":
        argumentos += ["--osx-bundle-identifier", "io.github.timetabling"]
    PyInstaller.__main__.run(argumentos)
    return ejecutable()


def ejecutable() -> Path:
    if sys.platform == "darwin":
        return DIST / f"{NOMBRE}.app" / "Contents" / "MacOS" / NOMBRE
    if sys.platform == "win32":
        return DIST / NOMBRE / f"{NOMBRE}.exe"
    return DIST / NOMBRE / NOMBRE


def comprimir() -> Path:
    nombre = f"{NOMBRE}-{version('timetabling')}-{sistema()}-{arquitectura()}.zip"
    destino = DIST / nombre
    destino.unlink(missing_ok=True)
    if sys.platform == "darwin":
        # `ditto` conserva los enlaces simbólicos y los permisos del .app.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(DIST / f"{NOMBRE}.app"), str(destino)], check=True)  # fmt: skip
    else:
        shutil.make_archive(str(destino.with_suffix("")), "zip", DIST, NOMBRE)
    return destino


def humo(exe: Path) -> None:
    """Prueba de humo del ejecutable empaquetado (§19)."""

    def correr(*argumentos: str, carpeta: Path) -> str:
        inicio = time.monotonic()
        resultado = subprocess.run([str(exe), *argumentos], cwd=carpeta, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=300)  # fmt: skip
        salida = (resultado.stdout + resultado.stderr).strip()
        print(f"$ {NOMBRE} {' '.join(argumentos)}  ({time.monotonic() - inicio:.1f} s, "
              f"código {resultado.returncode})")  # fmt: skip
        print("  " + salida.replace("\n", "\n  "))
        if resultado.returncode != 0:
            raise SystemExit(f"La prueba de humo falló en «{' '.join(argumentos)}».")
        return salida

    with tempfile.TemporaryDirectory() as temporal:
        carpeta = Path(temporal)
        salida = correr("--version", carpeta=carpeta)
        creado = correr("ejemplo", "u.horario", "--tamano", "pequeno", carpeta=carpeta)
        if "«u.horario»" not in creado:
            raise SystemExit(f"La salida no llega en UTF-8: «{creado}»")
        if version("timetabling") not in salida:
            raise SystemExit(f"--version no muestra {version('timetabling')}: «{salida}»")
        correr("ejemplo", "t.horario", "--tamano", "pequeno", carpeta=carpeta)
        salida = correr("generar", "t.horario", "--tiempo-limite", "30", carpeta=carpeta)
        if "Guardado como" not in salida:
            raise SystemExit("generar no guardó ningún horario.")
        # Además (no lo pide §19): el PDF usa Qt dentro del paquete.
        correr("exportar", "t.horario", "--solucion", "1", "--salida", "t.pdf", carpeta=carpeta)
        if not (carpeta / "t.pdf").read_bytes().startswith(b"%PDF"):
            raise SystemExit("exportar no generó un PDF válido.")
    print("Prueba de humo: OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--humo", action="store_true", help="corre la prueba de humo al final")
    parser.add_argument("--solo-humo", action="store_true", help="no construye: solo la prueba")
    parser.add_argument("--sin-zip", action="store_true", help="no genera el .zip")
    args = parser.parse_args()
    if args.solo_humo:
        humo(ejecutable())
        return
    exe = pyinstaller(generar_icono())
    print(f"Ejecutable: {exe}")
    if not args.sin_zip:
        print(f"Paquete: {comprimir()}")
    if args.humo:
        humo(exe)


if __name__ == "__main__":
    main()
