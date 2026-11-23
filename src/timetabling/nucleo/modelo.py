"""Creado con Claude.

Restricciones duras (§8) sobre CP-SAT. Cada restricción se registra con una clave de familia y
una clave de entidad; con suposiciones activadas, cada grupo de restricciones queda bajo un
literal para el diagnóstico (§11.3).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Literal

from ortools.sat.python import cp_model

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.clases import grupos_de_clase, profesores_posibles
from timetabling.dominio.modelos import Clase, DatosEscuela, ReglasAsignatura, por_id
from timetabling.nucleo.franjas import Calendario, Franja, adyacentes, evaluar_franja, prohibida

FAMILIAS: tuple[str, ...] = (
    "disponibilidad",
    "prohibidas",
    "curricular",
    "grupo",
    "profesor",
    "carga",
    "continuidad",
    "espacio",
    "diaria",
    "bloque",
    "sin_huecos",
    "fija",
    "division",
)

ModoSuposiciones = Literal["ninguno", "familia", "entidad"]

Lit = cp_model.IntVar
Expr = cp_model.LinearExpr


@dataclass
class ClaseModelo:
    """Lo que el modelo necesita de una clase."""

    clase: Clase
    nivel_id: int
    reglas: ReglasAsignatura
    tipo_espacio: str | None
    franjas: list[Franja]
    fijos: tuple[int, ...]
    """Profesores que la imparten siempre (los fijos, o el único candidato)."""
    candidatos: tuple[int, ...]
    """Si no hay fijos, candidatos entre los que el generador elige uno."""

    @property
    def id(self) -> int:
        assert self.clase.id is not None
        return self.clase.id


@dataclass
class ModeloHorario:
    modelo: cp_model.CpModel
    calendario: Calendario
    clases: dict[int, ClaseModelo]
    z: dict[tuple[int, str], Lit] = field(default_factory=dict)
    x: dict[tuple[int, int, str], Lit] = field(default_factory=dict)
    y: dict[tuple[int, int], Lit] = field(default_factory=dict)
    ocupa: dict[tuple[int, str], cp_model.IntVar] = field(default_factory=dict)
    """`o[p,s]`: el profesor da clase en la franja (suma de sus `x`)."""
    dia_con_clase: dict[tuple[int, str], Lit] = field(default_factory=dict)
    pares: dict[int, tuple[dict[tuple[str, str], Lit], dict[str, Lit]]] = field(
        default_factory=dict
    )
    """Por clase: variables de bloque doble `b` (pares adyacentes) y sueltas `u`."""
    suposiciones: dict[tuple[str, str], Lit] = field(default_factory=dict)
    """`(familia, entidad) → literal`; la entidad es «*» en el modo por familia."""

    def colocaciones(self, solver: cp_model.CpSolver) -> list[Colocacion]:
        resultado: list[Colocacion] = []
        for (clase_id, franja_id), var in self.z.items():
            if not solver.boolean_value(var):
                continue
            info = self.clases[clase_id]
            if info.fijos:
                profesores = info.fijos
            else:
                profesores = tuple(
                    p for p in info.candidatos
                    if (clase_id, p, franja_id) in self.x
                    and solver.boolean_value(self.x[(clase_id, p, franja_id)])
                )  # fmt: skip
            resultado.append(Colocacion(clase_id, franja_id, profesores))
        return sorted(resultado)


class ConstructorModelo:
    """Construye el modelo duro. `refinar` lista las familias que, en modo «entidad», llevan un
    literal por entidad; las demás llevan uno por familia.

    Con suposiciones (diagnóstico), la disponibilidad de los profesores (D5) y las franjas
    prohibidas (D15) no se podan: se vuelven restricciones de las familias «disponibilidad» y
    «prohibidas», para que el diagnóstico pueda nombrarlas."""

    def __init__(
        self,
        datos: DatosEscuela,
        calendario: Calendario | None = None,
        modo: ModoSuposiciones = "ninguno",
        refinar: Iterable[str] = (),
        fijar: Iterable[Colocacion] = (),
        activas: Iterable[tuple[str, str]] | None = None,
    ) -> None:
        """Con `activas`, solo se imponen las restricciones de esas claves (familia, entidad
        o «*»), sin literales; las demás quedan desactivadas. Así el diagnóstico prueba
        subconjuntos con la relajación lineal completa."""
        self.datos = datos
        self.activas = set(activas) if activas is not None else None
        self.calendario = calendario or Calendario.de(datos)
        self.modo = modo
        self.refinar = set(refinar)
        self.fijar = list(fijar)
        self.m = cp_model.CpModel()
        self.profesores = por_id(datos.profesores)
        self.h = ModeloHorario(self.m, self.calendario, {})
        self.podar = modo == "ninguno" and self.activas is None
        self._apagada: Lit | None = None
        self._no_disponibles: list[tuple[int, int, str]] = []
        self._prohibidas: list[tuple[int, str]] = []

    # ------------------------------------------------------------------ registro

    def clave(self, familia: str, entidad: str) -> tuple[str, str]:
        refinada = self.modo == "entidad" and familia in self.refinar
        return (familia, entidad if refinada else "*")

    def _literal(self, familia: str, entidad: str) -> Lit | None:
        if self.activas is not None:
            if self.clave(familia, entidad) in self.activas:
                return None
            if self._apagada is None:
                self._apagada = self.m.new_constant(0)
            return self._apagada
        if self.modo == "ninguno":
            return None
        clave = self.clave(familia, entidad)
        if clave not in self.h.suposiciones:
            self.h.suposiciones[clave] = self.m.new_bool_var(f"sup[{clave[0]}|{clave[1]}]")
        return self.h.suposiciones[clave]

    def _r(self, familia: str, entidad: str, restriccion: cp_model.Constraint) -> None:
        literal = self._literal(familia, entidad)
        if literal is not None:
            restriccion.only_enforce_if(literal)

    # ------------------------------------------------------------------ construcción

    def construir(self) -> ModeloHorario:
        self._clases()
        self._variables()
        self._poda_como_restricciones()
        self._d1()
        self._d2()
        self._d3_y_ocupacion()
        self._d7()
        self._d8()
        self._d9()
        self._d10()
        self._d11()
        self._d12()
        self._d13()
        self._d16()
        return self.h

    def _clases(self) -> None:
        asignaturas = por_id(self.datos.asignaturas)
        grupos = por_id(self.datos.grupos)
        grados = por_id(self.datos.grados)
        for clase in self.datos.clases:
            if clase.id is None or clase.asignatura_id not in asignaturas:
                continue
            ids = grupos_de_clase(clase)
            niveles = {grados[grupos[g].grado_id].nivel_id for g in ids if g in grupos}
            if len(niveles) != 1:
                continue
            nivel_id = next(iter(niveles))
            asignatura = asignaturas[clase.asignatura_id]
            reglas = asignatura.reglas_efectivas(nivel_id)
            utiles = self.calendario.utiles_comunes(ids)  # D14
            if self.podar:
                franjas = [f for f in utiles if not prohibida(reglas, f)]  # D15
            else:
                franjas = list(utiles)
                self._prohibidas += [(clase.id, f.id) for f in utiles if prohibida(reglas, f)]
            posibles = tuple(profesores_posibles(self.datos, clase))  # D4
            if clase.profesores or len(posibles) == 1:
                fijos, candidatos = posibles, ()
            else:
                fijos, candidatos = (), posibles
            for p in fijos:  # D5 para todos los fijos
                invalidas = {
                    f.id for f in franjas if not evaluar_franja(self.profesores[p], f).valida
                }
                if self.podar:
                    franjas = [f for f in franjas if f.id not in invalidas]
                else:
                    self._no_disponibles += [(clase.id, p, f) for f in sorted(invalidas)]
            self.h.clases[clase.id] = ClaseModelo(
                clase=clase,
                nivel_id=nivel_id,
                reglas=reglas,
                tipo_espacio=clase.espacio_efectivo(asignatura),
                franjas=franjas,
                fijos=fijos,
                candidatos=candidatos,
            )

    def _variables(self) -> None:
        m, h = self.m, self.h
        for c in h.clases.values():
            if c.fijos:
                for s in c.franjas:
                    z = m.new_bool_var(f"z[{c.id},{s.id}]")
                    h.z[(c.id, s.id)] = z
                    for p in c.fijos:
                        h.x[(c.id, p, s.id)] = z
                continue
            validas: dict[int, set[str]] = {
                p: {
                    s.id
                    for s in c.franjas
                    if not self.podar or evaluar_franja(self.profesores[p], s).valida
                }
                for p in c.candidatos
            }  # D5
            if not self.podar:
                self._no_disponibles += [
                    (c.id, p, s.id)
                    for p in c.candidatos
                    for s in c.franjas
                    if not evaluar_franja(self.profesores[p], s).valida
                ]
            franjas = [s for s in c.franjas if any(s.id in v for v in validas.values())]
            c.franjas = franjas
            for p in c.candidatos:
                h.y[(c.id, p)] = m.new_bool_var(f"y[{c.id},{p}]")
            # D6: un solo profesor a cargo.
            self._r(
                "continuidad",
                f"clase:{c.id}",
                m.add(sum(h.y[(c.id, p)] for p in c.candidatos) == 1),
            )
            for s in franjas:
                z = m.new_bool_var(f"z[{c.id},{s.id}]")
                h.z[(c.id, s.id)] = z
                xs = []
                for p in c.candidatos:
                    if s.id in validas[p]:
                        x = m.new_bool_var(f"x[{c.id},{p},{s.id}]")
                        h.x[(c.id, p, s.id)] = x
                        m.add_implication(x, h.y[(c.id, p)])
                        xs.append(x)
                m.add(z == sum(xs))

    def _poda_como_restricciones(self) -> None:
        """Sin poda (diagnóstico): D5 y D15 como restricciones con suposiciones."""
        for clase_id, p, franja_id in self._no_disponibles:
            x = self.h.x.get((clase_id, p, franja_id))
            if x is not None:
                self._r("disponibilidad", f"profesor:{p}", self.m.add(x == 0))
        for clase_id, franja_id in self._prohibidas:
            z = self.h.z.get((clase_id, franja_id))
            if z is not None:
                asignatura = self.h.clases[clase_id].clase.asignatura_id
                self._r("prohibidas", f"asignatura:{asignatura}", self.m.add(z == 0))

    # ------------------------------------------------------------------ utilidades

    def _z_de(self, clase_id: int, franja_id: str) -> Lit | None:
        return self.h.z.get((clase_id, franja_id))

    def _dias_de(self, c: ClaseModelo) -> dict[str, list[Franja]]:
        por_dia: dict[str, list[Franja]] = defaultdict(list)
        for s in c.franjas:
            por_dia[s.dia].append(s)
        return por_dia

    # ------------------------------------------------------------------ D1, D2

    def _d1(self) -> None:
        for c in self.h.clases.values():
            zs = [self.h.z[(c.id, s.id)] for s in c.franjas]
            self._r("curricular", f"clase:{c.id}", self.m.add(sum(zs) == c.clase.horas_semanales))

    def _d2(self) -> None:
        """Por grupo y franja: a lo más una clase, salvo partes distintas de una división
        simultánea, que pueden coincidir."""
        simultaneas = {d.id for d in self.datos.divisiones if d.simultanea and d.id is not None}
        completas: dict[int, list[int]] = defaultdict(list)
        partes: dict[int, dict[int, dict[str, list[int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        for c in self.h.clases.values():
            for d in c.clase.destinatarios:
                if d.division_id is None or d.parte is None or d.division_id not in simultaneas:
                    completas[d.grupo_id].append(c.id)
                else:
                    partes[d.grupo_id][d.division_id][d.parte].append(c.id)
        for grupo in self.datos.grupos:
            if grupo.id is None:
                continue
            for s in self.calendario.utiles_grupo.get(grupo.id, []):
                terminos: list[Lit] = [
                    z for cid in dict.fromkeys(completas[grupo.id])
                    if (z := self._z_de(cid, s.id)) is not None
                ]  # fmt: skip
                for division_id, por_parte in partes[grupo.id].items():
                    activas = {
                        parte: [z for cid in ids if (z := self._z_de(cid, s.id)) is not None]
                        for parte, ids in por_parte.items()
                    }
                    activas = {p: zs for p, zs in activas.items() if zs}
                    if not activas:
                        continue
                    a = self.m.new_bool_var(f"div[{grupo.id},{division_id},{s.id}]")
                    for zs in activas.values():
                        self._r("grupo", f"grupo:{grupo.id}", self.m.add(sum(zs) <= a))
                    terminos.append(a)
                if len(terminos) > 1:
                    self._r("grupo", f"grupo:{grupo.id}", self.m.add(sum(terminos) <= 1))

    # ------------------------------------------------------------------ D3, ocupación

    def _d3_y_ocupacion(self) -> None:
        por_profesor: dict[int, dict[str, list[Lit]]] = defaultdict(lambda: defaultdict(list))
        for (_, p, s), x in self.h.x.items():
            por_profesor[p][s].append(x)
        for p, por_franja in por_profesor.items():
            for s, xs in por_franja.items():
                o = self.m.new_int_var(0, len(xs), f"o[{p},{s}]")
                self.m.add(o == sum(xs))
                self.h.ocupa[(p, s)] = o
            for s, xs in por_franja.items():
                if len(xs) > 1:  # dos clases del mismo profesor en la misma franja
                    self._r("profesor", f"profesor:{p}", self.m.add(self.h.ocupa[(p, s)] <= 1))
            for clique in self.calendario.cliques:
                terminos = [self.h.ocupa[(p, s)] for s in clique if (p, s) in self.h.ocupa]
                if len(terminos) > 1:
                    self._r("profesor", f"profesor:{p}", self.m.add(sum(terminos) <= 1))

    def _franjas_profesor(self, p: int) -> dict[str, list[Franja]]:
        por_dia: dict[str, list[Franja]] = defaultdict(list)
        for q, s in self.h.ocupa:
            if q == p:
                f = self.calendario.franjas[s]
                por_dia[f.dia].append(f)
        return por_dia

    def dia_con_clase(self, p: int, dia: str) -> Lit:
        """Literal «el profesor da clase ese día» (D7 y B5)."""
        clave = (p, dia)
        if clave not in self.h.dia_con_clase:
            d = self.m.new_bool_var(f"dia[{p},{dia}]")
            os = [self.h.ocupa[(p, f.id)] for f in self._franjas_profesor(p).get(dia, [])]
            for o in os:
                self.m.add(o <= d)
            self.m.add(d <= sum(os))
            self.h.dia_con_clase[clave] = d
        return self.h.dia_con_clase[clave]

    # ------------------------------------------------------------------ D7, D8

    def _d7(self) -> None:
        for p in {q for q, _ in self.h.ocupa}:
            profesor = self.profesores[p]
            por_dia = self._franjas_profesor(p)
            semana = [(self.h.ocupa[(p, f.id)], f.duracion) for fs in por_dia.values() for f in fs]
            maximo_posible = sum(d for _, d in semana)
            expr = sum(o * d for o, d in semana)
            entidad = f"profesor:{p}"
            if maximo_posible > profesor.carga_max_semanal_min:
                self._r("carga", entidad, self.m.add(expr <= profesor.carga_max_semanal_min))
            if profesor.carga_min_semanal_min > 0:
                self._r("carga", entidad, self.m.add(expr >= profesor.carga_min_semanal_min))
            for _dia, fs in por_dia.items():
                if self._maximo_dia(fs) > profesor.carga_max_diaria_min:
                    self._r(
                        "carga",
                        entidad,
                        self.m.add(
                            sum(self.h.ocupa[(p, f.id)] * f.duracion for f in fs)
                            <= profesor.carga_max_diaria_min
                        ),
                    )
            if profesor.max_dias is not None and len(por_dia) > profesor.max_dias:
                dias = [self.dia_con_clase(p, dia) for dia in por_dia]
                self._r("carga", entidad, self.m.add(sum(dias) <= profesor.max_dias))
                # Corte: los minutos del día caben en el tope diario solo si da clase ese día.
                # Es redundante con lo anterior, pero refuerza la relajación lineal.
                for dia, fs in por_dia.items():
                    tope = min(profesor.carga_max_diaria_min, self._maximo_dia(fs))
                    minutos = sum(self.h.ocupa[(p, f.id)] * f.duracion for f in fs)
                    self._r(
                        "carga", entidad, self.m.add(minutos <= tope * self.dia_con_clase(p, dia))
                    )

    def _maximo_dia(self, franjas: list[Franja]) -> int:
        """Cota de minutos en un día: suma de la línea de tiempo cubierta por sus franjas."""
        minutos: set[int] = set()
        for f in franjas:
            minutos.update(range(f.inicio, f.fin))
        return len(minutos)

    def _d8(self) -> None:
        """Por profesor y día: en cualquier ventana de M + P minutos hay a lo más M ocupados.
        Basta con ventanas que empiezan al inicio de una franja o terminan al final de una."""
        rejilla = self.calendario.rejilla
        descanso = self.datos.configuracion.descanso_minimo_min
        for p in {q for q, _ in self.h.ocupa}:
            profesor = self.profesores[p]
            limite = profesor.max_minutos_continuos
            ventana = limite + descanso
            for _dia, fs in self._franjas_profesor(p).items():
                if self._maximo_dia(fs) <= limite:
                    continue
                inicios = {f.inicio for f in fs} | {f.fin - ventana for f in fs}
                vistas: set[tuple[tuple[str, int], ...]] = set()
                for t in sorted(inicios):
                    fin = t + ventana
                    terminos = tuple(
                        sorted(
                            (f.id, min(f.fin, fin) - max(f.inicio, t))
                            for f in fs
                            if f.inicio < fin and t < f.fin
                        )
                    )
                    cubiertos: set[int] = set()
                    for f in fs:
                        cubiertos.update(range(max(f.inicio, t), min(f.fin, fin)))
                    if len(cubiertos) <= limite or terminos in vistas:
                        continue
                    vistas.add(terminos)
                    # Con M en el mcd de Δ, el tope es exacto en la rejilla.
                    tope = (limite // rejilla.delta) * rejilla.delta
                    self._r(
                        "carga",
                        f"profesor:{p}",
                        self.m.add(sum(self.h.ocupa[(p, fid)] * m for fid, m in terminos) <= tope),
                    )

    # ------------------------------------------------------------------ D9, D10

    def _d9(self) -> None:
        capacidad: dict[str, int] = defaultdict(int)
        for espacio in self.datos.espacios:
            capacidad[espacio.tipo] += espacio.cantidad
        por_tipo: dict[str, dict[str, list[Lit]]] = defaultdict(lambda: defaultdict(list))
        for c in self.h.clases.values():
            if c.tipo_espacio is None:
                continue
            for s in c.franjas:
                por_tipo[c.tipo_espacio][s.id].append(self.h.z[(c.id, s.id)])
        for tipo, por_franja in por_tipo.items():
            for clique in self.calendario.cliques:
                terminos = [z for s in clique for z in por_franja.get(s, [])]
                if len(terminos) > capacidad[tipo]:
                    self._r(
                        "espacio", f"espacio:{tipo}", self.m.add(sum(terminos) <= capacidad[tipo])
                    )

    def _d10(self) -> None:
        """Por destinatario, asignatura y día: a lo más `max_horas_dia`; con máximo 2, las dos
        horas deben ser adyacentes."""
        por_grupo: dict[tuple[int, int], list[tuple[ClaseModelo, int | None, str | None]]] = (
            defaultdict(list)
        )
        for c in self.h.clases.values():
            for d in c.clase.destinatarios:
                por_grupo[(d.grupo_id, c.clase.asignatura_id)].append((c, d.division_id, d.parte))
        for (grupo_id, _), entradas in por_grupo.items():
            completas = [c for c, div, _ in entradas if div is None]
            partes = {(div, parte) for _, div, parte in entradas if div is not None}
            conjuntos = (
                [completas + [c for c, div, parte in entradas if (div, parte) == u] for u in partes]
                if partes
                else [completas]
            )
            for conjunto in conjuntos:
                self._d10_conjunto(grupo_id, list({c.id: c for c in conjunto}.values()))

    def _d10_conjunto(self, grupo_id: int, clases: list[ClaseModelo]) -> None:
        if not clases:
            return
        maximo = clases[0].reglas.max_horas_dia
        total = sum(c.clase.horas_semanales for c in clases)
        por_dia: dict[str, dict[str, tuple[Franja, list[Lit]]]] = defaultdict(dict)
        for c in clases:
            for s in c.franjas:
                _, zs = por_dia[s.dia].setdefault(s.id, (s, []))
                zs.append(self.h.z[(c.id, s.id)])
        entidad = f"grupo:{grupo_id}"
        for franjas in por_dia.values():
            todas = [z for _, zs in franjas.values() for z in zs]
            if len(franjas) > maximo and total > maximo:
                self._r("diaria", entidad, self.m.add(sum(todas) <= maximo))
            if maximo == 2 and total >= 2:
                for (s1, z1), (s2, z2) in combinations(franjas.values(), 2):
                    if not adyacentes(s1, s2):
                        self._r("diaria", entidad, self.m.add(sum(z1) + sum(z2) <= 1))

    # ------------------------------------------------------------------ D11, D12

    def pares_de(self, c: ClaseModelo) -> tuple[dict[tuple[str, str], Lit], dict[str, Lit]]:
        """Variables `b` sobre pares adyacentes y `u` sueltas: `z[s] = Σ b + u[s]` (D11, B8)."""
        if c.id not in self.h.pares:
            b: dict[tuple[str, str], Lit] = {}
            u: dict[str, Lit] = {}
            for franjas in self._dias_de(c).values():
                ordenadas = sorted(franjas, key=lambda f: f.indice)
                for s1, s2 in zip(ordenadas, ordenadas[1:], strict=False):
                    if adyacentes(s1, s2):
                        b[(s1.id, s2.id)] = self.m.new_bool_var(f"b[{c.id},{s1.id},{s2.id}]")
            for s in c.franjas:
                u[s.id] = self.m.new_bool_var(f"u[{c.id},{s.id}]")
                pares = [v for (a, d), v in b.items() if s.id in (a, d)]
                self.m.add(self.h.z[(c.id, s.id)] == sum(pares) + u[s.id])
            self.h.pares[c.id] = (b, u)
        return self.h.pares[c.id]

    def _d11(self) -> None:
        for c in self.h.clases.values():
            if c.reglas.bloque_doble != "obligatorio":
                continue
            _, u = self.pares_de(c)
            self._r(
                "bloque",
                f"clase:{c.id}",
                self.m.add(sum(u.values()) <= c.clase.horas_semanales % 2),
            )

    def _d12(self) -> None:
        niveles = por_id(self.datos.niveles)
        por_grupo_franja: dict[tuple[int, str], list[Lit]] = defaultdict(list)
        for c in self.h.clases.values():
            for g in grupos_de_clase(c.clase):
                for s in c.franjas:
                    por_grupo_franja[(g, s.id)].append(self.h.z[(c.id, s.id)])
        for grupo in self.datos.grupos:
            if grupo.id is None:
                continue
            nivel = niveles.get(self.datos.nivel_de_grupo(grupo.id).id or 0)
            if nivel is None or nivel.huecos_alumnos != "prohibidos":
                continue
            por_dia: dict[str, list[Franja]] = defaultdict(list)
            for s in self.calendario.utiles_grupo.get(grupo.id, []):
                por_dia[s.dia].append(s)
            for franjas in por_dia.values():
                ocupadas: list[Lit | int] = []
                for s in sorted(franjas, key=lambda f: f.indice):
                    zs = por_grupo_franja.get((grupo.id, s.id), [])
                    if not zs:
                        ocupadas.append(0)
                        continue
                    o = self.m.new_bool_var(f"ocupada[{grupo.id},{s.id}]")
                    for z in zs:
                        self.m.add_implication(z, o)
                    self.m.add(o <= sum(zs))
                    ocupadas.append(o)
                for a, b in zip(ocupadas, ocupadas[1:], strict=False):
                    if isinstance(b, int):
                        continue
                    self._r("sin_huecos", f"grupo:{grupo.id}", self.m.add(b <= a))

    # ------------------------------------------------------------------ D13, D16

    def _d13(self) -> None:
        objetivos: list[tuple[int, str, int | None]] = []
        for fija in self.datos.fijas:
            c = self.h.clases.get(fija.clase_id)
            if c is None:
                continue
            franja = self.calendario.franja(c.nivel_id, fija.dia, fija.indice_franja)
            objetivos.append((c.id, franja.id if franja else "?", fija.profesor_id))
        for colocacion in self.fijar:
            profesor = colocacion.profesores[0] if len(colocacion.profesores) == 1 else None
            objetivos.append((colocacion.clase_id, colocacion.franja_id, profesor))
        for clase_id, franja_id, profesor in objetivos:
            entidad = f"clase:{clase_id}"
            z = self._z_de(clase_id, franja_id)
            if z is None:
                self._r("fija", entidad, self.m.add_bool_or([]))
                continue
            self._r("fija", entidad, self.m.add(z == 1))
            if profesor is not None and not self.h.clases[clase_id].fijos:
                x = self.h.x.get((clase_id, profesor, franja_id))
                if x is None:
                    self._r("fija", entidad, self.m.add_bool_or([]))
                else:
                    self._r("fija", entidad, self.m.add(x == 1))

    def _d16(self) -> None:
        divisiones = por_id(self.datos.divisiones)
        por_division: dict[tuple[int, int], dict[str, list[ClaseModelo]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for c in self.h.clases.values():
            for d in c.clase.destinatarios:
                if d.division_id is None or d.parte is None:
                    continue
                division = divisiones.get(d.division_id)
                if division and division.simultanea:
                    por_division[(d.division_id, c.clase.asignatura_id)][d.parte].append(c)
        for (division_id, _), partes in por_division.items():
            division = divisiones[division_id]
            listas = [partes.get(p, []) for p in division.partes]
            franjas = {s.id for lista in listas for c in lista for s in c.franjas}
            entidad = f"division:{division_id}"
            for s in sorted(franjas):
                sumas = [
                    sum(z for c in lista if (z := self._z_de(c.id, s)) is not None)
                    for lista in listas
                ]
                for a, b in zip(sumas, sumas[1:], strict=False):
                    self._r("division", entidad, self.m.add(a == b))
