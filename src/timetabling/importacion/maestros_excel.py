"""Creado con Claude.

Cuadro de maestros (§15.2). Un bloque de horario por maestro: el nombre encima de la fila de
días y la columna de horas a la izquierda. Cada celda dice qué da a esa hora: «ESPAÑOL 3A»,
«Math PPA», «2A (8:00-8:45)»… Si solo trae el grupo se usa la asignatura más frecuente del
maestro; si solo trae la asignatura, el único grupo posible (un grado de un solo grupo).

Crea o completa profesores (asignaturas, grados; disponibles toda la jornada) y fija el
profesor de las clases. Con «Importar también los horarios como borrador», cada celda se
coloca en la franja de mayor traslape de su nivel; las que no se pueden colocar se listan.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from timetabling.dominio.clases import grupos_de_clase
from timetabling.dominio.modelos import DatosEscuela, Grupo, Profesor, por_id
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.importacion.comun import Ids, Resultado, destino_inicial, sincronizar_clases
from timetabling.importacion.textos import (
    RECESOS_POR_DEFECTO,
    TUTORIAS_POR_DEFECTO,
    clave,
    clave_maestro,
    contiene,
    dia_de,
    limpio,
    nombre_maestro,
    nombres_grado,
    rango,
    rango_dentro,
)
from timetabling.nucleo.franjas import generar_franjas

SIN_PROFESOR = ("biblioteca", "library")
_GRUPO = re.compile(r"(?<![A-Za-z0-9])(PP|K|\d{1,2})\s*[°º]?\s*([A-H])(?![A-Za-z0-9])", re.I)
_HORAS = re.compile(r"\(?\s*\d{1,2}:\d{2}\s*[-–a]\s*\d{1,2}:\d{2}\s*\)?")

# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CeldaMaestro:
    dia: str
    inicio: int | None
    fin: int | None
    texto: str


@dataclass
class BloqueMaestro:
    nombre: str
    celdas: list[CeldaMaestro] = field(default_factory=list)

    @property
    def clave(self) -> str:
        return clave_maestro(re.sub(r"\(.*?\)", "", self.nombre))


def leer_hoja(filas: list[list[object]]) -> list[BloqueMaestro]:
    ancho = max((len(f) for f in filas), default=0)
    filas = [list(f) + [None] * (ancho - len(f)) for f in filas]

    def encabezado(i: int, j: int) -> bool:
        return 0 <= i < len(filas) and any(dia_de(filas[i][k]) == "L" for k in range(j, ancho))

    bloques: list[BloqueMaestro] = []
    for i, fila in enumerate(filas):
        for j, celda in enumerate(fila):
            if dia_de(celda) != "L":
                continue
            dias = {k: d for k in range(j, min(j + 7, ancho)) if (d := dia_de(fila[k]))}
            nombre = ""
            for arriba in (i - 1, i - 2):
                if arriba >= 0:
                    nombre = next((limpio(filas[arriba][k]) for k in dias
                                   if limpio(filas[arriba][k])), "")  # fmt: skip
                if nombre:
                    break
            bloque = BloqueMaestro(nombre)
            for k in range(i + 1, len(filas)):
                # Termina donde empieza el siguiente bloque (su nombre va una fila arriba).
                if encabezado(k, j) or encabezado(k + 1, j):
                    break
                horas = rango(filas[k][j - 1]) if j > 0 else None
                for c, dia in dias.items():
                    texto = limpio(filas[k][c])
                    if not texto:
                        continue
                    propias = horas or rango_dentro(texto)
                    inicio, fin = propias if propias else (None, None)
                    bloque.celdas.append(CeldaMaestro(dia, inicio, fin, texto))
            bloques.append(bloque)
    return bloques


def leer_libro(ruta: str | Path) -> list[BloqueMaestro]:
    libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    try:
        filas = [[list(f) for f in hoja.iter_rows(values_only=True)] for hoja in libro.worksheets]
        return [b for hoja in filas for b in leer_hoja(hoja)]
    finally:
        libro.close()


@dataclass(frozen=True)
class CeldaLeida:
    asignatura: str
    """Texto de la asignatura ('' si la celda solo trae el grupo)."""
    grupos: tuple[tuple[str, str], ...]
    """(grado, sección) escritos: («3», «A»), («PP», «B»), («K», «A»)."""


def interpretar(texto: str) -> CeldaLeida:
    grupos = tuple((g.upper(), s.upper()) for g, s in _GRUPO.findall(texto))
    resto = _GRUPO.sub(" ", texto)
    resto = _HORAS.sub(" ", resto)
    resto = " ".join(re.sub(r"[(),]", " ", resto).split()).strip(" -/")
    return CeldaLeida(resto, grupos)


# ---------------------------------------------------------------------------
# Mapeo editable
# ---------------------------------------------------------------------------


@dataclass
class MapeoMaestros:
    maestros: dict[str, str] = field(default_factory=dict)
    """Nombre del bloque → nombre del profesor ('' = no es un maestro, se omite)."""
    asignaturas: dict[str, str] = field(default_factory=dict)
    """Texto de la celda → asignatura existente ('' = no es clase)."""
    recesos: list[str] = field(default_factory=lambda: list(RECESOS_POR_DEFECTO))
    tutorias: list[str] = field(default_factory=lambda: list(TUTORIAS_POR_DEFECTO))
    con_horarios: bool = False


def mapeo_inicial(datos: DatosEscuela, bloques: list[BloqueMaestro]) -> MapeoMaestros:
    mapeo = MapeoMaestros()
    existentes = {clave_maestro(p.nombre): p.nombre for p in datos.profesores}
    for b in bloques:
        if not b.nombre or b.nombre in mapeo.maestros:
            continue
        if contiene(b.nombre, SIN_PROFESOR):
            mapeo.maestros[b.nombre] = ""
            continue
        mapeo.maestros[b.nombre] = existentes.get(b.clave) or nombre_maestro(
            re.sub(r"\(.*?\)", "", b.nombre)
        )
    asignaturas = {clave(a.nombre) for a in datos.asignaturas}
    for b in bloques:
        for c in b.celdas:
            if contiene(c.texto, mapeo.recesos) or contiene(c.texto, mapeo.tutorias):
                continue
            texto = interpretar(c.texto).asignatura
            if texto and texto not in mapeo.asignaturas:
                sugerida = destino_inicial(datos, texto)
                mapeo.asignaturas[texto] = sugerida if clave(sugerida) in asignaturas else ""
    return mapeo


# ---------------------------------------------------------------------------
# Aplicar
# ---------------------------------------------------------------------------


@dataclass
class ResultadoMaestros(Resultado):
    colocaciones: list[tuple[int, str, tuple[int, ...]]] = field(default_factory=list)
    """(clase, franja, profesores) del borrador, si se pidió importar los horarios."""
    sin_colocar: list[str] = field(default_factory=list)


def _grado_de(datos: DatosEscuela, token: str) -> list[int]:
    if token == "PP":
        return [g.id for g in datos.grados if g.id is not None and "prepa" in clave(g.nombre)]
    if token == "K":
        return [g.id for g in datos.grados if g.id is not None and clave(g.nombre).startswith("k")]
    return [g.id for g in datos.grados if g.id is not None and token in nombres_grado(g.nombre)]


def _grupo(datos: DatosEscuela, token: tuple[str, str]) -> Grupo | None:
    grados = _grado_de(datos, token[0])
    candidatos = [g for g in datos.grupos if g.grado_id in grados
                  and clave(g.seccion) == clave(token[1])]  # fmt: skip
    return candidatos[0] if len(candidatos) == 1 else None


def aplicar(
    datos: DatosEscuela, bloques: list[BloqueMaestro], mapeo: MapeoMaestros
) -> ResultadoMaestros:
    datos = datos.model_copy(deep=True)
    resultado = ResultadoMaestros(datos)
    ids = Ids(datos)
    sincronizar_clases(datos, ids, resultado)
    asignaturas = {clave(a.nombre): a for a in datos.asignaturas}
    asig_por_id = por_id(datos.asignaturas)
    grupos = por_id(datos.grupos)
    plan = {(p.grado_id, p.asignatura_id): p.horas_semanales for p in datos.plan}
    por_grado: dict[int, list[Grupo]] = defaultdict(list)
    for g in datos.grupos:
        por_grado[g.grado_id].append(g)

    nombres: dict[str, str] = {}  # clave del maestro → nombre del profesor
    sesiones: dict[str, Counter[tuple[int, int]]] = defaultdict(Counter)
    celdas_ok: list[tuple[str, int, int, CeldaMaestro]] = []  # maestro, grupo, asignatura, celda
    no_resueltas: Counter[str] = Counter()
    otras: Counter[str] = Counter()
    tutorias = 0
    for bloque in bloques:
        destino = mapeo.maestros.get(bloque.nombre, "")
        if not destino or not bloque.celdas:
            continue
        k = clave_maestro(destino)
        nombres.setdefault(k, destino)
        leidas = []
        for c in bloque.celdas:
            if contiene(c.texto, mapeo.recesos):
                continue
            if contiene(c.texto, mapeo.tutorias):
                tutorias += 1
                continue
            leidas.append((c, interpretar(c.texto)))
        conocidas = Counter(
            mapeo.asignaturas.get(x.asignatura, "") for _, x in leidas if x.grupos and x.asignatura
        )
        conocidas.pop("", None)
        principal = conocidas.most_common(1)[0][0] if conocidas else ""
        for c, x in leidas:
            nombre = mapeo.asignaturas.get(x.asignatura, "") if x.asignatura else principal
            asignatura = asignaturas.get(clave(nombre)) if nombre else None
            if asignatura is None or asignatura.id is None:
                if x.grupos:
                    no_resueltas[f"{destino}: «{c.texto}»"] += 1
                else:
                    otras[f"{destino}: {c.texto}"] += 1
                continue
            if x.grupos:
                destinos = [_grupo(datos, t) for t in x.grupos]
            else:
                # Sin grupo: el de un grado de un solo grupo que tenga la asignatura.
                unicos = [gs[0] for gid, gs in por_grado.items()
                          if len(gs) == 1 and (gid, asignatura.id) in plan]  # fmt: skip
                destinos = [unicos[0] if len(unicos) == 1 else None]
            for grupo in destinos:
                if grupo is None or grupo.id is None:
                    no_resueltas[f"{destino}: «{c.texto}» (grupo no reconocido)"] += 1
                    continue
                if (grupo.grado_id, asignatura.id) not in plan:
                    no_resueltas[f"{destino}: «{c.texto}» ({asignatura.nombre} no está en el "
                                 f"plan de {datos.nombre_grupo(grupo.id)})"] += 1  # fmt: skip
                    continue
                sesiones[k][(grupo.id, asignatura.id)] += 1
                celdas_ok.append((k, grupo.id, asignatura.id, c))
    if tutorias:
        resultado.avisos.append(f"Se omitieron {tutorias} celdas de tutoría.")

    # Cada (grupo, asignatura) queda con el maestro que más sesiones da de ella.
    candidatos: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for k, conteo in sesiones.items():
        for par, n in conteo.items():
            candidatos[par].append((n, k))
    elegido: dict[tuple[int, int], str] = {}
    for par, lista in sorted(candidatos.items()):
        lista.sort(key=lambda t: (-t[0], nombres[t[1]]))
        elegido[par] = lista[0][1]
        if len(lista) > 1:
            detalle = ", ".join(f"{nombres[m]} ({n})" for n, m in lista)
            resultado.avisos.append(
                f"{asig_por_id[par[1]].nombre} en {datos.nombre_grupo(par[0])} la dan varios "
                f"maestros ({detalle}); se asigna a {nombres[lista[0][1]]}."
            )

    # Profesores: se crean o se completan (sin quitar lo que tenían).
    existentes = {clave_maestro(p.nombre): p for p in datos.profesores}
    ids_prof: dict[str, int] = {}
    nuevos: list[str] = []
    actualizados: list[str] = []
    for k in sorted(sesiones, key=lambda m: nombres[m]):
        pares = list(sesiones[k])
        asigs = sorted({a for _, a in pares})
        grados = sorted({grupos[g].grado_id for g, _ in pares})
        actual = existentes.get(k)
        if actual is None:
            actual = Profesor(id=ids.nuevo("profesores"), nombre=nombres[k], asignaturas=asigs,
                              grados=grados)  # fmt: skip
            datos.profesores.append(actual)
            nuevos.append(actual.nombre)
        else:
            faltan_a = [a for a in asigs if a not in actual.asignaturas]
            faltan_g = [g for g in grados if g not in actual.grados]
            if faltan_a or faltan_g:
                actual.asignaturas = [*actual.asignaturas, *faltan_a]
                actual.grados = [*actual.grados, *faltan_g]
                actualizados.append(actual.nombre)
            if not actual.activo:
                actual.activo = True
                actualizados.append(f"{actual.nombre} (se reactiva)")
        assert actual.id is not None
        ids_prof[k] = actual.id
    if nuevos:
        resultado.resumen.append("Profesores nuevos: " + ", ".join(nuevos))
    if actualizados:
        resultado.resumen.append("Profesores completados: " + ", ".join(actualizados))

    # Profesor fijo de cada clase: el elegido de sus grupos (si es el mismo para todos).
    fijadas = 0
    for clase in datos.clases:
        if clase.id is None:
            continue
        elegidos = {elegido.get((g, clase.asignatura_id)) for g in grupos_de_clase(clase)}
        if len(elegidos) == 1 and None not in elegidos:
            profesor = ids_prof[elegidos.pop()]  # type: ignore[index]
            if clase.profesores != [profesor]:
                clase.profesores = [profesor]
                fijadas += 1
    if fijadas:
        resultado.resumen.append(f"Clases con profesor fijo: {fijadas}")

    # Comparación con el plan de estudios.
    for grupo in sorted(datos.grupos, key=lambda g: (g.grado_id, g.seccion)):
        for (grado_id, asignatura_id), horas in sorted(plan.items()):
            if grado_id != grupo.grado_id or grupo.id is None:
                continue
            nombre = f"{asig_por_id[asignatura_id].nombre} en {datos.nombre_grupo(grupo.id)}"
            if (grupo.id, asignatura_id) not in elegido:
                resultado.avisos.append(f"{nombre}: ningún maestro la tiene en el cuadro.")
                continue
            dadas = sum(s[(grupo.id, asignatura_id)] for s in sesiones.values())
            if dadas != horas:
                resultado.avisos.append(
                    f"{nombre}: el plan pide {horas} h/semana y el cuadro tiene {dadas}."
                )
    for texto, n in sorted(no_resueltas.items()):
        resultado.avisos.append(
            f"Celda no reconocida — {texto}" + (f" ({n} veces)" if n > 1 else "")
        )
    for texto, n in sorted(otras.items()):
        resultado.avisos.append(f"No es una clase (se omite) — {texto}"
                                + (f" ({n} veces)" if n > 1 else ""))  # fmt: skip

    if mapeo.con_horarios:
        _horarios(datos, celdas_ok, ids_prof, resultado)
    return resultado


def _horarios(
    datos: DatosEscuela,
    celdas: list[tuple[str, int, int, CeldaMaestro]],
    ids_prof: dict[str, int],
    resultado: ResultadoMaestros,
) -> None:
    """Cada celda a la franja de mayor traslape de su nivel (§15.2)."""
    franjas_nivel = {n.id: generar_franjas(n) for n in datos.niveles if n.id is not None}
    clase_de: dict[tuple[int, int], int] = {}
    for clase in datos.clases:
        for g in grupos_de_clase(clase):
            if clase.id is not None:
                clase_de.setdefault((g, clase.asignatura_id), clase.id)
    colocaciones: dict[tuple[int, str], set[int]] = defaultdict(set)
    asignaturas = por_id(datos.asignaturas)
    for k, grupo_id, asignatura_id, celda in celdas:
        descripcion = (f"{asignaturas[asignatura_id].nombre} {datos.nombre_grupo(grupo_id)} "
                       f"({NOMBRES_DIAS[celda.dia]}")  # type: ignore[index]  # fmt: skip
        if celda.inicio is None or celda.fin is None:
            resultado.sin_colocar.append(descripcion + ", sin hora)")
            continue
        descripcion += f" {texto_rango(celda.inicio, celda.fin)})"
        nivel = datos.nivel_de_grupo(grupo_id)
        traslapes = [
            (min(f.fin, celda.fin) - max(f.inicio, celda.inicio), -f.indice, f)
            for f in franjas_nivel.get(nivel.id, [])
            if f.dia == celda.dia
        ]
        mejor = max(traslapes, default=None, key=lambda t: (t[0], t[1]))
        clase_id = clase_de.get((grupo_id, asignatura_id))
        if mejor is None or mejor[0] <= 0 or clase_id is None:
            resultado.sin_colocar.append(descripcion)
            continue
        colocaciones[(clase_id, mejor[2].id)].add(ids_prof[k])
    resultado.colocaciones = sorted((c, f, tuple(sorted(p))) for (c, f), p in colocaciones.items())
    resultado.resumen.append(f"Borrador con los horarios del cuadro: {len(colocaciones)} clases")
    if resultado.sin_colocar:
        resultado.avisos.append(
            f"{len(resultado.sin_colocar)} celdas no se pudieron colocar en una franja: "
            + "; ".join(resultado.sin_colocar[:10])
            + ("…" if len(resultado.sin_colocar) > 10 else "")
        )
