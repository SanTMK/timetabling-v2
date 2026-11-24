"""Creado con Claude.

Ausencias y suplencias (§14). Trabaja sobre el horario **vigente** sin modificarlo: una ausencia
deja «afectadas» las clases del ausente en esas fechas (en las ausencias parciales, solo las que
tocan el rango de horas); cada clase afectada se cubre con un suplente o se marca «sin cubrir».
Una suplencia se identifica por (fecha, asignación) y guarda la solución vigente de ese momento.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from timetabling.dominio.modelos import Ausencia, Solucion, Suplencia, por_id
from timetabling.dominio.tiempo import se_traslapan, texto_rango
from timetabling.exportacion.excel import FilaSuplencia, exportar_suplencias_del_dia
from timetabling.nucleo.suplencias import Candidato, candidatos, dia_de
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.persistencia.repositorio import Repositorio


class ErrorSuplencias(ErrorProyecto):
    """No hay horario vigente o la operación no tiene sentido."""


@dataclass(frozen=True)
class ClaseAfectada:
    """Una ocurrencia del vigente que el ausente no puede dar en una fecha."""

    fecha: date
    solucion_id: int
    asignacion_id: int
    profesor_ausente_id: int
    profesor_ausente: str
    inicio: int
    fin: int
    asignatura: str
    grupos: str
    suplencia: Suplencia | None = None

    @property
    def horas(self) -> str:
        return texto_rango(self.inicio, self.fin)

    @property
    def estado(self) -> str:
        if self.suplencia is None:
            return "Pendiente"
        return "Sin cubrir" if self.suplencia.suplente_id is None else "Cubierta"


@dataclass(frozen=True)
class FilaConteo:
    """Conteo mensual de un profesor: suplencias que **realizó** y, de sus clases afectadas,
    cuántas fueron **cubiertas** por otros y cuántas quedaron **sin cubrir**."""

    profesor_id: int
    nombre: str
    realizadas: int
    cubiertas: int
    sin_cubrir: int


def fechas(desde: date, hasta: date) -> list[date]:
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]


def toca(ausencia: Ausencia, fecha: date, inicio: int, fin: int) -> bool:
    """La ausencia cubre esa fecha y, si es parcial, se cruza con [inicio, fin)."""
    if not ausencia.fecha_inicio <= fecha <= ausencia.fecha_fin:
        return False
    if ausencia.desde is None or ausencia.hasta is None:
        return True
    return se_traslapan(inicio, fin, ausencia.desde, ausencia.hasta)


class Suplencias:
    """Operaciones de la pantalla Suplencias sobre un repositorio abierto."""

    def __init__(self, repo: Repositorio) -> None:
        self.repo = repo
        self._vigente: Solucion | None = None
        self._vigente_id: int | None = None

    # ------------------------------------------------------------------ vigente

    def vigente(self) -> Solucion | None:
        ident = self.repo.solucion_vigente_id()
        if ident is None:
            self._vigente = None
            self._vigente_id = None
            return None
        if ident != self._vigente_id:
            self._vigente = self.repo.cargar_solucion(ident)
            self._vigente_id = ident
        return self._vigente

    def _exigir_vigente(self) -> Solucion:
        vigente = self.vigente()
        if vigente is None or vigente.id is None:
            raise ErrorSuplencias(
                "No hay un horario vigente: marque uno en Resultados para gestionar suplencias."
            )
        return vigente

    # ------------------------------------------------------------------ ausencias

    def ausencias(self) -> list[Ausencia]:
        return self.repo.listar_ausencias()

    def ausencias_de(self, fecha: date) -> list[Ausencia]:
        return [a for a in self.ausencias() if a.fecha_inicio <= fecha <= a.fecha_fin]

    def registrar_ausencia(self, ausencia: Ausencia) -> tuple[Ausencia, list[ClaseAfectada]]:
        """Guarda la ausencia y devuelve las clases afectadas del vigente en esas fechas."""
        guardada = self.repo.guardar(ausencia)
        return guardada, self.afectadas_por(guardada)

    def eliminar_ausencia(self, ident: int) -> int:
        """Elimina la ausencia y las suplencias de sus clases que ya no tienen ausencia que las
        justifique. Devuelve cuántas suplencias se quitaron."""
        ausencia = next((a for a in self.ausencias() if a.id == ident), None)
        if ausencia is None:
            return 0
        antes = {(c.fecha, c.asignacion_id) for c in self.afectadas_por(ausencia)}
        self.repo.eliminar(Ausencia, ident)
        siguen = {
            (c.fecha, c.asignacion_id)
            for f in fechas(ausencia.fecha_inicio, ausencia.fecha_fin)
            for c in self.afectadas_del_dia(f)
        }
        quitadas = 0
        for s in self.repo.listar_suplencias(ausencia.fecha_inicio, ausencia.fecha_fin):
            clave = (s.fecha, s.asignacion_id)
            if clave in antes and clave not in siguen and s.id is not None:
                self.repo.eliminar(Suplencia, s.id)
                quitadas += 1
        return quitadas

    # ------------------------------------------------------------------ clases afectadas

    def _afectadas(
        self, ausencias: Iterable[Ausencia], dias: Iterable[date]
    ) -> list[ClaseAfectada]:
        vigente = self.vigente()
        if vigente is None or vigente.id is None:
            return []
        ausencias = list(ausencias)
        dias = sorted(set(dias))
        if not ausencias or not dias:
            return []
        registradas = {
            (s.fecha, s.asignacion_id): s for s in self.repo.listar_suplencias(dias[0], dias[-1])
        }
        resultado: dict[tuple[date, int], ClaseAfectada] = {}
        for fecha in dias:
            dia = dia_de(fecha)
            for a in vigente.asignaciones:
                if a.id is None or a.profesor_id is None:
                    continue
                f = vigente.franjas[a.franja]
                if f.dia != dia:
                    continue
                if not any(
                    x.profesor_id == a.profesor_id and toca(x, fecha, f.inicio, f.fin)
                    for x in ausencias
                ):
                    continue
                resultado[(fecha, a.id)] = ClaseAfectada(
                    fecha=fecha,
                    solucion_id=vigente.id,
                    asignacion_id=a.id,
                    profesor_ausente_id=a.profesor_id,
                    profesor_ausente=a.profesor_nombre,
                    inicio=f.inicio,
                    fin=f.fin,
                    asignatura=a.asignatura_nombre,
                    grupos=a.grupos_texto,
                    suplencia=registradas.get((fecha, a.id)),
                )
        return sorted(
            resultado.values(),
            key=lambda c: (c.fecha, c.inicio, c.profesor_ausente, c.asignatura, c.grupos),
        )

    def afectadas_por(self, ausencia: Ausencia) -> list[ClaseAfectada]:
        """Clases del vigente que deja sin profesor una ausencia (todas sus fechas)."""
        return self._afectadas([ausencia], fechas(ausencia.fecha_inicio, ausencia.fecha_fin))

    def afectadas_del_dia(self, fecha: date) -> list[ClaseAfectada]:
        """Clases afectadas por todas las ausencias registradas que tocan esa fecha."""
        return self._afectadas(self.ausencias_de(fecha), [fecha])

    # ------------------------------------------------------------------ candidatos y asignación

    def candidatos(self, afectada: ClaseAfectada) -> list[Candidato]:
        vigente = self._exigir_vigente()
        inicio_mes = afectada.fecha.replace(day=1)
        siguiente = (inicio_mes + timedelta(days=32)).replace(day=1)
        suplencias = [
            s
            for s in self.repo.listar_suplencias(inicio_mes, siguiente - timedelta(days=1))
            if not (s.fecha == afectada.fecha and s.asignacion_id == afectada.asignacion_id)
        ]
        return candidatos(
            self.repo.cargar_datos(),
            vigente,
            afectada.asignacion_id,
            afectada.fecha,
            suplencias,
            self.ausencias(),
        )

    def asignar(
        self, afectada: ClaseAfectada, suplente_id: int | None, nota: str = ""
    ) -> Suplencia:
        """Cubre la clase con `suplente_id` o la marca «sin cubrir» (`None`). Reemplaza lo que
        hubiera registrado para esa fecha y clase."""
        if suplente_id is not None and suplente_id == afectada.profesor_ausente_id:
            raise ErrorSuplencias("El suplente no puede ser el profesor ausente.")
        existente = next(
            (
                s
                for s in self.repo.listar_suplencias(afectada.fecha, afectada.fecha)
                if s.asignacion_id == afectada.asignacion_id
            ),
            None,
        )
        suplencia = Suplencia(
            id=existente.id if existente else None,
            fecha=afectada.fecha,
            solucion_id=afectada.solucion_id,
            asignacion_id=afectada.asignacion_id,
            profesor_ausente_id=afectada.profesor_ausente_id,
            suplente_id=suplente_id,
            nota=nota,
        )
        return self.repo.guardar(suplencia)

    def quitar(self, suplencia_id: int) -> None:
        """Vuelve la clase a «pendiente»."""
        self.repo.eliminar(Suplencia, suplencia_id)

    # ------------------------------------------------------------------ reportes

    def suplencias_del_dia(self, fecha: date) -> list[Suplencia]:
        return self.repo.listar_suplencias(fecha, fecha)

    def conteo_mensual(self, anio: int, mes: int) -> list[FilaConteo]:
        inicio = date(anio, mes, 1)
        fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        realizadas: Counter[int] = Counter()
        cubiertas: Counter[int] = Counter()
        sin_cubrir: Counter[int] = Counter()
        for s in self.repo.listar_suplencias(inicio, fin):
            if s.suplente_id is None:
                sin_cubrir[s.profesor_ausente_id] += 1
            else:
                realizadas[s.suplente_id] += 1
                cubiertas[s.profesor_ausente_id] += 1
        profesores = por_id(self.repo.cargar_datos().profesores)
        ids = set(realizadas) | set(cubiertas) | set(sin_cubrir)
        filas = [
            FilaConteo(
                i,
                profesores[i].nombre if i in profesores else f"Profesor {i}",
                realizadas[i],
                cubiertas[i],
                sin_cubrir[i],
            )
            for i in ids
        ]
        return sorted(filas, key=lambda f: f.nombre)

    def reporte_del_dia(self, fecha: date) -> list[FilaSuplencia]:
        """Renglones del reporte «Suplencias del día»: cada clase afectada con su estado."""
        profesores = por_id(self.repo.cargar_datos().profesores)
        filas = []
        for c in self.afectadas_del_dia(fecha):
            suplente = ""
            nota = ""
            if c.suplencia is not None:
                nota = c.suplencia.nota
                if c.suplencia.suplente_id is not None:
                    p = profesores.get(c.suplencia.suplente_id)
                    suplente = p.nombre if p else f"Profesor {c.suplencia.suplente_id}"
            filas.append(
                FilaSuplencia(
                    c.horas, c.asignatura, c.grupos, c.profesor_ausente, suplente, c.estado, nota
                )  # fmt: skip
            )
        return filas

    def exportar_reporte_del_dia(self, fecha: date, ruta: Path | str) -> Path:
        datos = self.repo.cargar_datos()
        profesores = por_id(datos.profesores)
        motivos = [
            (profesores[a.profesor_id].nombre, a)
            for a in self.ausencias_de(fecha)
            if a.profesor_id in profesores
        ]
        escuela = datos.configuracion.nombre_escuela
        if Path(ruta).suffix.lower() == ".pdf":
            from timetabling.exportacion.pdf import exportar_suplencias_del_dia_pdf

            return exportar_suplencias_del_dia_pdf(
                escuela, fecha, self.reporte_del_dia(fecha), motivos, ruta
            )
        return exportar_suplencias_del_dia(
            escuela, fecha, self.reporte_del_dia(fecha), motivos, ruta
        )
