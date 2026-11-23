"""Creado con Claude.

Cuidado del archivo de proyecto (§6.1): detección de carpetas sincronizadas o de red, y archivo
de bloqueo `.horario.lock` con el PID y el equipo. Todo es local, sin red.
"""

import json
import os
import platform
import socket
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath

_SERVICIOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("OneDrive", ("onedrive",)),
    ("Dropbox", ("dropbox",)),
    ("Google Drive", ("google drive", "googledrive", "my drive", "mi unidad")),
    ("iCloud Drive", ("icloud drive", "iclouddrive", "mobile documents", "com~apple~clouddocs")),
)


@dataclass(frozen=True)
class Aviso:
    """Aviso no bloqueante al abrir un proyecto."""

    clave: str
    mensaje: str


def detectar_carpeta_sincronizada(ruta: Path) -> str | None:
    """Nombre del servicio de sincronización o «una unidad de red», o `None`.

    Se decide por los nombres de la ruta y, en Windows, por el tipo de unidad."""
    texto = str(ruta)
    partes = [p.lower() for p in (PureWindowsPath(texto).parts if "\\" in texto else ruta.parts)]
    for servicio, claves in _SERVICIOS:
        for parte in partes:
            if any(parte == clave or parte.startswith(clave) for clave in claves):
                return servicio
    if any(parte.startswith("cloudstorage") for parte in partes):
        return "un servicio de almacenamiento en la nube"
    if texto.startswith(("\\\\", "//")):
        return "una unidad de red"
    if sys.platform == "win32" and _es_unidad_remota_windows(texto):
        return "una unidad de red"
    return None


def _es_unidad_remota_windows(texto: str) -> bool:  # pragma: no cover - solo Windows
    import ctypes

    unidad = PureWindowsPath(texto).drive
    if not unidad:
        return False
    tipo = ctypes.windll.kernel32.GetDriveTypeW(unidad + "\\")  # type: ignore[attr-defined]
    return bool(tipo == 4)  # DRIVE_REMOTE


def aviso_carpeta_sincronizada(ruta: Path) -> Aviso | None:
    servicio = detectar_carpeta_sincronizada(ruta)
    if servicio is None:
        return None
    return Aviso(
        "carpeta_sincronizada",
        f"El proyecto está en una carpeta de {servicio}. Para evitar archivos dañados o en "
        "conflicto: no lo abra en dos equipos a la vez, espere a que termine la sincronización "
        "antes de abrirlo y, si es posible, trabaje con una copia en una carpeta local.",
    )


# ---------------------------------------------------------------------------
# Archivo de bloqueo
# ---------------------------------------------------------------------------


def ruta_bloqueo(ruta: Path) -> Path:
    return ruta.with_name(ruta.name + ".lock")


def nombre_equipo() -> str:
    return platform.node() or socket.gethostname()


def proceso_vivo(pid: int) -> bool:
    """Indica si el proceso existe en este equipo."""
    if pid <= 0:
        return False
    if sys.platform == "win32":  # pragma: no cover - solo Windows
        return _proceso_vivo_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _proceso_vivo_windows(pid: int) -> bool:  # pragma: no cover - solo Windows
    # `os.kill(pid, 0)` en Windows terminaría el proceso; se consulta con la API nativa.
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    proceso = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not proceso:
        return False
    try:
        codigo = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(proceso, ctypes.byref(codigo)):
            return False
        return codigo.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(proceso)


@dataclass(frozen=True)
class InfoBloqueo:
    pid: int
    equipo: str
    fecha: str


def leer_bloqueo(ruta: Path) -> InfoBloqueo | None:
    archivo = ruta_bloqueo(ruta)
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        return InfoBloqueo(int(datos["pid"]), str(datos["equipo"]), str(datos.get("fecha", "")))
    except FileNotFoundError:
        return None
    except (ValueError, KeyError, TypeError, OSError):
        return InfoBloqueo(0, "", "")


def bloqueo_vigente(info: InfoBloqueo) -> bool:
    """Un bloqueo de otro equipo se considera vigente; uno de este equipo, solo si su proceso
    sigue vivo y no es este mismo proceso."""
    if not info.equipo:
        return False
    if info.equipo != nombre_equipo():
        return True
    return info.pid != os.getpid() and proceso_vivo(info.pid)


def tomar_bloqueo(ruta: Path) -> tuple[bool, Aviso | None]:
    """Crea el archivo de bloqueo. Devuelve `(propio, aviso)`: si otro lo tiene vigente, no se
    toma y se devuelve un aviso."""
    info = leer_bloqueo(ruta)
    if info is not None and bloqueo_vigente(info):
        donde = "en este equipo" if info.equipo == nombre_equipo() else f"en «{info.equipo}»"
        return False, Aviso(
            "bloqueo",
            f"El proyecto podría estar abierto {donde} "
            f"(desde {info.fecha or 'fecha desconocida'}). "
            "Si lo modifica en dos lugares a la vez, se pueden perder cambios.",
        )
    contenido = {
        "pid": os.getpid(),
        "equipo": nombre_equipo(),
        "fecha": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        ruta_bloqueo(ruta).write_text(json.dumps(contenido), encoding="utf-8")
    except OSError:
        return False, Aviso("bloqueo", "No se pudo crear el archivo de bloqueo del proyecto.")
    return True, None


def soltar_bloqueo(ruta: Path) -> None:
    info = leer_bloqueo(ruta)
    if info is not None and info.pid == os.getpid() and info.equipo == nombre_equipo():
        ruta_bloqueo(ruta).unlink(missing_ok=True)
