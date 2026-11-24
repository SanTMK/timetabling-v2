"""Creado con Claude.

Sesión de trabajo sobre un proyecto abierto (§17). La interfaz habla con esta clase y no con el
repositorio: aquí se coordinan las operaciones compuestas (sincronizar clases, guardar un grupo
con sus divisiones, juntar o dividir clases) y se avisa a los observadores cuando cambian los
datos. No depende de Qt.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from timetabling.dominio.clases import (
    ResultadoSincronizacion,
    profesores_posibles,
    sincronizar_con_plan,
)
from timetabling.dominio.comparacion import Comparacion, comparar
from timetabling.dominio.modelos import (
    Clase,
    Configuracion,
    DatosEscuela,
    Destinatario,
    Division,
    Grupo,
    PlanEstudios,
    Profesor,
    Solucion,
    por_id,
)
from timetabling.exportacion.excel import FilaCambio, exportar_excel
from timetabling.importacion import horarios_excel, maestros_excel
from timetabling.importacion.comun import Resultado
from timetabling.nucleo.franjas import Calendario
from timetabling.nucleo.validacion import Problema, validar
from timetabling.persistencia.archivo import Aviso
from timetabling.persistencia.repositorio import Repositorio, ResumenSolucion
from timetabling.persistencia.respaldos import Respaldo

E = BaseModel

Observador = Callable[[], None]


@dataclass(frozen=True)
class PuntoControl:
    """Un renglón de la lista de verificación de Inicio."""

    clave: str
    texto: str
    ok: bool
    pantalla: str


class SesionProyecto:
    def __init__(self, repo: Repositorio) -> None:
        self.repo = repo
        self._observadores: list[Observador] = []
        self._datos: DatosEscuela | None = None
        self._calendario: Calendario | None = None
        self._problemas: list[Problema] | None = None

    # ------------------------------------------------------------------ ciclo de vida

    @classmethod
    def nuevo(cls, ruta: Path | str, nombre_escuela: str = "Mi escuela") -> "SesionProyecto":
        return cls(Repositorio.crear(ruta, Configuracion(nombre_escuela=nombre_escuela)))

    @classmethod
    def abrir(cls, ruta: Path | str) -> "SesionProyecto":
        return cls(Repositorio.abrir(ruta))

    def cerrar(self) -> None:
        self.repo.cerrar()

    @property
    def ruta(self) -> Path:
        return self.repo.ruta

    @property
    def avisos(self) -> list[Aviso]:
        return self.repo.avisos

    def suscribir(self, observador: Observador) -> None:
        self._observadores.append(observador)

    def _cambio(self) -> None:
        self._datos = None
        self._calendario = None
        self._problemas = None
        for observador in list(self._observadores):
            observador()

    # ------------------------------------------------------------------ lectura

    @property
    def datos(self) -> DatosEscuela:
        if self._datos is None:
            self._datos = self.repo.cargar_datos()
        return self._datos

    @property
    def calendario(self) -> Calendario:
        if self._calendario is None:
            self._calendario = Calendario.de(self.datos)
        return self._calendario

    def problemas(self) -> list[Problema]:
        if self._problemas is None:
            self._problemas = sorted(validar(self.datos), key=lambda p: not p.es_error)
        return self._problemas

    def vigente(self) -> ResumenSolucion | None:
        ident = self.repo.solucion_vigente_id()
        return next((s for s in self.repo.listar_soluciones() if s.id == ident), None)

    def puntos_de_control(self) -> list[PuntoControl]:
        """Lista de verificación del proyecto (§17, Inicio)."""
        datos = self.datos
        problemas = self.problemas()
        errores = [p for p in problemas if p.es_error]
        sin_franjas = [n for n in datos.niveles if not self.calendario.utiles_nivel.get(n.id or 0)]
        con_plan = {f.grado_id for f in datos.plan}
        sin_plan = [g for g in datos.grados if g.id not in con_plan]
        sin_grupos = [g for g in datos.grados if g.id not in {x.grado_id for x in datos.grupos}]
        activos = [p for p in datos.profesores if p.activo]
        sin_habilitar = [p for p in activos if not p.asignaturas or not p.grados]
        cobertura = [p for p in errores if p.entidad == "grupo" and "recibe" in p.mensaje]

        def contar(n: int, singular: str, plural: str) -> str:
            return f"{n} {singular if n == 1 else plural}"

        return [
            PuntoControl(
                "niveles",
                "Niveles" if datos.niveles and not sin_franjas
                else ("Sin niveles" if not datos.niveles
                      else contar(len(sin_franjas), "nivel sin franjas", "niveles sin franjas")),
                bool(datos.niveles) and not sin_franjas,
                "niveles",
            ),
            PuntoControl(
                "grupos",
                "Grados y grupos" if datos.grupos and not sin_grupos
                else contar(len(sin_grupos) or 1, "grado sin grupos", "grados sin grupos"),
                bool(datos.grupos) and not sin_grupos,
                "grados",
            ),
            PuntoControl(
                "asignaturas", "Asignaturas" if datos.asignaturas else "Sin asignaturas",
                bool(datos.asignaturas), "asignaturas",
            ),
            PuntoControl(
                "plan",
                "Plan" if datos.plan and not sin_plan
                else contar(len(sin_plan) or 1, "grado sin plan", "grados sin plan"),
                bool(datos.plan) and not sin_plan,
                "plan",
            ),
            PuntoControl(
                "clases",
                "Clases" if datos.clases and not cobertura
                else contar(len(cobertura) or 1, "diferencia con el plan",
                            "diferencias con el plan"),
                bool(datos.clases) and not cobertura,
                "clases",
            ),
            PuntoControl(
                "profesores",
                "Profesores" if activos and not sin_habilitar
                else (contar(len(sin_habilitar), "profesor sin asignaturas o grados",
                             "profesores sin asignaturas o grados") if activos
                      else "Sin profesores"),
                bool(activos) and not sin_habilitar,
                "profesores",
            ),
            PuntoControl(
                "validacion",
                "Validación sin errores" if not errores
                else contar(len(errores), "error de validación", "errores de validación"),
                not errores,
                "validacion",
            ),
        ]  # fmt: skip

    # ------------------------------------------------------------------ escritura

    def guardar[T: BaseModel](self, entidad: T) -> T:
        guardada = self.repo.guardar(entidad)
        self._cambio()
        return guardada

    def guardar_configuracion(self, configuracion: Configuracion) -> None:
        self.repo.guardar_configuracion(configuracion)
        self._cambio()

    def guardar_plan(self, filas: Iterable[PlanEstudios]) -> None:
        """Guarda varias celdas del plan en una transacción (0 horas elimina la fila)."""
        with self.repo.transaccion():
            for fila in filas:
                self.repo.guardar(fila)
        self._cambio()

    def guardar_grupo(
        self, grupo: Grupo, divisiones: list[Division], quitar: Iterable[int] = ()
    ) -> Grupo:
        """Guarda un grupo con sus divisiones; `quitar` son ids de divisiones a eliminar."""
        with self.repo.transaccion():
            guardado = self.repo.guardar(grupo)
            for ident in quitar:
                self.repo.eliminar(Division, ident)
            for division in divisiones:
                self.repo.guardar(division.model_copy(update={"grupo_id": guardado.id}))
        self._cambio()
        return guardado

    def afectados(self, tipo: type[BaseModel], ident: int) -> dict[str, int]:
        return self.repo.afectados_por_eliminar(tipo, ident)

    def eliminar(self, tipo: type[BaseModel], ident: int) -> dict[str, int]:
        afectados = self.repo.eliminar(tipo, ident)
        self._cambio()
        return afectados

    def profesor_en_uso(self, ident: int) -> bool:
        return self.repo.profesor_en_uso(ident)

    def activar_profesor(self, ident: int, activo: bool) -> None:
        self.repo.desactivar_profesor(ident, activo)
        self._cambio()

    # ------------------------------------------------------------------ clases

    def sincronizar_clases(self) -> ResultadoSincronizacion:
        """Crea las clases del plan que falten (§5.2), en una transacción."""
        resultado = sincronizar_con_plan(self.datos)
        with self.repo.transaccion():
            resultado.nuevas = [self.repo.guardar(c) for c in resultado.nuevas]
        self._cambio()
        return resultado

    def juntar_clases(self, clases: list[int]) -> Clase:
        """Une varias clases de la misma asignatura (de grupos del mismo nivel) en una clase
        conjunta. Conserva la primera (horas y profesores) y elimina las demás."""
        por_clase = por_id(self.datos.clases)
        elegidas = [por_clase[c] for c in clases]
        primera = elegidas[0]
        if any(c.asignatura_id != primera.asignatura_id for c in elegidas):
            raise ValueError("Solo se pueden juntar clases de la misma asignatura.")
        destinatarios = list(dict.fromkeys(d for c in elegidas for d in c.destinatarios))
        with self.repo.transaccion():
            unida = self.repo.guardar(
                primera.model_copy(update={"destinatarios": destinatarios, "origen": "manual"})
            )
            for otra in elegidas[1:]:
                self.repo.eliminar(Clase, otra.id or 0)
        self._cambio()
        return unida

    def dividir_clase(self, clase_id: int, division_id: int) -> list[Clase]:
        """Sustituye una clase de grupo completo por una clase por parte de la división, con
        las mismas horas."""
        clase = por_id(self.datos.clases)[clase_id]
        division = por_id(self.datos.divisiones)[division_id]
        if len(clase.destinatarios) != 1 or clase.destinatarios[0].grupo_id != division.grupo_id:
            raise ValueError("Solo se puede dividir una clase del grupo de la división.")
        with self.repo.transaccion():
            nuevas = [
                self.repo.guardar(
                    Clase(
                        asignatura_id=clase.asignatura_id,
                        destinatarios=[
                            Destinatario(grupo_id=division.grupo_id, division_id=division_id,
                                         parte=parte)
                        ],
                        horas_semanales=clase.horas_semanales,
                        origen="manual",
                    )
                )
                for parte in division.partes
            ]  # fmt: skip
            self.repo.eliminar(Clase, clase_id)
        self._cambio()
        return nuevas

    def candidatos(self, clase: Clase) -> list[Profesor]:
        """Profesores activos habilitados para la clase (sin importar los fijos actuales)."""
        libre = clase.model_copy(update={"profesores": []})
        ids = set(profesores_posibles(self.datos, libre))
        return [p for p in self.datos.profesores if p.id in ids]

    # ------------------------------------------------------------------ soluciones

    def soluciones(self) -> list[ResumenSolucion]:
        return self.repo.listar_soluciones()

    def cargar_solucion(self, ident: int) -> Solucion:
        return self.repo.cargar_solucion(ident)

    def guardar_solucion(self, solucion: Solucion) -> Solucion:
        guardada = self.repo.guardar_solucion(solucion)
        self._cambio()
        return guardada

    def marcar_vigente(self, ident: int | None) -> None:
        self.repo.marcar_vigente(ident)
        self._cambio()

    def eliminar_solucion(self, ident: int) -> None:
        self.repo.eliminar_solucion(ident)
        self._cambio()

    def desactualizada(self, solucion: ResumenSolucion | Solucion) -> bool:
        return solucion.huella_niveles != self.datos.huella_niveles()

    def referencia_de(self, solucion: Solucion) -> Solucion | None:
        """Con qué se compara una solución (§13.5): la de la que partió (`base_id`) o, si no
        tiene, el vigente (si es otra)."""
        if solucion.base_id is not None:
            try:
                return self.cargar_solucion(solucion.base_id)
            except KeyError:
                pass
        vigente = self.vigente()
        if vigente is not None and vigente.id != solucion.id:
            return self.cargar_solucion(vigente.id)
        return None

    def comparacion_de(self, solucion: Solucion) -> tuple[Solucion, Comparacion] | None:
        referencia = self.referencia_de(solucion)
        if referencia is None:
            return None
        return referencia, comparar(referencia, solucion)

    def exportar_excel(self, solucion: Solucion, ruta: Path | str) -> Path:
        """Exporta con la hoja `Cambios` si hay con qué comparar."""
        comparada = self.comparacion_de(solucion)
        cambios = None
        if comparada is not None:
            cambios = [
                FilaCambio(
                    c.clase,
                    c.antes.texto() if c.antes else "—",
                    c.despues.texto() if c.despues else "—",
                    c.descripcion,
                )
                for c in comparada[1].cambios
            ]
        return exportar_excel(self.datos, solucion, ruta, cambios=cambios)

    def exportar_pdf(
        self,
        solucion: Solucion,
        ruta: Path | str,
        grupos: Iterable[str] | None = None,
        profesores: Iterable[str] | None = None,
    ) -> tuple[Path, int]:
        """PDF con una página por grupo y por profesor elegidos (`None` = todos)."""
        from timetabling.exportacion.pdf import exportar_pdf

        return exportar_pdf(self.datos, solucion, ruta, grupos=grupos, profesores=profesores)

    def origen_fijas(self, bloqueadas: int = 0, de_donde: str = "") -> str:
        """Texto para la pantalla Generar: cuántas fijas hay y de dónde vienen (§12.5)."""
        partes = []
        if self.datos.fijas:
            partes.append(f"{len(self.datos.fijas)} capturadas en el proyecto")
        if bloqueadas:
            partes.append(f"{bloqueadas} clases bloqueadas en «{de_donde}»")
        if not partes:
            return "No hay asignaciones fijas: bloquee clases en el Editor para fijarlas."
        return "Asignaciones fijas: " + " y ".join(partes) + "."

    # ------------------------------------------------------------------ importación (§15)

    def importar_horarios(
        self, hojas: list[horarios_excel.HojaLeida], mapeo: horarios_excel.MapeoHorarios
    ) -> Resultado:
        from timetabling.servicios.importacion import importar_horarios

        resultado = importar_horarios(self.repo, hojas, mapeo)
        self._cambio()
        return resultado

    def importar_maestros(
        self, bloques: list[maestros_excel.BloqueMaestro], mapeo: maestros_excel.MapeoMaestros
    ) -> tuple[maestros_excel.ResultadoMaestros, Solucion | None]:
        from timetabling.servicios.importacion import importar_maestros

        resultado = importar_maestros(self.repo, bloques, mapeo)
        self._cambio()
        return resultado

    # ------------------------------------------------------------------ archivo

    def guardar_como(self, ruta: Path | str) -> Path:
        return self.repo.guardar_como(ruta)

    def listar_respaldos(self) -> list[Respaldo]:
        return self.repo.listar_respaldos()

    def restaurar_respaldo(self, ruta: Path | str) -> None:
        self.repo.restaurar_respaldo(ruta)
        self._cambio()
