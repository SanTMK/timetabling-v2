"""Creado con Claude.

Repositorio del proyecto `.horario` (§6): abre y crea archivos SQLite, lee y escribe todas las
entidades, borra con cascadas controladas y hace respaldos. Cada operación compuesta se ejecuta
en una transacción.
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Self, TypeVar

from pydantic import BaseModel

from timetabling.dominio.modelos import (
    ESTADOS_VALIDOS_PARA_VIGENTE,
    AliasImportacion,
    Asignacion,
    AsignacionFija,
    Asignatura,
    Ausencia,
    BloqueoGrupo,
    Clase,
    Configuracion,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Division,
    Espacio,
    EstadoSolucion,
    Evento,
    EventoProfesor,
    FranjaGuardada,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    RangoFranjas,
    Receso,
    ReglasAsignatura,
    ReglasAsignaturaNivel,
    Solucion,
    Suplencia,
    Violacion,
)
from timetabling.persistencia import archivo, migraciones, respaldos
from timetabling.persistencia.archivo import Aviso
from timetabling.persistencia.migraciones import ErrorArchivoNoValido, ErrorProyecto

UMBRAL_RESPALDO_CASCADA = 20
"""Un borrado que afecta más filas que esto hace un respaldo previo (§6.4)."""

E = TypeVar("E", bound=BaseModel)


class ErrorProfesorEnUso(ErrorProyecto):
    """El profesor aparece en un horario guardado o en una suplencia: se debe desactivar."""


class ErrorSolucion(ErrorProyecto):
    """Operación no permitida sobre una solución."""


@dataclass(frozen=True)
class ResumenSolucion:
    id: int
    nombre: str
    fecha: datetime
    estado: EstadoSolucion
    origen: str
    vigente: bool
    base_id: int | None
    huella_niveles: str
    asignaciones: int


_TABLAS: dict[type[BaseModel], str] = {
    Nivel: "niveles",
    Grado: "grados",
    Grupo: "grupos",
    Division: "divisiones",
    Asignatura: "asignaturas",
    Profesor: "profesores",
    Espacio: "espacios",
    AliasImportacion: "alias_importacion",
    Clase: "clases",
    AsignacionFija: "asignaciones_fijas",
    Solucion: "soluciones",
    Ausencia: "ausencias",
    Suplencia: "suplencias",
}

ETIQUETAS: dict[str, str] = {
    "niveles": "niveles",
    "recesos": "recesos",
    "eventos_nivel": "eventos de nivel",
    "duraciones_especiales": "duraciones especiales",
    "grados": "grados",
    "grupos": "grupos",
    "bloqueos_grupo": "bloqueos de grupo",
    "divisiones": "divisiones",
    "asignaturas": "asignaturas",
    "reglas_asignatura_nivel": "reglas por nivel",
    "rangos_franjas": "rangos de franjas",
    "plan": "filas del plan",
    "profesores": "profesores",
    "profesor_asignaturas": "habilitaciones por asignatura",
    "profesor_grados": "habilitaciones por grado",
    "disponibilidad": "rangos de disponibilidad",
    "eventos_profesor": "eventos de profesor",
    "espacios": "espacios",
    "alias_importacion": "alias de importación",
    "clases": "clases",
    "clase_destinatarios": "destinatarios de clase",
    "clase_profesores": "profesores de clase",
    "asignaciones_fijas": "asignaciones fijas",
    "soluciones": "soluciones",
    "franjas_guardadas": "franjas guardadas",
    "asignaciones": "asignaciones de horarios",
    "ausencias": "ausencias",
    "suplencias": "suplencias",
}

# Referencias que quedan en NULL al borrar (se informan aparte).
_REFERENCIAS_NULABLES: tuple[tuple[str, str, str], ...] = (
    ("asignaciones", "clase_id", "asignaciones de horarios que pierden su clase"),
    ("asignaciones", "profesor_id", "asignaciones de horarios que pierden su profesor"),
    ("grupos", "titular_id", "grupos que pierden su titular"),
    ("asignaciones_fijas", "profesor_id", "asignaciones fijas que pierden su profesor"),
)


def _dias(texto: str) -> list[Any]:
    return list(texto)


def _conectar(ruta: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(ruta), isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.DatabaseError as error:
        con.close()
        raise ErrorArchivoNoValido(f"«{ruta.name}» no es un proyecto de horarios.") from error
    return con


class Repositorio:
    """Acceso a un archivo de proyecto abierto. Úselo como administrador de contexto."""

    def __init__(self, ruta: Path, con: sqlite3.Connection) -> None:
        self.ruta = ruta
        self._con = con
        self._profundidad = 0
        self.avisos: list[Aviso] = []
        self._bloqueo_propio = False

    # ------------------------------------------------------------------ apertura

    @classmethod
    def crear(cls, ruta: Path | str, configuracion: Configuracion | None = None) -> Self:
        """Crea un proyecto nuevo y vacío. Falla si el archivo ya existe."""
        ruta = Path(ruta)
        if ruta.exists():
            raise FileExistsError(f"Ya existe «{ruta}».")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        repo = cls(ruta, _conectar(ruta))
        try:
            with repo.transaccion() as con:
                migraciones.crear_esquema(con)
                con.execute(
                    "INSERT INTO configuracion (id, datos) VALUES (1, ?)",
                    ((configuracion or Configuracion()).model_dump_json(),),
                )
        except BaseException:
            repo._con.close()
            ruta.unlink(missing_ok=True)
            raise
        repo._preparar_avisos()
        return repo

    @classmethod
    def abrir(cls, ruta: Path | str, respaldo_diario: bool = True) -> Self:
        """Abre un proyecto existente: comprueba la versión, migra si hace falta, toma el
        bloqueo y hace el respaldo del día."""
        ruta = Path(ruta)
        if not ruta.is_file():
            raise FileNotFoundError(f"No existe «{ruta}».")
        con = _conectar(ruta)
        repo = cls(ruta, con)
        try:
            version = migraciones.leer_version(con)
            migraciones.verificar_version(version)
            if version < migraciones.VERSION_ESQUEMA:
                repo.crear_respaldo()
                with repo.transaccion() as c:
                    migraciones.migrar(c, version)
            if respaldo_diario and not respaldos.hay_respaldo_del_dia(ruta, date.today()):
                repo.crear_respaldo()
        except BaseException:
            con.close()
            raise
        repo._preparar_avisos()
        return repo

    def _preparar_avisos(self) -> None:
        aviso = archivo.aviso_carpeta_sincronizada(self.ruta.resolve())
        if aviso:
            self.avisos.append(aviso)
        self._bloqueo_propio, aviso_bloqueo = archivo.tomar_bloqueo(self.ruta)
        if aviso_bloqueo:
            self.avisos.append(aviso_bloqueo)

    def cerrar(self) -> None:
        self._con.close()
        if self._bloqueo_propio:
            archivo.soltar_bloqueo(self.ruta)
            self._bloqueo_propio = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.cerrar()

    @property
    def conexion(self) -> sqlite3.Connection:
        """Conexión subyacente (para pruebas y diagnósticos de solo lectura)."""
        return self._con

    # ------------------------------------------------------------------ transacciones

    @contextmanager
    def transaccion(self) -> Iterator[sqlite3.Connection]:
        """Transacción (o punto de guardado si ya hay una en curso)."""
        nivel = self._profundidad
        punto = f"punto_{nivel}"
        self._con.execute("BEGIN IMMEDIATE" if nivel == 0 else f"SAVEPOINT {punto}")
        self._profundidad += 1
        try:
            yield self._con
        except BaseException:
            if nivel == 0:
                self._con.execute("ROLLBACK")
            else:
                self._con.execute(f"ROLLBACK TO {punto}")
                self._con.execute(f"RELEASE {punto}")
            raise
        else:
            self._con.execute("COMMIT" if nivel == 0 else f"RELEASE {punto}")
        finally:
            self._profundidad = nivel

    # ------------------------------------------------------------------ respaldos

    def crear_respaldo(self) -> Path:
        return respaldos.respaldar_conexion(self._con, self.ruta, self._conservar_respaldos())

    def _conservar_respaldos(self) -> int:
        try:
            return self.cargar_configuracion().respaldos_a_conservar
        except (sqlite3.DatabaseError, ValueError):
            return Configuracion.model_fields["respaldos_a_conservar"].default  # type: ignore[no-any-return]

    def listar_respaldos(self) -> list[respaldos.Respaldo]:
        return respaldos.listar_respaldos(self.ruta)

    def restaurar_respaldo(self, ruta_respaldo: Path | str) -> None:
        """Sustituye el contenido del proyecto por el de un respaldo (respaldando antes el
        estado actual)."""
        fuente = _conectar(Path(ruta_respaldo))
        try:
            version = migraciones.leer_version(fuente)
            migraciones.verificar_version(version)
            self.crear_respaldo()
            fuente.backup(self._con)
        finally:
            fuente.close()
        self._con.execute("PRAGMA foreign_keys = ON")
        if version < migraciones.VERSION_ESQUEMA:
            with self.transaccion() as con:
                migraciones.migrar(con, version)

    def guardar_como(self, ruta_nueva: Path | str) -> Path:
        """Copia el proyecto a otro archivo (el repositorio sigue apuntando al original)."""
        destino = Path(ruta_nueva)
        if destino.exists():
            raise FileExistsError(f"Ya existe «{destino}».")
        copia = sqlite3.connect(str(destino))
        try:
            self._con.backup(copia)
            copia.execute("PRAGMA journal_mode = DELETE")
        finally:
            copia.close()
        return destino

    # ------------------------------------------------------------------ configuración

    def cargar_configuracion(self) -> Configuracion:
        fila = self._con.execute("SELECT datos FROM configuracion WHERE id = 1").fetchone()
        return Configuracion.model_validate_json(fila["datos"]) if fila else Configuracion()

    def guardar_configuracion(self, configuracion: Configuracion) -> None:
        with self.transaccion() as con:
            con.execute(
                "INSERT INTO configuracion (id, datos) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET datos = excluded.datos",
                (configuracion.model_dump_json(),),
            )

    # ------------------------------------------------------------------ escritura genérica

    def _upsert(self, tabla: str, ident: int | None, valores: dict[str, Any]) -> int:
        columnas = list(valores)
        if ident is None:
            cursor = self._con.execute(
                f"INSERT INTO {tabla} ({', '.join(columnas)}) "
                f"VALUES ({', '.join('?' for _ in columnas)})",
                list(valores.values()),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid
        asignaciones = ", ".join(f"{c} = excluded.{c}" for c in columnas)
        self._con.execute(
            f"INSERT INTO {tabla} (id, {', '.join(columnas)}) "
            f"VALUES (?, {', '.join('?' for _ in columnas)}) "
            f"ON CONFLICT(id) DO UPDATE SET {asignaciones}",
            [ident, *valores.values()],
        )
        return ident

    def _reemplazar_hijos(
        self, tabla: str, columna: str, padre: int, filas: list[dict[str, Any]]
    ) -> None:
        self._con.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (padre,))
        for orden, fila in enumerate(filas):
            completa = {columna: padre, **fila}
            if "orden" not in completa and tabla not in ("duraciones_especiales",):
                completa["orden"] = orden
            self._con.execute(
                f"INSERT INTO {tabla} ({', '.join(completa)}) "
                f"VALUES ({', '.join('?' for _ in completa)})",
                list(completa.values()),
            )

    def guardar(self, entidad: E) -> E:
        """Inserta o actualiza una entidad (con sus datos dependientes) y la devuelve con id."""
        escritor = self._escritores().get(type(entidad))
        if escritor is None:
            raise TypeError(f"No se puede guardar un {type(entidad).__name__}.")
        with self.transaccion():
            ident = escritor(entidad)
        if isinstance(entidad, Solucion):
            return self.cargar_solucion(ident)  # type: ignore[return-value]
        if "id" in type(entidad).model_fields:
            return entidad.model_copy(update={"id": ident})
        return entidad

    def _escritores(self) -> dict[type[BaseModel], Callable[[Any], int]]:
        return {
            Nivel: self._escribir_nivel,
            Grado: self._escribir_grado,
            Grupo: self._escribir_grupo,
            Division: self._escribir_division,
            Asignatura: self._escribir_asignatura,
            PlanEstudios: self._escribir_plan,
            Profesor: self._escribir_profesor,
            Espacio: self._escribir_espacio,
            AliasImportacion: self._escribir_alias,
            Clase: self._escribir_clase,
            AsignacionFija: self._escribir_fija,
            Solucion: self._escribir_solucion,
            Ausencia: self._escribir_ausencia,
            Suplencia: self._escribir_suplencia,
        }

    def _escribir_nivel(self, n: Nivel) -> int:
        ident = self._upsert(
            "niveles",
            n.id,
            {
                "nombre": n.nombre,
                "duracion_min": n.duracion_min,
                "inicio_jornada": n.inicio_jornada,
                "fin_jornada": n.fin_jornada,
                "dias": "".join(n.dias),
                "huecos_alumnos": n.huecos_alumnos,
                "preferir_titular": int(n.preferir_titular),
            },
        )
        self._reemplazar_hijos(
            "recesos",
            "nivel_id",
            ident,
            [{"nombre": r.nombre, "inicio": r.inicio, "fin": r.fin} for r in n.recesos],
        )
        self._reemplazar_hijos(
            "eventos_nivel",
            "nivel_id",
            ident,
            [
                {"nombre": e.nombre, "dia": e.dia, "inicio": e.inicio, "fin": e.fin}
                for e in n.eventos
            ],
        )
        self._reemplazar_hijos(
            "duraciones_especiales",
            "nivel_id",
            ident,
            [{"indice": i, "minutos": m} for i, m in n.duraciones_especiales.items()],
        )
        return ident

    def _escribir_grado(self, g: Grado) -> int:
        return self._upsert("grados", g.id, {"nivel_id": g.nivel_id, "nombre": g.nombre})

    def _escribir_grupo(self, g: Grupo) -> int:
        ident = self._upsert(
            "grupos",
            g.id,
            {
                "grado_id": g.grado_id,
                "seccion": g.seccion,
                "estudiantes": g.estudiantes,
                "titular_id": g.titular_id,
            },
        )
        self._reemplazar_hijos(
            "bloqueos_grupo",
            "grupo_id",
            ident,
            [
                {"nombre": b.nombre, "dia": b.dia, "inicio": b.inicio, "fin": b.fin}
                for b in g.bloqueos
            ],
        )
        return ident

    def _escribir_division(self, d: Division) -> int:
        return self._upsert(
            "divisiones",
            d.id,
            {
                "grupo_id": d.grupo_id,
                "nombre": d.nombre,
                "partes": json.dumps(d.partes, ensure_ascii=False),
                "simultanea": int(d.simultanea),
            },
        )

    @staticmethod
    def _filas_rangos(
        rangos: list[RangoFranjas], tipo: str, nivel_id: int | None
    ) -> list[dict[str, Any]]:
        return [
            {
                "nivel_id": nivel_id,
                "tipo": tipo,
                "dias": "".join(r.dias),
                "desde_indice": r.desde_indice,
                "hasta_indice": r.hasta_indice,
                "desde": r.desde,
                "hasta": r.hasta,
            }
            for r in rangos
        ]

    def _escribir_asignatura(self, a: Asignatura) -> int:
        reglas = a.reglas_por_defecto
        ident = self._upsert(
            "asignaturas",
            a.id,
            {
                "nombre": a.nombre,
                "color": a.color,
                "espacio_requerido": a.espacio_requerido,
                "max_horas_dia": reglas.max_horas_dia,
                "bloque_doble": reglas.bloque_doble,
            },
        )
        rangos = self._filas_rangos(reglas.franjas_prohibidas, "prohibida", None)
        rangos += self._filas_rangos(reglas.franjas_preferidas, "preferida", None)
        filas_nivel: list[dict[str, Any]] = []
        for propia in a.reglas_por_nivel:
            filas_nivel.append(
                {
                    "nivel_id": propia.nivel_id,
                    "max_horas_dia": propia.max_horas_dia,
                    "bloque_doble": propia.bloque_doble,
                    "define_prohibidas": int(propia.franjas_prohibidas is not None),
                    "define_preferidas": int(propia.franjas_preferidas is not None),
                }
            )
            rangos += self._filas_rangos(
                propia.franjas_prohibidas or [], "prohibida", propia.nivel_id
            )
            rangos += self._filas_rangos(
                propia.franjas_preferidas or [], "preferida", propia.nivel_id
            )
        self._con.execute("DELETE FROM reglas_asignatura_nivel WHERE asignatura_id = ?", (ident,))
        for fila in filas_nivel:
            self._con.execute(
                "INSERT INTO reglas_asignatura_nivel (asignatura_id, nivel_id, max_horas_dia, "
                "bloque_doble, define_prohibidas, define_preferidas) VALUES (?, ?, ?, ?, ?, ?)",
                (ident, *fila.values()),
            )
        self._reemplazar_hijos("rangos_franjas", "asignatura_id", ident, rangos)
        return ident

    def _escribir_plan(self, fila: PlanEstudios) -> int:
        """Guardar 0 horas elimina la fila (§5.1)."""
        if fila.horas_semanales == 0:
            self._con.execute(
                "DELETE FROM plan WHERE grado_id = ? AND asignatura_id = ?",
                (fila.grado_id, fila.asignatura_id),
            )
            return 0
        self._con.execute(
            "INSERT INTO plan (grado_id, asignatura_id, horas_semanales) VALUES (?, ?, ?) "
            "ON CONFLICT(grado_id, asignatura_id) DO UPDATE SET "
            "horas_semanales = excluded.horas_semanales",
            (fila.grado_id, fila.asignatura_id, fila.horas_semanales),
        )
        return 0

    def _escribir_profesor(self, p: Profesor) -> int:
        ident = self._upsert(
            "profesores",
            p.id,
            {
                "nombre": p.nombre,
                "activo": int(p.activo),
                "disponible_toda_la_jornada": int(p.disponible_toda_la_jornada),
                "carga_max_semanal_min": p.carga_max_semanal_min,
                "carga_max_diaria_min": p.carga_max_diaria_min,
                "carga_min_semanal_min": p.carga_min_semanal_min,
                "max_dias": p.max_dias,
                "max_minutos_continuos": p.max_minutos_continuos,
            },
        )
        self._reemplazar_hijos(
            "profesor_asignaturas",
            "profesor_id",
            ident,
            [{"asignatura_id": a, "tipo": "imparte"} for a in p.asignaturas]
            + [{"asignatura_id": a, "tipo": "suplencia"} for a in p.suplencia_asignaturas],
        )
        self._reemplazar_hijos(
            "profesor_grados",
            "profesor_id",
            ident,
            [{"grado_id": g, "tipo": "imparte"} for g in p.grados]
            + [{"grado_id": g, "tipo": "suplencia"} for g in p.suplencia_grados],
        )
        self._reemplazar_hijos(
            "disponibilidad",
            "profesor_id",
            ident,
            [
                {"dia": d.dia, "inicio": d.inicio, "fin": d.fin, "tipo": d.tipo}
                for d in p.disponibilidad
            ],
        )
        self._reemplazar_hijos(
            "eventos_profesor",
            "profesor_id",
            ident,
            [
                {"nombre": e.nombre, "dia": e.dia, "inicio": e.inicio, "fin": e.fin}
                for e in p.eventos
            ],
        )
        return ident

    def _escribir_espacio(self, e: Espacio) -> int:
        return self._upsert(
            "espacios", e.id, {"nombre": e.nombre, "tipo": e.tipo, "cantidad": e.cantidad}
        )

    def _escribir_alias(self, a: AliasImportacion) -> int:
        return self._upsert(
            "alias_importacion", a.id, {"texto": a.texto, "asignatura_id": a.asignatura_id}
        )

    def _escribir_clase(self, c: Clase) -> int:
        ident = self._upsert(
            "clases",
            c.id,
            {
                "asignatura_id": c.asignatura_id,
                "horas_semanales": c.horas_semanales,
                "sobrescribe_espacio": int(c.sobrescribe_espacio),
                "espacio_requerido": c.espacio_requerido,
                "origen": c.origen,
            },
        )
        self._reemplazar_hijos(
            "clase_destinatarios",
            "clase_id",
            ident,
            [
                {"grupo_id": d.grupo_id, "division_id": d.division_id, "parte": d.parte}
                for d in c.destinatarios
            ],
        )
        self._reemplazar_hijos(
            "clase_profesores", "clase_id", ident, [{"profesor_id": p} for p in c.profesores]
        )
        return ident

    def _escribir_fija(self, f: AsignacionFija) -> int:
        return self._upsert(
            "asignaciones_fijas",
            f.id,
            {
                "clase_id": f.clase_id,
                "profesor_id": f.profesor_id,
                "dia": f.dia,
                "indice_franja": f.indice_franja,
            },
        )

    def _escribir_ausencia(self, a: Ausencia) -> int:
        return self._upsert(
            "ausencias",
            a.id,
            {
                "profesor_id": a.profesor_id,
                "fecha_inicio": a.fecha_inicio.isoformat(),
                "fecha_fin": a.fecha_fin.isoformat(),
                "desde": a.desde,
                "hasta": a.hasta,
                "motivo": a.motivo,
            },
        )

    def _escribir_suplencia(self, s: Suplencia) -> int:
        return self._upsert(
            "suplencias",
            s.id,
            {
                "fecha": s.fecha.isoformat(),
                "solucion_id": s.solucion_id,
                "asignacion_id": s.asignacion_id,
                "profesor_ausente_id": s.profesor_ausente_id,
                "suplente_id": s.suplente_id,
                "nota": s.nota,
            },
        )

    # ------------------------------------------------------------------ lectura

    def _filas(self, sql: str, *parametros: Any) -> list[sqlite3.Row]:
        return self._con.execute(sql, parametros).fetchall()

    def _hijos(self, tabla: str, columna: str) -> dict[int, list[sqlite3.Row]]:
        agrupados: dict[int, list[sqlite3.Row]] = defaultdict(list)
        orden = "orden" if tabla != "duraciones_especiales" else "indice"
        for fila in self._filas(f"SELECT * FROM {tabla} ORDER BY {columna}, {orden}"):
            agrupados[fila[columna]].append(fila)
        return agrupados

    def cargar_datos(self) -> DatosEscuela:
        """Lee todos los datos de captura de la escuela."""
        return DatosEscuela(
            configuracion=self.cargar_configuracion(),
            niveles=self._leer_niveles(),
            grados=[
                Grado(id=f["id"], nivel_id=f["nivel_id"], nombre=f["nombre"])
                for f in self._filas("SELECT * FROM grados ORDER BY id")
            ],
            grupos=self._leer_grupos(),
            divisiones=[
                Division(
                    id=f["id"],
                    grupo_id=f["grupo_id"],
                    nombre=f["nombre"],
                    partes=json.loads(f["partes"]),
                    simultanea=bool(f["simultanea"]),
                )
                for f in self._filas("SELECT * FROM divisiones ORDER BY id")
            ],
            asignaturas=self._leer_asignaturas(),
            plan=[
                PlanEstudios(
                    grado_id=f["grado_id"],
                    asignatura_id=f["asignatura_id"],
                    horas_semanales=f["horas_semanales"],
                )
                for f in self._filas("SELECT * FROM plan ORDER BY grado_id, asignatura_id")
            ],
            profesores=self._leer_profesores(),
            espacios=[
                Espacio(id=f["id"], nombre=f["nombre"], tipo=f["tipo"], cantidad=f["cantidad"])
                for f in self._filas("SELECT * FROM espacios ORDER BY id")
            ],
            alias=[
                AliasImportacion(id=f["id"], texto=f["texto"], asignatura_id=f["asignatura_id"])
                for f in self._filas("SELECT * FROM alias_importacion ORDER BY id")
            ],
            clases=self._leer_clases(),
            fijas=[
                AsignacionFija(
                    id=f["id"],
                    clase_id=f["clase_id"],
                    profesor_id=f["profesor_id"],
                    dia=f["dia"],
                    indice_franja=f["indice_franja"],
                )
                for f in self._filas("SELECT * FROM asignaciones_fijas ORDER BY id")
            ],
        )

    def _leer_niveles(self) -> list[Nivel]:
        recesos = self._hijos("recesos", "nivel_id")
        eventos = self._hijos("eventos_nivel", "nivel_id")
        especiales = self._hijos("duraciones_especiales", "nivel_id")
        return [
            Nivel(
                id=f["id"],
                nombre=f["nombre"],
                duracion_min=f["duracion_min"],
                inicio_jornada=f["inicio_jornada"],
                fin_jornada=f["fin_jornada"],
                dias=_dias(f["dias"]),
                recesos=[
                    Receso(nombre=r["nombre"], inicio=r["inicio"], fin=r["fin"])
                    for r in recesos[f["id"]]
                ],
                eventos=[
                    Evento(nombre=e["nombre"], dia=e["dia"], inicio=e["inicio"], fin=e["fin"])
                    for e in eventos[f["id"]]
                ],
                duraciones_especiales={d["indice"]: d["minutos"] for d in especiales[f["id"]]},
                huecos_alumnos=f["huecos_alumnos"],
                preferir_titular=bool(f["preferir_titular"]),
            )
            for f in self._filas("SELECT * FROM niveles ORDER BY id")
        ]

    def _leer_grupos(self) -> list[Grupo]:
        bloqueos = self._hijos("bloqueos_grupo", "grupo_id")
        return [
            Grupo(
                id=f["id"],
                grado_id=f["grado_id"],
                seccion=f["seccion"],
                estudiantes=f["estudiantes"],
                titular_id=f["titular_id"],
                bloqueos=[
                    BloqueoGrupo(nombre=b["nombre"], dia=b["dia"], inicio=b["inicio"], fin=b["fin"])
                    for b in bloqueos[f["id"]]
                ],
            )
            for f in self._filas("SELECT * FROM grupos ORDER BY id")
        ]

    def _leer_asignaturas(self) -> list[Asignatura]:
        rangos: dict[tuple[int, int | None, str], list[RangoFranjas]] = defaultdict(list)
        for r in self._filas("SELECT * FROM rangos_franjas ORDER BY asignatura_id, orden"):
            rangos[(r["asignatura_id"], r["nivel_id"], r["tipo"])].append(
                RangoFranjas(
                    dias=tuple(_dias(r["dias"])),
                    desde_indice=r["desde_indice"],
                    hasta_indice=r["hasta_indice"],
                    desde=r["desde"],
                    hasta=r["hasta"],
                )
            )
        por_nivel = self._hijos_sin_orden("reglas_asignatura_nivel", "asignatura_id", "nivel_id")
        resultado: list[Asignatura] = []
        for f in self._filas("SELECT * FROM asignaturas ORDER BY id"):
            ident = f["id"]
            resultado.append(
                Asignatura(
                    id=ident,
                    nombre=f["nombre"],
                    color=f["color"],
                    espacio_requerido=f["espacio_requerido"],
                    reglas_por_defecto=ReglasAsignatura(
                        max_horas_dia=f["max_horas_dia"],
                        bloque_doble=f["bloque_doble"],
                        franjas_prohibidas=rangos[(ident, None, "prohibida")],
                        franjas_preferidas=rangos[(ident, None, "preferida")],
                    ),
                    reglas_por_nivel=[
                        ReglasAsignaturaNivel(
                            nivel_id=r["nivel_id"],
                            max_horas_dia=r["max_horas_dia"],
                            bloque_doble=r["bloque_doble"],
                            franjas_prohibidas=(
                                rangos[(ident, r["nivel_id"], "prohibida")]
                                if r["define_prohibidas"]
                                else None
                            ),
                            franjas_preferidas=(
                                rangos[(ident, r["nivel_id"], "preferida")]
                                if r["define_preferidas"]
                                else None
                            ),
                        )
                        for r in por_nivel[ident]
                    ],
                )
            )
        return resultado

    def _hijos_sin_orden(
        self, tabla: str, columna: str, orden: str
    ) -> dict[int, list[sqlite3.Row]]:
        agrupados: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for fila in self._filas(f"SELECT * FROM {tabla} ORDER BY {columna}, {orden}"):
            agrupados[fila[columna]].append(fila)
        return agrupados

    def _leer_profesores(self) -> list[Profesor]:
        asignaturas = self._hijos("profesor_asignaturas", "profesor_id")
        grados = self._hijos("profesor_grados", "profesor_id")
        disponibilidad = self._hijos("disponibilidad", "profesor_id")
        eventos = self._hijos("eventos_profesor", "profesor_id")
        resultado: list[Profesor] = []
        for f in self._filas("SELECT * FROM profesores ORDER BY id"):
            ident = f["id"]
            resultado.append(
                Profesor(
                    id=ident,
                    nombre=f["nombre"],
                    activo=bool(f["activo"]),
                    asignaturas=[
                        a["asignatura_id"] for a in asignaturas[ident] if a["tipo"] == "imparte"
                    ],
                    grados=[g["grado_id"] for g in grados[ident] if g["tipo"] == "imparte"],
                    disponibilidad=[
                        Disponibilidad(
                            dia=d["dia"], inicio=d["inicio"], fin=d["fin"], tipo=d["tipo"]
                        )
                        for d in disponibilidad[ident]
                    ],
                    disponible_toda_la_jornada=bool(f["disponible_toda_la_jornada"]),
                    eventos=[
                        EventoProfesor(
                            nombre=e["nombre"], dia=e["dia"], inicio=e["inicio"], fin=e["fin"]
                        )
                        for e in eventos[ident]
                    ],
                    suplencia_asignaturas=[
                        a["asignatura_id"] for a in asignaturas[ident] if a["tipo"] == "suplencia"
                    ],
                    suplencia_grados=[
                        g["grado_id"] for g in grados[ident] if g["tipo"] == "suplencia"
                    ],
                    carga_max_semanal_min=f["carga_max_semanal_min"],
                    carga_max_diaria_min=f["carga_max_diaria_min"],
                    carga_min_semanal_min=f["carga_min_semanal_min"],
                    max_dias=f["max_dias"],
                    max_minutos_continuos=f["max_minutos_continuos"],
                )
            )
        return resultado

    def _leer_clases(self) -> list[Clase]:
        destinatarios = self._hijos("clase_destinatarios", "clase_id")
        profesores = self._hijos("clase_profesores", "clase_id")
        return [
            Clase(
                id=f["id"],
                asignatura_id=f["asignatura_id"],
                destinatarios=[
                    Destinatario(
                        grupo_id=d["grupo_id"], division_id=d["division_id"], parte=d["parte"]
                    )
                    for d in destinatarios[f["id"]]
                ],
                profesores=[p["profesor_id"] for p in profesores[f["id"]]],
                horas_semanales=f["horas_semanales"],
                sobrescribe_espacio=bool(f["sobrescribe_espacio"]),
                espacio_requerido=f["espacio_requerido"],
                origen=f["origen"],
            )
            for f in self._filas("SELECT * FROM clases ORDER BY id")
        ]

    # ------------------------------------------------------------------ reemplazo completo

    def reemplazar_datos(self, datos: DatosEscuela) -> list[str]:
        """Sustituye todos los datos de captura por `datos` en una transacción, con respaldo
        previo. Las soluciones se conservan. Las entidades se emparejan por id: las que faltan
        se borran, salvo los profesores en uso, que se desactivan. Devuelve los nombres de los
        profesores desactivados."""
        entidades: list[tuple[str, list[Any]]] = [
            ("niveles", datos.niveles),
            ("grados", datos.grados),
            ("grupos", datos.grupos),
            ("divisiones", datos.divisiones),
            ("asignaturas", datos.asignaturas),
            ("profesores", datos.profesores),
            ("espacios", datos.espacios),
            ("alias_importacion", datos.alias),
            ("clases", datos.clases),
            ("asignaciones_fijas", datos.fijas),
        ]
        for tabla, lista in entidades:
            if any(e.id is None for e in lista):
                raise ValueError(f"Todas las entidades de «{ETIQUETAS[tabla]}» necesitan id.")
        if self._hay_datos():
            self.crear_respaldo()
        desactivados: list[str] = []
        with self.transaccion() as con:
            for tabla, lista in reversed(entidades):
                ids = {e.id for e in lista}
                existentes = [f["id"] for f in con.execute(f"SELECT id FROM {tabla}")]
                for ident in existentes:
                    if ident in ids:
                        continue
                    if tabla == "profesores" and self.profesor_en_uso(ident):
                        nombre = con.execute(
                            "UPDATE profesores SET activo = 0 WHERE id = ? RETURNING nombre",
                            (ident,),
                        ).fetchone()["nombre"]
                        desactivados.append(nombre)
                        continue
                    con.execute(f"DELETE FROM {tabla} WHERE id = ?", (ident,))
            con.execute("DELETE FROM plan")
            self.guardar_configuracion(datos.configuracion)
            for entidad in [
                *datos.niveles,
                *datos.grados,
                *datos.asignaturas,
                *datos.profesores,
                *datos.grupos,
                *datos.divisiones,
                *datos.plan,
                *datos.espacios,
                *datos.alias,
                *datos.clases,
                *datos.fijas,
            ]:
                self._escritores()[type(entidad)](entidad)
            self._limpiar_clases_vacias()
        return desactivados

    def _hay_datos(self) -> bool:
        return any(
            self._con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
            for t in ("niveles", "profesores", "asignaturas", "soluciones")
        )

    # ------------------------------------------------------------------ borrado

    def profesor_en_uso(self, profesor_id: int) -> bool:
        """El profesor aparece en algún horario guardado o en una suplencia."""
        return bool(
            self._con.execute(
                "SELECT EXISTS (SELECT 1 FROM asignaciones WHERE profesor_id = ?) "
                "OR EXISTS (SELECT 1 FROM suplencias "
                "WHERE profesor_ausente_id = ? OR suplente_id = ?)",
                (profesor_id, profesor_id, profesor_id),
            ).fetchone()[0]
        )

    def desactivar_profesor(self, profesor_id: int, activo: bool = False) -> None:
        with self.transaccion() as con:
            con.execute("UPDATE profesores SET activo = ? WHERE id = ?", (int(activo), profesor_id))

    def _limpiar_clases_vacias(self) -> None:
        self._con.execute(
            "DELETE FROM clases WHERE id NOT IN (SELECT clase_id FROM clase_destinatarios)"
        )

    def _borrar(self, tabla: str, ident: int) -> None:
        self._con.execute(f"DELETE FROM {tabla} WHERE id = ?", (ident,))
        self._limpiar_clases_vacias()

    def _conteos(self) -> dict[str, int]:
        conteos = {
            tabla: self._con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            for tabla in ETIQUETAS
        }
        for tabla, columna, etiqueta in _REFERENCIAS_NULABLES:
            conteos[etiqueta] = self._con.execute(
                f"SELECT COUNT(*) FROM {tabla} WHERE {columna} IS NULL"
            ).fetchone()[0]
        return conteos

    def _comprobar_borrable(self, tipo: type[BaseModel], ident: int) -> str:
        tabla = _TABLAS.get(tipo)
        if tabla is None:
            raise TypeError(f"No se puede eliminar un {tipo.__name__}.")
        if tipo is Profesor and self.profesor_en_uso(ident):
            nombre = self._con.execute(
                "SELECT nombre FROM profesores WHERE id = ?", (ident,)
            ).fetchone()["nombre"]
            raise ErrorProfesorEnUso(
                f"«{nombre}» aparece en un horario guardado o en una suplencia y no se puede "
                "eliminar. Puede desactivarlo: no entrará al generador ni a las suplencias."
            )
        return tabla

    def afectados_por_eliminar(self, tipo: type[BaseModel], ident: int) -> dict[str, int]:
        """Cuenta lo que se borraría (o quedaría sin referencia) sin modificar nada."""
        tabla = self._comprobar_borrable(tipo, ident)
        antes = self._conteos()
        try:
            with self.transaccion():
                self._borrar(tabla, ident)
                despues = self._conteos()
                raise _Deshacer
        except _Deshacer:
            pass
        resultado: dict[str, int] = {}
        for clave, valor in antes.items():
            cambio = abs(despues[clave] - valor)
            if cambio:
                resultado[ETIQUETAS.get(clave, clave)] = cambio
        return resultado

    def eliminar(self, tipo: type[BaseModel], ident: int) -> dict[str, int]:
        """Elimina una entidad con sus dependientes. Respalda antes si se borran soluciones o
        muchas filas. Devuelve lo afectado."""
        tabla = self._comprobar_borrable(tipo, ident)
        afectados = self.afectados_por_eliminar(tipo, ident)
        filas = sum(v for k, v in afectados.items() if k in ETIQUETAS.values())
        if tipo is Solucion or filas > UMBRAL_RESPALDO_CASCADA:
            self.crear_respaldo()
        with self.transaccion():
            self._borrar(tabla, ident)
        return afectados

    # ------------------------------------------------------------------ soluciones

    def _escribir_solucion(self, s: Solucion) -> int:
        if s.vigente:
            self._comprobar_vigente(s)
            self._con.execute("UPDATE soluciones SET vigente = 0 WHERE vigente = 1")
        ident = self._upsert(
            "soluciones",
            s.id,
            {
                "nombre": s.nombre,
                "fecha": s.fecha.isoformat(),
                "estado": s.estado.value,
                "origen": s.origen,
                "tiempo_s": s.tiempo_s,
                "penalizaciones": json.dumps(s.penalizaciones),
                "penalizaciones_son_cota": int(s.penalizaciones_son_cota),
                "nota": s.nota,
                "vigente": int(s.vigente),
                "base_id": s.base_id,
                "huella_niveles": s.huella_niveles,
                "violaciones": json.dumps(
                    [v.model_dump() for v in s.violaciones], ensure_ascii=False
                ),
            },
        )
        self._con.execute("DELETE FROM franjas_guardadas WHERE solucion_id = ?", (ident,))
        ids_franja: list[int] = []
        for orden, franja in enumerate(s.franjas):
            cursor = self._con.execute(
                "INSERT INTO franjas_guardadas (solucion_id, orden, nivel_id, dia, indice, "
                "inicio, fin) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ident, orden, franja.nivel_id, franja.dia, franja.indice, franja.inicio,
                 franja.fin),
            )  # fmt: skip
            assert cursor.lastrowid is not None
            ids_franja.append(cursor.lastrowid)
        for a in s.asignaciones:
            self._con.execute(
                "INSERT INTO asignaciones (id, solucion_id, franja_id, clase_id, profesor_id, "
                "asignatura_nombre, grupos_texto, profesor_nombre, color, bloqueada) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (a.id, ident, ids_franja[a.franja], a.clase_id, a.profesor_id,
                 a.asignatura_nombre, a.grupos_texto, a.profesor_nombre, a.color,
                 int(a.bloqueada)),
            )  # fmt: skip
        return ident

    @staticmethod
    def _comprobar_vigente(s: Solucion) -> None:
        if s.estado not in ESTADOS_VALIDOS_PARA_VIGENTE or s.violaciones or not s.asignaciones:
            raise ErrorSolucion(
                f"«{s.nombre}» no se puede marcar como vigente: solo un horario válido y "
                "completo puede serlo."
            )

    def guardar_solucion(self, solucion: Solucion) -> Solucion:
        return self.guardar(solucion)

    def cargar_solucion(self, ident: int) -> Solucion:
        fila = self._con.execute("SELECT * FROM soluciones WHERE id = ?", (ident,)).fetchone()
        if fila is None:
            raise KeyError(f"No existe la solución {ident}.")
        franjas = self._filas(
            "SELECT * FROM franjas_guardadas WHERE solucion_id = ? ORDER BY orden", ident
        )
        posicion = {f["id"]: i for i, f in enumerate(franjas)}
        return Solucion(
            id=fila["id"],
            nombre=fila["nombre"],
            fecha=datetime.fromisoformat(fila["fecha"]),
            estado=EstadoSolucion(fila["estado"]),
            origen=fila["origen"],
            tiempo_s=fila["tiempo_s"],
            penalizaciones=json.loads(fila["penalizaciones"]),
            penalizaciones_son_cota=bool(fila["penalizaciones_son_cota"]),
            nota=fila["nota"],
            vigente=bool(fila["vigente"]),
            base_id=fila["base_id"],
            huella_niveles=fila["huella_niveles"],
            franjas=[
                FranjaGuardada(
                    nivel_id=f["nivel_id"],
                    dia=f["dia"],
                    indice=f["indice"],
                    inicio=f["inicio"],
                    fin=f["fin"],
                )
                for f in franjas
            ],
            asignaciones=[
                Asignacion(
                    id=a["id"],
                    clase_id=a["clase_id"],
                    franja=posicion[a["franja_id"]],
                    profesor_id=a["profesor_id"],
                    asignatura_nombre=a["asignatura_nombre"],
                    grupos_texto=a["grupos_texto"],
                    profesor_nombre=a["profesor_nombre"],
                    color=a["color"],
                    bloqueada=bool(a["bloqueada"]),
                )
                for a in self._filas(
                    "SELECT * FROM asignaciones WHERE solucion_id = ? ORDER BY id", ident
                )
            ],
            violaciones=[Violacion(**v) for v in json.loads(fila["violaciones"])],
        )

    def listar_soluciones(self) -> list[ResumenSolucion]:
        return [
            ResumenSolucion(
                id=f["id"],
                nombre=f["nombre"],
                fecha=datetime.fromisoformat(f["fecha"]),
                estado=EstadoSolucion(f["estado"]),
                origen=f["origen"],
                vigente=bool(f["vigente"]),
                base_id=f["base_id"],
                huella_niveles=f["huella_niveles"],
                asignaciones=f["n"],
            )
            for f in self._filas(
                "SELECT s.*, (SELECT COUNT(*) FROM asignaciones a WHERE a.solucion_id = s.id) "
                "AS n FROM soluciones s ORDER BY s.fecha DESC, s.id DESC"
            )
        ]

    def solucion_vigente_id(self) -> int | None:
        fila = self._con.execute("SELECT id FROM soluciones WHERE vigente = 1").fetchone()
        return None if fila is None else int(fila["id"])

    def marcar_vigente(self, ident: int | None) -> None:
        """Marca una solución válida como la vigente (o ninguna con `None`)."""
        with self.transaccion() as con:
            if ident is not None:
                self._comprobar_vigente(self.cargar_solucion(ident))
            con.execute("UPDATE soluciones SET vigente = 0 WHERE vigente = 1")
            if ident is not None:
                con.execute("UPDATE soluciones SET vigente = 1 WHERE id = ?", (ident,))

    def eliminar_solucion(self, ident: int) -> None:
        self.eliminar(Solucion, ident)

    # ------------------------------------------------------------------ ausencias y suplencias

    def listar_ausencias(self) -> list[Ausencia]:
        return [
            Ausencia(
                id=f["id"],
                profesor_id=f["profesor_id"],
                fecha_inicio=date.fromisoformat(f["fecha_inicio"]),
                fecha_fin=date.fromisoformat(f["fecha_fin"]),
                desde=f["desde"],
                hasta=f["hasta"],
                motivo=f["motivo"],
            )
            for f in self._filas("SELECT * FROM ausencias ORDER BY fecha_inicio, id")
        ]

    def listar_suplencias(
        self, desde: date | None = None, hasta: date | None = None
    ) -> list[Suplencia]:
        return [
            Suplencia(
                id=f["id"],
                fecha=date.fromisoformat(f["fecha"]),
                solucion_id=f["solucion_id"],
                asignacion_id=f["asignacion_id"],
                profesor_ausente_id=f["profesor_ausente_id"],
                suplente_id=f["suplente_id"],
                nota=f["nota"],
            )
            for f in self._filas(
                "SELECT * FROM suplencias WHERE fecha >= ? AND fecha <= ? ORDER BY fecha, id",
                (desde or date.min).isoformat(),
                (hasta or date.max).isoformat(),
            )
        ]


class _Deshacer(Exception):
    """Fuerza la reversión de una simulación de borrado."""
