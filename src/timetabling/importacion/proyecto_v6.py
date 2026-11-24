"""Creado con Claude.

Proyecto de la versión anterior (esquema v6, §15.3). Lee un `.horario` v6 (también las
versiones 1–5 de ese esquema, a las que les faltan tablas o columnas) y lo convierte a los
datos de la v2. Las soluciones y las asignaciones fijas se devuelven como colocaciones; el
servicio las guarda como `Solucion` con su instantánea de franjas.
"""

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from timetabling.dominio.modelos import (
    CRITERIOS,
    MULTIPLICADORES,
    PERFILES,
    Asignatura,
    Clase,
    Configuracion,
    Criterios,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Espacio,
    EstadoSolucion,
    Evento,
    EventoProfesor,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    RangoFranjas,
    Receso,
    ReglasAsignatura,
    ReglasAsignaturaNivel,
    por_id,
)
from timetabling.importacion.textos import clave
from timetabling.nucleo.franjas import generar_franjas

# Pesos v6 → criterios v2 (B9 «cambios_vigente» no se importa: es fijo en la v2).
PESOS_V6 = {
    "huecos_profesor": "B1", "distribucion_semanal": "B2", "exigente_tarde": "B3",
    "preferible_no": "B4", "dias_profesor": "B5", "desequilibrio_carga": "B6",
    "titular_preescolar": "B7", "bloque_doble_preferido": "B8",
}  # fmt: skip
PESOS_V6_POR_DEFECTO = {
    "huecos_profesor": 10, "distribucion_semanal": 8, "exigente_tarde": 3, "preferible_no": 6,
    "dias_profesor": 2, "desequilibrio_carga": 1, "titular_preescolar": 5,
    "bloque_doble_preferido": 4,
}  # fmt: skip


class ErrorV6(ValueError):
    """El archivo no es un proyecto v6 legible."""


@dataclass
class SolucionV6:
    nombre: str
    fecha: datetime
    estado: EstadoSolucion
    tiempo_s: float
    nota: str
    vigente: bool
    colocaciones: list[tuple[int, str, tuple[int, ...], bool]] = field(default_factory=list)
    """(clase, franja, profesores, bloqueada)."""
    omitidas: int = 0


@dataclass
class ImportacionV6:
    datos: DatosEscuela
    soluciones: list[SolucionV6] = field(default_factory=list)
    importado: list[str] = field(default_factory=list)
    """Renglones del informe: qué se importó."""
    no_importado: list[str] = field(default_factory=list)
    version: int = 6


def es_v6(ruta: str | Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{Path(ruta)}?mode=ro", uri=True)
        try:
            tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master")}
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False
    return "esquema_version" in tablas and "metadatos" not in tablas


class _Lector:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.tablas = {
            f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    def filas(self, tabla: str, orden: str = "rowid") -> list[dict[str, Any]]:
        if tabla not in self.tablas:
            return []
        cursor = self.con.execute(f"SELECT * FROM {tabla} ORDER BY {orden}")
        columnas = [d[0] for d in cursor.description]
        return [dict(zip(columnas, f, strict=True)) for f in cursor.fetchall()]


def criterios_de(pesos: dict[str, Any]) -> tuple[Criterios, str]:
    """Perfil más cercano a los pesos v6 (por el ángulo entre vectores) y los pesos v6 como
    pesos avanzados. B10 no existía: recibe el peso equivalente al del perfil elegido."""
    v6 = {c: float(pesos.get(k, PESOS_V6_POR_DEFECTO[k])) for k, c in PESOS_V6.items()}
    claves = list(v6)

    def coseno(perfil: str) -> float:
        p = [MULTIPLICADORES[PERFILES[perfil][c]] for c in claves]  # type: ignore[index]
        a = [v6[c] for c in claves]
        norma = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in p))
        return sum(x * y for x, y in zip(a, p, strict=True)) / norma if norma else 0.0

    perfil = max(("equilibrado", "profesores", "alumnos"), key=coseno)
    multiplicadores = PERFILES[perfil]  # type: ignore[index]
    escala = sum(v6.values()) / max(1, sum(MULTIPLICADORES[multiplicadores[c]] for c in claves))
    avanzados = {**v6, "B10": round(MULTIPLICADORES[multiplicadores["B10"]] * escala, 2)}
    criterios = Criterios.de_perfil(perfil)  # type: ignore[arg-type]
    criterios.pesos_avanzados = {c: avanzados[c] for c in CRITERIOS}
    return criterios, perfil


def contar(n: int, singular: str, plural: str = "") -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _mitad(nivel: Nivel) -> int:
    return nivel.inicio_jornada + ((nivel.fin_jornada - nivel.inicio_jornada) // 2) // 5 * 5


def leer(ruta: str | Path) -> ImportacionV6:
    if not es_v6(ruta):
        raise ErrorV6("El archivo no es un proyecto de la versión anterior (esquema v6).")
    con = sqlite3.connect(f"file:{Path(ruta)}?mode=ro", uri=True)
    try:
        return _convertir(_Lector(con))
    finally:
        con.close()


def _convertir(lector: _Lector) -> ImportacionV6:  # noqa: C901
    version_fila = lector.filas("esquema_version")
    version = int(version_fila[0]["version"]) if version_fila else 0
    datos = DatosEscuela()
    resultado = ImportacionV6(datos, version=version)
    imp, no = resultado.importado, resultado.no_importado

    # Configuración.
    config = (lector.filas("configuracion") or [{}])[0]
    criterios, perfil = criterios_de(json.loads(config.get("pesos") or "{}"))
    datos.configuracion = Configuracion(
        nombre_escuela=config.get("nombre_escuela") or "Mi escuela",
        margen_traslado_min=min(120, int(config.get("margen_traslado_min") or 0)),
        tiempo_limite_s=max(1, int(config.get("tiempo_limite_s") or 300)),
        hilos=max(1, int(config.get("hilos") or 1)),
        criterios=criterios,
    )
    imp.append(f"Configuración: perfil «{perfil}» (el más cercano a los pesos anteriores, que se "
               "guardan también como pesos avanzados)")  # fmt: skip

    # Niveles, recesos y eventos.
    recesos: dict[int, list[Receso]] = defaultdict(list)
    for r in lector.filas("recesos", "inicio"):
        recesos[r["nivel_id"]].append(Receso(nombre=r["nombre"], inicio=r["inicio"], fin=r["fin"]))
    eventos_v6 = {e["id"]: e for e in lector.filas("eventos", "id")}
    eventos: dict[int, list[Evento]] = defaultdict(list)
    for e in eventos_v6.values():
        eventos[e["nivel_id"]].append(
            Evento(nombre=e["nombre"], dia=e["dia"], inicio=e["inicio"], fin=e["fin"])
        )
    for n in lector.filas("niveles", "id"):
        especiales = json.loads(n.get("duraciones_especiales") or "{}")
        datos.niveles.append(Nivel(
            id=n["id"], nombre=n["nombre"], duracion_min=n["duracion_min"],
            inicio_jornada=n["inicio_jornada"], fin_jornada=n["fin_jornada"],
            dias=[d for d in str(n["dias"]).split(",") if d],  # type: ignore[misc]
            recesos=recesos[n["id"]], eventos=eventos[n["id"]],
            duraciones_especiales={int(k): int(v) for k, v in especiales.items()},
            huecos_alumnos="prohibidos" if n.get("sin_huecos_alumnos") else "penalizar",
            preferir_titular="preescolar" in clave(n["nombre"]),
        ))  # fmt: skip
    n_recesos = sum(map(len, recesos.values()))
    imp.append(f"Niveles: {len(datos.niveles)} (con {contar(n_recesos, 'receso')} y "
               f"{contar(len(eventos_v6), 'evento')})")  # fmt: skip
    titulares = [n.nombre for n in datos.niveles if n.preferir_titular]
    if titulares:
        imp.append("«Preferir titular» activado en: " + ", ".join(titulares))

    # Grados y grupos.
    datos.grados = [Grado(id=g["id"], nivel_id=g["nivel_id"], nombre=g["nombre"])
                    for g in lector.filas("grados", "id")]  # fmt: skip
    datos.grupos = [Grupo(id=g["id"], grado_id=g["grado_id"], seccion=g["seccion"],
                          estudiantes=g.get("estudiantes") or 0, titular_id=g.get("titular_id"))
                    for g in lector.filas("grupos", "id")]  # fmt: skip
    imp.append(f"Grados: {len(datos.grados)} · grupos: {len(datos.grupos)}")

    # Plan (primero, para saber en qué niveles se da cada asignatura exigente).
    datos.plan = [PlanEstudios(grado_id=p["grado_id"], asignatura_id=p["asignatura_id"],
                               horas_semanales=p["horas_semanales"])
                  for p in lector.filas("plan_estudios") if p["horas_semanales"] > 0]  # fmt: skip
    grados = por_id(datos.grados)
    niveles = por_id(datos.niveles)
    niveles_de_asignatura: dict[int, set[int]] = defaultdict(set)
    for p in datos.plan:
        if p.grado_id in grados:
            niveles_de_asignatura[p.asignatura_id].add(grados[p.grado_id].nivel_id)

    # Asignaturas.
    exigentes = []
    for a in lector.filas("asignaturas", "id"):
        por_nivel = []
        if a.get("exigente"):
            exigentes.append(a["nombre"])
            for nivel_id in sorted(niveles_de_asignatura.get(a["id"]) or niveles):
                nivel = niveles[nivel_id]
                mitad = RangoFranjas(desde=nivel.inicio_jornada, hasta=_mitad(nivel))
                por_nivel.append(ReglasAsignaturaNivel(nivel_id=nivel_id,
                                                       franjas_preferidas=[mitad]))  # fmt: skip
        datos.asignaturas.append(Asignatura(
            id=a["id"], nombre=a["nombre"], color=a["color"],
            espacio_requerido=a.get("espacio_requerido"),
            reglas_por_defecto=ReglasAsignatura(max_horas_dia=a["max_horas_dia"],
                                                bloque_doble=a["bloque_doble"]),
            reglas_por_nivel=por_nivel,
        ))  # fmt: skip
    imp.append(f"Asignaturas: {len(datos.asignaturas)} · filas del plan: {len(datos.plan)}")
    if exigentes:
        imp.append("Exigentes → franja preferida «primera mitad de la jornada»: "
                   + ", ".join(exigentes))  # fmt: skip

    # Profesores.
    def relacion(tabla: str, columna: str) -> dict[int, list[int]]:
        r: dict[int, list[int]] = defaultdict(list)
        for f in lector.filas(tabla):
            r[f["profesor_id"]].append(f[columna])
        return r

    asignaturas_p = relacion("profesor_asignatura", "asignatura_id")
    grados_p = relacion("profesor_grado", "grado_id")
    sup_asig = relacion("profesor_suplencia_asignatura", "asignatura_id")
    sup_grado = relacion("profesor_suplencia_grado", "grado_id")
    eventos_p = relacion("profesor_evento", "evento_id")
    disponibilidad: dict[int, list[Disponibilidad]] = defaultdict(list)
    for d in lector.filas("disponibilidad", "inicio"):
        disponibilidad[d["profesor_id"]].append(
            Disponibilidad(dia=d["dia"], inicio=d["inicio"], fin=d["fin"], tipo=d["tipo"])
        )
    sin_disponibilidad = []
    for p in lector.filas("profesores", "id"):
        duracion = max((niveles[grados[g].nivel_id].duracion_min for g in grados_p[p["id"]]
                        if g in grados), default=50)  # fmt: skip
        propios = []
        for e in eventos_p[p["id"]]:
            if e in eventos_v6:
                ev = eventos_v6[e]
                nivel = niveles.get(ev["nivel_id"])
                nombre = f"{ev['nombre']} ({nivel.nombre})" if nivel else ev["nombre"]
                propios.append(EventoProfesor(nombre=nombre, dia=ev["dia"], inicio=ev["inicio"],
                                              fin=ev["fin"]))  # fmt: skip
        rangos = disponibilidad[p["id"]]
        if not rangos:
            sin_disponibilidad.append(p["nombre"])
        datos.profesores.append(Profesor(
            id=p["id"], nombre=p["nombre"],
            asignaturas=asignaturas_p[p["id"]], grados=grados_p[p["id"]],
            disponibilidad=rangos, disponible_toda_la_jornada=not rangos, eventos=propios,
            suplencia_asignaturas=sup_asig[p["id"]], suplencia_grados=sup_grado[p["id"]],
            carga_max_semanal_min=p["carga_max_semanal_min"],
            carga_max_diaria_min=p["carga_max_diaria_min"],
            max_minutos_continuos=max(5, p["max_consecutivas"] * duracion),
        ))  # fmt: skip
    imp.append(f"Profesores: {len(datos.profesores)}")
    if sin_disponibilidad:
        no.append("Sin disponibilidad guardada (se importan disponibles toda la jornada): "
                  + ", ".join(sin_disponibilidad))  # fmt: skip
    datos.espacios = [Espacio(id=e["id"], nombre=e["nombre"], tipo=e["tipo"],
                              cantidad=max(1, e["cantidad"]))
                      for e in lector.filas("espacios", "id")]  # fmt: skip
    imp.append(f"Espacios: {len(datos.espacios)}")

    # Clases: una por (grupo, asignatura) del plan, con el docente asignado como profesor fijo.
    docentes = {(d["grupo_id"], d["asignatura_id"]): d["profesor_id"]
                for d in lector.filas("docentes_asignados")}  # fmt: skip
    clase_de: dict[tuple[int, int], int] = {}
    for grupo in datos.grupos:
        for p in datos.plan:
            if p.grado_id != grupo.grado_id or grupo.id is None:
                continue
            ident = len(datos.clases) + 1
            fijo = docentes.get((grupo.id, p.asignatura_id))
            datos.clases.append(Clase(
                id=ident, asignatura_id=p.asignatura_id, horas_semanales=p.horas_semanales,
                destinatarios=[Destinatario(grupo_id=grupo.id)],
                profesores=[fijo] if fijo is not None else [], origen="plan",
            ))  # fmt: skip
            clase_de[(grupo.id, p.asignatura_id)] = ident
    imp.append(f"Clases: {len(datos.clases)} ({len(docentes)} con docente asignado)")

    franjas = {f.id for n in datos.niveles for f in generar_franjas(n)}
    nivel_de_grupo = {
        g.id: grados[g.grado_id].nivel_id for g in datos.grupos if g.grado_id in grados
    }

    def colocar(destino: SolucionV6, filas: list[dict[str, Any]], bloqueada: bool) -> None:
        agrupadas: dict[tuple[int, str], set[int]] = defaultdict(set)
        for f in filas:
            clase = clase_de.get((f["grupo_id"], f["asignatura_id"]))
            nivel = f.get("nivel_id") or nivel_de_grupo.get(f["grupo_id"])
            dia = f["dia"]
            indice = f["indice"] if "indice" in f else f["indice_franja"]
            franja = f"{nivel}:{dia}:{indice}"
            if clase is None or franja not in franjas:
                destino.omitidas += 1
                continue
            profesores = agrupadas[(clase, franja)]
            if f.get("profesor_id") is not None:
                profesores.add(f["profesor_id"])
        destino.colocaciones = sorted((c, fr, tuple(sorted(p)), bloqueada)
                                      for (c, fr), p in agrupadas.items())  # fmt: skip

    # Asignaciones fijas → borrador con clases bloqueadas.
    fijas = lector.filas("asignaciones_fijas", "id")
    if fijas:
        ahora = datetime.now().replace(microsecond=0)
        borrador = SolucionV6("Asignaciones fijas importadas", ahora,
                              EstadoSolucion.BORRADOR, 0.0,
                              "Asignaciones fijas de la versión anterior, como clases bloqueadas.",
                              False)  # fmt: skip
        colocar(borrador, fijas, True)
        resultado.soluciones.append(borrador)
        bloqueadas = contar(len(borrador.colocaciones), "clase bloqueada", "clases bloqueadas")
        imp.append(f"Asignaciones fijas: {bloqueadas} en el borrador «Asignaciones fijas "
                   "importadas»")  # fmt: skip
        if borrador.omitidas:
            no.append(f"{borrador.omitidas} asignaciones fijas sin clase o franja equivalente")

    # Soluciones.
    asignaciones: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for a in lector.filas("asignaciones", "id"):
        asignaciones[a["solucion_id"]].append(a)
    for s in lector.filas("soluciones", "id"):
        try:
            fecha = datetime.fromisoformat(s["fecha"])
        except (TypeError, ValueError):
            fecha = datetime.now().replace(microsecond=0)
        try:
            estado = EstadoSolucion(s["estado"])
        except ValueError:
            estado = EstadoSolucion.FACTIBLE
        solucion = SolucionV6(
            nombre=f"Importada del {fecha:%d/%m/%Y %H:%M}", fecha=fecha, estado=estado,
            tiempo_s=float(s.get("tiempo_s") or 0.0),
            nota=" ".join(x for x in [s.get("nota") or "", "(Versión anterior.)"] if x),
            vigente=bool(s.get("vigente")),
        )  # fmt: skip
        colocar(solucion, asignaciones[s["id"]], False)
        resultado.soluciones.append(solucion)
        if solucion.omitidas:
            no.append(f"«{solucion.nombre}»: {solucion.omitidas} asignaciones sin clase o franja "
                      "equivalente")  # fmt: skip
    horarios = [s for s in resultado.soluciones if s.estado != EstadoSolucion.BORRADOR]
    if horarios:
        vigente = next((s.nombre for s in horarios if s.vigente), None)
        imp.append(f"Horarios guardados: {len(horarios)}"
                   + (f" (vigente: «{vigente}»)" if vigente else ""))  # fmt: skip
    no.append("Las penalizaciones guardadas no se importan: se recalculan con los criterios v2")
    return resultado
