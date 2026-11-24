"""Creado con Claude.

Piezas comunes de las importaciones de Excel (§15): asignación de ids nuevos, alias de
asignaturas (`AliasImportacion`) y el resultado que se muestra en el resumen del asistente.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel

from timetabling.dominio.clases import sincronizar_con_plan
from timetabling.dominio.modelos import AliasImportacion, Asignatura, DatosEscuela, ReglasAsignatura
from timetabling.importacion.textos import COLORES, clave, limpio

# Variantes frecuentes que se unifican aunque no haya alias guardado.
UNIFICADAS = {
    "tecnologia": "Tecnología", "technology": "Tecnología", "tecnology": "Tecnología",
    "caracter": "Carácter", "character": "Carácter", "valores": "Valores", "values": "Valores",
    "sceince": "Science", "wiritng": "Writing",
}  # fmt: skip


class Ids:
    """Ids nuevos por tipo de entidad (los guarda `reemplazar_datos`, que exige ids)."""

    def __init__(self, datos: DatosEscuela) -> None:
        self._siguiente: dict[str, int] = {}
        for nombre in ("niveles", "grados", "grupos", "divisiones", "asignaturas", "profesores",
                       "espacios", "alias", "clases", "fijas"):  # fmt: skip
            lista: Iterable[BaseModel] = getattr(datos, nombre)
            self._siguiente[nombre] = max((getattr(e, "id", 0) or 0 for e in lista), default=0) + 1

    def nuevo(self, tipo: str) -> int:
        ident = self._siguiente[tipo]
        self._siguiente[tipo] += 1
        return ident


@dataclass
class Resultado:
    """Lo que hará (o hizo) una importación: datos resultantes, resumen y avisos."""

    datos: DatosEscuela
    resumen: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def texto(self) -> str:
        partes = ["Se creará o cambiará:", *[f"• {r}" for r in self.resumen]]
        if not self.resumen:
            partes = ["No hay cambios que aplicar."]
        if self.avisos:
            partes += ["", "Avisos:", *[f"• {a}" for a in self.avisos]]
        return "\n".join(partes)


def destino_inicial(datos: DatosEscuela, texto: str) -> str:
    """Asignatura sugerida para un texto del cuadro: alias guardado, asignatura con el mismo
    nombre (sin acentos ni mayúsculas), variante conocida o el propio texto."""
    k = clave(texto)
    asignaturas = {a.id: a for a in datos.asignaturas}
    for alias in datos.alias:
        if clave(alias.texto) == k and alias.asignatura_id in asignaturas:
            return asignaturas[alias.asignatura_id].nombre
    for a in datos.asignaturas:
        if clave(a.nombre) == k:
            return a.nombre
    unificada = UNIFICADAS.get(k)
    if unificada:
        existente = next(
            (a for a in datos.asignaturas if clave(a.nombre) == clave(unificada)), None
        )
        return existente.nombre if existente else unificada
    texto = limpio(texto)
    return texto if not texto.isupper() else texto.capitalize()


def asegurar_asignatura(
    datos: DatosEscuela, ids: Ids, nombre: str, max_dia: int, resultado: Resultado,
    nuevas: list[str],
) -> int:  # fmt: skip
    """Id de la asignatura `nombre`; la crea si no existe. Sube su máximo diario si el cuadro
    trae más sesiones en un día."""
    existente = next((a for a in datos.asignaturas if clave(a.nombre) == clave(nombre)), None)
    if existente is None:
        usados = {a.color for a in datos.asignaturas}
        libres = [c for c in COLORES if c not in usados] or COLORES
        existente = Asignatura(
            id=ids.nuevo("asignaturas"),
            nombre=nombre,
            color=libres[len(nuevas) % len(libres)],
            reglas_por_defecto=ReglasAsignatura(max_horas_dia=max(max_dia, 1)),
        )
        datos.asignaturas.append(existente)
        nuevas.append(nombre)
    elif max_dia > existente.reglas_por_defecto.max_horas_dia:
        resultado.avisos.append(
            f"{existente.nombre}: el cuadro tiene hasta {max_dia} sesiones en un día; se sube el "
            f"máximo diario de {existente.reglas_por_defecto.max_horas_dia} a {max_dia}."
        )
        existente.reglas_por_defecto = existente.reglas_por_defecto.model_copy(
            update={"max_horas_dia": max_dia}
        )
    assert existente.id is not None
    return existente.id


def guardar_alias(
    datos: DatosEscuela, ids: Ids, textos: dict[str, str], resultado: Resultado
) -> None:
    """Guarda como alias los textos que se mapearon a una asignatura de otro nombre."""
    nuevos = 0
    for texto, nombre in sorted(textos.items()):
        if not nombre or clave(texto) == clave(nombre):
            continue
        asignatura = next((a for a in datos.asignaturas if clave(a.nombre) == clave(nombre)), None)
        if asignatura is None or asignatura.id is None:
            continue
        actual = next((a for a in datos.alias if clave(a.texto) == clave(texto)), None)
        if actual is not None:
            if actual.asignatura_id != asignatura.id:
                actual.asignatura_id = asignatura.id
                nuevos += 1
            continue
        datos.alias.append(
            AliasImportacion(
                id=ids.nuevo("alias"), texto=limpio(texto), asignatura_id=asignatura.id
            )
        )
        nuevos += 1
    if nuevos:
        resultado.resumen.append(f"Alias de importación guardados: {nuevos}")


def sincronizar_clases(datos: DatosEscuela, ids: Ids, resultado: Resultado) -> None:
    """Crea las clases de grupo completo que falten para el plan importado (§8)."""
    nuevas = sincronizar_con_plan(datos).nuevas
    for clase in nuevas:
        clase.id = ids.nuevo("clases")
        datos.clases.append(clase)
    if nuevas:
        resultado.resumen.append(f"Clases nuevas (sincronizadas con el plan): {len(nuevas)}")
