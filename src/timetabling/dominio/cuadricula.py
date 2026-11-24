"""Creado con Claude.

Disposición común de los horarios (§16, §17): la misma cuadrícula alimenta la vista de la
interfaz, Excel y PDF. Se arma desde una `Solucion` guardada (con sus propias franjas y copias
desnormalizadas), así que sigue siendo legible aunque los datos hayan cambiado.

- Por grupo y por espacio: filas = franjas del nivel (con los recesos), columnas = días.
- Por profesor: si da clase en un solo nivel, la cuadrícula del nivel; si da en varios, filas en
  la rejilla Δ con celdas que abarcan la duración real.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import reduce
from math import gcd
from typing import Literal

from timetabling.dominio.colores import COLOR_POR_DEFECTO, GRIS_RECESO
from timetabling.dominio.modelos import (
    Asignacion,
    DatosEscuela,
    FranjaGuardada,
    Solucion,
    por_id,
)
from timetabling.dominio.tiempo import DIAS, Dia, a_hhmm, texto_rango

TipoCelda = Literal["clase", "receso"]


@dataclass(frozen=True)
class Fila:
    inicio: int
    fin: int
    receso: bool = False

    @property
    def etiqueta(self) -> str:
        return "Receso" if self.receso else texto_rango(self.inicio, self.fin)

    @property
    def etiqueta_inicio(self) -> str:
        """Solo la hora de inicio (filas finas de la rejilla Δ)."""
        return a_hhmm(self.inicio)


@dataclass
class Celda:
    fila: int
    columna: int
    lineas: list[str]
    color: str = COLOR_POR_DEFECTO
    tipo: TipoCelda = "clase"
    filas: int = 1
    columnas: int = 1
    bloqueada: bool = False
    cambiada: bool = False
    conflicto: bool = False

    @property
    def marcas(self) -> str:
        return "".join(
            m for m, activo in (("📌", self.bloqueada), ("↻", self.cambiada), ("⚠", self.conflicto))
            if activo
        )  # fmt: skip

    @property
    def texto(self) -> str:
        lineas = list(self.lineas)
        if lineas and self.marcas:
            lineas[0] = f"{self.marcas} {lineas[0]}"
        return "\n".join(lineas)


@dataclass
class Cuadricula:
    titulo: str
    dias: list[Dia]
    filas: list[Fila]
    celdas: list[Celda] = field(default_factory=list)
    subtitulo: str = ""

    def celda(self, fila: int, columna: int) -> Celda | None:
        for c in self.celdas:
            if c.fila <= fila < c.fila + c.filas and c.columna <= columna < c.columna + c.columnas:
                return c
        return None


@dataclass(frozen=True)
class _Entrada:
    """Una clase en una franja (con todos sus profesores)."""

    clase_id: int | None
    franja: FranjaGuardada
    asignatura: str
    grupos_texto: str
    profesores: tuple[str, ...]
    profesor_ids: tuple[int | None, ...]
    color: str
    bloqueada: bool
    indice_franja: int


_PARTE = re.compile(r"^(.*?)(?: \((.*)\))?$")


class Disposicion:
    def __init__(
        self,
        solucion: Solucion,
        datos: DatosEscuela,
        cambiadas: set[tuple[int | None, int]] | None = None,
        conflictos: set[tuple[int | None, int]] | None = None,
    ) -> None:
        self.solucion = solucion
        self.datos = datos
        self.cambiadas = cambiadas or set()
        self.conflictos = conflictos or set()
        self.clases = por_id(datos.clases)
        self.niveles = por_id(datos.niveles)
        self.entradas = self._entradas(solucion.asignaciones)

    def _entradas(self, asignaciones: list[Asignacion]) -> list[_Entrada]:
        agrupadas: dict[tuple[int | None, int, str], list[Asignacion]] = defaultdict(list)
        for a in asignaciones:
            agrupadas[(a.clase_id, a.franja, a.grupos_texto)].append(a)
        resultado = []
        for (clase_id, franja, _), lista in agrupadas.items():
            primera = lista[0]
            resultado.append(
                _Entrada(
                    clase_id=clase_id,
                    franja=self.solucion.franjas[franja],
                    asignatura=primera.asignatura_nombre,
                    grupos_texto=primera.grupos_texto,
                    profesores=tuple(a.profesor_nombre for a in lista if a.profesor_nombre),
                    profesor_ids=tuple(a.profesor_id for a in lista),
                    color=primera.color,
                    bloqueada=any(a.bloqueada for a in lista),
                    indice_franja=franja,
                )
            )
        return resultado

    # ------------------------------------------------------------------ grupos

    def _grupos_de(self, entrada: _Entrada) -> list[tuple[str, str | None]]:
        """(nombre del grupo, parte) a los que llega la entrada."""
        clase = self.clases.get(entrada.clase_id) if entrada.clase_id is not None else None
        if clase is not None:
            try:
                return [(self.datos.nombre_grupo(d.grupo_id), d.parte) for d in clase.destinatarios]
            except KeyError:
                pass
        resultado = []
        for pedazo in entrada.grupos_texto.split(", "):
            coincidencia = _PARTE.match(pedazo)
            if coincidencia:
                resultado.append((coincidencia.group(1), coincidencia.group(2)))
        return resultado

    def grupos(self) -> list[str]:
        """Grupos con clases en la solución, en el orden de los datos."""
        presentes = {g for e in self.entradas for g, _ in self._grupos_de(e)}
        ordenados = [self.datos.nombre_grupo(g.id or 0) for g in self.datos.grupos]
        return [g for g in ordenados if g in presentes] + sorted(presentes - set(ordenados))

    def profesores(self) -> list[str]:
        presentes = {p for e in self.entradas for p in e.profesores}
        ordenados = [p.nombre for p in self.datos.profesores]
        return [p for p in ordenados if p in presentes] + sorted(presentes - set(ordenados))

    def espacios(self) -> list[tuple[str, int]]:
        """(tipo de espacio, nivel) con clases que lo requieren."""
        claves = {
            (tipo, e.franja.nivel_id)
            for e in self.entradas
            if (tipo := self._tipo_espacio(e)) is not None and e.franja.nivel_id is not None
        }
        return sorted(claves, key=lambda k: (k[0], k[1]))

    def _tipo_espacio(self, entrada: _Entrada) -> str | None:
        clase = self.clases.get(entrada.clase_id) if entrada.clase_id is not None else None
        if clase is None:
            return None
        asignatura = por_id(self.datos.asignaturas).get(clase.asignatura_id)
        return clase.espacio_efectivo(asignatura) if asignatura else None

    def nombre_nivel(self, nivel_id: int | None) -> str:
        nivel = self.niveles.get(nivel_id) if nivel_id is not None else None
        return nivel.nombre if nivel else "Nivel eliminado"

    # ------------------------------------------------------------------ filas

    def _filas_nivel(self, nivel_id: int | None) -> tuple[list[Dia], list[Fila], dict[int, int]]:
        """Días, filas (franjas y recesos) y `índice de franja → fila` de un nivel."""
        franjas = [f for f in self.solucion.franjas if f.nivel_id == nivel_id]
        dias = [d for d in DIAS if any(f.dia == d for f in franjas)]
        if not dias:
            return [], [], {}
        modelo = sorted((f for f in franjas if f.dia == dias[0]), key=lambda f: f.indice)
        filas: list[Fila] = []
        posicion: dict[int, int] = {}
        for anterior, franja in zip([None, *modelo], modelo, strict=False):
            if anterior is not None and franja.inicio > anterior.fin:
                filas.append(Fila(anterior.fin, franja.inicio, receso=True))
            posicion[franja.indice] = len(filas)
            filas.append(Fila(franja.inicio, franja.fin))
        return dias, filas, posicion

    def _celdas_receso(self, filas: list[Fila], dias: list[Dia]) -> list[Celda]:
        return [
            Celda(i, 0, ["Receso"], GRIS_RECESO, "receso", columnas=len(dias))
            for i, fila in enumerate(filas)
            if fila.receso
        ]

    def _celda(
        self, fila: int, columna: int, entradas: list[_Entrada], lineas: list[str], filas: int = 1
    ) -> Celda:
        claves = {(e.clase_id, e.indice_franja) for e in entradas}
        return Celda(
            fila,
            columna,
            lineas,
            entradas[0].color,
            filas=filas,
            bloqueada=any(e.bloqueada for e in entradas),
            cambiada=bool(claves & self.cambiadas),
            conflicto=bool(claves & self.conflictos),
        )

    # ------------------------------------------------------------------ vistas

    def por_grupo(self, nombre: str) -> Cuadricula:
        propias: list[tuple[_Entrada, str | None]] = []
        for e in self.entradas:
            for grupo, parte in self._grupos_de(e):
                if grupo == nombre:
                    propias.append((e, parte))
        nivel_id = self._nivel_grupo(nombre, [e for e, _ in propias])
        dias, filas, posicion = self._filas_nivel(nivel_id)
        cuadricula = Cuadricula(nombre, dias, filas, self._celdas_receso(filas, dias),
                                self.nombre_nivel(nivel_id))  # fmt: skip
        por_celda: dict[tuple[int, int], list[tuple[_Entrada, str | None]]] = defaultdict(list)
        for e, parte in propias:
            if e.franja.dia in dias and e.franja.indice in posicion:
                por_celda[(posicion[e.franja.indice], dias.index(e.franja.dia))].append((e, parte))
        for (fila, columna), lista in sorted(por_celda.items()):
            lineas: list[str] = []
            ordenadas = sorted(lista, key=lambda x: (x[1] or "", x[0].asignatura))
            for e, parte in ordenadas:
                titulo = e.asignatura + (f" ({parte})" if parte else "")
                profesores = ", ".join(e.profesores)
                if len(ordenadas) > 1:  # varias clases (partes de una división): una línea c/u
                    lineas.append(f"{titulo} · {profesores}" if profesores else titulo)
                else:
                    lineas.extend([titulo, profesores] if profesores else [titulo])
            cuadricula.celdas.append(self._celda(fila, columna, [e for e, _ in lista], lineas))
        return cuadricula

    def _nivel_grupo(self, nombre: str, entradas: list[_Entrada]) -> int | None:
        for grupo in self.datos.grupos:
            if self.datos.nombre_grupo(grupo.id or 0) == nombre:
                return self.datos.nivel_de_grupo(grupo.id or 0).id
        return entradas[0].franja.nivel_id if entradas else None

    def por_profesor(self, nombre: str) -> Cuadricula:
        propias = [e for e in self.entradas if nombre in e.profesores]
        niveles = {e.franja.nivel_id for e in propias}
        if len(niveles) <= 1:
            nivel_id = next(iter(niveles)) if niveles else None
            dias, filas, posicion = self._filas_nivel(nivel_id)
            cuadricula = Cuadricula(nombre, dias, filas, self._celdas_receso(filas, dias),
                                    self.nombre_nivel(nivel_id))  # fmt: skip
            por_celda: dict[tuple[int, int], list[_Entrada]] = defaultdict(list)
            for e in propias:
                if e.franja.indice in posicion and e.franja.dia in dias:
                    por_celda[(posicion[e.franja.indice], dias.index(e.franja.dia))].append(e)
            for (fila, columna), lista in sorted(por_celda.items()):
                lineas = (
                    [x for e in lista for x in (e.asignatura, e.grupos_texto)]
                    if len(lista) == 1
                    else [f"{e.asignatura} · {e.grupos_texto}" for e in lista]
                )
                cuadricula.celdas.append(self._celda(fila, columna, lista, lineas))
            return cuadricula
        return self._por_profesor_rejilla(nombre, propias, niveles)

    def _por_profesor_rejilla(
        self, nombre: str, propias: list[_Entrada], niveles: set[int | None]
    ) -> Cuadricula:
        franjas = [f for f in self.solucion.franjas if f.nivel_id in niveles]
        dias = [d for d in DIAS if any(f.dia == d for f in franjas)]
        limites = {x for f in franjas for x in (f.inicio, f.fin)}
        delta = max(5, reduce(gcd, limites, 0))
        inicio = min(f.inicio for f in franjas)
        fin = max(f.fin for f in franjas)
        filas = [Fila(t, t + delta) for t in range(inicio, fin, delta)]
        subtitulo = ", ".join(self.nombre_nivel(n) for n in sorted(niveles, key=lambda n: n or 0))
        cuadricula = Cuadricula(nombre, dias, filas, [], f"{subtitulo} (rejilla de {delta} min)")
        por_celda: dict[tuple[int, int, int], list[_Entrada]] = defaultdict(list)
        for e in propias:
            fila = (e.franja.inicio - inicio) // delta
            alto = max(1, (e.franja.fin - e.franja.inicio) // delta)
            por_celda[(fila, dias.index(e.franja.dia), alto)].append(e)
        for (fila, columna, alto), lista in sorted(por_celda.items()):
            lineas = [x for e in lista for x in (e.asignatura, e.grupos_texto)]
            cuadricula.celdas.append(self._celda(fila, columna, lista, lineas, filas=alto))
        return cuadricula

    def por_espacio(self, tipo: str, nivel_id: int) -> Cuadricula:
        dias, filas, posicion = self._filas_nivel(nivel_id)
        cuadricula = Cuadricula(f"Espacio «{tipo}»", dias, filas, self._celdas_receso(filas, dias),
                                self.nombre_nivel(nivel_id))  # fmt: skip
        por_celda: dict[tuple[int, int], list[_Entrada]] = defaultdict(list)
        for e in self.entradas:
            if e.franja.nivel_id == nivel_id and self._tipo_espacio(e) == tipo:
                por_celda[(posicion[e.franja.indice], dias.index(e.franja.dia))].append(e)
        for (fila, columna), lista in sorted(por_celda.items()):
            lineas = [f"{e.grupos_texto} ({e.asignatura})" for e in lista]
            cuadricula.celdas.append(self._celda(fila, columna, lista, lineas))
        return cuadricula
