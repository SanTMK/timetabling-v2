"""Creado con Claude.

Conversión entre colocaciones (núcleo) y `Solucion` guardada (§5.3): instantánea de franjas y
copias desnormalizadas que mantienen legible el horario.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.clases import texto_destinatarios
from timetabling.dominio.modelos import (
    Asignacion,
    DatosEscuela,
    EstadoSolucion,
    FranjaGuardada,
    OrigenSolucion,
    Solucion,
    Violacion,
    por_id,
)
from timetabling.dominio.tiempo import DIAS, NOMBRES_DIAS, texto_rango
from timetabling.nucleo.franjas import Calendario


def a_solucion(
    datos: DatosEscuela,
    colocaciones: Iterable[Colocacion],
    *,
    nombre: str,
    estado: EstadoSolucion,
    origen: OrigenSolucion,
    calendario: Calendario | None = None,
    tiempo_s: float = 0.0,
    penalizaciones: dict[str, float] | None = None,
    penalizaciones_son_cota: bool = False,
    violaciones: list[Violacion] | None = None,
    nota: str = "",
    base_id: int | None = None,
) -> Solucion:
    """Arma una `Solucion` con la instantánea de todas las franjas de la escuela."""
    calendario = calendario or Calendario.de(datos)
    franjas = sorted(
        calendario.franjas.values(), key=lambda f: (f.nivel_id, DIAS.index(f.dia), f.indice)
    )
    posicion = {f.id: i for i, f in enumerate(franjas)}
    clases = por_id(datos.clases)
    asignaturas = por_id(datos.asignaturas)
    profesores = por_id(datos.profesores)
    asignaciones: list[Asignacion] = []
    for c in sorted(colocaciones):
        clase = clases[c.clase_id]
        asignatura = asignaturas[clase.asignatura_id]
        comunes = {
            "clase_id": c.clase_id,
            "franja": posicion[c.franja_id],
            "asignatura_nombre": asignatura.nombre,
            "grupos_texto": texto_destinatarios(datos, clase),
            "color": asignatura.color,
            "bloqueada": c.bloqueada,
        }
        for p in c.profesores or (None,):
            asignaciones.append(
                Asignacion(
                    profesor_id=p,
                    profesor_nombre=profesores[p].nombre if p in profesores else "",
                    **comunes,  # type: ignore[arg-type]
                )
            )
    return Solucion(
        nombre=nombre,
        fecha=datetime.now().replace(microsecond=0),
        estado=estado,
        origen=origen,
        tiempo_s=tiempo_s,
        penalizaciones=dict(penalizaciones or {}),
        penalizaciones_son_cota=penalizaciones_son_cota,
        nota=nota,
        base_id=base_id,
        huella_niveles=datos.huella_niveles(),
        franjas=[
            FranjaGuardada(
                nivel_id=f.nivel_id, dia=f.dia, indice=f.indice, inicio=f.inicio, fin=f.fin
            )
            for f in franjas
        ],
        asignaciones=asignaciones,
        violaciones=list(violaciones or []),
    )


def a_colocaciones(solucion: Solucion) -> list[Colocacion]:
    """Colocaciones de una solución con la misma huella de niveles (las franjas guardadas se
    corresponden por nivel, día e índice). Las asignaciones sin clase se omiten. El mapeo por
    traslape para soluciones desactualizadas llega con el reajuste (§13)."""
    agrupadas: dict[tuple[int, str], tuple[list[int], bool]] = {}
    for a in solucion.asignaciones:
        if a.clase_id is None:
            continue
        f = solucion.franjas[a.franja]
        if f.nivel_id is None:
            continue
        clave = (a.clase_id, f"{f.nivel_id}:{f.dia}:{f.indice}")
        profesores, bloqueada = agrupadas.get(clave, ([], False))
        if a.profesor_id is not None:
            profesores.append(a.profesor_id)
        agrupadas[clave] = (profesores, bloqueada or a.bloqueada)
    return sorted(
        Colocacion(clase_id, franja_id, tuple(sorted(profesores)), bloqueada)
        for (clase_id, franja_id), (profesores, bloqueada) in agrupadas.items()
    )


@dataclass
class Mapeo:
    """Colocaciones actuales que corresponden a un horario guardado (§13.2, §13.3)."""

    colocaciones: list[Colocacion] = field(default_factory=list)
    sin_correspondencia: list[str] = field(default_factory=list)
    """Ocurrencias que no se pudieron mapear (clase o franja inexistente)."""
    por_traslape: bool = False


def mapear_solucion(
    solucion: Solucion, datos: DatosEscuela, calendario: Calendario | None = None
) -> Mapeo:
    """Lleva un horario guardado a las clases y franjas actuales.

    - Clase: por `clase_id` si existe; si no, por asignatura + destinatarios (texto guardado).
    - Franja: si la huella de niveles coincide, la misma (nivel, día, índice); si no, la franja
      actual de **mayor traslape en minutos** del mismo día y nivel.
    - Profesores: los guardados que siguen existiendo.
    Lo que no se puede mapear se cuenta como «sin correspondencia».
    """
    calendario = calendario or Calendario.de(datos)
    clases = por_id(datos.clases)
    asignaturas = por_id(datos.asignaturas)
    profesores = por_id(datos.profesores)
    por_texto: dict[tuple[str, str], int] = {}
    for clase in datos.clases:
        asignatura = asignaturas.get(clase.asignatura_id)
        if clase.id is not None and asignatura is not None:
            por_texto[(asignatura.nombre, texto_destinatarios(datos, clase))] = clase.id
    traslape = solucion.huella_niveles != datos.huella_niveles()
    por_nivel_dia: dict[tuple[int, str], list] = {}  # type: ignore[type-arg]
    for f in calendario.franjas.values():
        por_nivel_dia.setdefault((f.nivel_id, f.dia), []).append(f)

    agrupadas: dict[tuple[int | None, str, str, int], list[int]] = {}
    bloqueadas: dict[tuple[int | None, str, str, int], bool] = {}
    for a in solucion.asignaciones:
        clave = (a.clase_id, a.asignatura_nombre, a.grupos_texto, a.franja)
        agrupadas.setdefault(clave, [])
        if a.profesor_id is not None:
            agrupadas[clave].append(a.profesor_id)
        bloqueadas[clave] = bloqueadas.get(clave, False) or a.bloqueada

    mapeo = Mapeo(por_traslape=traslape)
    ocupadas: set[tuple[int, str]] = set()
    for clave, ids in sorted(agrupadas.items(), key=lambda x: (str(x[0][0]), x[0][3])):
        clase_id, asignatura, grupos, indice = clave
        guardada = solucion.franjas[indice]
        texto = f"{asignatura} · {grupos} ({NOMBRES_DIAS[guardada.dia][:2]} "
        texto += f"{texto_rango(guardada.inicio, guardada.fin)})"
        actual = clase_id if clase_id in clases else por_texto.get((asignatura, grupos))
        if actual is None or guardada.nivel_id is None:
            mapeo.sin_correspondencia.append(texto)
            continue
        if not traslape:
            franja = calendario.franja(guardada.nivel_id, guardada.dia, guardada.indice)
        else:
            candidatas = por_nivel_dia.get((guardada.nivel_id, guardada.dia), [])
            minutos = [
                (min(f.fin, guardada.fin) - max(f.inicio, guardada.inicio), -f.indice, f)
                for f in candidatas
            ]
            mejor = max(minutos, default=None, key=lambda x: (x[0], x[1]))
            franja = mejor[2] if mejor is not None and mejor[0] > 0 else None
        if franja is None or (actual, franja.id) in ocupadas:
            mapeo.sin_correspondencia.append(texto)
            continue
        ocupadas.add((actual, franja.id))
        vigentes = tuple(sorted(p for p in ids if p in profesores))
        mapeo.colocaciones.append(Colocacion(actual, franja.id, vigentes, bloqueadas[clave]))
    mapeo.colocaciones.sort()
    return mapeo
