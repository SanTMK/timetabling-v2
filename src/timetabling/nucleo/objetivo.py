"""Creado con Claude.

Restricciones blandas (§9): criterios B1–B10 con unidades normalizadas y prioridades.

- `ConstructorObjetivo` agrega al modelo CP-SAT las variables y la expresión a minimizar.
- `evaluar()` calcula los mismos criterios sobre un horario, sin solver: es la fuente de las
  penalizaciones informadas (también en vivo en el editor).

Unidades: B1 y B6 en bloques de 50 min; los demás en franjas, días o cambios. El peso efectivo es
`multiplicador × unidad`. Para que el objetivo sea entero, los coeficientes se escalan:
`ESCALA_UNIDAD` por unidad y `ESCALA_UNIDAD / 50` por minuto.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from math import ceil

from ortools.sat.python import cp_model

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.clases import grupos_de_clase, profesores_posibles
from timetabling.dominio.modelos import (
    CRITERIOS,
    MULTIPLICADOR_B9,
    MULTIPLICADORES,
    Criterios,
    DatosEscuela,
    por_id,
)
from timetabling.nucleo.franjas import Calendario, Franja, adyacentes, evaluar_franja, preferida
from timetabling.nucleo.modelo import ClaseModelo, ConstructorModelo

MINUTOS_UNIDAD = 50
ESCALA_UNIDAD = 5000
"""Coeficiente entero de una unidad con peso 1 (permite pesos avanzados con dos decimales)."""

POR_MINUTO = frozenset({"B1", "B6"})


def pesos(criterios: Criterios, con_base: bool = False) -> dict[str, float]:
    """Peso por unidad de cada criterio activo (0 = desactivado, no se construye)."""
    if criterios.modo_avanzado and criterios.pesos_avanzados:
        resultado = {c: float(criterios.pesos_avanzados.get(c, 0.0)) for c in CRITERIOS}
    else:
        resultado = {c: float(MULTIPLICADORES[criterios.prioridades[c]]) for c in CRITERIOS}
    if con_base:
        resultado["B9"] = float(MULTIPLICADOR_B9)
    return {c: p for c, p in resultado.items() if p > 0}


def coeficiente(criterio: str, peso: float) -> int:
    """Coeficiente entero del objetivo por unidad interna (minuto o unidad)."""
    por_unidad = peso * ESCALA_UNIDAD
    return round(por_unidad / MINUTOS_UNIDAD) if criterio in POR_MINUTO else round(por_unidad)


def total_ponderado(valores: dict[str, float], pesos_: dict[str, float]) -> float:
    return sum(valores.get(c, 0.0) * p for c, p in pesos_.items())


# ---------------------------------------------------------------------------
# Datos compartidos por el constructor y el evaluador
# ---------------------------------------------------------------------------


def _dias_lectivos(calendario: Calendario, grupos: list[int]) -> int:
    return max(1, len({f.dia for f in calendario.utiles_comunes(grupos)}))


def _tope_diario(horas: int, dias: int) -> int:
    return ceil(horas / dias)


def _grupos_de_carga(datos: DatosEscuela) -> dict[tuple[int, int], set[int]]:
    """(asignatura, nivel) → profesores que pueden impartir sus clases (B6, si son ≥ 2)."""
    grupos: dict[tuple[int, int], set[int]] = defaultdict(set)
    for clase in datos.clases:
        try:
            nivel = datos.nivel_de_grupo(clase.destinatarios[0].grupo_id).id
        except KeyError:
            continue
        if nivel is None:
            continue
        grupos[(clase.asignatura_id, nivel)].update(profesores_posibles(datos, clase))
    return {k: v for k, v in grupos.items() if len(v) >= 2}


def _segmentos(limites: Iterable[int]) -> list[tuple[int, int]]:
    puntos = sorted(set(limites))
    return list(zip(puntos, puntos[1:], strict=False))


def _recesos_del_dia(datos: DatosEscuela, dia: str) -> dict[int, list[tuple[int, int]]]:
    return {
        n.id: [(r.inicio, r.fin) for r in n.recesos]
        for n in datos.niveles
        if n.id is not None and dia in n.dias
    }


def _en_receso(segmento: tuple[int, int], recesos: list[tuple[int, int]]) -> bool:
    return any(a <= segmento[0] and segmento[1] <= b for a, b in recesos)


# ---------------------------------------------------------------------------
# Constructor del objetivo
# ---------------------------------------------------------------------------


@dataclass
class Objetivo:
    expresion: cp_model.LinearExprT
    pesos: dict[str, float]
    terminos: int = 0
    por_criterio: dict[str, list[tuple[cp_model.LinearExprT, int]]] = field(default_factory=dict)
    """Criterio → `(expresión, unidades internas)`: minutos para B1 y B6, unidades para el
    resto."""

    @property
    def vacio(self) -> bool:
        return self.terminos == 0

    def valores(self, solver: cp_model.CpSolver) -> dict[str, float]:
        """Valor de cada criterio activo según el solver, en su unidad normalizada."""
        resultado: dict[str, float] = {}
        for criterio, terminos in self.por_criterio.items():
            total = sum(solver.value(e) * k for e, k in terminos)
            resultado[criterio] = total / MINUTOS_UNIDAD if criterio in POR_MINUTO else total
        return resultado


class ConstructorObjetivo:
    def __init__(
        self,
        constructor: ConstructorModelo,
        criterios: Criterios,
        base: Iterable[Colocacion] | None = None,
    ) -> None:
        self.c = constructor
        self.h = constructor.h
        self.m = constructor.m
        self.datos = constructor.datos
        self.calendario = constructor.calendario
        self.base = list(base) if base is not None else None
        self.pesos = pesos(criterios, con_base=self.base is not None)
        self._terminos: list[tuple[cp_model.LinearExprT, int]] = []
        self._por_criterio: dict[str, list[tuple[cp_model.LinearExprT, int]]] = defaultdict(list)

    def _sumar(self, criterio: str, expr: cp_model.LinearExprT, cantidad: int = 1) -> None:
        coef = coeficiente(criterio, self.pesos[criterio]) * cantidad
        self._por_criterio[criterio].append((expr, cantidad))
        if coef:
            self._terminos.append((expr, coef))

    def construir(self) -> Objetivo:
        for criterio, metodo in (
            ("B1", self._b1),
            ("B2", self._b2),
            ("B3", self._b3),
            ("B4", self._b4),
            ("B5", self._b5),
            ("B6", self._b6),
            ("B7", self._b7),
            ("B8", self._b8),
            ("B9", self._b9),
            ("B10", self._b10),
        ):
            if criterio in self.pesos:
                metodo()
        expresion = sum(e * k for e, k in self._terminos) if self._terminos else 0
        return Objetivo(expresion, self.pesos, len(self._terminos), dict(self._por_criterio))

    # ------------------------------------------------------------------ B1

    def _ensenia_nivel(
        self, p: int, dia: str, nivel_id: int, franjas: list[Franja]
    ) -> cp_model.IntVar | None:
        os = [self.h.ocupa[(p, f.id)] for f in franjas if f.nivel_id == nivel_id]
        if not os:
            return None
        v = self.m.new_bool_var(f"ensenia[{p},{dia},{nivel_id}]")
        for o in os:
            self.m.add(o <= v)
        self.m.add(v <= sum(os))  # sin esto, el solver se «excusaría» de cualquier receso
        return v

    def _b1(self) -> None:
        por_dia: dict[tuple[int, str], list[Franja]] = defaultdict(list)
        for p, s in self.h.ocupa:
            f = self.calendario.franjas[s]
            por_dia[(p, f.dia)].append(f)
        for (p, dia), franjas in por_dia.items():
            if len(franjas) < 2:
                continue
            inicio, fin = min(f.inicio for f in franjas), max(f.fin for f in franjas)
            recesos = _recesos_del_dia(self.datos, dia)
            limites = [x for f in franjas for x in (f.inicio, f.fin)]
            limites += [min(max(x, inicio), fin) for rs in recesos.values() for r in rs for x in r]
            segmentos = _segmentos(limites)
            ocupaciones = [
                [self.h.ocupa[(p, f.id)] for f in franjas if f.inicio <= a and b <= f.fin]
                for a, b in segmentos
            ]
            ensenia: dict[int, cp_model.IntVar | None] = {}
            antes: cp_model.IntVar | None = None
            despues: list[cp_model.IntVar] = []
            primeras: list[cp_model.IntVar] = []
            for k, ocup in enumerate(ocupaciones):
                a = self.m.new_bool_var(f"b1a[{p},{dia},{k}]")
                if antes is not None:
                    self.m.add(a >= antes)
                if ocup:
                    self.m.add(a >= sum(ocup))
                primeras.append(a)
                antes = a
            siguiente: cp_model.IntVar | None = None
            for k in reversed(range(len(ocupaciones))):
                b = self.m.new_bool_var(f"b1b[{p},{dia},{k}]")
                if siguiente is not None:
                    self.m.add(b >= siguiente)
                if ocupaciones[k]:
                    self.m.add(b >= sum(ocupaciones[k]))
                despues.insert(0, b)
                siguiente = b
            for k, (segmento, ocup) in enumerate(zip(segmentos, ocupaciones, strict=True)):
                g = self.m.new_bool_var(f"b1g[{p},{dia},{k}]")
                self.m.add(g >= primeras[k] + despues[k] - 1 - sum(ocup))
                niveles = [n for n, rs in recesos.items() if _en_receso(segmento, rs)]
                excusas = []
                for n in niveles:
                    if n not in ensenia:
                        ensenia[n] = self._ensenia_nivel(p, dia, n, franjas)
                    if ensenia[n] is not None:
                        excusas.append(ensenia[n])
                if excusas:
                    pen = self.m.new_bool_var(f"b1p[{p},{dia},{k}]")
                    self.m.add(pen >= g - sum(excusas))
                    g = pen
                self._sumar("B1", g, segmento[1] - segmento[0])

    # ------------------------------------------------------------------ B2, B3, B4, B5

    def _b2(self) -> None:
        for c in self.h.clases.values():
            horas = c.clase.horas_semanales
            tope = _tope_diario(horas, _dias_lectivos(self.calendario, grupos_de_clase(c.clase)))
            por_dia: dict[str, list[cp_model.IntVar]] = defaultdict(list)
            for s in c.franjas:
                por_dia[s.dia].append(self.h.z[(c.id, s.id)])
            for dia, zs in por_dia.items():
                maximo = min(len(zs), c.reglas.max_horas_dia, horas)
                if maximo <= tope:
                    continue
                e = self.m.new_int_var(0, maximo - tope, f"b2[{c.id},{dia}]")
                self.m.add(e >= sum(zs) - tope)
                self._sumar("B2", e)

    def _b3(self) -> None:
        for c in self.h.clases.values():
            if not c.reglas.franjas_preferidas:
                continue
            for s in c.franjas:
                if not preferida(c.reglas, s):
                    self._sumar("B3", self.h.z[(c.id, s.id)])

    def _b4(self) -> None:
        profesores = self.c.profesores
        for (_, p, s), x in self.h.x.items():
            if evaluar_franja(profesores[p], self.calendario.franjas[s]).validez == "preferible_no":
                self._sumar("B4", x)

    def _b5(self) -> None:
        for p, dia in {(p, self.calendario.franjas[s].dia) for p, s in self.h.ocupa}:
            self._sumar("B5", self.c.dia_con_clase(p, dia))

    # ------------------------------------------------------------------ B6, B7, B8

    def _b6(self) -> None:
        for (asignatura_id, nivel_id), profesores in _grupos_de_carga(self.datos).items():
            clases = [
                c for c in self.h.clases.values()
                if c.clase.asignatura_id == asignatura_id and c.nivel_id == nivel_id
            ]  # fmt: skip
            cargas = []
            tope = 0
            for p in sorted(profesores):
                terminos = [
                    (self.h.x[(c.id, p, s.id)], s.duracion)
                    for c in clases
                    for s in c.franjas
                    if (c.id, p, s.id) in self.h.x
                ]
                tope = max(tope, sum(d for _, d in terminos))
                cargas.append(sum(x * d for x, d in terminos) if terminos else 0)
            if tope == 0:
                continue
            alto = self.m.new_int_var(0, tope, f"b6max[{asignatura_id},{nivel_id}]")
            bajo = self.m.new_int_var(0, tope, f"b6min[{asignatura_id},{nivel_id}]")
            for carga in cargas:
                self.m.add(alto >= carga)
                self.m.add(bajo <= carga)
            self._sumar("B6", alto - bajo)

    def _b7(self) -> None:
        niveles = por_id(self.datos.niveles)
        grupos = por_id(self.datos.grupos)
        for c in self.h.clases.values():
            nivel = niveles.get(c.nivel_id)
            if nivel is None or not nivel.preferir_titular:
                continue
            for g in grupos_de_clase(c.clase):
                titular = grupos[g].titular_id if g in grupos else None
                if titular is None:
                    continue
                for s in c.franjas:
                    z = self.h.z[(c.id, s.id)]
                    if c.fijos:
                        if titular not in c.fijos:
                            self._sumar("B7", z)
                        continue
                    x = self.h.x.get((c.id, titular, s.id))
                    self._sumar("B7", z if x is None else z - x)

    def _b8(self) -> None:
        for c in self.h.clases.values():
            if c.reglas.bloque_doble != "preferido":
                continue
            _, u = self.c.pares_de(c)
            self._sumar("B8", sum(u.values()) - self.c.horas_de(c) % 2)

    # ------------------------------------------------------------------ B9, B10

    def _b9(self) -> None:
        for colocacion in self.base or []:
            self._sumar("B9", 2)
            z = self.h.z.get((colocacion.clase_id, colocacion.franja_id))
            if z is None:
                continue  # ya no puede ir ahí: cuesta 2 siempre
            info: ClaseModelo | None = self.h.clases.get(colocacion.clase_id)
            mismo = 0
            if info is not None and info.fijos:
                mismo = z if set(colocacion.profesores) == set(info.fijos) else 0
            elif len(colocacion.profesores) == 1:
                mismo = self.h.x.get(
                    (colocacion.clase_id, colocacion.profesores[0], colocacion.franja_id), 0
                )
            # 2 − z − x: moverla cuesta 2; cambiar solo el profesor, 1.
            self._sumar("B9", -z)
            if not isinstance(mismo, int):
                self._sumar("B9", -mismo)

    def _b10(self) -> None:
        niveles = por_id(self.datos.niveles)
        por_grupo_franja: dict[tuple[int, str], list[cp_model.IntVar]] = defaultdict(list)
        for c in self.h.clases.values():
            for g in grupos_de_clase(c.clase):
                for s in c.franjas:
                    por_grupo_franja[(g, s.id)].append(self.h.z[(c.id, s.id)])
        for grupo in self.datos.grupos:
            if grupo.id is None:
                continue
            nivel = niveles.get(self.datos.nivel_de_grupo(grupo.id).id or 0)
            if nivel is None or nivel.huecos_alumnos != "penalizar":
                continue
            por_dia: dict[str, list[Franja]] = defaultdict(list)
            for s in self.calendario.utiles_grupo.get(grupo.id, []):
                por_dia[s.dia].append(s)
            for dia, franjas in por_dia.items():
                ordenadas = sorted(franjas, key=lambda f: f.indice)
                ocupadas: list[cp_model.IntVar | None] = []
                for s in ordenadas:
                    zs = por_grupo_franja.get((grupo.id, s.id), [])
                    if not zs:
                        ocupadas.append(None)
                        continue
                    o = self.m.new_bool_var(f"b10o[{grupo.id},{s.id}]")
                    for z in zs:
                        self.m.add_implication(z, o)
                    self.m.add(o <= sum(zs))
                    ocupadas.append(o)
                if sum(o is not None for o in ocupadas) < 2:
                    continue
                n = len(ocupadas)
                primeras = [self.m.new_bool_var(f"b10a[{grupo.id},{dia},{k}]") for k in range(n)]
                ultimas = [self.m.new_bool_var(f"b10b[{grupo.id},{dia},{k}]") for k in range(n)]
                for k, o in enumerate(ocupadas):
                    if k:
                        self.m.add(primeras[k] >= primeras[k - 1])
                    if k < n - 1:
                        self.m.add(ultimas[k] >= ultimas[k + 1])
                    if o is not None:
                        self.m.add(primeras[k] >= o)
                        self.m.add(ultimas[k] >= o)
                    g = self.m.new_bool_var(f"b10g[{grupo.id},{dia},{k}]")
                    self.m.add(g >= primeras[k] + ultimas[k] - 1 - (o if o is not None else 0))
                    self._sumar("B10", g)


# ---------------------------------------------------------------------------
# Evaluación sin solver
# ---------------------------------------------------------------------------


def evaluar(
    datos: DatosEscuela,
    colocaciones: Iterable[Colocacion],
    calendario: Calendario | None = None,
    base: Iterable[Colocacion] | None = None,
) -> dict[str, float]:
    """Valor de cada criterio (en su unidad normalizada) para un horario, sin solver. Incluye
    todos los criterios, estén activos o no; B9 solo si hay base."""
    calendario = calendario or Calendario.de(datos)
    colocaciones = [c for c in colocaciones if c.franja_id in calendario.franjas]
    franjas = calendario.franjas
    clases = por_id(datos.clases)
    profesores = por_id(datos.profesores)
    asignaturas = por_id(datos.asignaturas)
    niveles = por_id(datos.niveles)
    grupos = por_id(datos.grupos)
    valores: dict[str, float] = dict.fromkeys(CRITERIOS, 0.0)

    por_profesor_dia: dict[tuple[int, str], list[Franja]] = defaultdict(list)
    for c in colocaciones:
        for p in c.profesores:
            por_profesor_dia[(p, franjas[c.franja_id].dia)].append(franjas[c.franja_id])

    # B1: minutos libres entre la primera y la última clase, sin los recesos de sus niveles.
    minutos_b1 = 0
    for (_, dia), lista in por_profesor_dia.items():
        inicio, fin = min(f.inicio for f in lista), max(f.fin for f in lista)
        recesos = _recesos_del_dia(datos, dia)
        ensenia = {f.nivel_id for f in lista}
        propios = [r for n, rs in recesos.items() if n in ensenia for r in rs]
        limites = [x for f in lista for x in (f.inicio, f.fin)]
        limites += [min(max(x, inicio), fin) for rs in recesos.values() for r in rs for x in r]
        for segmento in _segmentos(limites):
            ocupado = any(f.inicio <= segmento[0] and segmento[1] <= f.fin for f in lista)
            if not ocupado and not _en_receso(segmento, propios):
                minutos_b1 += segmento[1] - segmento[0]
    valores["B1"] = minutos_b1 / MINUTOS_UNIDAD

    por_clase_dia: dict[tuple[int, str], int] = defaultdict(int)
    for c in colocaciones:
        por_clase_dia[(c.clase_id, franjas[c.franja_id].dia)] += 1
    for (clase_id, _), cuenta in por_clase_dia.items():
        clase = clases.get(clase_id)
        if clase is None:
            continue
        tope = _tope_diario(
            clase.horas_semanales, _dias_lectivos(calendario, grupos_de_clase(clase))
        )
        valores["B2"] += max(0, cuenta - tope)

    for c in colocaciones:
        clase = clases.get(c.clase_id)
        if clase is None or clase.asignatura_id not in asignaturas:
            continue
        franja = franjas[c.franja_id]
        reglas = asignaturas[clase.asignatura_id].reglas_efectivas(franja.nivel_id)
        if reglas.franjas_preferidas and not preferida(reglas, franja):
            valores["B3"] += 1
        for p in c.profesores:
            if p in profesores and evaluar_franja(profesores[p], franja).validez == "preferible_no":
                valores["B4"] += 1

    valores["B5"] = float(len(por_profesor_dia))

    # B6: máximo − mínimo de minutos entre los profesores de cada asignatura y nivel.
    cargas: dict[tuple[int, int], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for c in colocaciones:
        clase = clases.get(c.clase_id)
        if clase is None:
            continue
        franja = franjas[c.franja_id]
        for p in c.profesores:
            cargas[(clase.asignatura_id, franja.nivel_id)][p] += franja.duracion
    desequilibrio = 0
    for clave, profesores_grupo in _grupos_de_carga(datos).items():
        minutos = [cargas[clave].get(p, 0) for p in profesores_grupo]
        desequilibrio += max(minutos) - min(minutos)
    valores["B6"] = desequilibrio / MINUTOS_UNIDAD

    for c in colocaciones:
        clase = clases.get(c.clase_id)
        if clase is None:
            continue
        nivel = niveles.get(franjas[c.franja_id].nivel_id)
        if nivel is None or not nivel.preferir_titular:
            continue
        for g in grupos_de_clase(clase):
            titular = grupos[g].titular_id if g in grupos else None
            if titular is not None and titular not in c.profesores:
                valores["B7"] += 1

    # B8: horas sueltas mínimas (tramos adyacentes de largo impar) menos horas % 2.
    por_clase: dict[int, dict[str, list[Franja]]] = defaultdict(lambda: defaultdict(list))
    for c in colocaciones:
        por_clase[c.clase_id][franjas[c.franja_id].dia].append(franjas[c.franja_id])
    for clase_id, por_dia in por_clase.items():
        clase = clases.get(clase_id)
        if clase is None or clase.asignatura_id not in asignaturas:
            continue
        nivel_id = next(iter(por_dia.values()))[0].nivel_id
        if asignaturas[clase.asignatura_id].reglas_efectivas(nivel_id).bloque_doble != "preferido":
            continue
        sueltas = 0
        for lista in por_dia.values():
            ordenadas = sorted(lista, key=lambda f: f.indice)
            tramo = 1
            for anterior, actual in zip(ordenadas, ordenadas[1:], strict=False):
                if adyacentes(anterior, actual):
                    tramo += 1
                else:
                    sueltas += tramo % 2
                    tramo = 1
            sueltas += tramo % 2
        valores["B8"] += max(0, sueltas - clase.horas_semanales % 2)

    if base is not None:
        actuales = {(c.clase_id, c.franja_id): set(c.profesores) for c in colocaciones}
        cambios = 0
        for b in base:
            ahora = actuales.get((b.clase_id, b.franja_id))
            if ahora is None:
                cambios += 2
            elif ahora != set(b.profesores):
                cambios += 1
        valores["B9"] = float(cambios)

    # B10: franjas libres entre la primera y la última clase de cada grupo y día.
    ocupadas: dict[int, set[str]] = defaultdict(set)
    for c in colocaciones:
        clase = clases.get(c.clase_id)
        if clase is not None:
            for g in grupos_de_clase(clase):
                ocupadas[g].add(c.franja_id)
    for grupo in datos.grupos:
        if grupo.id is None:
            continue
        if datos.nivel_de_grupo(grupo.id).huecos_alumnos != "penalizar":
            continue
        por_dia_g: dict[str, list[Franja]] = defaultdict(list)
        for f in calendario.utiles_grupo.get(grupo.id, []):
            por_dia_g[f.dia].append(f)
        for lista in por_dia_g.values():
            marcas = [f.id in ocupadas[grupo.id] for f in sorted(lista, key=lambda f: f.indice)]
            if sum(marcas) >= 2:
                primera = marcas.index(True)
                ultima = len(marcas) - 1 - marcas[::-1].index(True)
                valores["B10"] += sum(1 for m in marcas[primera:ultima] if not m)
    return valores
