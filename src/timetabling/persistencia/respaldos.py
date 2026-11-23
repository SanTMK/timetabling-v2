"""Creado con Claude.

Respaldos automáticos (§6.4) en
`<carpeta del proyecto>/.respaldos/<nombre>-AAAAMMDD-HHMMSS.horario`, creados con la API de
respaldo de `sqlite3`.
"""

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

CARPETA_RESPALDOS = ".respaldos"


@dataclass(frozen=True)
class Respaldo:
    ruta: Path
    fecha: datetime


def carpeta_respaldos(ruta_proyecto: Path) -> Path:
    return ruta_proyecto.parent / CARPETA_RESPALDOS


def _patron(ruta_proyecto: Path) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(ruta_proyecto.stem)}-(\d{{8}})-(\d{{6}})(?:-(\d+))?\.horario$")


def listar_respaldos(ruta_proyecto: Path) -> list[Respaldo]:
    """Respaldos del proyecto, del más reciente al más antiguo."""
    carpeta = carpeta_respaldos(ruta_proyecto)
    if not carpeta.is_dir():
        return []
    patron = _patron(ruta_proyecto)
    encontrados: list[tuple[datetime, int, Path]] = []
    for archivo in carpeta.iterdir():
        coincidencia = patron.match(archivo.name)
        if coincidencia:
            fecha = datetime.strptime(coincidencia.group(1) + coincidencia.group(2), "%Y%m%d%H%M%S")
            encontrados.append((fecha, int(coincidencia.group(3) or 0), archivo))
    encontrados.sort(reverse=True)
    return [Respaldo(ruta=archivo, fecha=fecha) for fecha, _, archivo in encontrados]


def _ruta_nueva(ruta_proyecto: Path, ahora: datetime) -> Path:
    carpeta = carpeta_respaldos(ruta_proyecto)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = f"{ruta_proyecto.stem}-{ahora:%Y%m%d-%H%M%S}"
    # El contador nunca reutiliza un nombre liberado por la poda: así el orden por nombre
    # siempre coincide con el orden de creación.
    usados = [-1]
    for archivo in carpeta.glob(f"{base}*.horario"):
        resto = archivo.name[len(base) : -len(".horario")]
        if resto == "":
            usados.append(0)
        elif resto.startswith("-") and resto[1:].isdigit():
            usados.append(int(resto[1:]))
    siguiente = max(usados) + 1
    return carpeta / (f"{base}.horario" if siguiente == 0 else f"{base}-{siguiente}.horario")


def podar(ruta_proyecto: Path, conservar: int) -> list[Path]:
    """Elimina los respaldos más antiguos y deja los últimos `conservar`."""
    eliminados: list[Path] = []
    for respaldo in listar_respaldos(ruta_proyecto)[max(conservar, 1) :]:
        respaldo.ruta.unlink(missing_ok=True)
        eliminados.append(respaldo.ruta)
    return eliminados


def respaldar_conexion(
    con: sqlite3.Connection,
    ruta_proyecto: Path,
    conservar: int,
    ahora: datetime | None = None,
) -> Path:
    """Copia la base abierta a un archivo de respaldo nuevo y poda los antiguos."""
    destino = _ruta_nueva(ruta_proyecto, ahora or datetime.now())
    copia = sqlite3.connect(destino)
    try:
        con.backup(copia)
        copia.execute("PRAGMA journal_mode = DELETE")
    finally:
        copia.close()
    podar(ruta_proyecto, conservar)
    return destino


def respaldar_archivo(ruta_proyecto: Path, conservar: int, ahora: datetime | None = None) -> Path:
    """Copia un archivo de proyecto cerrado (por ejemplo, antes de sobrescribirlo)."""
    destino = _ruta_nueva(ruta_proyecto, ahora or datetime.now())
    shutil.copy2(ruta_proyecto, destino)
    podar(ruta_proyecto, conservar)
    return destino


def hay_respaldo_del_dia(ruta_proyecto: Path, dia: date) -> bool:
    return any(r.fecha.date() == dia for r in listar_respaldos(ruta_proyecto))
