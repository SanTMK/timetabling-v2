"""Creado con Claude.

Clases a partir del plan de estudios (§5.2): sincronización, cobertura del plan, clases
huérfanas y textos de destinatarios.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from timetabling.dominio.modelos import Clase, DatosEscuela, Destinatario, Profesor, por_id


@dataclass(frozen=True)
class DiferenciaCobertura:
    """Un grupo (o una parte de una división) recibe más o menos horas que las del plan."""

    grupo_id: int
    asignatura_id: int
    esperado: int
    recibido: int
    division_id: int | None = None
    parte: str | None = None

    @property
    def diferencia(self) -> int:
        """Positiva = horas de más; negativa = horas de menos."""
        return self.recibido - self.esperado


@dataclass
class ResultadoSincronizacion:
    nuevas: list[Clase] = field(default_factory=list)
    diferencias: list[DiferenciaCobertura] = field(default_factory=list)
    huerfanas: list[Clase] = field(default_factory=list)


def texto_destinatario(datos: DatosEscuela, destinatario: Destinatario) -> str:
    nombre = datos.nombre_grupo(destinatario.grupo_id)
    return nombre if destinatario.parte is None else f"{nombre} ({destinatario.parte})"


def texto_destinatarios(datos: DatosEscuela, clase: Clase) -> str:
    """«7°A, 7°B» o «8°A (Básico)»."""
    return ", ".join(texto_destinatario(datos, d) for d in clase.destinatarios)


def grupos_de_clase(clase: Clase) -> list[int]:
    """Ids de los grupos a los que llega la clase, sin repetir y en orden."""
    return list(dict.fromkeys(d.grupo_id for d in clase.destinatarios))


def horas_plan(datos: DatosEscuela) -> dict[tuple[int, int], int]:
    """`(grupo_id, asignatura_id) → horas del plan` para cada grupo."""
    por_grado: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for fila in datos.plan:
        if fila.horas_semanales > 0:
            por_grado[fila.grado_id].append((fila.asignatura_id, fila.horas_semanales))
    resultado: dict[tuple[int, int], int] = {}
    for grupo in datos.grupos:
        assert grupo.id is not None
        for asignatura_id, horas in por_grado.get(grupo.grado_id, []):
            resultado[(grupo.id, asignatura_id)] = horas
    return resultado


def cobertura_del_plan(
    datos: DatosEscuela, clases: list[Clase] | None = None
) -> list[DiferenciaCobertura]:
    """Diferencias entre las horas del plan y las recibidas por las clases (§5.2).

    Si el grupo tiene clases de la asignatura sobre partes de una división, cada parte debe
    recibir las horas del plan (las clases de grupo completo cuentan para todas las partes).
    """
    clases = datos.clases if clases is None else clases
    divisiones = por_id(datos.divisiones)
    completo: dict[tuple[int, int], int] = defaultdict(int)
    por_parte: dict[tuple[int, int], dict[tuple[int, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for clase in clases:
        for destinatario in clase.destinatarios:
            clave = (destinatario.grupo_id, clase.asignatura_id)
            if destinatario.division_id is None or destinatario.parte is None:
                completo[clave] += clase.horas_semanales
            else:
                por_parte[clave][(destinatario.division_id, destinatario.parte)] += (
                    clase.horas_semanales
                )

    diferencias: list[DiferenciaCobertura] = []
    for (grupo_id, asignatura_id), esperado in sorted(horas_plan(datos).items()):
        clave = (grupo_id, asignatura_id)
        partes = por_parte.get(clave)
        if not partes:
            recibido = completo.get(clave, 0)
            if recibido != esperado:
                diferencias.append(DiferenciaCobertura(grupo_id, asignatura_id, esperado, recibido))
            continue
        for division_id in sorted({d for d, _ in partes}):
            division = divisiones.get(division_id)
            nombres = (
                division.partes if division else sorted(p for d, p in partes if d == division_id)
            )
            for parte in nombres:
                recibido = completo.get(clave, 0) + partes.get((division_id, parte), 0)
                if recibido != esperado:
                    diferencias.append(
                        DiferenciaCobertura(
                            grupo_id, asignatura_id, esperado, recibido, division_id, parte
                        )
                    )
    return diferencias


def clases_huerfanas(datos: DatosEscuela, clases: list[Clase] | None = None) -> list[Clase]:
    """Clases cuya asignatura no está en el plan del grado de alguno de sus grupos."""
    clases = datos.clases if clases is None else clases
    plan = horas_plan(datos)
    return [
        clase
        for clase in clases
        if any((g, clase.asignatura_id) not in plan for g in grupos_de_clase(clase))
    ]


def sincronizar_con_plan(datos: DatosEscuela) -> ResultadoSincronizacion:
    """Crea una clase de grupo completo por cada `(grupo, asignatura)` del plan que ninguna
    clase cubre. No modifica las clases existentes. Devuelve las nuevas (sin id) y las
    diferencias e huérfanas calculadas sobre el conjunto resultante."""
    cubiertos = {
        (d.grupo_id, clase.asignatura_id) for clase in datos.clases for d in clase.destinatarios
    }
    nuevas = [
        Clase(
            asignatura_id=asignatura_id,
            destinatarios=[Destinatario(grupo_id=grupo_id)],
            horas_semanales=horas,
            origen="plan",
        )
        for (grupo_id, asignatura_id), horas in sorted(horas_plan(datos).items())
        if (grupo_id, asignatura_id) not in cubiertos
    ]
    todas = [*datos.clases, *nuevas]
    return ResultadoSincronizacion(
        nuevas=nuevas,
        diferencias=cobertura_del_plan(datos, todas),
        huerfanas=clases_huerfanas(datos, todas),
    )


def profesor_habilitado(datos: DatosEscuela, profesor: Profesor, clase: Clase) -> bool:
    """Activo y habilitado para la asignatura y para el grado de cada destinatario (§8)."""
    if not profesor.activo or clase.asignatura_id not in profesor.asignaturas:
        return False
    grupos = por_id(datos.grupos)
    return all(
        d.grupo_id in grupos and grupos[d.grupo_id].grado_id in profesor.grados
        for d in clase.destinatarios
    )


def profesores_posibles(datos: DatosEscuela, clase: Clase) -> list[int]:
    """Profesores que pueden impartir la clase: sus fijos (si están activos y habilitados) o,
    si no tiene, todos los habilitados."""
    profesores = por_id(datos.profesores)
    if clase.profesores:
        fijos = [profesores.get(p) for p in clase.profesores]
        if all(p is not None and profesor_habilitado(datos, p, clase) for p in fijos):
            return list(clase.profesores)
        return []
    return [
        p.id for p in datos.profesores if p.id is not None and profesor_habilitado(datos, p, clase)
    ]


def chocan_destinatarios(
    a: Destinatario, b: Destinatario, simultaneas: set[int] | None = None
) -> bool:
    """Dos destinatarios del mismo grupo no pueden tener clase a la vez (D2), salvo que sean
    partes **distintas** de una misma división simultánea."""
    if a.grupo_id != b.grupo_id:
        return False
    if a.division_id is None or b.division_id is None:
        return True
    if a.division_id != b.division_id:
        return True
    if simultaneas is not None and a.division_id not in simultaneas:
        return True
    return a.parte == b.parte
