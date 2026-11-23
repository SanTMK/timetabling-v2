"""Creado con Claude.

Verificador (§11.2): comprueba referencias y D1–D16 sobre una lista de colocaciones, sin
compartir código con `modelo.py`. Las comprobaciones locales usan `conflictos.py`; D5 se revisa
minuto a minuto y D9 con la ocupación física real. En modo parcial (borradores), las horas
faltantes son «pendientes» y no violaciones.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import DatosEscuela, Profesor, Violacion, por_id
from timetabling.dominio.tiempo import NOMBRES_DIAS, a_hhmm, texto_rango
from timetabling.nucleo.conflictos import Conflictos
from timetabling.nucleo.franjas import Calendario, Franja, adyacentes


@dataclass
class ResultadoVerificacion:
    violaciones: list[Violacion] = field(default_factory=list)
    pendientes: dict[int, int] = field(default_factory=dict)
    """Clase → horas que faltan (solo en modo parcial)."""

    @property
    def valida(self) -> bool:
        return not self.violaciones


def minutos_disponibles(profesor: Profesor, dia: str, desde: int, hasta: int) -> set[int]:
    """Minutos de `[desde, hasta)` en que el profesor puede dar clase ese día (D5, minuto a
    minuto): su disponibilidad (o toda la jornada) menos `no_disponible` y sus eventos."""
    franja = set(range(desde, hasta))
    if profesor.disponible_toda_la_jornada:
        minutos = set(franja)
    else:
        minutos = set()
        for rango in profesor.disponibilidad:
            if rango.dia == dia and rango.tipo != "no_disponible":
                minutos.update(range(rango.inicio, rango.fin))
        minutos &= franja
    for rango in profesor.disponibilidad:
        if rango.dia == dia and rango.tipo == "no_disponible":
            minutos.difference_update(range(rango.inicio, rango.fin))
    for evento in profesor.eventos:
        if evento.dia == dia:
            minutos.difference_update(range(evento.inicio, evento.fin))
    return minutos


class _Verificador:
    def __init__(
        self, datos: DatosEscuela, colocaciones: list[Colocacion], parcial: bool,
        calendario: Calendario | None,
    ) -> None:  # fmt: skip
        self.datos = datos
        self.colocaciones = colocaciones
        self.parcial = parcial
        self.calendario = calendario or Calendario.de(datos)
        self.conflictos = Conflictos(datos, self.calendario)
        self.resultado = ResultadoVerificacion()
        self.clases = por_id(datos.clases)
        self.profesores = por_id(datos.profesores)
        self.divisiones = por_id(datos.divisiones)
        self.asignaturas = por_id(datos.asignaturas)
        self._vistas: set[tuple[str, str]] = set()

    def violacion(self, restriccion: str, mensaje: str, clase_id: int | None = None) -> None:
        if (restriccion, mensaje) in self._vistas:
            return
        self._vistas.add((restriccion, mensaje))
        self.resultado.violaciones.append(Violacion(restriccion=restriccion, mensaje=mensaje,
                                                    clase_id=clase_id))  # fmt: skip

    def texto(self, clase_id: int) -> str:
        info = self.conflictos.info.get(clase_id)
        return info.texto if info else f"la clase {clase_id}"

    def ejecutar(self) -> ResultadoVerificacion:
        validas = self.referencias()
        franjas = self.calendario.franjas
        orden = sorted(
            validas, key=lambda c: (franjas[c.franja_id].dia, franjas[c.franja_id].inicio, c)
        )
        for colocacion in orden:
            for motivo in self.conflictos.motivos_colocacion(colocacion):
                if motivo.es_dura and motivo.restriccion != "D5":
                    self.violacion(motivo.restriccion, motivo.texto, colocacion.clase_id)
            self.d5_minuto_a_minuto(colocacion)
            self.conflictos.agregar(colocacion)
        self.d1(validas)
        self.d7_minima(validas)
        self.d11(validas)
        self.d12(validas)
        self.d13(validas)
        self.d16(validas)
        return self.resultado

    def referencias(self) -> list[Colocacion]:
        validas: list[Colocacion] = []
        for c in self.colocaciones:
            if c.clase_id not in self.conflictos.info:
                self.violacion("referencia", f"La clase {c.clase_id} no existe.", c.clase_id)
            elif c.franja_id not in self.calendario.franjas:
                self.violacion(
                    "referencia",
                    f"{self.texto(c.clase_id)} está en la franja {c.franja_id}, que no existe.",
                    c.clase_id,
                )
            elif any(p not in self.profesores for p in c.profesores):
                self.violacion(
                    "referencia", f"{self.texto(c.clase_id)} tiene un profesor que no existe.",
                    c.clase_id,
                )  # fmt: skip
            else:
                validas.append(c)
        return validas

    def d5_minuto_a_minuto(self, colocacion: Colocacion) -> None:
        franja = self.calendario.franjas[colocacion.franja_id]
        for p in colocacion.profesores:
            profesor = self.profesores[p]
            libres = minutos_disponibles(profesor, franja.dia, franja.inicio, franja.fin)
            if len(libres) < franja.duracion:
                faltan = sorted(set(range(franja.inicio, franja.fin)) - libres)
                self.violacion(
                    "D5",
                    f"{profesor.nombre} no está disponible el {NOMBRES_DIAS[franja.dia].lower()} "
                    f"a las {a_hhmm(faltan[0])} y tiene {self.texto(colocacion.clase_id)} de "
                    f"{texto_rango(franja.inicio, franja.fin)}.",
                    colocacion.clase_id,
                )

    def d1(self, colocaciones: list[Colocacion]) -> None:
        cuenta = Counter(c.clase_id for c in colocaciones)
        for clase in self.datos.clases:
            if clase.id is None or clase.id not in self.conflictos.info:
                continue
            tiene = cuenta[clase.id]
            if tiene < clase.horas_semanales:
                if self.parcial:
                    self.resultado.pendientes[clase.id] = clase.horas_semanales - tiene
                else:
                    self.violacion(
                        "D1",
                        f"{self.texto(clase.id)} tiene {tiene} de {clase.horas_semanales} horas.",
                        clase.id,
                    )

    def d7_minima(self, colocaciones: list[Colocacion]) -> None:
        if self.parcial:
            return
        minutos: dict[int, int] = defaultdict(int)
        for c in colocaciones:
            for p in c.profesores:
                minutos[p] += self.calendario.franjas[c.franja_id].duracion
        for profesor in self.datos.profesores:
            if not profesor.activo or profesor.id is None:
                continue
            if minutos[profesor.id] < profesor.carga_min_semanal_min:
                self.violacion(
                    "D7",
                    f"{profesor.nombre} tiene {minutos[profesor.id]} min de clase y su carga "
                    f"mínima es de {profesor.carga_min_semanal_min} min.",
                )

    def _por_clase_y_dia(
        self, colocaciones: list[Colocacion]
    ) -> dict[int, dict[str, list[Franja]]]:
        agrupadas: dict[int, dict[str, list[Franja]]] = defaultdict(lambda: defaultdict(list))
        for c in colocaciones:
            franja = self.calendario.franjas[c.franja_id]
            agrupadas[c.clase_id][franja.dia].append(franja)
        return agrupadas

    def d11(self, colocaciones: list[Colocacion]) -> None:
        """Bloque doble obligatorio: las franjas de cada día se agrupan en tramos adyacentes;
        cada tramo de largo impar deja una suelta; sueltas ≤ horas % 2."""
        cuenta = Counter(c.clase_id for c in colocaciones)
        for clase_id, por_dia in self._por_clase_y_dia(colocaciones).items():
            info = self.conflictos.info[clase_id]
            if info.reglas.bloque_doble != "obligatorio":
                continue
            if self.parcial and cuenta[clase_id] < info.clase.horas_semanales:
                continue
            sueltas = 0
            for franjas in por_dia.values():
                franjas = sorted(franjas, key=lambda f: f.indice)
                tramo = 1
                for anterior, actual in zip(franjas, franjas[1:], strict=False):
                    if adyacentes(anterior, actual):
                        tramo += 1
                    else:
                        sueltas += tramo % 2
                        tramo = 1
                sueltas += tramo % 2
            if sueltas > info.clase.horas_semanales % 2:
                self.violacion(
                    "D11",
                    f"{info.texto} debe darse en bloques dobles y tiene {sueltas} horas sueltas.",
                    clase_id,
                )

    def d12(self, colocaciones: list[Colocacion]) -> None:
        """Sin huecos: las franjas ocupadas del grupo son las primeras útiles de cada día."""
        if self.parcial:
            return
        ocupadas: dict[int, set[str]] = defaultdict(set)
        for c in colocaciones:
            for d in self.conflictos.info[c.clase_id].clase.destinatarios:
                ocupadas[d.grupo_id].add(c.franja_id)
        for grupo in self.datos.grupos:
            if grupo.id is None:
                continue
            nivel = self.datos.nivel_de_grupo(grupo.id)
            if nivel.huecos_alumnos != "prohibidos":
                continue
            por_dia: dict[str, list[Franja]] = defaultdict(list)
            for f in self.calendario.utiles_grupo.get(grupo.id, []):
                por_dia[f.dia].append(f)
            for dia, franjas in por_dia.items():
                marcas = [
                    f.id in ocupadas[grupo.id] for f in sorted(franjas, key=lambda f: f.indice)
                ]
                if any(not a and b for a, b in zip(marcas, marcas[1:], strict=False)):
                    self.violacion(
                        "D12",
                        f"{self.datos.nombre_grupo(grupo.id)} tiene huecos el "
                        f"{NOMBRES_DIAS[dia].lower()} (prohibidos en {nivel.nombre}).",  # type: ignore[index]
                    )

    def d13(self, colocaciones: list[Colocacion]) -> None:
        for fija in self.datos.fijas:
            info = self.conflictos.info.get(fija.clase_id)
            if info is None or info.nivel_id is None:
                continue
            franja = self.calendario.franja(info.nivel_id, fija.dia, fija.indice_franja)
            ok = franja is not None and any(
                c.clase_id == fija.clase_id
                and c.franja_id == franja.id
                and (fija.profesor_id is None or fija.profesor_id in c.profesores)
                for c in colocaciones
            )
            if not ok:
                self.violacion(
                    "D13",
                    f"{info.texto} no respeta su asignación fija del "
                    f"{NOMBRES_DIAS[fija.dia].lower()}, hora {fija.indice_franja + 1}.",
                    fija.clase_id,
                )

    def d16(self, colocaciones: list[Colocacion]) -> None:
        """Las partes de una división simultánea ocurren en las mismas franjas por asignatura."""
        cuenta = Counter(c.clase_id for c in colocaciones)
        por_parte: dict[tuple[int, int], dict[str, Counter[str]]] = defaultdict(
            lambda: defaultdict(Counter)
        )
        incompletas: set[tuple[int, int]] = set()
        for c in colocaciones:
            info = self.conflictos.info[c.clase_id]
            for d in info.clase.destinatarios:
                if d.division_id is None or d.parte is None:
                    continue
                division = self.divisiones.get(d.division_id)
                if division is None or not division.simultanea:
                    continue
                clave = (d.division_id, info.clase.asignatura_id)
                por_parte[clave][d.parte][c.franja_id] += 1
                if cuenta[c.clase_id] < info.clase.horas_semanales:
                    incompletas.add(clave)
        for clave, partes in por_parte.items():
            if self.parcial and clave in incompletas:
                continue
            division = self.divisiones[clave[0]]
            conjuntos = [partes.get(p, Counter()) for p in division.partes]
            if any(c != conjuntos[0] for c in conjuntos[1:]):
                grupo = self.datos.nombre_grupo(division.grupo_id)
                asignatura = self.asignaturas[clave[1]].nombre
                self.violacion(
                    "D16",
                    f"Las partes de «{division.nombre}» de {grupo} no tienen {asignatura} en las "
                    "mismas franjas.",
                )


def verificar(
    datos: DatosEscuela,
    colocaciones: Iterable[Colocacion],
    parcial: bool = False,
    calendario: Calendario | None = None,
) -> ResultadoVerificacion:
    """Comprueba un horario completo (o parcial, para borradores)."""
    return _Verificador(datos, list(colocaciones), parcial, calendario).ejecutar()
