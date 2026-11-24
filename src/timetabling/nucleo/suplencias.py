"""Creado con Claude.

Candidatos para cubrir una clase (§11.4). Dada una ocurrencia del horario vigente (y
opcionalmente una fecha), lista los profesores que pueden cubrirla:

- habilitados: titulares (asignatura y grados) o marcados como suplentes para esa asignatura
  **y** grado; activos; distintos del ausente;
- disponibles en la franja, sin evento que la toque y sin ausencia registrada esa fecha;
- sin otra clase **ni otra suplencia** ese día que se les cruce (con margen de traslado).

Orden: primero quienes la imparten normalmente, luego sin «preferible no», luego con menos
clases y suplencias ese día, luego con menos suplencias en el mes, luego por nombre.

Trabaja con las horas guardadas de la solución (día, inicio, fin), así sirve aunque esté
desactualizada.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from timetabling.dominio.modelos import (
    Ausencia,
    Clase,
    DatosEscuela,
    FranjaGuardada,
    Profesor,
    Solucion,
    Suplencia,
    por_id,
)
from timetabling.dominio.tiempo import DIAS, Dia, se_traslapan, texto_rango
from timetabling.nucleo.franjas import Franja, evaluar_franja


def dia_de(fecha: date) -> Dia:
    """Letra del día de la semana de una fecha (L M X J V S D)."""
    return DIAS[fecha.weekday()]


@dataclass(frozen=True)
class Candidato:
    profesor_id: int
    nombre: str
    titular: bool
    """La imparte normalmente (habilitado para la asignatura y los grados)."""
    preferible_no: bool
    carga_del_dia: int
    """Clases y suplencias que ya tiene ese día."""
    suplencias_del_mes: int

    @property
    def detalle(self) -> str:
        partes = ["titular" if self.titular else "suplente"]
        if self.preferible_no:
            partes.append("prefiere no")
        partes.append(_contar(self.carga_del_dia, "clase", "clases") + " ese día")
        partes.append(_contar(self.suplencias_del_mes, "suplencia", "suplencias") + " en el mes")
        return ", ".join(partes)


def _contar(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _habilitado(profesor: Profesor, clase: Clase, grados: set[int]) -> tuple[bool, bool]:
    """(puede cubrirla, es titular)."""
    titular = clase.asignatura_id in profesor.asignaturas and grados <= set(profesor.grados)
    suplente = clase.asignatura_id in profesor.suplencia_asignaturas and grados <= set(
        profesor.suplencia_grados
    )
    return titular or suplente, titular


def ausente_en(ausencias: Iterable[Ausencia], profesor_id: int, fecha: date, inicio: int,
               fin: int) -> bool:  # fmt: skip
    """El profesor tiene una ausencia que toca esa fecha y hora."""
    for a in ausencias:
        if a.profesor_id != profesor_id or not a.fecha_inicio <= fecha <= a.fecha_fin:
            continue
        if a.desde is None or a.hasta is None or se_traslapan(inicio, fin, a.desde, a.hasta):
            return True
    return False


def candidatos(
    datos: DatosEscuela,
    solucion: Solucion,
    asignacion_id: int,
    fecha: date | None = None,
    suplencias: Iterable[Suplencia] = (),
    ausencias: Iterable[Ausencia] = (),
) -> list[Candidato]:
    """Profesores que pueden cubrir la asignación `asignacion_id` de la solución, en orden."""
    por_asignacion = {a.id: a for a in solucion.asignaciones}
    asignacion = por_asignacion.get(asignacion_id)
    if asignacion is None or asignacion.clase_id is None:
        return []
    clase = por_id(datos.clases).get(asignacion.clase_id)
    if clase is None:
        return []
    grupos = por_id(datos.grupos)
    grados = {grupos[d.grupo_id].grado_id for d in clase.destinatarios if d.grupo_id in grupos}
    guardada: FranjaGuardada = solucion.franjas[asignacion.franja]
    franja = Franja(guardada.nivel_id or 0, guardada.dia, guardada.indice, guardada.inicio,
                    guardada.fin)  # fmt: skip
    margen = datos.configuracion.margen_traslado_min
    ausente = asignacion.profesor_id
    suplencias = list(suplencias)
    ausencias = list(ausencias)

    # Ocupación del día: clases del horario y suplencias de esa fecha.
    ocupado: dict[int, list[tuple[int, int, int | None]]] = {}
    for a in solucion.asignaciones:
        f = solucion.franjas[a.franja]
        if a.profesor_id is not None and f.dia == franja.dia:
            # Si el profesor está ausente esa fecha, esa clase suya no lo ocupa.
            if fecha is not None and ausente_en(ausencias, a.profesor_id, fecha, f.inicio, f.fin):
                continue
            ocupado.setdefault(a.profesor_id, []).append((f.inicio, f.fin, f.nivel_id))
    del_mes: Counter[int] = Counter()
    for s in suplencias:
        if s.suplente_id is None:
            continue
        if fecha is not None and (s.fecha.year, s.fecha.month) == (fecha.year, fecha.month):
            del_mes[s.suplente_id] += 1
        if fecha is not None and s.fecha == fecha and s.asignacion_id in por_asignacion:
            otra = por_asignacion[s.asignacion_id]
            f = solucion.franjas[otra.franja]
            ocupado.setdefault(s.suplente_id, []).append((f.inicio, f.fin, f.nivel_id))

    resultado: list[tuple[tuple[object, ...], Candidato]] = []
    for profesor in datos.profesores:
        if profesor.id is None or not profesor.activo or profesor.id == ausente:
            continue
        puede, titular = _habilitado(profesor, clase, grados)
        if not puede:
            continue
        evaluacion = evaluar_franja(profesor, franja)
        if not evaluacion.valida:
            continue
        if fecha is not None and ausente_en(ausencias, profesor.id, fecha, franja.inicio,
                                            franja.fin):  # fmt: skip
            continue
        cruces = [
            (i, f, n)
            for i, f, n in ocupado.get(profesor.id, [])
            if se_traslapan(franja.inicio, franja.fin, i, f, margen if n != franja.nivel_id else 0)
        ]
        if cruces:
            continue
        candidato = Candidato(
            profesor_id=profesor.id,
            nombre=profesor.nombre,
            titular=titular,
            preferible_no=evaluacion.validez == "preferible_no",
            carga_del_dia=len(ocupado.get(profesor.id, [])),
            suplencias_del_mes=del_mes[profesor.id],
        )
        orden = (not titular, candidato.preferible_no, candidato.carga_del_dia,
                 candidato.suplencias_del_mes, profesor.nombre)  # fmt: skip
        resultado.append((orden, candidato))
    return [c for _, c in sorted(resultado, key=lambda x: x[0])]


def texto_asignacion(solucion: Solucion, asignacion_id: int) -> str:
    asignacion = next((a for a in solucion.asignaciones if a.id == asignacion_id), None)
    if asignacion is None:
        return "Clase eliminada del horario"
    f = solucion.franjas[asignacion.franja]
    return (
        f"{texto_rango(f.inicio, f.fin)} · {asignacion.asignatura_nombre} · "
        f"{asignacion.grupos_texto}"
    )
