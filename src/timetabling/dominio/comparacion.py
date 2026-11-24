"""Creado con Claude.

Comparación de dos horarios guardados (§13.4). Por cada clase se emparejan las ocurrencias de
ambos horarios resolviendo un problema de asignación de costo mínimo: 0 = igual, 1 = solo cambia
el profesor, 2 = cambia la hora, 3 = cambian ambas. Lo que queda sin pareja se informa como
clase agregada o quitada.

Las clases se identifican por `clase_id`; si la clase se borró, por asignatura y grupos (las
copias desnormalizadas). Las horas se comparan en tiempo real (día, inicio y fin), así que la
comparación funciona aunque uno de los horarios esté desactualizado.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from timetabling.dominio.modelos import Solucion
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango

TipoCambio = Literal["igual", "profesor", "hora", "ambos", "agregada", "quitada"]
CostosCambio = {"igual": 0, "profesor": 1, "hora": 2, "ambos": 3}
DESCRIPCION: dict[TipoCambio, str] = {
    "igual": "Sin cambios",
    "profesor": "Cambia el profesor",
    "hora": "Cambia la hora",
    "ambos": "Cambian la hora y el profesor",
    "agregada": "Clase agregada",
    "quitada": "Clase quitada",
}

Clave = tuple[str, object, object]


@dataclass(frozen=True)
class Ocurrencia:
    dia: str
    inicio: int
    fin: int
    profesores: tuple[str, ...]
    clase_id: int | None
    indice_franja: int

    def texto(self) -> str:
        quienes = f" ({', '.join(self.profesores)})" if self.profesores else ""
        return f"{NOMBRES_DIAS[self.dia]} {texto_rango(self.inicio, self.fin)}{quienes}"  # type: ignore[index]

    @property
    def hora(self) -> tuple[str, int, int]:
        return (self.dia, self.inicio, self.fin)


@dataclass(frozen=True)
class CambioClase:
    clase: str
    tipo: TipoCambio
    antes: Ocurrencia | None
    despues: Ocurrencia | None

    @property
    def descripcion(self) -> str:
        return DESCRIPCION[self.tipo]


@dataclass
class Comparacion:
    cambios: list[CambioClase] = field(default_factory=list)
    """Solo las diferencias (no incluye las ocurrencias iguales)."""
    clases_afectadas: int = 0
    profesores_afectados: set[str] = field(default_factory=set)

    @property
    def sin_cambios(self) -> bool:
        return not self.cambios

    def marcas(self) -> set[tuple[int | None, int]]:
        """(clase_id, índice de franja) del horario nuevo que cambiaron (para ↻)."""
        return {
            (c.despues.clase_id, c.despues.indice_franja)
            for c in self.cambios
            if c.despues is not None
        }

    def resumen(self) -> str:
        if self.sin_cambios:
            return "Sin cambios."
        return (
            f"{self.clases_afectadas} clases y {len(self.profesores_afectados)} profesores "
            f"afectados ({len(self.cambios)} cambios)."
        )


def costo(a: Ocurrencia, b: Ocurrencia) -> int:
    misma_hora = a.hora == b.hora
    mismos = set(a.profesores) == set(b.profesores)
    if misma_hora:
        return 0 if mismos else 1
    return 2 if mismos else 3


def tipo_de(a: Ocurrencia, b: Ocurrencia) -> TipoCambio:
    return ("igual", "profesor", "hora", "ambos")[costo(a, b)]  # type: ignore[return-value]


def asignacion_minima(costos: list[list[float]]) -> list[tuple[int, int]]:
    """Asignación de costo mínimo (método húngaro, O(n³)) para una matriz rectangular.
    Devuelve las parejas `(fila, columna)`; con más filas que columnas, sobran filas."""
    filas = len(costos)
    columnas = len(costos[0]) if filas else 0
    if not filas or not columnas:
        return []
    transpuesta = filas > columnas
    matriz = [list(fila) for fila in zip(*costos, strict=True)] if transpuesta else costos
    n, m = len(matriz), len(matriz[0])
    infinito = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    pareja = [0] * (m + 1)  # pareja[j] = fila asignada a la columna j (1-indexado)
    camino = [0] * (m + 1)
    for i in range(1, n + 1):
        pareja[0] = i
        j0 = 0
        minimos = [infinito] * (m + 1)
        usados = [False] * (m + 1)
        while True:
            usados[j0] = True
            i0 = pareja[j0]
            delta = infinito
            j1 = 0
            for j in range(1, m + 1):
                if usados[j]:
                    continue
                actual = matriz[i0 - 1][j - 1] - u[i0] - v[j]
                if actual < minimos[j]:
                    minimos[j] = actual
                    camino[j] = j0
                if minimos[j] < delta:
                    delta = minimos[j]
                    j1 = j
            for j in range(m + 1):
                if usados[j]:
                    u[pareja[j]] += delta
                    v[j] -= delta
                else:
                    minimos[j] -= delta
            j0 = j1
            if pareja[j0] == 0:
                break
        while j0:
            j1 = camino[j0]
            pareja[j0] = pareja[j1]
            j0 = j1
    resultado = [(pareja[j] - 1, j - 1) for j in range(1, m + 1) if pareja[j]]
    if transpuesta:
        resultado = [(c, f) for f, c in resultado]
    return sorted(resultado)


def _clave(clase_id: int | None, asignatura: str, grupos: str) -> Clave:
    return ("id", clase_id, None) if clase_id is not None else ("texto", asignatura, grupos)


def ocurrencias(solucion: Solucion) -> dict[Clave, tuple[str, list[Ocurrencia]]]:
    """Por clase: su texto y sus ocurrencias (una por franja, con todos sus profesores)."""
    agrupadas: dict[tuple[Clave, int], list[str]] = defaultdict(list)
    textos: dict[Clave, str] = {}
    ids: dict[Clave, int | None] = {}
    for a in solucion.asignaciones:
        clave = _clave(a.clase_id, a.asignatura_nombre, a.grupos_texto)
        textos[clave] = f"{a.asignatura_nombre} · {a.grupos_texto}"
        ids[clave] = a.clase_id
        lista = agrupadas[(clave, a.franja)]
        if a.profesor_nombre:
            lista.append(a.profesor_nombre)
    resultado: dict[Clave, tuple[str, list[Ocurrencia]]] = {}
    orden = sorted(agrupadas.items(), key=lambda x: (str(x[0][0]), x[0][1]))
    for (clave, indice), profesores in orden:
        f = solucion.franjas[indice]
        resultado.setdefault(clave, (textos[clave], []))[1].append(
            Ocurrencia(f.dia, f.inicio, f.fin, tuple(sorted(profesores)), ids[clave], indice)
        )
    return resultado


def comparar(anterior: Solucion, nueva: Solucion) -> Comparacion:
    """Diferencias de `nueva` respecto a `anterior` (§13.4)."""
    viejas = ocurrencias(anterior)
    nuevas = ocurrencias(nueva)
    comparacion = Comparacion()
    afectadas: set[Clave] = set()
    for clave in sorted(set(viejas) | set(nuevas), key=str):
        texto = (nuevas.get(clave) or viejas[clave])[0]
        antes = viejas.get(clave, (texto, []))[1]
        despues = nuevas.get(clave, (texto, []))[1]
        previos = len(comparacion.cambios)
        emparejadas: list[tuple[int, int]] = []
        if antes and despues:
            emparejadas = asignacion_minima([[costo(a, d) for d in despues] for a in antes])
        usadas_a = {i for i, _ in emparejadas}
        usadas_d = {j for _, j in emparejadas}
        for i, j in emparejadas:
            tipo = tipo_de(antes[i], despues[j])
            if tipo != "igual":
                comparacion.cambios.append(CambioClase(texto, tipo, antes[i], despues[j]))
        for i, a in enumerate(antes):
            if i not in usadas_a:
                comparacion.cambios.append(CambioClase(texto, "quitada", a, None))
        for j, d in enumerate(despues):
            if j not in usadas_d:
                comparacion.cambios.append(CambioClase(texto, "agregada", None, d))
        if len(comparacion.cambios) > previos:
            afectadas.add(clave)
    for cambio in comparacion.cambios:
        for o in (cambio.antes, cambio.despues):
            if o is not None:
                comparacion.profesores_afectados.update(o.profesores)
    comparacion.clases_afectadas = len(afectadas)
    return comparacion
