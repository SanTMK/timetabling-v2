"""Creado con Claude.

Entidades del dominio (§5, §14) como modelos pydantic y el agregado `DatosEscuela`.

Las entidades editables heredan de `Modelo` (`validate_assignment=True`, `extra="forbid"`); los
valores inmutables (recesos, rangos, destinatarios…) heredan de `Valor` (`frozen=True`).
"""

import hashlib
import json
import os
import re
from collections.abc import Iterable
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from timetabling.dominio.tiempo import DIAS_POR_DEFECTO, Dia, Minuto, ordenar_dias, texto_rango

# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------


class Modelo(BaseModel):
    """Base de las entidades editables."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class Valor(BaseModel):
    """Base de los valores inmutables."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _texto_no_vacio(valor: str, campo: str) -> str:
    limpio = valor.strip()
    if not limpio:
        raise ValueError(f"El campo «{campo}» no puede quedar vacío.")
    return limpio


def _validar_intervalo(inicio: int, fin: int, que: str) -> None:
    if inicio >= fin:
        raise ValueError(
            f"{que}: el inicio debe ser anterior al fin ({texto_rango_seguro(inicio, fin)})."
        )


def texto_rango_seguro(inicio: int, fin: int) -> str:
    try:
        return texto_rango(inicio, fin)
    except ValueError:
        return f"{inicio}–{fin}"


# ---------------------------------------------------------------------------
# Configuración y criterios (§5.1, §9)
# ---------------------------------------------------------------------------

Prioridad = Literal["desactivado", "baja", "media", "alta", "muy_alta"]
Criterio = Literal["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B10"]
Perfil = Literal["equilibrado", "profesores", "alumnos", "personalizado"]

CRITERIOS: tuple[Criterio, ...] = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B10")
MULTIPLICADORES: dict[Prioridad, int] = {
    "desactivado": 0,
    "baja": 1,
    "media": 4,
    "alta": 16,
    "muy_alta": 64,
}
MULTIPLICADOR_B9 = 64

NOMBRES_CRITERIOS: dict[str, str] = {
    "B1": "Huecos de profesores",
    "B2": "Mala distribución semanal",
    "B3": "Fuera de las franjas preferidas",
    "B4": "Franjas «preferible no» de profesores",
    "B5": "Días con clase por profesor",
    "B6": "Desequilibrio de carga",
    "B7": "Grupos sin su titular",
    "B8": "Bloque doble preferido no logrado",
    "B9": "Cambios respecto a la base",
    "B10": "Huecos de alumnos",
}

PERFILES: dict[Perfil, dict[Criterio, Prioridad]] = {
    "equilibrado": {
        "B1": "alta", "B2": "alta", "B3": "media", "B4": "media", "B5": "baja",
        "B6": "baja", "B7": "media", "B8": "media", "B10": "alta",
    },
    "profesores": {
        "B1": "muy_alta", "B2": "media", "B3": "baja", "B4": "alta", "B5": "media",
        "B6": "media", "B7": "baja", "B8": "baja", "B10": "media",
    },
    "alumnos": {
        "B1": "media", "B2": "muy_alta", "B3": "alta", "B4": "baja", "B5": "baja",
        "B6": "baja", "B7": "alta", "B8": "alta", "B10": "muy_alta",
    },
}  # fmt: skip


class Criterios(Modelo):
    """Prioridades de las restricciones blandas (§9.2)."""

    perfil: Perfil = "equilibrado"
    prioridades: dict[Criterio, Prioridad] = Field(
        default_factory=lambda: dict(PERFILES["equilibrado"])
    )
    modo_avanzado: bool = False
    pesos_avanzados: dict[Criterio, float] = Field(default_factory=dict)

    @field_validator("prioridades")
    @classmethod
    def _completas(cls, valor: dict[Criterio, Prioridad]) -> dict[Criterio, Prioridad]:
        faltan = [c for c in CRITERIOS if c not in valor]
        if faltan:
            raise ValueError(f"Faltan prioridades para: {', '.join(faltan)}.")
        return valor

    @field_validator("pesos_avanzados")
    @classmethod
    def _pesos_no_negativos(cls, valor: dict[Criterio, float]) -> dict[Criterio, float]:
        for criterio, peso in valor.items():
            if peso < 0:
                raise ValueError(f"El peso de {criterio} no puede ser negativo.")
        return valor

    @classmethod
    def de_perfil(cls, perfil: Perfil) -> Self:
        if perfil == "personalizado":
            raise ValueError("«personalizado» no es un perfil predefinido.")
        return cls(perfil=perfil, prioridades=dict(PERFILES[perfil]))


def _hilos_por_defecto() -> int:
    return max(1, min(8, os.cpu_count() or 1))


class Configuracion(Modelo):
    nombre_escuela: str = "Mi escuela"
    margen_traslado_min: int = Field(default=0, ge=0, le=120)
    descanso_minimo_min: int = Field(default=10, ge=0, le=60)
    tiempo_limite_s: int = Field(default=300, ge=1)
    hilos: int = Field(default_factory=_hilos_por_defecto, ge=1)
    criterios: Criterios = Field(default_factory=Criterios)
    respaldos_a_conservar: int = Field(default=10, ge=1)

    @field_validator("nombre_escuela")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "nombre de la escuela")


# ---------------------------------------------------------------------------
# Niveles, grados y grupos
# ---------------------------------------------------------------------------


class Receso(Valor):
    nombre: str = "Receso"
    inicio: Minuto
    fin: Minuto

    @model_validator(mode="after")
    def _intervalo(self) -> Self:
        _validar_intervalo(self.inicio, self.fin, f"Receso «{self.nombre}»")
        return self


class Evento(Valor):
    """Actividad de todo el nivel (D14), por ejemplo la hora cívica."""

    nombre: str = "Hora cívica"
    dia: Dia
    inicio: Minuto
    fin: Minuto

    @model_validator(mode="after")
    def _intervalo(self) -> Self:
        _validar_intervalo(self.inicio, self.fin, f"Evento «{self.nombre}»")
        return self


HuecosAlumnos = Literal["permitidos", "penalizar", "prohibidos"]


class Nivel(Modelo):
    id: int | None = None
    nombre: str
    duracion_min: int = Field(default=50, ge=5, le=240)
    inicio_jornada: Minuto
    fin_jornada: Minuto
    dias: list[Dia] = Field(default_factory=lambda: list(DIAS_POR_DEFECTO), min_length=1)
    recesos: list[Receso] = Field(default_factory=list)
    eventos: list[Evento] = Field(default_factory=list)
    duraciones_especiales: dict[int, int] = Field(default_factory=dict)
    huecos_alumnos: HuecosAlumnos = "penalizar"
    preferir_titular: bool = False

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "nombre del nivel")

    @field_validator("dias")
    @classmethod
    def _dias(cls, valor: list[Dia]) -> list[Dia]:
        return ordenar_dias(valor)

    @field_validator("duraciones_especiales")
    @classmethod
    def _duraciones(cls, valor: dict[int, int]) -> dict[int, int]:
        for indice, minutos in valor.items():
            if indice < 0:
                raise ValueError(f"Índice de franja no válido en duraciones especiales: {indice}.")
            if not 5 <= minutos <= 240:
                raise ValueError(
                    f"La duración especial de la hora {indice + 1} debe estar entre 5 y 240 min."
                )
        return dict(sorted(valor.items()))

    @model_validator(mode="after")
    def _jornada(self) -> Self:
        _validar_intervalo(self.inicio_jornada, self.fin_jornada, f"Jornada de «{self.nombre}»")
        return self


class Grado(Modelo):
    id: int | None = None
    nivel_id: int
    nombre: str

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "nombre del grado")


class BloqueoGrupo(Valor):
    """Franja en la que un grupo no tiene clase (sale temprano, natación…)."""

    dia: Dia
    inicio: Minuto
    fin: Minuto
    nombre: str = "Bloqueo"

    @model_validator(mode="after")
    def _intervalo(self) -> Self:
        _validar_intervalo(self.inicio, self.fin, f"Bloqueo «{self.nombre}»")
        return self


class Grupo(Modelo):
    id: int | None = None
    grado_id: int
    seccion: str
    estudiantes: int = Field(default=0, ge=0, description="Informativo")
    titular_id: int | None = None
    bloqueos: list[BloqueoGrupo] = Field(default_factory=list)

    @field_validator("seccion")
    @classmethod
    def _seccion(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "sección")


class Division(Modelo):
    """Subgrupos de un grupo. Las partes pueden tener clase al mismo tiempo."""

    id: int | None = None
    grupo_id: int
    nombre: str = "Inglés por nivel"
    partes: list[str] = Field(min_length=2)
    simultanea: bool = True

    @field_validator("partes")
    @classmethod
    def _partes(cls, valor: list[str]) -> list[str]:
        limpias = [_texto_no_vacio(p, "parte") for p in valor]
        if len(set(limpias)) != len(limpias):
            raise ValueError("Las partes de una división no pueden repetirse.")
        return limpias


# ---------------------------------------------------------------------------
# Asignaturas y plan
# ---------------------------------------------------------------------------


class RangoFranjas(Valor):
    """Rango de franjas por índice (`desde_indice`–`hasta_indice`, inclusive) o por hora
    (`desde`–`hasta`). `dias` vacío significa todos los días."""

    dias: tuple[Dia, ...] = ()
    desde_indice: int | None = Field(default=None, ge=0)
    hasta_indice: int | None = Field(default=None, ge=0)
    desde: Minuto | None = None
    hasta: Minuto | None = None

    @field_validator("dias")
    @classmethod
    def _dias(cls, valor: tuple[Dia, ...]) -> tuple[Dia, ...]:
        return tuple(ordenar_dias(valor))

    @model_validator(mode="after")
    def _forma(self) -> Self:
        por_indice = self.desde_indice is not None or self.hasta_indice is not None
        por_hora = self.desde is not None or self.hasta is not None
        if por_indice == por_hora:
            raise ValueError("Un rango de franjas se define por índices o por horas, no ambos.")
        if por_indice:
            if self.desde_indice is None or self.hasta_indice is None:
                raise ValueError("Faltan «desde» o «hasta» en el rango de franjas.")
            if self.desde_indice > self.hasta_indice:
                raise ValueError("En el rango de franjas, «desde» no puede ser mayor que «hasta».")
        else:
            if self.desde is None or self.hasta is None:
                raise ValueError("Faltan «desde» o «hasta» en el rango de franjas.")
            _validar_intervalo(self.desde, self.hasta, "Rango de franjas")
        return self

    def incluye_dia(self, dia: Dia) -> bool:
        return not self.dias or dia in self.dias


BloqueDoble = Literal["no", "preferido", "obligatorio"]


class ReglasAsignatura(Modelo):
    max_horas_dia: int = Field(default=2, ge=1, le=24)
    bloque_doble: BloqueDoble = "no"
    franjas_prohibidas: list[RangoFranjas] = Field(default_factory=list)
    franjas_preferidas: list[RangoFranjas] = Field(default_factory=list)


class ReglasAsignaturaNivel(Modelo):
    """Sobrescritura de reglas para un nivel; `None` significa «hereda la regla por defecto»."""

    nivel_id: int
    max_horas_dia: int | None = Field(default=None, ge=1, le=24)
    bloque_doble: BloqueDoble | None = None
    franjas_prohibidas: list[RangoFranjas] | None = None
    franjas_preferidas: list[RangoFranjas] | None = None


_PATRON_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Asignatura(Modelo):
    id: int | None = None
    nombre: str
    color: str = "#9E9E9E"
    espacio_requerido: str | None = None
    reglas_por_defecto: ReglasAsignatura = Field(default_factory=ReglasAsignatura)
    reglas_por_nivel: list[ReglasAsignaturaNivel] = Field(default_factory=list)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "nombre de la asignatura")

    @field_validator("color")
    @classmethod
    def _color(cls, valor: str) -> str:
        if not _PATRON_COLOR.match(valor):
            raise ValueError(f"Color no válido: «{valor}». Use el formato #RRGGBB.")
        return valor.upper()

    @field_validator("espacio_requerido")
    @classmethod
    def _espacio(cls, valor: str | None) -> str | None:
        return valor.strip() or None if valor is not None else None

    @field_validator("reglas_por_nivel")
    @classmethod
    def _niveles_unicos(cls, valor: list[ReglasAsignaturaNivel]) -> list[ReglasAsignaturaNivel]:
        niveles = [r.nivel_id for r in valor]
        if len(set(niveles)) != len(niveles):
            raise ValueError("Hay más de una sobrescritura de reglas para el mismo nivel.")
        return valor

    def reglas_efectivas(self, nivel_id: int | None) -> ReglasAsignatura:
        """Reglas por defecto con la sobrescritura del nivel aplicada."""
        base = self.reglas_por_defecto
        for propia in self.reglas_por_nivel:
            if propia.nivel_id == nivel_id:
                return ReglasAsignatura(
                    max_horas_dia=propia.max_horas_dia or base.max_horas_dia,
                    bloque_doble=propia.bloque_doble or base.bloque_doble,
                    franjas_prohibidas=(
                        base.franjas_prohibidas
                        if propia.franjas_prohibidas is None
                        else propia.franjas_prohibidas
                    ),
                    franjas_preferidas=(
                        base.franjas_preferidas
                        if propia.franjas_preferidas is None
                        else propia.franjas_preferidas
                    ),
                )
        return base


class PlanEstudios(Modelo):
    grado_id: int
    asignatura_id: int
    horas_semanales: int = Field(ge=0, description="En horas-clase del nivel; 0 elimina la fila")


# ---------------------------------------------------------------------------
# Profesores, espacios, alias
# ---------------------------------------------------------------------------

TipoDisponibilidad = Literal["disponible", "preferible_no", "no_disponible"]


class Disponibilidad(Valor):
    dia: Dia
    inicio: Minuto
    fin: Minuto
    tipo: TipoDisponibilidad = "disponible"

    @model_validator(mode="after")
    def _intervalo(self) -> Self:
        _validar_intervalo(self.inicio, self.fin, "Rango de disponibilidad")
        return self


class EventoProfesor(Valor):
    """Compromiso propio del profesor (junta, curso) en el que no puede dar clase."""

    nombre: str = "Evento"
    dia: Dia
    inicio: Minuto
    fin: Minuto

    @model_validator(mode="after")
    def _intervalo(self) -> Self:
        _validar_intervalo(self.inicio, self.fin, f"Evento «{self.nombre}»")
        return self


class Profesor(Modelo):
    id: int | None = None
    nombre: str
    activo: bool = True
    asignaturas: list[int] = Field(default_factory=list)
    grados: list[int] = Field(default_factory=list)
    disponibilidad: list[Disponibilidad] = Field(default_factory=list)
    disponible_toda_la_jornada: bool = True
    eventos: list[EventoProfesor] = Field(default_factory=list)
    suplencia_asignaturas: list[int] = Field(default_factory=list)
    suplencia_grados: list[int] = Field(default_factory=list)
    carga_max_semanal_min: int = Field(default=2400, ge=0)
    carga_max_diaria_min: int = Field(default=480, ge=0)
    carga_min_semanal_min: int = Field(default=0, ge=0)
    max_dias: int | None = Field(default=None, ge=1, le=7)
    max_minutos_continuos: int = Field(default=200, ge=5)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "nombre del profesor")

    @field_validator("asignaturas", "grados", "suplencia_asignaturas", "suplencia_grados")
    @classmethod
    def _sin_repetir(cls, valor: list[int]) -> list[int]:
        return list(dict.fromkeys(valor))

    @model_validator(mode="after")
    def _cargas(self) -> Self:
        if self.carga_min_semanal_min > self.carga_max_semanal_min:
            raise ValueError(f"La carga mínima de «{self.nombre}» supera su carga máxima semanal.")
        return self


class Espacio(Modelo):
    id: int | None = None
    nombre: str
    tipo: str
    cantidad: int = Field(default=1, ge=1)

    @field_validator("nombre", "tipo")
    @classmethod
    def _textos(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "nombre o tipo del espacio")


class AliasImportacion(Modelo):
    id: int | None = None
    texto: str
    asignatura_id: int

    @field_validator("texto")
    @classmethod
    def _texto(cls, valor: str) -> str:
        return _texto_no_vacio(valor, "texto del alias")


# ---------------------------------------------------------------------------
# Clases (§5.2) y asignaciones fijas
# ---------------------------------------------------------------------------


class Destinatario(Valor):
    """Grupo completo (`division_id` y `parte` nulos) o una parte de una división del grupo."""

    grupo_id: int
    division_id: int | None = None
    parte: str | None = None

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if (self.division_id is None) != (self.parte is None):
            raise ValueError("Un destinatario parcial necesita la división y la parte.")
        return self

    @property
    def es_grupo_completo(self) -> bool:
        return self.division_id is None


OrigenClase = Literal["plan", "manual"]


class Clase(Modelo):
    id: int | None = None
    asignatura_id: int
    destinatarios: list[Destinatario] = Field(min_length=1)
    profesores: list[int] = Field(default_factory=list)
    horas_semanales: int = Field(ge=1)
    sobrescribe_espacio: bool = False
    espacio_requerido: str | None = None
    origen: OrigenClase = "manual"

    @field_validator("destinatarios")
    @classmethod
    def _destinatarios(cls, valor: list[Destinatario]) -> list[Destinatario]:
        if len(set(valor)) != len(valor):
            raise ValueError("Una clase no puede repetir destinatarios.")
        return valor

    @field_validator("profesores")
    @classmethod
    def _profesores(cls, valor: list[int]) -> list[int]:
        if len(set(valor)) != len(valor):
            raise ValueError("Una clase no puede repetir profesores.")
        return valor

    def espacio_efectivo(self, asignatura: Asignatura) -> str | None:
        return self.espacio_requerido if self.sobrescribe_espacio else asignatura.espacio_requerido


class AsignacionFija(Modelo):
    id: int | None = None
    clase_id: int
    profesor_id: int | None = None
    dia: Dia
    indice_franja: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Soluciones (§5.3)
# ---------------------------------------------------------------------------


class EstadoSolucion(StrEnum):
    OPTIMO = "OPTIMO"
    FACTIBLE = "FACTIBLE"
    INFACTIBLE = "INFACTIBLE"
    SIN_SOLUCION_EN_TIEMPO = "SIN_SOLUCION_EN_TIEMPO"
    CANCELADO = "CANCELADO"
    BORRADOR = "BORRADOR"
    INVALIDA = "INVALIDA"


OrigenSolucion = Literal["generado", "manual", "editado", "importado"]


class FranjaGuardada(Valor):
    nivel_id: int | None
    dia: Dia
    indice: int = Field(ge=0)
    inicio: Minuto
    fin: Minuto


class Asignacion(Modelo):
    """Una clase en una franja con un profesor. Las copias desnormalizadas mantienen legible el
    horario aunque se edite o elimine la entidad original. `franja` es el índice dentro de
    `Solucion.franjas`. Una clase con varios profesores lleva una asignación por profesor."""

    id: int | None = None
    clase_id: int | None
    franja: int = Field(ge=0)
    profesor_id: int | None
    asignatura_nombre: str
    grupos_texto: str
    profesor_nombre: str = ""
    color: str = "#9E9E9E"
    bloqueada: bool = False


class Violacion(Valor):
    restriccion: str
    mensaje: str
    clase_id: int | None = None


class Solucion(Modelo):
    id: int | None = None
    nombre: str
    fecha: datetime = Field(default_factory=lambda: datetime.now().replace(microsecond=0))
    estado: EstadoSolucion
    origen: OrigenSolucion
    tiempo_s: float = Field(default=0.0, ge=0)
    penalizaciones: dict[str, float] = Field(default_factory=dict)
    penalizaciones_son_cota: bool = False
    nota: str = ""
    vigente: bool = False
    base_id: int | None = None
    huella_niveles: str = ""
    franjas: list[FranjaGuardada] = Field(default_factory=list)
    asignaciones: list[Asignacion] = Field(default_factory=list)
    violaciones: list[Violacion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _referencias(self) -> Self:
        total = len(self.franjas)
        for asignacion in self.asignaciones:
            if asignacion.franja >= total:
                raise ValueError(
                    f"La asignación de «{asignacion.asignatura_nombre}» apunta a una franja "
                    "que no existe en la solución."
                )
        return self

    @property
    def editable(self) -> bool:
        return self.estado is EstadoSolucion.BORRADOR

    def desactualizada(self, huella_actual: str) -> bool:
        return self.huella_niveles != huella_actual


ESTADOS_VALIDOS_PARA_VIGENTE = frozenset(
    {EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE, EstadoSolucion.CANCELADO}
)


# ---------------------------------------------------------------------------
# Ausencias y suplencias (§14)
# ---------------------------------------------------------------------------


class Ausencia(Modelo):
    id: int | None = None
    profesor_id: int
    fecha_inicio: date
    fecha_fin: date
    desde: Minuto | None = None
    hasta: Minuto | None = None
    motivo: str = ""

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final de la ausencia es anterior a la inicial.")
        if (self.desde is None) != (self.hasta is None):
            raise ValueError("Una ausencia parcial necesita hora de inicio y de fin.")
        if self.desde is not None and self.hasta is not None:
            _validar_intervalo(self.desde, self.hasta, "Ausencia parcial")
        return self


class Suplencia(Modelo):
    id: int | None = None
    fecha: date
    solucion_id: int | None = None
    asignacion_id: int | None = None
    profesor_ausente_id: int
    suplente_id: int | None = None
    nota: str = ""


# ---------------------------------------------------------------------------
# Agregado
# ---------------------------------------------------------------------------


def por_id[T: BaseModel](entidades: Iterable[T]) -> dict[int, T]:
    """Índice `id → entidad` (las entidades sin id se omiten)."""
    resultado: dict[int, T] = {}
    for entidad in entidades:
        ident = getattr(entidad, "id", None)
        if ident is not None:
            resultado[ident] = entidad
    return resultado


class DatosEscuela(Modelo):
    """Todos los datos de captura de una escuela (sin soluciones, ausencias ni suplencias)."""

    configuracion: Configuracion = Field(default_factory=Configuracion)
    niveles: list[Nivel] = Field(default_factory=list)
    grados: list[Grado] = Field(default_factory=list)
    grupos: list[Grupo] = Field(default_factory=list)
    divisiones: list[Division] = Field(default_factory=list)
    asignaturas: list[Asignatura] = Field(default_factory=list)
    plan: list[PlanEstudios] = Field(default_factory=list)
    profesores: list[Profesor] = Field(default_factory=list)
    espacios: list[Espacio] = Field(default_factory=list)
    alias: list[AliasImportacion] = Field(default_factory=list)
    clases: list[Clase] = Field(default_factory=list)
    fijas: list[AsignacionFija] = Field(default_factory=list)

    def nivel_de_grado(self, grado_id: int) -> Nivel:
        grado = por_id(self.grados)[grado_id]
        return por_id(self.niveles)[grado.nivel_id]

    def nivel_de_grupo(self, grupo_id: int) -> Nivel:
        return self.nivel_de_grado(por_id(self.grupos)[grupo_id].grado_id)

    def nombre_grupo(self, grupo_id: int) -> str:
        """Nombre visible: grado + sección («7°A»)."""
        grupo = por_id(self.grupos)[grupo_id]
        return f"{por_id(self.grados)[grupo.grado_id].nombre}{grupo.seccion}"

    def huella_niveles(self) -> str:
        return huella_niveles(self.niveles)


def huella_niveles(niveles: Iterable[Nivel]) -> str:
    """Hash estable de la configuración temporal de los niveles (§5.3). El nombre del nivel y
    las opciones que no afectan las franjas no forman parte de la huella."""
    contenido = [
        {
            "id": n.id,
            "duracion": n.duracion_min,
            "jornada": [n.inicio_jornada, n.fin_jornada],
            "dias": list(n.dias),
            "recesos": sorted([r.inicio, r.fin] for r in n.recesos),
            "eventos": sorted([e.dia, e.inicio, e.fin] for e in n.eventos),
            "especiales": sorted([i, m] for i, m in n.duraciones_especiales.items()),
        }
        for n in sorted(niveles, key=lambda n: (n.id is None, n.id or 0, n.nombre))
    ]
    texto = json.dumps(contenido, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]
