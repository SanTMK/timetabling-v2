"""Creado con Claude.

Estadísticas de una solución guardada: carga docente (§16.1, hoja `CargaDocente`; pestaña de
Resultados).
"""

from collections import defaultdict
from dataclasses import dataclass

from timetabling.dominio.modelos import DatosEscuela, Solucion, por_id


@dataclass(frozen=True)
class CargaProfesor:
    nombre: str
    minutos: int
    minimo: int
    maximo: int
    dias: int
    minutos_hueco: int

    @property
    def porcentaje(self) -> float:
        return 100.0 * self.minutos / self.maximo if self.maximo else 0.0


def carga_docente(solucion: Solucion, datos: DatosEscuela) -> list[CargaProfesor]:
    """Minutos asignados, límites, días con clase y minutos de hueco por profesor. Los huecos no
    cuentan los recesos de los niveles en que da clase ese día."""
    profesores = por_id(datos.profesores)
    niveles = por_id(datos.niveles)
    intervalos: dict[str, dict[str, set[tuple[int, int, int | None]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for a in solucion.asignaciones:
        if not a.profesor_nombre:
            continue
        f = solucion.franjas[a.franja]
        intervalos[a.profesor_nombre][f.dia].add((f.inicio, f.fin, f.nivel_id))
    nombres = [p.nombre for p in datos.profesores if p.nombre in intervalos]
    nombres += sorted(set(intervalos) - set(nombres))
    por_nombre = {p.nombre: p for p in profesores.values()}
    resultado = []
    for nombre in nombres:
        minutos = 0
        hueco = 0
        for del_dia in intervalos[nombre].values():
            ordenados = sorted(del_dia)
            minutos += sum(fin - inicio for inicio, fin, _ in ordenados)
            ocupados = set()
            for inicio, fin, _ in ordenados:
                ocupados.update(range(inicio, fin))
            recesos = set()
            for nivel_id in {n for _, _, n in ordenados}:
                nivel = niveles.get(nivel_id) if nivel_id is not None else None
                for r in nivel.recesos if nivel else []:
                    recesos.update(range(r.inicio, r.fin))
            tramo = set(range(ordenados[0][0], max(fin for _, fin, _ in ordenados)))
            hueco += len(tramo - ocupados - recesos)
        profesor = por_nombre.get(nombre)
        resultado.append(
            CargaProfesor(
                nombre=nombre,
                minutos=minutos,
                minimo=profesor.carga_min_semanal_min if profesor else 0,
                maximo=profesor.carga_max_semanal_min if profesor else 0,
                dias=len(intervalos[nombre]),
                minutos_hueco=hueco,
            )
        )
    return resultado
