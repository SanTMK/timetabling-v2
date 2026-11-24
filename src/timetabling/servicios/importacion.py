"""Creado con Claude.

Casos de uso de la importación (§15): vista previa, resumen y aplicación **en una
transacción, con respaldo previo**. Los módulos de `importacion/` calculan el resultado sin
tocar el archivo; aquí se guarda (datos, alias, borradores y soluciones importadas).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import DatosEscuela, EstadoSolucion, Solucion
from timetabling.importacion import horarios_excel, maestros_excel, proyecto_v6
from timetabling.importacion.comun import Resultado
from timetabling.nucleo.franjas import Calendario
from timetabling.nucleo.objetivo import evaluar, pesos, total_ponderado
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios.soluciones import a_solucion

NOMBRE_BORRADOR_MAESTROS = "Horarios del cuadro de maestros"


class ErrorImportacion(ErrorProyecto):
    """La importación no se puede hacer (archivo ilegible, destino existente…)."""


def aplicar_en_repositorio(
    repo: Repositorio, datos: DatosEscuela, soluciones: Iterable[Solucion] = ()
) -> list[Solucion]:
    """Respaldo y, en una transacción, los datos nuevos y las soluciones (todo o nada)."""
    repo.crear_respaldo()
    guardadas = []
    with repo.transaccion():
        repo.reemplazar_datos(datos, respaldo=False)
        for solucion in soluciones:
            guardadas.append(repo.guardar_solucion(solucion))
    return guardadas


# ---------------------------------------------------------------------------
# Cuadro de horarios por grado
# ---------------------------------------------------------------------------


def leer_horarios(ruta: Path | str) -> list[horarios_excel.HojaLeida]:
    try:
        return horarios_excel.leer_libro(ruta)
    except (OSError, ValueError, KeyError) as error:
        raise ErrorImportacion(f"No se pudo leer «{Path(ruta).name}»: {error}") from error


def importar_horarios(
    repo: Repositorio,
    hojas: list[horarios_excel.HojaLeida],
    mapeo: horarios_excel.MapeoHorarios,
) -> Resultado:
    resultado = horarios_excel.aplicar(repo.cargar_datos(), hojas, mapeo)
    aplicar_en_repositorio(repo, resultado.datos)
    return resultado


# ---------------------------------------------------------------------------
# Cuadro de maestros
# ---------------------------------------------------------------------------


def leer_maestros(ruta: Path | str) -> list[maestros_excel.BloqueMaestro]:
    try:
        return maestros_excel.leer_libro(ruta)
    except (OSError, ValueError, KeyError) as error:
        raise ErrorImportacion(f"No se pudo leer «{Path(ruta).name}»: {error}") from error


def borrador_de_maestros(resultado: maestros_excel.ResultadoMaestros) -> Solucion | None:
    if not resultado.colocaciones:
        return None
    datos = resultado.datos
    colocaciones = [Colocacion(c, f, p) for c, f, p in resultado.colocaciones]
    calendario = Calendario.de(datos)
    conflictos = verificar(datos, colocaciones, parcial=True, calendario=calendario).violaciones
    nota = "Importado del cuadro de maestros."
    if conflictos:
        nota += f" {len(conflictos)} conflictos por revisar en el editor."
    if resultado.sin_colocar:
        nota += f" {len(resultado.sin_colocar)} celdas sin franja."
    return a_solucion(datos, colocaciones, nombre=NOMBRE_BORRADOR_MAESTROS,
                      estado=EstadoSolucion.BORRADOR, origen="importado",
                      calendario=calendario, nota=nota)  # fmt: skip


def importar_maestros(
    repo: Repositorio,
    bloques: list[maestros_excel.BloqueMaestro],
    mapeo: maestros_excel.MapeoMaestros,
) -> tuple[maestros_excel.ResultadoMaestros, Solucion | None]:
    resultado = maestros_excel.aplicar(repo.cargar_datos(), bloques, mapeo)
    borrador = borrador_de_maestros(resultado) if mapeo.con_horarios else None
    guardadas = aplicar_en_repositorio(repo, resultado.datos, [borrador] if borrador else [])
    return resultado, (guardadas[0] if guardadas else None)


# ---------------------------------------------------------------------------
# Proyecto v6
# ---------------------------------------------------------------------------


@dataclass
class InformeV6:
    importado: list[str] = field(default_factory=list)
    no_importado: list[str] = field(default_factory=list)

    def texto(self, previo: bool = False) -> str:
        """Informe al terminar o, con `previo`, resumen antes de aplicar."""
        partes = ["Se importará:" if previo else "Se importó:", *[f"• {r}" for r in self.importado]]
        if self.no_importado:
            titulo = "No se importará o cambiará:" if previo else "No se importó o cambió:"
            partes += ["", titulo, *[f"• {r}" for r in self.no_importado]]
        return "\n".join(partes)


def soluciones_v6(lectura: proyecto_v6.ImportacionV6) -> tuple[list[Solucion], list[str]]:
    """Soluciones v2 con franjas reconstruidas; la vigente solo se conserva si es válida."""
    datos = lectura.datos
    calendario = Calendario.de(datos)
    tabla = pesos(datos.configuracion.criterios)
    resultado: list[Solucion] = []
    avisos: list[str] = []
    for s in lectura.soluciones:
        colocaciones = [Colocacion(c, f, p, b) for c, f, p, b in s.colocaciones]
        borrador = s.estado == EstadoSolucion.BORRADOR
        verificacion = verificar(datos, colocaciones, parcial=borrador, calendario=calendario)
        penalizaciones: dict[str, float] = {}
        if not borrador:
            penalizaciones = evaluar(datos, colocaciones, calendario)
            penalizaciones["total"] = total_ponderado(penalizaciones, tabla)
        solucion = a_solucion(
            datos, colocaciones, nombre=s.nombre, estado=s.estado, origen="importado",
            calendario=calendario, tiempo_s=s.tiempo_s, penalizaciones=penalizaciones,
            violaciones=[] if borrador else verificacion.violaciones, nota=s.nota,
        ).model_copy(update={"fecha": s.fecha})  # fmt: skip
        if not borrador and verificacion.violaciones:
            solucion = solucion.model_copy(update={"estado": EstadoSolucion.INVALIDA})
            avisos.append(f"«{s.nombre}» incumple {len(verificacion.violaciones)} reglas de la v2 "
                          "(se importa como inválida)")  # fmt: skip
        vigente = s.vigente and solucion.estado != EstadoSolucion.INVALIDA
        if s.vigente and not vigente:
            avisos.append(f"«{s.nombre}» era el vigente, pero no es válido en la v2: no se marca")
        resultado.append(solucion.model_copy(update={"vigente": vigente}))
    return resultado, avisos


def importar_v6(origen: Path | str, destino: Path | str) -> InformeV6:
    """Crea `destino` con el contenido del proyecto v6 `origen` (§15.3)."""
    origen, destino = Path(origen), Path(destino)
    if destino.exists():
        raise ErrorImportacion(f"Ya existe «{destino.name}»: elija otro nombre.")
    try:
        lectura = proyecto_v6.leer(origen)
    except (proyecto_v6.ErrorV6, ValueError, KeyError) as error:
        raise ErrorImportacion(f"No se pudo importar «{origen.name}»: {error}") from error
    soluciones, avisos = soluciones_v6(lectura)
    repo = Repositorio.crear(destino, lectura.datos.configuracion)
    try:
        with repo.transaccion():
            repo.reemplazar_datos(lectura.datos, respaldo=False)
            for solucion in soluciones:
                repo.guardar_solucion(solucion)
    except Exception:
        repo.cerrar()
        destino.unlink(missing_ok=True)
        raise
    repo.cerrar()
    return InformeV6(
        [f"Proyecto v6 (esquema versión {lectura.version}) → «{destino.name}»",
         *lectura.importado],
        [*lectura.no_importado, *avisos],
    )  # fmt: skip
