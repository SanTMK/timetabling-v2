"""Creado con Claude.

Persistencia (§6): ida y vuelta de todas las entidades, cascadas, `SET NULL`, profesores en
uso, huella de niveles, respaldos, bloqueo de archivo, versiones y migraciones.
"""

import json
import os
import sqlite3
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from timetabling.cli import app
from timetabling.dominio.modelos import (
    AliasImportacion,
    Asignacion,
    AsignacionFija,
    Asignatura,
    Ausencia,
    Clase,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Division,
    EstadoSolucion,
    Evento,
    EventoProfesor,
    FranjaGuardada,
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
    huella_niveles,
)
from timetabling.ejemplo import crear_ejemplo, ejemplo_mediano, ejemplo_pequeno
from timetabling.persistencia import archivo, migraciones, respaldos
from timetabling.persistencia.migraciones import (
    ErrorArchivoNoValido,
    ErrorProyectoAnterior,
    ErrorVersionEsquema,
)
from timetabling.persistencia.repositorio import (
    ErrorProfesorEnUso,
    ErrorSolucion,
    Repositorio,
)

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _ordenado(datos: DatosEscuela) -> DatosEscuela:
    """El repositorio devuelve el plan ordenado por grado y asignatura."""
    return datos.model_copy(
        update={"plan": sorted(datos.plan, key=lambda f: (f.grado_id, f.asignatura_id))}
    )


def _proyecto(ruta: Path, datos: DatosEscuela | None = None) -> Repositorio:
    datos = datos or ejemplo_pequeno()
    repo = Repositorio.crear(ruta, datos.configuracion)
    repo.reemplazar_datos(datos)
    return repo


def _solucion(datos: DatosEscuela, **campos: object) -> Solucion:
    """Una solución mínima con dos asignaciones de la primera clase."""
    clase = datos.clases[0]
    nivel = datos.niveles[0]
    profesor = datos.profesores[0]
    assert clase.id is not None and profesor.id is not None
    valores: dict[str, object] = {
        "nombre": "Prueba",
        "fecha": datetime(2026, 11, 23, 9, 0, 0),
        "estado": EstadoSolucion.FACTIBLE,
        "origen": "generado",
        "tiempo_s": 12.5,
        "penalizaciones": {"B1": 3.0, "B2": 1.0},
        "penalizaciones_son_cota": True,
        "nota": "nota",
        "huella_niveles": datos.huella_niveles(),
        "franjas": [
            FranjaGuardada(nivel_id=nivel.id, dia="L", indice=0, inicio=450, fin=500),
            FranjaGuardada(nivel_id=nivel.id, dia="M", indice=1, inicio=500, fin=550),
        ],
        "asignaciones": [
            Asignacion(
                clase_id=clase.id,
                franja=i,
                profesor_id=profesor.id,
                asignatura_nombre="Español",
                grupos_texto="1°A",
                profesor_nombre=profesor.nombre,
                color="#E57373",
                bloqueada=i == 0,
            )
            for i in range(2)
        ],
    }
    valores.update(campos)
    return Solucion(**valores)  # type: ignore[arg-type]


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Repositorio]:
    repositorio = _proyecto(tmp_path / "escuela.horario")
    yield repositorio
    repositorio.cerrar()


# ---------------------------------------------------------------------------
# Archivo y conexión
# ---------------------------------------------------------------------------


def test_pragmas(repo: Repositorio) -> None:
    con = repo.conexion
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not Path(str(repo.ruta) + "-wal").exists()


def test_crear_falla_si_existe(tmp_path: Path) -> None:
    ruta = tmp_path / "a.horario"
    Repositorio.crear(ruta).cerrar()
    with pytest.raises(FileExistsError):
        Repositorio.crear(ruta)


def test_abrir_inexistente(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Repositorio.abrir(tmp_path / "no.horario")


def test_archivo_no_valido(tmp_path: Path) -> None:
    ruta = tmp_path / "basura.horario"
    ruta.write_bytes(b"esto no es sqlite" * 100)
    with pytest.raises(ErrorArchivoNoValido):
        Repositorio.abrir(ruta)


# ---------------------------------------------------------------------------
# Ida y vuelta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fabrica", [ejemplo_pequeno, ejemplo_mediano])
def test_ida_y_vuelta_ejemplos(tmp_path: Path, fabrica: Callable[[], DatosEscuela]) -> None:
    datos = fabrica()
    with _proyecto(tmp_path / "e.horario", datos) as repo:
        assert repo.cargar_datos() == _ordenado(datos)
    with Repositorio.abrir(tmp_path / "e.horario") as repo:
        assert repo.cargar_datos() == _ordenado(datos)


def test_ida_y_vuelta_todos_los_campos(repo: Repositorio) -> None:
    """Entidades con todos los campos opcionales llenos."""
    datos = repo.cargar_datos()
    nivel = datos.niveles[0].model_copy(
        update={
            "eventos": [Evento(dia="X", inicio=600, fin=650)],
            "duraciones_especiales": {0: 40, 3: 60},
            "huecos_alumnos": "prohibidos",
            "preferir_titular": True,
            "dias": ["L", "M", "X", "J", "V", "S"],
            "recesos": [Receso(inicio=600, fin=630), Receso(nombre="Comida", inicio=720, fin=760)],
        }
    )
    repo.guardar(nivel)
    asignatura = repo.guardar(
        Asignatura(
            nombre="Química",
            color="#123abc",
            espacio_requerido="laboratorio",
            reglas_por_defecto=ReglasAsignatura(
                max_horas_dia=3,
                bloque_doble="obligatorio",
                franjas_prohibidas=[RangoFranjas(dias=("L",), desde_indice=0, hasta_indice=1)],
                franjas_preferidas=[RangoFranjas(desde=420, hasta=660)],
            ),
            reglas_por_nivel=[
                ReglasAsignaturaNivel(nivel_id=nivel.id or 0, max_horas_dia=1),
                # Sobrescribe con lista vacía: distinto de heredar.
            ],
        )
    )
    asignatura2 = repo.guardar(
        Asignatura(
            nombre="Robótica",
            reglas_por_nivel=[
                ReglasAsignaturaNivel(
                    nivel_id=nivel.id or 0,
                    bloque_doble="preferido",
                    franjas_prohibidas=[],
                    franjas_preferidas=[RangoFranjas(dias=("V",), desde_indice=2, hasta_indice=2)],
                )
            ],
        )
    )
    grado = datos.grados[0]
    profesor = repo.guardar(
        Profesor(
            nombre="Zoe Completa",
            activo=True,
            asignaturas=[asignatura.id or 0],
            grados=[grado.id or 0],
            disponibilidad=[
                Disponibilidad(dia="L", inicio=420, fin=600),
                Disponibilidad(dia="M", inicio=420, fin=480, tipo="preferible_no"),
                Disponibilidad(dia="X", inicio=700, fin=800, tipo="no_disponible"),
            ],
            disponible_toda_la_jornada=False,
            eventos=[EventoProfesor(nombre="Junta", dia="J", inicio=780, fin=840)],
            suplencia_asignaturas=[asignatura2.id or 0],
            suplencia_grados=[grado.id or 0],
            carga_max_semanal_min=1200,
            carga_max_diaria_min=300,
            carga_min_semanal_min=100,
            max_dias=4,
            max_minutos_continuos=150,
        )
    )
    grupo = datos.grupos[0].model_copy(update={"titular_id": profesor.id, "estudiantes": 31})
    repo.guardar(grupo)
    division = repo.guardar(
        Division(
            grupo_id=grupo.id, nombre="Taller", partes=["Uno", "Dos", "Tres"], simultanea=False
        )
    )
    clase = repo.guardar(
        Clase(
            asignatura_id=asignatura.id or 0,
            destinatarios=[
                Destinatario(grupo_id=grupo.id or 0, division_id=division.id, parte="Dos")
            ],
            profesores=[profesor.id or 0],
            horas_semanales=3,
            sobrescribe_espacio=True,
            espacio_requerido=None,
            origen="manual",
        )
    )
    fija = repo.guardar(
        AsignacionFija(clase_id=clase.id or 0, profesor_id=profesor.id, dia="M", indice_franja=2)
    )
    alias = repo.guardar(AliasImportacion(texto="QUIM", asignatura_id=asignatura.id or 0))
    repo.guardar(PlanEstudios(grado_id=grado.id or 0, asignatura_id=asignatura.id or 0,
                              horas_semanales=3))  # fmt: skip

    cargados = repo.cargar_datos()
    assert next(n for n in cargados.niveles if n.id == nivel.id) == nivel
    assert next(a for a in cargados.asignaturas if a.id == asignatura.id) == asignatura
    assert next(a for a in cargados.asignaturas if a.id == asignatura2.id) == asignatura2
    assert next(p for p in cargados.profesores if p.id == profesor.id) == profesor
    assert next(g for g in cargados.grupos if g.id == grupo.id) == grupo
    assert next(d for d in cargados.divisiones if d.id == division.id) == division
    assert next(c for c in cargados.clases if c.id == clase.id) == clase
    assert cargados.fijas == [fija]
    assert cargados.alias == [alias]
    regla_robotica = asignatura2.reglas_efectivas(nivel.id)
    assert regla_robotica.franjas_prohibidas == []
    assert regla_robotica.bloque_doble == "preferido"


def test_configuracion_ida_y_vuelta(repo: Repositorio) -> None:
    config = repo.cargar_configuracion()
    config.nombre_escuela = "Otra"
    config.criterios.prioridades["B1"] = "muy_alta"
    config.criterios.perfil = "personalizado"
    config.criterios.modo_avanzado = True
    config.criterios.pesos_avanzados = {"B1": 2.5}
    repo.guardar_configuracion(config)
    assert repo.cargar_configuracion() == config


def test_solucion_ausencia_suplencia_ida_y_vuelta(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    solucion = _solucion(datos, violaciones=[Violacion(restriccion="D3", mensaje="x", clase_id=1)])
    solucion.estado = EstadoSolucion.INVALIDA
    guardada = repo.guardar_solucion(solucion)
    assert guardada.id is not None
    assert all(a.id is not None for a in guardada.asignaciones)
    sin_ids = guardada.model_copy(
        update={
            "id": None,
            "asignaciones": [a.model_copy(update={"id": None}) for a in guardada.asignaciones],
        }
    )
    assert sin_ids == solucion

    profesor = datos.profesores[0].id or 0
    otro = datos.profesores[1].id or 0
    ausencia = repo.guardar(
        Ausencia(profesor_id=profesor, fecha_inicio=date(2026, 11, 23),
                 fecha_fin=date(2026, 11, 24), desde=450, hasta=600, motivo="Médico")
    )  # fmt: skip
    suplencia = repo.guardar(
        Suplencia(
            fecha=date(2026, 11, 23),
            solucion_id=guardada.id,
            asignacion_id=guardada.asignaciones[0].id,
            profesor_ausente_id=profesor,
            suplente_id=otro,
            nota="ok",
        )
    )
    assert repo.listar_ausencias() == [ausencia]
    assert repo.listar_suplencias() == [suplencia]
    assert repo.listar_suplencias(desde=date(2026, 11, 24)) == []
    resumen = repo.listar_soluciones()[0]
    assert (resumen.id, resumen.asignaciones, resumen.estado) == (
        guardada.id,
        2,
        EstadoSolucion.INVALIDA,
    )


def test_plan_cero_elimina_fila(repo: Repositorio) -> None:
    fila = repo.cargar_datos().plan[0]
    repo.guardar(fila.model_copy(update={"horas_semanales": 0}))
    plan = repo.cargar_datos().plan
    assert (fila.grado_id, fila.asignatura_id) not in {(f.grado_id, f.asignatura_id) for f in plan}


# ---------------------------------------------------------------------------
# Borrados: cascadas, SET NULL, profesores en uso
# ---------------------------------------------------------------------------


def test_cascada_de_nivel(repo: Repositorio) -> None:
    nivel_id = repo.cargar_datos().niveles[0].id or 0
    afectados = repo.afectados_por_eliminar(Nivel, nivel_id)
    assert afectados["niveles"] == 1
    assert afectados["grados"] == 5
    assert afectados["grupos"] == 5
    assert afectados["clases"] == 35
    assert afectados["filas del plan"] == 35
    assert afectados["recesos"] == 1
    # La simulación no cambia nada.
    assert len(repo.cargar_datos().clases) == 35

    repo.eliminar(Nivel, nivel_id)
    datos = repo.cargar_datos()
    assert (datos.niveles, datos.grados, datos.grupos, datos.clases, datos.plan) == (
        [], [], [], [], []
    )  # fmt: skip
    assert repo.conexion.execute("SELECT COUNT(*) FROM recesos").fetchone()[0] == 0
    # Los profesores no son estructurales del nivel: se conservan, sin grados.
    assert all(p.grados == [] for p in datos.profesores)


def test_borrar_grupo_elimina_clases_vacias_pero_no_conjuntas(tmp_path: Path) -> None:
    datos = ejemplo_mediano()
    with _proyecto(tmp_path / "m.horario", datos) as repo:
        conjunta = next(c for c in datos.clases if len(c.destinatarios) == 2)
        primero = conjunta.destinatarios[0].grupo_id
        repo.eliminar(Grupo, primero)
        cargada = next(c for c in repo.cargar_datos().clases if c.id == conjunta.id)
        assert cargada.destinatarios == conjunta.destinatarios[1:]
        assert all(
            any(d.grupo_id != primero for d in c.destinatarios) for c in repo.cargar_datos().clases
        )


def test_set_null_en_soluciones(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    guardada = repo.guardar_solucion(_solucion(datos))
    clase_id = datos.clases[0].id or 0
    afectados = repo.afectados_por_eliminar(Clase, clase_id)
    assert afectados["asignaciones de horarios que pierden su clase"] == 2
    repo.eliminar(Clase, clase_id)
    cargada = repo.cargar_solucion(guardada.id or 0)
    assert all(a.clase_id is None for a in cargada.asignaciones)
    assert cargada.asignaciones[0].asignatura_nombre == "Español"
    assert cargada.asignaciones[0].grupos_texto == "1°A"


def test_profesor_en_uso_no_se_elimina_y_se_desactiva(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    repo.guardar_solucion(_solucion(datos))
    profesor = datos.profesores[0]
    assert repo.profesor_en_uso(profesor.id or 0)
    with pytest.raises(ErrorProfesorEnUso, match=profesor.nombre):
        repo.eliminar(Profesor, profesor.id or 0)
    with pytest.raises(ErrorProfesorEnUso):
        repo.afectados_por_eliminar(Profesor, profesor.id or 0)
    repo.desactivar_profesor(profesor.id or 0)
    assert not next(p for p in repo.cargar_datos().profesores if p.id == profesor.id).activo
    # Se puede crear otro activo con el mismo nombre; dos activos iguales, no.
    repo.guardar(Profesor(nombre=profesor.nombre))
    with pytest.raises(sqlite3.IntegrityError):
        repo.guardar(Profesor(nombre=profesor.nombre))


def test_profesor_en_suplencia_no_se_elimina(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    ausente, suplente = datos.profesores[2].id or 0, datos.profesores[3].id or 0
    repo.guardar(Suplencia(fecha=date(2026, 1, 1), profesor_ausente_id=ausente,
                           suplente_id=suplente))  # fmt: skip
    for ident in (ausente, suplente):
        with pytest.raises(ErrorProfesorEnUso):
            repo.eliminar(Profesor, ident)


def test_profesor_libre_se_elimina(repo: Repositorio) -> None:
    profesor = repo.cargar_datos().profesores[-1]
    afectados = repo.eliminar(Profesor, profesor.id or 0)
    assert afectados["profesores"] == 1
    assert afectados["habilitaciones por grado"] == 5
    assert profesor.id not in {p.id for p in repo.cargar_datos().profesores}


def test_reemplazar_datos_desactiva_profesores_en_uso(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    guardada = repo.guardar_solucion(_solucion(datos))
    nuevos = datos.model_copy(update={"profesores": datos.profesores[1:], "clases": []})
    desactivados = repo.reemplazar_datos(nuevos)
    assert desactivados == [datos.profesores[0].nombre]
    cargados = repo.cargar_datos()
    assert len(cargados.profesores) == len(datos.profesores)
    assert cargados.clases == []
    # La solución sigue legible.
    assert len(repo.cargar_solucion(guardada.id or 0).asignaciones) == 2


# ---------------------------------------------------------------------------
# Soluciones: vigente
# ---------------------------------------------------------------------------


def test_una_sola_vigente(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    a = repo.guardar_solucion(_solucion(datos, nombre="A"))
    b = repo.guardar_solucion(_solucion(datos, nombre="B"))
    repo.marcar_vigente(a.id)
    assert repo.solucion_vigente_id() == a.id
    repo.marcar_vigente(b.id)
    assert repo.solucion_vigente_id() == b.id
    assert [s.vigente for s in repo.listar_soluciones() if s.id == a.id] == [False]
    c = repo.guardar_solucion(_solucion(datos, nombre="C", vigente=True))
    assert repo.solucion_vigente_id() == c.id
    repo.marcar_vigente(None)
    assert repo.solucion_vigente_id() is None


@pytest.mark.parametrize(
    "estado", [EstadoSolucion.BORRADOR, EstadoSolucion.INVALIDA, EstadoSolucion.INFACTIBLE]
)
def test_no_vigente_si_no_es_valida(repo: Repositorio, estado: EstadoSolucion) -> None:
    solucion = repo.guardar_solucion(_solucion(repo.cargar_datos(), estado=estado))
    with pytest.raises(ErrorSolucion):
        repo.marcar_vigente(solucion.id)


def test_eliminar_solucion_respalda(repo: Repositorio) -> None:
    solucion = repo.guardar_solucion(_solucion(repo.cargar_datos()))
    antes = len(repo.listar_respaldos())
    repo.eliminar_solucion(solucion.id or 0)
    assert repo.listar_soluciones() == []
    assert len(repo.listar_respaldos()) == antes + 1


# ---------------------------------------------------------------------------
# Huella de niveles
# ---------------------------------------------------------------------------


def test_huella_niveles() -> None:
    nivel = Nivel(id=1, nombre="Primaria", inicio_jornada=450, fin_jornada=840)
    base = huella_niveles([nivel])
    assert huella_niveles([nivel.model_copy()]) == base
    assert huella_niveles([nivel.model_copy(update={"nombre": "Otro"})]) == base
    assert huella_niveles([nivel.model_copy(update={"preferir_titular": True})]) == base
    cambios = [
        {"duracion_min": 45},
        {"fin_jornada": 900},
        {"dias": ["L", "M"]},
        {"recesos": [Receso(inicio=600, fin=630)]},
        {"eventos": [Evento(dia="L", inicio=450, fin=500)]},
        {"duraciones_especiales": {0: 30}},
    ]
    for cambio in cambios:
        assert huella_niveles([nivel.model_copy(update=cambio)]) != base, cambio


def test_solucion_desactualizada(repo: Repositorio) -> None:
    datos = repo.cargar_datos()
    solucion = repo.guardar_solucion(_solucion(datos))
    assert not solucion.desactualizada(repo.cargar_datos().huella_niveles())
    nivel = datos.niveles[0]
    repo.guardar(nivel.model_copy(update={"duracion_min": 45}))
    assert solucion.desactualizada(repo.cargar_datos().huella_niveles())
    # Sigue viéndose con sus propias franjas.
    assert repo.cargar_solucion(solucion.id or 0).franjas == solucion.franjas


# ---------------------------------------------------------------------------
# Respaldos
# ---------------------------------------------------------------------------


def test_respaldo_diario_al_abrir(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    _proyecto(ruta).cerrar()
    assert respaldos.listar_respaldos(ruta) == []
    Repositorio.abrir(ruta).cerrar()
    assert len(respaldos.listar_respaldos(ruta)) == 1
    Repositorio.abrir(ruta).cerrar()
    assert len(respaldos.listar_respaldos(ruta)) == 1
    nombre = respaldos.listar_respaldos(ruta)[0].ruta.name
    assert nombre.startswith(f"e-{date.today():%Y%m%d}-") and nombre.endswith(".horario")
    assert respaldos.listar_respaldos(ruta)[0].ruta.parent == tmp_path / ".respaldos"


def test_respaldo_antes_de_reemplazar(repo: Repositorio) -> None:
    antes = len(repo.listar_respaldos())
    repo.reemplazar_datos(repo.cargar_datos())
    assert len(repo.listar_respaldos()) == antes + 1


def test_respaldo_en_cascada_grande(repo: Repositorio) -> None:
    antes = len(repo.listar_respaldos())
    repo.eliminar(AliasImportacion, repo.guardar(
        AliasImportacion(texto="X", asignatura_id=repo.cargar_datos().asignaturas[0].id or 0)
    ).id or 0)  # fmt: skip
    assert len(repo.listar_respaldos()) == antes
    repo.eliminar(Nivel, repo.cargar_datos().niveles[0].id or 0)
    assert len(repo.listar_respaldos()) == antes + 1


def test_poda_de_respaldos(repo: Repositorio) -> None:
    config = repo.cargar_configuracion()
    config.respaldos_a_conservar = 3
    repo.guardar_configuracion(config)
    rutas = [repo.crear_respaldo() for _ in range(5)]
    actuales = repo.listar_respaldos()
    assert len(actuales) == 3
    assert {r.ruta for r in actuales} == set(rutas[-3:])


def test_restaurar_respaldo(repo: Repositorio) -> None:
    respaldo = repo.crear_respaldo()
    repo.eliminar(Nivel, repo.cargar_datos().niveles[0].id or 0)
    assert repo.cargar_datos().grupos == []
    repo.restaurar_respaldo(respaldo)
    datos = repo.cargar_datos()
    assert len(datos.grupos) == 5
    assert repo.conexion.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_guardar_como(repo: Repositorio, tmp_path: Path) -> None:
    destino = repo.guardar_como(tmp_path / "copia.horario")
    with Repositorio.abrir(destino, respaldo_diario=False) as copia:
        assert copia.cargar_datos() == repo.cargar_datos()


def test_sobrescribir_ejemplo_respalda(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    crear_ejemplo(ruta)
    with pytest.raises(FileExistsError):
        crear_ejemplo(ruta)
    crear_ejemplo(ruta, "mediano", sobrescribir=True)
    assert len(respaldos.listar_respaldos(ruta)) == 1
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        assert len(repo.cargar_datos().grupos) == 30


# ---------------------------------------------------------------------------
# Bloqueo y carpetas sincronizadas
# ---------------------------------------------------------------------------


def test_bloqueo_de_archivo(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    repo = _proyecto(ruta)
    candado = archivo.ruta_bloqueo(ruta)
    assert candado.name == "e.horario.lock"
    info = json.loads(candado.read_text(encoding="utf-8"))
    assert info["pid"] == os.getpid() and info["equipo"] == archivo.nombre_equipo()
    assert repo.avisos == []
    repo.cerrar()
    assert not candado.exists()


def test_bloqueo_de_otro_equipo_avisa(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    _proyecto(ruta).cerrar()
    candado = archivo.ruta_bloqueo(ruta)
    candado.write_text(json.dumps({"pid": 1, "equipo": "OTRO-EQUIPO", "fecha": "x"}))
    repo = Repositorio.abrir(ruta)
    assert [a.clave for a in repo.avisos] == ["bloqueo"]
    assert "OTRO-EQUIPO" in repo.avisos[0].mensaje
    repo.cerrar()
    # No se suelta un bloqueo ajeno.
    assert candado.exists()


def test_bloqueo_vencido_se_ignora(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    _proyecto(ruta).cerrar()
    candado = archivo.ruta_bloqueo(ruta)
    candado.write_text(json.dumps({"pid": 2**22 + 12345, "equipo": archivo.nombre_equipo()}))
    with Repositorio.abrir(ruta) as repo:
        assert repo.avisos == []
    assert not candado.exists()


@pytest.mark.parametrize(
    ("ruta", "esperado"),
    [
        ("C:\\Users\\ana\\OneDrive - Escuela\\horarios\\e.horario", "OneDrive"),
        ("/Users/ana/Dropbox/e.horario", "Dropbox"),
        ("/Users/ana/Library/CloudStorage/GoogleDrive-ana/Mi unidad/e.horario", "Google Drive"),
        ("/Users/ana/Library/Mobile Documents/com~apple~CloudDocs/e.horario", "iCloud Drive"),
        ("\\\\servidor\\compartido\\e.horario", "una unidad de red"),
        ("/Users/ana/Documentos/e.horario", None),
    ],
)
def test_carpeta_sincronizada(ruta: str, esperado: str | None) -> None:
    assert archivo.detectar_carpeta_sincronizada(Path(ruta)) == esperado


def test_aviso_carpeta_sincronizada_al_abrir(tmp_path: Path) -> None:
    ruta = tmp_path / "Dropbox" / "e.horario"
    with _proyecto(ruta) as repo:
        assert "carpeta_sincronizada" in [a.clave for a in repo.avisos]


# ---------------------------------------------------------------------------
# Versiones y migraciones
# ---------------------------------------------------------------------------


def test_proyecto_mas_nuevo(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    with _proyecto(ruta) as repo:
        repo.conexion.execute("UPDATE metadatos SET valor = '99' WHERE clave = 'version_esquema'")
    with pytest.raises(ErrorVersionEsquema, match="99"):
        Repositorio.abrir(ruta)


def test_proyecto_v6_se_detecta(tmp_path: Path) -> None:
    ruta = tmp_path / "viejo.horario"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE esquema_version (version INTEGER)")
    con.execute("INSERT INTO esquema_version VALUES (6)")
    con.commit()
    con.close()
    with pytest.raises(ErrorProyectoAnterior, match="Importar proyecto anterior"):
        Repositorio.abrir(ruta)


def test_migracion_se_aplica_con_respaldo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta = tmp_path / "e.horario"
    _proyecto(ruta).cerrar()

    def a_v2(con: sqlite3.Connection) -> None:
        con.execute("CREATE TABLE nueva (x INTEGER)")

    monkeypatch.setattr(migraciones, "VERSION_ESQUEMA", 2)
    monkeypatch.setitem(migraciones.MIGRACIONES, 2, a_v2)
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        assert "nueva" in migraciones.tablas(repo.conexion)
        assert migraciones.leer_version(repo.conexion) == 2
        assert len(repo.listar_respaldos()) == 1


def test_esquema_actual_tiene_version_1() -> None:
    assert migraciones.VERSION_ESQUEMA == 1
    assert migraciones.MIGRACIONES == {}


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------


def test_cli_ejemplo_crea_ambos(tmp_path: Path) -> None:
    corredor = CliRunner()
    for tamano, grupos, profesores in (("pequeno", 5, 12), ("mediano", 30, 42)):
        ruta = tmp_path / f"{tamano}.horario"
        resultado = corredor.invoke(app, ["ejemplo", str(ruta), "--tamano", tamano])
        assert resultado.exit_code == 0, resultado.output
        with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
            datos = repo.cargar_datos()
            assert (len(datos.grupos), len(datos.profesores)) == (grupos, profesores)
    repetido = corredor.invoke(app, ["ejemplo", str(tmp_path / "pequeno.horario")])
    assert repetido.exit_code == 1
    forzado = corredor.invoke(app, ["ejemplo", str(tmp_path / "pequeno.horario"), "--sobrescribir"])
    assert forzado.exit_code == 0


def test_ejemplo_mediano_tiene_lo_pedido() -> None:
    datos = ejemplo_mediano()
    nombres = {n.nombre: n for n in datos.niveles}
    assert nombres["Preescolar"].duracion_min == 45
    assert nombres["Primaria"].duracion_min == nombres["Secundaria"].duracion_min == 50
    assert len({tuple((r.inicio, r.fin) for r in n.recesos) for n in datos.niveles}) == 3
    assert datos.configuracion.margen_traslado_min == 10
    por_nivel = {n: 0 for n in nombres}
    for grupo in datos.grupos:
        por_nivel[datos.nivel_de_grupo(grupo.id or 0).nombre] += 1
    assert por_nivel == {"Preescolar": 6, "Primaria": 12, "Secundaria": 12}
    assert any(len(c.destinatarios) == 2 for c in datos.clases)  # conjunta
    assert datos.divisiones and any(
        d.division_id is not None for c in datos.clases for d in c.destinatarios
    )
    fisica = next(a for a in datos.asignaturas if a.nombre == "Ed. Física")
    assert fisica.reglas_por_defecto.franjas_prohibidas
    assert any(g.bloqueos for g in datos.grupos)
    parcial = [p for p in datos.profesores if not p.disponible_toda_la_jornada]
    assert parcial
    assert len({datos.nivel_de_grado(g).id for g in parcial[0].grados}) > 1


def test_mas_dias_respaldo_no_cuenta_como_hoy(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    _proyecto(ruta).cerrar()
    con = sqlite3.connect(ruta)
    respaldos.respaldar_conexion(con, ruta, 10, ahora=datetime.now() - timedelta(days=1))
    con.close()
    assert not respaldos.hay_respaldo_del_dia(ruta, date.today())
    Repositorio.abrir(ruta).cerrar()
    assert respaldos.hay_respaldo_del_dia(ruta, date.today())
