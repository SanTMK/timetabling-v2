"""Creado con Claude.

Cuadro de horarios por grado (§15.1). Un libro con una hoja por grado; en cada hoja, cada grupo
es un bloque de columnas de días (Monday … Friday o Lunes … Viernes) con la columna de horas
(«8:00-8:45») a la izquierda y el nombre del grupo encima. Lo que sigue a «Horarios de Examen»
se ignora; las celdas vacías pintadas de celeste son la hora cívica.

El flujo es el del asistente: `leer_libro` (vista previa) → `mapeo_inicial` (editable: hojas →
grados, textos → asignaturas, recesos y tutorías) → `aplicar` (resultado con el resumen; no
toca el archivo: lo guarda el servicio en una transacción).
"""

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import openpyxl

from timetabling.dominio.modelos import DatosEscuela, Evento, Grado, Grupo, PlanEstudios, por_id
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.importacion.comun import (
    Ids,
    Resultado,
    asegurar_asignatura,
    destino_inicial,
    guardar_alias,
    sincronizar_clases,
)
from timetabling.importacion.textos import (
    FIN_TABLA,
    RECESOS_POR_DEFECTO,
    TUTORIAS_POR_DEFECTO,
    clave,
    contiene,
    dia_de,
    limpio,
    mismo_grado,
    rango,
)
from timetabling.nucleo.franjas import generar_franjas

# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Celda:
    dia: str
    inicio: int
    fin: int
    texto: str


@dataclass
class GrupoLeido:
    etiqueta: str
    seccion: str
    celdas: list[Celda] = field(default_factory=list)


@dataclass
class HojaLeida:
    nombre: str
    grupos: list[GrupoLeido] = field(default_factory=list)
    eventos: set[tuple[str, int, int]] = field(default_factory=set)
    """Celdas vacías pintadas de celeste (día, inicio, fin): la hora cívica."""


def es_celeste(color: str | None) -> bool:
    """Relleno celeste o cian (``FF00FFFF``, ``FF66FFFF``…): poco rojo, mucho verde y azul."""
    if not color or not re.fullmatch(r"[0-9A-Fa-f]{8}", color):
        return False
    r, g, b = (int(color[i : i + 2], 16) for i in (2, 4, 6))
    return r < 0x80 and g >= 0xC0 and b >= 0xC0


def leer_hoja(
    nombre: str, filas: list[list[object]], rellenos: list[list[str | None]] | None = None
) -> HojaLeida:
    hoja = HojaLeida(nombre)
    encabezado = next(
        (i for i, fila in enumerate(filas) if any(dia_de(c) == "L" for c in fila)), None
    )
    if encabezado is None:
        return hoja
    fin = next(
        (i for i, fila in enumerate(filas)
         if i > encabezado and any(FIN_TABLA in clave(limpio(c)) for c in fila)),
        len(filas),
    )  # fmt: skip
    cabecera = filas[encabezado]
    lunes = [j for j, c in enumerate(cabecera) if dia_de(c) == "L"]
    for numero, j in enumerate(lunes):
        dias = {k: d for k in range(j, min(j + 7, len(cabecera))) if (d := dia_de(cabecera[k]))}
        etiqueta = ""
        for i in range(encabezado - 1, -1, -1):
            etiqueta = next((limpio(filas[i][k]) for k in dias if k < len(filas[i])
                             and limpio(filas[i][k])), "")  # fmt: skip
            if etiqueta:
                break
        # Sección: la última letra de la etiqueta («1A» → «A») si hay varios grupos en la hoja;
        # si no, por orden (A, B, C…).
        letra = re.search(r"([A-Za-z])\s*$", etiqueta) if len(lunes) > 1 else None
        grupo = GrupoLeido(etiqueta, letra[1].upper() if letra else chr(ord("A") + numero))
        for i in range(encabezado + 1, fin):
            fila = filas[i]
            horas = rango(fila[j - 1]) if 0 < j <= len(fila) else None
            if horas is None:
                continue
            for k, dia in dias.items():
                texto = limpio(fila[k]) if k < len(fila) else ""
                if texto:
                    grupo.celdas.append(Celda(dia, *horas, texto))
                elif rellenos is not None and i < len(rellenos) and k < len(rellenos[i]):
                    if es_celeste(rellenos[i][k]):
                        hoja.eventos.add((dia, *horas))
        hoja.grupos.append(grupo)
    return hoja


def _color(celda: object) -> str | None:
    relleno = getattr(celda, "fill", None)
    if relleno is None or not relleno.fill_type:
        return None
    color = relleno.fgColor
    return color.rgb if color is not None and color.type == "rgb" else None


def leer_libro(ruta: str | Path) -> list[HojaLeida]:
    libro = openpyxl.load_workbook(ruta, data_only=True)
    try:
        hojas = []
        for hoja in libro.worksheets:
            celdas = [list(f) for f in hoja.iter_rows()]
            hojas.append(leer_hoja(hoja.title, [[c.value for c in f] for f in celdas],
                                   [[_color(c) for c in f] for f in celdas]))  # fmt: skip
        return hojas
    finally:
        libro.close()


# ---------------------------------------------------------------------------
# Mapeo editable
# ---------------------------------------------------------------------------


@dataclass
class DestinoHoja:
    """Grado de una hoja: uno existente (`grado_id`), uno nuevo (`nuevo_grado` en `nivel_id`)
    o ninguno (la hoja se omite)."""

    grado_id: int | None = None
    nuevo_grado: str | None = None
    nivel_id: int | None = None

    @property
    def omitir(self) -> bool:
        return self.grado_id is None and not (self.nuevo_grado and self.nivel_id is not None)


@dataclass
class MapeoHorarios:
    hojas: dict[str, DestinoHoja] = field(default_factory=dict)
    asignaturas: dict[str, str] = field(default_factory=dict)
    """Texto del cuadro → nombre de la asignatura ('' = ignorar la celda)."""
    recesos: list[str] = field(default_factory=lambda: list(RECESOS_POR_DEFECTO))
    tutorias: list[str] = field(default_factory=lambda: list(TUTORIAS_POR_DEFECTO))

    def tipo(self, texto: str) -> str:
        """«receso», «tutoría», «ignorar» o «clase»."""
        if contiene(texto, self.recesos):
            return "receso"
        if contiene(texto, self.tutorias):
            return "tutoría"
        if self.asignaturas.get(texto, None) == "":
            return "ignorar"
        return "clase"

    def a_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def de_json(cls, texto: str) -> "MapeoHorarios":
        crudo = json.loads(texto)
        return cls(
            hojas={k: DestinoHoja(**v) for k, v in crudo.get("hojas", {}).items()},
            asignaturas=dict(crudo.get("asignaturas", {})),
            recesos=list(crudo.get("recesos", RECESOS_POR_DEFECTO)),
            tutorias=list(crudo.get("tutorias", TUTORIAS_POR_DEFECTO)),
        )


def textos(hojas: list[HojaLeida], mapeo: MapeoHorarios | None = None) -> Counter[str]:
    """Textos de clase del cuadro (sin recesos ni tutorías) con cuántas celdas tienen."""
    mapeo = mapeo or MapeoHorarios()
    conteo: Counter[str] = Counter()
    for hoja in hojas:
        for grupo in hoja.grupos:
            for celda in grupo.celdas:
                if mapeo.tipo(celda.texto) in ("clase", "ignorar"):
                    conteo[celda.texto] += 1
    return conteo


def mapeo_inicial(datos: DatosEscuela, hojas: list[HojaLeida]) -> MapeoHorarios:
    """Sugerencia: cada hoja al grado del mismo nombre («1st» → «1°») y cada texto a su alias,
    a la asignatura del mismo nombre o a una nueva con ese nombre."""
    mapeo = MapeoHorarios()
    for hoja in hojas:
        if not any(g.celdas for g in hoja.grupos):
            continue
        grado = next((g for g in datos.grados if mismo_grado(hoja.nombre, g.nombre)), None)
        mapeo.hojas[hoja.nombre] = DestinoHoja(grado_id=grado.id if grado else None)
    for texto in textos(hojas, mapeo):
        mapeo.asignaturas[texto] = destino_inicial(datos, texto)
    return mapeo


# ---------------------------------------------------------------------------
# Aplicar
# ---------------------------------------------------------------------------


def aplicar(datos: DatosEscuela, hojas: list[HojaLeida], mapeo: MapeoHorarios) -> Resultado:
    """Datos resultantes de importar el cuadro (copia; el original no cambia)."""
    datos = datos.model_copy(deep=True)
    resultado = Resultado(datos)
    ids = Ids(datos)
    niveles = por_id(datos.niveles)

    # Hojas → grados (creando los nuevos).
    emparejadas: list[tuple[Grado, HojaLeida]] = []
    grados_nuevos: list[str] = []
    for hoja in hojas:
        destino = mapeo.hojas.get(hoja.nombre)
        if destino is None or destino.omitir or not any(g.celdas for g in hoja.grupos):
            if any(g.celdas for g in hoja.grupos):
                resultado.avisos.append(f"Hoja «{hoja.nombre}»: sin grado asignado; se omite.")
            continue
        if destino.grado_id is not None:
            grado = por_id(datos.grados).get(destino.grado_id)
            if grado is None:
                resultado.avisos.append(f"Hoja «{hoja.nombre}»: el grado ya no existe; se omite.")
                continue
        else:
            assert destino.nuevo_grado and destino.nivel_id is not None
            grado = next((g for g in datos.grados if g.nivel_id == destino.nivel_id
                          and clave(g.nombre) == clave(destino.nuevo_grado)), None)  # fmt: skip
            if grado is None:
                grado = Grado(id=ids.nuevo("grados"), nivel_id=destino.nivel_id,
                              nombre=destino.nuevo_grado.strip())  # fmt: skip
                datos.grados.append(grado)
                grados_nuevos.append(f"{grado.nombre} ({niveles[destino.nivel_id].nombre})")
        emparejadas.append((grado, hoja))
    if grados_nuevos:
        resultado.resumen.append("Grados nuevos: " + ", ".join(grados_nuevos))

    # Sesiones por grupo, máximo diario y plan por grado (el valor más frecuente).
    asignaturas_nuevas: list[str] = []
    planes: dict[int, dict[int, int]] = {}
    tutorias = 0
    for grado, hoja in emparejadas:
        assert grado.id is not None
        conteos: list[Counter[str]] = []
        maximo: dict[str, int] = defaultdict(int)
        for g in hoja.grupos:
            conteo: Counter[str] = Counter()
            por_dia: Counter[tuple[str, str]] = Counter()
            for celda in g.celdas:
                tipo = mapeo.tipo(celda.texto)
                if tipo == "tutoría":
                    tutorias += 1
                if tipo != "clase":
                    continue
                nombre = mapeo.asignaturas.get(celda.texto) or destino_inicial(datos, celda.texto)
                conteo[nombre] += 1
                por_dia[(nombre, celda.dia)] += 1
            for (nombre, _), n in por_dia.items():
                maximo[nombre] = max(maximo[nombre], n)
            conteos.append(conteo)
        plan: dict[int, int] = {}
        for nombre in sorted(set().union(*conteos)):
            valores = [c.get(nombre, 0) for c in conteos]
            frecuencia = Counter(valores).most_common()
            horas = max(v for v, n in frecuencia if n == frecuencia[0][1])
            if len(set(valores)) > 1:
                detalle = ", ".join(f"{g.seccion}={v}" for g, v in zip(hoja.grupos, valores,
                                                                        strict=True))  # fmt: skip
                resultado.avisos.append(f"{grado.nombre}: los grupos difieren en {nombre} "
                                        f"({detalle}); se usa {horas}.")  # fmt: skip
            if horas > 0:
                ident = asegurar_asignatura(datos, ids, nombre, maximo[nombre], resultado,
                                            asignaturas_nuevas)  # fmt: skip
                plan[ident] = horas
        planes[grado.id] = plan
    if asignaturas_nuevas:
        resultado.resumen.append("Asignaturas nuevas: " + ", ".join(asignaturas_nuevas))
    if tutorias:
        resultado.avisos.append(f"Se omitieron {tutorias} celdas de tutoría.")

    # Grupos y plan.
    grupos_nuevos: list[str] = []
    for grado, hoja in emparejadas:
        assert grado.id is not None
        for g in hoja.grupos:
            if not any(x.grado_id == grado.id and clave(x.seccion) == clave(g.seccion)
                       for x in datos.grupos):  # fmt: skip
                datos.grupos.append(Grupo(id=ids.nuevo("grupos"), grado_id=grado.id,
                                          seccion=g.seccion))  # fmt: skip
                grupos_nuevos.append(f"{grado.nombre}{g.seccion}")
        antes = {p.asignatura_id: p.horas_semanales for p in datos.plan if p.grado_id == grado.id}
        nuevo = planes[grado.id]
        datos.plan = [p for p in datos.plan if p.grado_id != grado.id]
        datos.plan += [PlanEstudios(grado_id=grado.id, asignatura_id=a, horas_semanales=h)
                       for a, h in sorted(nuevo.items())]  # fmt: skip
        asignaturas = por_id(datos.asignaturas)
        cambios = [f"{asignaturas[a].nombre} {antes.get(a, 0)}→{h}"
                   for a, h in sorted(nuevo.items()) if antes.get(a) != h]  # fmt: skip
        quitadas = [asignaturas[a].nombre for a in antes if a not in nuevo]
        if cambios:
            resultado.resumen.append(f"Plan de {grado.nombre}: " + ", ".join(cambios))
        if quitadas:
            resultado.resumen.append(f"Plan de {grado.nombre}: se quitan " + ", ".join(quitadas))
        _revisar_horas(datos, grado, hoja, mapeo, resultado)
    if grupos_nuevos:
        resultado.resumen.append("Grupos nuevos: " + ", ".join(grupos_nuevos))

    _eventos(datos, emparejadas, resultado)
    sincronizar_clases(datos, ids, resultado)
    guardar_alias(datos, ids, mapeo.asignaturas, resultado)
    return resultado


def _revisar_horas(
    datos: DatosEscuela, grado: Grado, hoja: HojaLeida, mapeo: MapeoHorarios, resultado: Resultado
) -> None:
    """Avisa si alguna celda no coincide con una franja del nivel del grado."""
    nivel = por_id(datos.niveles)[grado.nivel_id]
    franjas = {(f.dia, f.inicio, f.fin) for f in generar_franjas(nivel)}
    fuera = sorted({(c.inicio, c.fin) for g in hoja.grupos for c in g.celdas
                    if mapeo.tipo(c.texto) == "clase"
                    and (c.dia, c.inicio, c.fin) not in franjas})  # fmt: skip
    if fuera:
        horas = ", ".join(texto_rango(i, f) for i, f in fuera)
        resultado.avisos.append(f"{grado.nombre}: horas del cuadro que no son franjas del nivel "
                                f"«{nivel.nombre}» ({horas}).")  # fmt: skip


def _eventos(
    datos: DatosEscuela, emparejadas: list[tuple[Grado, HojaLeida]], resultado: Resultado
) -> None:
    """Agrega a cada nivel las horas cívicas marcadas en sus hojas (si no existen)."""
    por_nivel: dict[int, set[tuple[str, int, int]]] = defaultdict(set)
    for grado, hoja in emparejadas:
        por_nivel[grado.nivel_id] |= hoja.eventos
    for nivel in datos.niveles:
        nuevos = [
            Evento(dia=dia, inicio=inicio, fin=fin)  # type: ignore[arg-type]
            for dia, inicio, fin in sorted(por_nivel.get(nivel.id or 0, set()))
            if not any(e.dia == dia and e.inicio < fin and inicio < e.fin for e in nivel.eventos)
        ]
        if nuevos:
            nivel.eventos = [*nivel.eventos, *nuevos]
            texto = ", ".join(f"{NOMBRES_DIAS[e.dia]} {texto_rango(e.inicio, e.fin)}"
                              for e in nuevos)  # fmt: skip
            resultado.resumen.append(f"Hora cívica en {nivel.nombre}: {texto}")
