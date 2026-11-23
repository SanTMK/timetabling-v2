"""Creado con Claude.

Tiempo (§7): generación de franjas, franjas útiles, adyacencia, traslapes entre niveles,
cliques maximales, rejilla temporal Δ y validez de una franja para un profesor.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import reduce
from math import gcd
from typing import Literal

from timetabling.dominio.modelos import (
    DatosEscuela,
    Grupo,
    Nivel,
    Profesor,
    RangoFranjas,
    ReglasAsignatura,
    por_id,
)
from timetabling.dominio.tiempo import DIAS, Dia, se_traslapan, texto_rango

# ---------------------------------------------------------------------------
# Franjas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Franja:
    """Una hora-clase de un nivel en un día. `indice` cuenta desde 0 todas las franjas
    generadas del día (también las que toca un evento)."""

    nivel_id: int
    dia: Dia
    indice: int
    inicio: int
    fin: int
    receso_antes: bool = False

    @property
    def id(self) -> str:
        return f"{self.nivel_id}:{self.dia}:{self.indice}"

    @property
    def duracion(self) -> int:
        return self.fin - self.inicio

    def texto(self) -> str:
        return f"{self.dia} {texto_rango(self.inicio, self.fin)}"

    def toca(self, inicio: int, fin: int) -> bool:
        """La franja comparte al menos un minuto con `[inicio, fin)`."""
        return se_traslapan(self.inicio, self.fin, inicio, fin)


def generar_franjas_dia(nivel: Nivel, dia: Dia) -> list[Franja]:
    """Franjas consecutivas desde `inicio_jornada` (§7.1). Si una franja chocaría con un receso,
    empieza al terminar este. Se detiene cuando ya no cabe antes de `fin_jornada`."""
    assert nivel.id is not None
    recesos = sorted(nivel.recesos, key=lambda r: r.inicio)
    franjas: list[Franja] = []
    t = nivel.inicio_jornada
    indice = 0
    while True:
        duracion = nivel.duraciones_especiales.get(indice, nivel.duracion_min)
        receso_antes = False
        movido = True
        while movido:
            movido = False
            for receso in recesos:
                if se_traslapan(t, t + duracion, receso.inicio, receso.fin):
                    t = receso.fin
                    receso_antes = movido = True
        if t + duracion > nivel.fin_jornada:
            return franjas
        franjas.append(Franja(nivel.id, dia, indice, t, t + duracion, receso_antes))
        t += duracion
        indice += 1


def generar_franjas(nivel: Nivel) -> list[Franja]:
    """Todas las franjas del nivel en sus días."""
    return [f for dia in nivel.dias for f in generar_franjas_dia(nivel, dia)]


def tocada_por_evento(franja: Franja, nivel: Nivel) -> bool:
    return any(e.dia == franja.dia and franja.toca(e.inicio, e.fin) for e in nivel.eventos)


def franjas_utiles_nivel(nivel: Nivel) -> list[Franja]:
    """Franjas sin eventos del nivel (§7.2); se conservan los índices."""
    return [f for f in generar_franjas(nivel) if not tocada_por_evento(f, nivel)]


def franjas_utiles_grupo(utiles_nivel: Iterable[Franja], grupo: Grupo) -> list[Franja]:
    """Franjas útiles del nivel que no toca ningún bloqueo del grupo (§7.2)."""
    return [
        f
        for f in utiles_nivel
        if not any(b.dia == f.dia and f.toca(b.inicio, b.fin) for b in grupo.bloqueos)
    ]


def adyacentes(a: Franja, b: Franja) -> bool:
    """Consecutivas, del mismo nivel y día, sin receso ni hueco entre ellas (§7.3)."""
    if a.nivel_id != b.nivel_id or a.dia != b.dia:
        return False
    primera, segunda = (a, b) if a.indice < b.indice else (b, a)
    return segunda.indice == primera.indice + 1 and primera.fin == segunda.inicio


def se_traslapan_franjas(a: Franja, b: Franja, margen: int) -> bool:
    """Traslape con margen de traslado solo entre niveles distintos (§7.4)."""
    if a.dia != b.dia:
        return False
    m = margen if a.nivel_id != b.nivel_id else 0
    return se_traslapan(a.inicio, a.fin, b.inicio, b.fin, m)


def en_rango(rango: RangoFranjas, franja: Franja, completa: bool) -> bool:
    """La franja cae en el rango. Por índices: `desde ≤ índice ≤ hasta`. Por horas: si
    `completa`, la franja debe quedar dentro del rango (franjas preferidas); si no, basta con que
    lo toque (franjas prohibidas)."""
    if not rango.incluye_dia(franja.dia):
        return False
    if rango.desde_indice is not None and rango.hasta_indice is not None:
        return rango.desde_indice <= franja.indice <= rango.hasta_indice
    assert rango.desde is not None and rango.hasta is not None
    if completa:
        return rango.desde <= franja.inicio and franja.fin <= rango.hasta
    return franja.toca(rango.desde, rango.hasta)


def prohibida(reglas: ReglasAsignatura, franja: Franja) -> bool:
    return any(en_rango(r, franja, completa=False) for r in reglas.franjas_prohibidas)


def preferida(reglas: ReglasAsignatura, franja: Franja) -> bool:
    """Sin franjas preferidas, todas lo son."""
    return not reglas.franjas_preferidas or any(
        en_rango(r, franja, completa=True) for r in reglas.franjas_preferidas
    )


# ---------------------------------------------------------------------------
# Cliques maximales (Bron–Kerbosch con pivote)
# ---------------------------------------------------------------------------


def cliques_maximales(vecinos: dict[str, set[str]]) -> list[frozenset[str]]:
    """Todos los cliques maximales del grafo, incluidos los vértices aislados."""
    resultado: list[frozenset[str]] = []

    def expandir(r: set[str], p: set[str], x: set[str]) -> None:
        if not p and not x:
            resultado.append(frozenset(r))
            return
        pivote = max(p | x, key=lambda v: len(vecinos[v] & p))
        for v in sorted(p - vecinos[pivote]):
            expandir(r | {v}, p & vecinos[v], x & vecinos[v])
            p = p - {v}
            x = x | {v}

    expandir(set(), set(vecinos), set())
    return sorted(resultado, key=lambda c: sorted(c))


def cliques_de_traslape(franjas: Sequence[Franja], margen: int) -> list[frozenset[str]]:
    """Cliques maximales del grafo de traslapes, día por día."""
    por_dia: dict[Dia, list[Franja]] = defaultdict(list)
    for franja in franjas:
        por_dia[franja.dia].append(franja)
    cliques: list[frozenset[str]] = []
    for dia in DIAS:
        del_dia = por_dia.get(dia, [])
        vecinos: dict[str, set[str]] = {f.id: set() for f in del_dia}
        for i, a in enumerate(del_dia):
            for b in del_dia[i + 1 :]:
                if se_traslapan_franjas(a, b, margen):
                    vecinos[a.id].add(b.id)
                    vecinos[b.id].add(a.id)
        if vecinos:
            cliques.extend(cliques_maximales(vecinos))
    return cliques


# ---------------------------------------------------------------------------
# Rejilla temporal Δ (§7.5)
# ---------------------------------------------------------------------------

DELTA_MINIMO = 5


@dataclass(frozen=True)
class Rejilla:
    """Línea de tiempo discreta con paso `delta`; el tick `t` es `[t·Δ, (t+1)·Δ)`."""

    delta: int

    def ticks(self, inicio: int, fin: int) -> range:
        """Ticks que toca el intervalo `[inicio, fin)`."""
        return range(inicio // self.delta, -(-fin // self.delta))

    def ticks_franja(self, franja: Franja) -> range:
        return self.ticks(franja.inicio, franja.fin)

    def minutos(self, ticks: int) -> int:
        return ticks * self.delta


def calcular_rejilla(valores: Iterable[int]) -> Rejilla:
    """Δ = mcd de los valores positivos dados, con mínimo de 5 min."""
    positivos = [v for v in valores if v > 0]
    divisor = reduce(gcd, positivos, 0) if positivos else DELTA_MINIMO
    return Rejilla(max(divisor, DELTA_MINIMO))


# ---------------------------------------------------------------------------
# Disponibilidad del profesor (§7.6)
# ---------------------------------------------------------------------------

Validez = Literal["valida", "preferible_no", "invalida"]


@dataclass(frozen=True)
class EvaluacionFranja:
    validez: Validez
    motivo: str = ""

    @property
    def valida(self) -> bool:
        return self.validez != "invalida"


def fusionar(rangos: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Fusiona rangos traslapados o contiguos."""
    fusionados: list[tuple[int, int]] = []
    for inicio, fin in sorted(rangos):
        if fusionados and inicio <= fusionados[-1][1]:
            fusionados[-1] = (fusionados[-1][0], max(fusionados[-1][1], fin))
        else:
            fusionados.append((inicio, fin))
    return fusionados


def disponibilidad_efectiva(profesor: Profesor, dia: Dia) -> list[tuple[int, int]] | None:
    """Rangos fusionados en que el profesor puede dar clase ese día, o `None` si puede en
    toda la jornada (salvo los rangos `no_disponible`). `preferible_no` cuenta como disponible."""
    if profesor.disponible_toda_la_jornada:
        return None
    return fusionar(
        (d.inicio, d.fin)
        for d in profesor.disponibilidad
        if d.dia == dia and d.tipo in ("disponible", "preferible_no")
    )


def evaluar_franja(profesor: Profesor, franja: Franja) -> EvaluacionFranja:
    """Validez de una franja para un profesor: debe caber completa en su disponibilidad
    efectiva, no cruzarse con `no_disponible` ni con un evento suyo. Es `preferible_no` si
    toca un rango de ese tipo."""
    efectiva = disponibilidad_efectiva(profesor, franja.dia)
    if efectiva is not None and not any(
        i <= franja.inicio and franja.fin <= f for i, f in efectiva
    ):
        return EvaluacionFranja(
            "invalida", f"{profesor.nombre} no está disponible {franja.texto()}"
        )
    for rango in profesor.disponibilidad:
        if rango.dia == franja.dia and rango.tipo == "no_disponible":
            if franja.toca(rango.inicio, rango.fin):
                return EvaluacionFranja(
                    "invalida",
                    f"{profesor.nombre} no está disponible de "
                    f"{texto_rango(rango.inicio, rango.fin)}",
                )
    for evento in profesor.eventos:
        if evento.dia == franja.dia and franja.toca(evento.inicio, evento.fin):
            return EvaluacionFranja(
                "invalida",
                f"{profesor.nombre} tiene «{evento.nombre}» de "
                f"{texto_rango(evento.inicio, evento.fin)}",
            )
    for rango in profesor.disponibilidad:
        if rango.dia == franja.dia and rango.tipo == "preferible_no":
            if franja.toca(rango.inicio, rango.fin):
                return EvaluacionFranja(
                    "preferible_no",
                    f"{profesor.nombre} prefiere no dar clase de "
                    f"{texto_rango(rango.inicio, rango.fin)}",
                )
    return EvaluacionFranja("valida")


def franjas_parcialmente_cubiertas(profesor: Profesor, franjas: Iterable[Franja]) -> list[Franja]:
    """Franjas que algún rango disponible toca pero que no quedan válidas (§7.7): avisan que el
    rango quedó recortado."""
    if profesor.disponible_toda_la_jornada:
        return []
    resultado: list[Franja] = []
    for franja in franjas:
        toca = any(
            d.dia == franja.dia
            and d.tipo in ("disponible", "preferible_no")
            and franja.toca(d.inicio, d.fin)
            for d in profesor.disponibilidad
        )
        if toca and not evaluar_franja(profesor, franja).valida:
            resultado.append(franja)
    return resultado


# ---------------------------------------------------------------------------
# Calendario: todo lo temporal de una escuela
# ---------------------------------------------------------------------------


@dataclass
class Calendario:
    """Franjas, franjas útiles, cliques y rejilla de una escuela, precalculados."""

    datos: DatosEscuela
    franjas_nivel: dict[int, list[Franja]] = field(default_factory=dict)
    utiles_nivel: dict[int, list[Franja]] = field(default_factory=dict)
    utiles_grupo: dict[int, list[Franja]] = field(default_factory=dict)
    franjas: dict[str, Franja] = field(default_factory=dict)
    cliques: list[frozenset[str]] = field(default_factory=list)
    rejilla: Rejilla = field(default_factory=lambda: Rejilla(DELTA_MINIMO))

    @classmethod
    def de(cls, datos: DatosEscuela) -> "Calendario":
        calendario = cls(datos)
        for nivel in datos.niveles:
            assert nivel.id is not None
            todas = generar_franjas(nivel)
            calendario.franjas_nivel[nivel.id] = todas
            calendario.utiles_nivel[nivel.id] = [
                f for f in todas if not tocada_por_evento(f, nivel)
            ]
            calendario.franjas.update((f.id, f) for f in todas)
        grados = por_id(datos.grados)
        for grupo in datos.grupos:
            assert grupo.id is not None
            grado = grados.get(grupo.grado_id)
            utiles = calendario.utiles_nivel.get(grado.nivel_id, []) if grado else []
            calendario.utiles_grupo[grupo.id] = franjas_utiles_grupo(utiles, grupo)
        margen = datos.configuracion.margen_traslado_min
        utiles = [f for lista in calendario.utiles_nivel.values() for f in lista]
        calendario.cliques = cliques_de_traslape(utiles, margen)
        limites = [x for f in calendario.franjas.values() for x in (f.inicio, f.fin)]
        for nivel in datos.niveles:
            limites += [x for r in nivel.recesos for x in (r.inicio, r.fin)]
        limites += [margen, datos.configuracion.descanso_minimo_min]
        calendario.rejilla = calcular_rejilla(limites)
        return calendario

    def franja(self, nivel_id: int, dia: Dia, indice: int) -> Franja | None:
        return self.franjas.get(f"{nivel_id}:{dia}:{indice}")

    def utiles_comunes(self, grupos: Iterable[int]) -> list[Franja]:
        """Franjas útiles para todos los grupos dados (deben ser del mismo nivel)."""
        listas = [self.utiles_grupo.get(g, []) for g in grupos]
        if not listas:
            return []
        comunes = set.intersection(*(set(lista) for lista in listas))
        return sorted(comunes, key=lambda f: (DIAS.index(f.dia), f.indice))
