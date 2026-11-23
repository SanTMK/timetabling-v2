"""Creado con Claude.

Conversión entre colocaciones (núcleo) y `Solucion` guardada (§5.3): instantánea de franjas y
copias desnormalizadas que mantienen legible el horario.
"""

from collections.abc import Iterable
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
from timetabling.dominio.tiempo import DIAS
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
