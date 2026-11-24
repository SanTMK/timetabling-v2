"""Creado con Claude.

Importación (§15): cuadro de horarios por grado y cuadro de maestros (con los archivos de
ejemplo de `pruebas/datos/`), mapeos y alias, horarios como borrador, proyecto v6 (con un
`.horario` de esquema v6 real guardado en `pruebas/datos/`), la transacción con respaldo, la
línea de comandos y los asistentes de la interfaz.

Los archivos de ejemplo se regeneran con `uv run python -m pruebas.datos.generar_datos`.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from timetabling.cli import app
from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.modelos import (
    AliasImportacion,
    Asignatura,
    DatosEscuela,
    EstadoSolucion,
    Grado,
    Nivel,
    Profesor,
    Receso,
    por_id,
)
from timetabling.importacion import horarios_excel, maestros_excel, proyecto_v6
from timetabling.importacion.maestros_excel import interpretar
from timetabling.importacion.textos import (
    clave_maestro,
    mismo_grado,
    nombre_maestro,
    rango,
)
from timetabling.nucleo.validacion import hay_errores, validar
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio
from timetabling.servicios import importacion
from timetabling.servicios.importacion import ErrorImportacion, importar_v6

DATOS = Path(__file__).parent / "datos"
CUADRO_GRUPOS = DATOS / "cuadro_grupos.xlsx"
CUADRO_MAESTROS = DATOS / "cuadro_maestros.xlsx"
PROYECTO_V6 = DATOS / "proyecto_v6.horario"


def escuela_base() -> DatosEscuela:
    """Niveles y grados de la escuela de los cuadros (lo que la importación necesita)."""
    return DatosEscuela(
        niveles=[
            Nivel(id=1, nombre="Primaria", duracion_min=45, inicio_jornada=480, fin_jornada=680,
                  recesos=[Receso(inicio=570, fin=590)]),
            Nivel(id=2, nombre="Preescolar", duracion_min=40, inicio_jornada=480,
                  fin_jornada=655, recesos=[Receso(inicio=560, fin=580)],
                  duraciones_especiales={3: 35}),
        ],
        grados=[Grado(id=1, nivel_id=1, nombre="1°"), Grado(id=2, nivel_id=1, nombre="2°"),
                Grado(id=3, nivel_id=2, nombre="Kinder")],
    )  # fmt: skip


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    ruta = tmp_path / "escuela.horario"
    datos = escuela_base()
    with Repositorio.crear(ruta, datos.configuracion) as repo:
        repo.reemplazar_datos(datos)
    return ruta


def _importar_horarios(ruta: Path) -> None:
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        importacion.importar_horarios(repo, hojas, horarios_excel.mapeo_inicial(
            repo.cargar_datos(), hojas))  # fmt: skip


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------


def test_horas_de_12_horas_y_grados() -> None:
    assert rango("8:00-8:45") == (480, 525)
    assert rango(" 12:40 - 1:20 ") == (760, 800)  # antes de las 7 es tarde
    assert rango("Math") is None and rango(None) is None
    assert mismo_grado("1st", "1°") and mismo_grado("3rd", "Tercero")
    assert mismo_grado("kinder", "Kinder") and not mismo_grado("2nd", "1°")


def test_nombres_de_maestro_normalizados() -> None:
    assert nombre_maestro("MS. ANA PEREZ") == "Ms. Ana Perez"
    assert nombre_maestro("Mr.Bruno Díaz") == "Mr. Bruno Díaz"
    assert nombre_maestro("MTRA. LUISA gómez") == "Mtra. Luisa Gómez"
    assert nombre_maestro("prof juan") == "Prof. Juan"
    assert clave_maestro("Ms. Ana Perez") == clave_maestro("Ana Pérez") == "ana perez"


def test_interpretar_celdas_del_cuadro_de_maestros() -> None:
    assert interpretar("ESPAÑOL 3A") == maestros_excel.CeldaLeida("ESPAÑOL", (("3", "A"),))
    assert interpretar("Math PPA").grupos == (("PP", "A"),)
    assert interpretar("2A (8:00-8:45)") == maestros_excel.CeldaLeida("", (("2", "A"),))
    assert interpretar("Science 10B, 10C").grupos == (("10", "B"), ("10", "C"))
    assert interpretar("GYM KA") == maestros_excel.CeldaLeida("GYM", (("K", "A"),))
    assert interpretar("Algebra I").grupos == ()


# ---------------------------------------------------------------------------
# Cuadro de horarios por grado (§15.1)
# ---------------------------------------------------------------------------


def test_leer_cuadro_de_grupos() -> None:
    hojas = {h.nombre: h for h in horarios_excel.leer_libro(CUADRO_GRUPOS)}
    assert list(hojas) == ["1st", "2nd", "kinder"]
    primero = hojas["1st"]
    assert [(g.etiqueta, g.seccion) for g in primero.grupos] == [("1A", "A"), ("1B", "B")]
    # 19 horas con clase o tutoría + 5 recreos; lo de «Horarios de Examen» se ignora.
    assert len(primero.grupos[0].celdas) == 24
    assert primero.eventos == {("L", 480, 525)}  # celda celeste: hora cívica
    assert [g.seccion for g in hojas["kinder"].grupos] == ["A"]


def test_mapeo_inicial_hojas_y_textos() -> None:
    datos = escuela_base()
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    mapeo = horarios_excel.mapeo_inicial(datos, hojas)
    assert {h: d.grado_id for h, d in mapeo.hojas.items()} == {"1st": 1, "2nd": 2, "kinder": 3}
    assert mapeo.asignaturas["Sceince"] == "Science"  # variante conocida
    assert mapeo.asignaturas["MATH"] == "Math"
    assert "Recess" not in mapeo.asignaturas and "Tutoría" not in mapeo.asignaturas


def test_aplicar_crea_asignaturas_grupos_plan_eventos_y_clases() -> None:
    datos = escuela_base()
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    resultado = horarios_excel.aplicar(datos, hojas, horarios_excel.mapeo_inicial(datos, hojas))
    nuevos = resultado.datos
    assert datos.asignaturas == []  # el original no cambia
    nombres = {a.id: a.nombre for a in nuevos.asignaturas}
    plan = {(p.grado_id, nombres[p.asignatura_id]): p.horas_semanales for p in nuevos.plan}
    assert plan == {
        (1, "Math"): 6, (1, "Español"): 5, (1, "Science"): 3, (1, "Gym"): 2, (1, "Art"): 2,
        (2, "Math"): 6, (2, "Español"): 5, (2, "Science"): 3, (2, "Gym"): 2, (2, "Art"): 2,
        (3, "Play"): 10, (3, "Español"): 5, (3, "Gym"): 3,
    }  # fmt: skip
    assert sorted(nuevos.nombre_grupo(g.id) for g in nuevos.grupos if g.id) == [
        "1°A", "1°B", "2°A", "KinderA"]  # fmt: skip
    assert [(e.dia, e.inicio, e.fin) for e in nuevos.niveles[0].eventos] == [("L", 480, 525)]
    assert nuevos.niveles[1].eventos == []
    assert len(nuevos.clases) == 18 and all(c.id for c in nuevos.clases)
    assert [(a.texto, nombres[a.asignatura_id]) for a in nuevos.alias] == [("Sceince", "Science")]
    # Las celdas de recreo están fuera de las franjas, pero no cuentan como clase: sin avisos.
    assert resultado.avisos == ["Se omitieron 3 celdas de tutoría."]
    assert any("Asignaturas nuevas" in r for r in resultado.resumen)
    # Máximo diario: Play va 2 veces por día.
    play = next(a for a in nuevos.asignaturas if a.nombre == "Play")
    assert play.reglas_por_defecto.max_horas_dia == 2


def test_alias_guardados_y_asignaturas_existentes() -> None:
    datos = escuela_base()
    datos.asignaturas = [Asignatura(id=7, nombre="Matemáticas"), Asignatura(id=8, nombre="Arte")]
    datos.alias = [AliasImportacion(id=1, texto="Math", asignatura_id=7)]
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    mapeo = horarios_excel.mapeo_inicial(datos, hojas)
    assert mapeo.asignaturas["Math"] == mapeo.asignaturas["MATH"] == "Matemáticas"
    mapeo.asignaturas["Art"] = "Arte"  # mapeo editado: se guarda como alias
    nuevos = horarios_excel.aplicar(datos, hojas, mapeo).datos
    nombres = {a.nombre for a in nuevos.asignaturas}
    assert "Math" not in nombres and "Art" not in nombres
    assert {a.texto for a in nuevos.alias} == {"Math", "Art", "Sceince"}
    # La próxima vez, «Art» ya sale mapeado.
    assert horarios_excel.mapeo_inicial(nuevos, hojas).asignaturas["Art"] == "Arte"


def test_mapeo_grado_nuevo_omitir_recesos_e_ignorar() -> None:
    datos = escuela_base()
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    mapeo = horarios_excel.mapeo_inicial(datos, hojas)
    mapeo.hojas["2nd"] = horarios_excel.DestinoHoja(nuevo_grado="Segundo", nivel_id=1)
    mapeo.hojas["kinder"] = horarios_excel.DestinoHoja()  # omitir
    mapeo.recesos.append("Art")  # el usuario decide que «Art» no cuenta
    mapeo.asignaturas["Gym"] = ""  # ignorar
    nuevos = horarios_excel.aplicar(datos, hojas, mapeo).datos
    segundo = next(g for g in nuevos.grados if g.nombre == "Segundo")
    assert segundo.id == 4 and segundo.nivel_id == 1
    nombres = {a.id: a.nombre for a in nuevos.asignaturas}
    assert {nombres[p.asignatura_id] for p in nuevos.plan} == {"Math", "Español", "Science"}
    assert {p.grado_id for p in nuevos.plan} == {1, 4}
    # Sin ningún grado, el asistente no deja avanzar (lo comprueba la interfaz).
    assert horarios_excel.DestinoHoja().omitir


def test_grupos_que_difieren_usan_el_valor_mas_frecuente() -> None:
    def bloque(columna: int, etiqueta: str, materias: list[str]) -> dict[tuple[int, int], str]:
        celdas = {(0, columna + 2): etiqueta}
        for k, dia in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]):
            celdas[(1, columna + 1 + k)] = dia
        for k, materia in enumerate(materias):
            celdas[(2, columna)] = "8:00-8:45"
            celdas[(2, columna + 1 + k)] = materia
        return celdas

    celdas = {**bloque(0, "1A", ["Math", "Math", "Art"]), **bloque(7, "1B", ["Math", "Art"]),
              **bloque(14, "1C", ["Math", "Art"])}  # fmt: skip
    filas = [[celdas.get((i, j)) for j in range(21)] for i in range(3)]
    hoja = horarios_excel.leer_hoja("1st", filas)
    datos = escuela_base()
    resultado = horarios_excel.aplicar(datos, [hoja], horarios_excel.mapeo_inicial(datos, [hoja]))
    math = next(a.id for a in resultado.datos.asignaturas if a.nombre == "Math")
    assert next(p.horas_semanales for p in resultado.datos.plan if p.asignatura_id == math) == 1
    assert any("difieren en Math (A=2, B=1, C=1); se usa 1" in a for a in resultado.avisos)


def test_mapeo_en_json() -> None:
    mapeo = horarios_excel.mapeo_inicial(escuela_base(), horarios_excel.leer_libro(CUADRO_GRUPOS))
    mapeo.hojas["kinder"] = horarios_excel.DestinoHoja(nuevo_grado="K1", nivel_id=2)
    assert horarios_excel.MapeoHorarios.de_json(mapeo.a_json()) == mapeo


def test_importar_horarios_con_respaldo_y_en_una_transaccion(proyecto: Path) -> None:
    _importar_horarios(proyecto)
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        assert len(datos.plan) == 13 and len(datos.clases) == 18
        assert repo.listar_respaldos()  # respaldo previo


def test_aplicar_es_todo_o_nada(proyecto: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        resultado = horarios_excel.aplicar(datos, hojas, horarios_excel.mapeo_inicial(datos, hojas))

        def falla(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("falla simulada")

        monkeypatch.setattr(repo, "guardar_solucion", falla)
        borrador = importacion.borrador_de_maestros(maestros_excel.ResultadoMaestros(
            resultado.datos, colocaciones=[(1, "1:M:0", ())]))  # fmt: skip
        assert borrador is not None
        with pytest.raises(RuntimeError):
            importacion.aplicar_en_repositorio(repo, resultado.datos, [borrador])
        assert repo.cargar_datos().asignaturas == []  # nada quedó a medias


# ---------------------------------------------------------------------------
# Cuadro de maestros (§15.2)
# ---------------------------------------------------------------------------


def test_leer_cuadro_de_maestros() -> None:
    bloques = maestros_excel.leer_libro(CUADRO_MAESTROS)
    assert [b.nombre for b in bloques] == [
        "MS. ANA PEREZ", "Mr.Bruno Díaz", "Ms. Carla Ruiz", "MR. DIEGO SOTO", "Miss Elena Mora",
        "Mr. Fabián León", "MR. DIEGO SOTO (Kinder)", "Biblioteca"]  # fmt: skip
    ana = bloques[0]
    assert ana.celdas[0] == maestros_excel.CeldaMaestro("M", 480, 525, "MATH 1A")
    assert bloques[6].clave == bloques[3].clave == "diego soto"


def test_importar_maestros_crea_profesores_y_fija_clases(proyecto: Path) -> None:
    _importar_horarios(proyecto)
    bloques = maestros_excel.leer_libro(CUADRO_MAESTROS)
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        mapeo = maestros_excel.mapeo_inicial(datos, bloques)
        assert mapeo.maestros["Biblioteca"] == ""  # no es un maestro
        assert mapeo.maestros["MS. ANA PEREZ"] == "Ms. Ana Perez"
        assert mapeo.asignaturas["MATH"] == "Math" and mapeo.asignaturas["Lectura"] == ""
        resultado, borrador = importacion.importar_maestros(repo, bloques, mapeo)
        assert borrador is None
        assert resultado.avisos == []  # el cuadro coincide con el plan
        datos = repo.cargar_datos()
    profesores = {p.nombre: p for p in datos.profesores}
    assert sorted(profesores) == ["Miss Elena Mora", "Mr. Bruno Díaz", "Mr. Diego Soto",
                                  "Mr. Fabián León", "Ms. Ana Perez", "Ms. Carla Ruiz"]  # fmt: skip
    assert all(p.disponible_toda_la_jornada for p in datos.profesores)
    asignaturas = {a.id: a.nombre for a in datos.asignaturas}
    diego = profesores["Mr. Diego Soto"]
    assert [asignaturas[a] for a in diego.asignaturas] == ["Gym"] and sorted(diego.grados) == [
        1,
        2,
        3,
    ]
    nombres = por_id(datos.profesores)
    fijos = {(datos.nombre_grupo(c.destinatarios[0].grupo_id), asignaturas[c.asignatura_id]):
             nombres[c.profesores[0]].nombre for c in datos.clases}  # fmt: skip
    assert len(fijos) == 18
    # «2A (8:00-8:45)» solo trae el grupo: se usa la asignatura principal de Bruno.
    assert fijos[("2°A", "Español")] == "Mr. Bruno Díaz"
    assert fijos[("KinderA", "Gym")] == "Mr. Diego Soto"
    assert fijos[("2°A", "Art")] == "Ms. Carla Ruiz"


def test_completa_profesores_existentes_ignorando_el_titulo(proyecto: Path) -> None:
    _importar_horarios(proyecto)
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        datos.profesores = [Profesor(id=1, nombre="Ana Pérez", activo=False)]
        repo.reemplazar_datos(datos, respaldo=False)
        bloques = maestros_excel.leer_libro(CUADRO_MAESTROS)
        mapeo = maestros_excel.mapeo_inicial(repo.cargar_datos(), bloques)
        assert mapeo.maestros["MS. ANA PEREZ"] == "Ana Pérez"
        resultado, _ = importacion.importar_maestros(repo, bloques, mapeo)
        ana = next(p for p in repo.cargar_datos().profesores if p.id == 1)
    assert ana.activo and ana.nombre == "Ana Pérez" and len(ana.grados) == 2
    assert any("Ana Pérez" in r for r in resultado.resumen if "completados" in r)


def test_horarios_del_cuadro_como_borrador(proyecto: Path) -> None:
    _importar_horarios(proyecto)
    bloques = maestros_excel.leer_libro(CUADRO_MAESTROS)
    with Repositorio.abrir(proyecto, respaldo_diario=False) as repo:
        mapeo = maestros_excel.mapeo_inicial(repo.cargar_datos(), bloques)
        mapeo.con_horarios = True
        resultado, borrador = importacion.importar_maestros(repo, bloques, mapeo)
        assert borrador is not None and borrador.id is not None
        guardado = repo.cargar_solucion(borrador.id)
        datos = repo.cargar_datos()
    assert guardado.estado == EstadoSolucion.BORRADOR and guardado.origen == "importado"
    assert guardado.nombre == importacion.NOMBRE_BORRADOR_MAESTROS
    assert resultado.sin_colocar == []
    colocaciones = [Colocacion(c, f, p) for c, f, p in resultado.colocaciones]
    assert len(colocaciones) == 72
    # El horario del cuadro es completo y válido: se puede marcar como vigente tras revisarlo.
    assert verificar(datos, colocaciones).valida
    # Diego da Ed. Física en preescolar a las horas de ese nivel.
    diego = next(p.id for p in datos.profesores if p.nombre == "Mr. Diego Soto")
    assert any(f.startswith("2:") for c, f, p in resultado.colocaciones if p == (diego,))


def test_celdas_sin_hora_o_fuera_de_la_jornada_se_listan() -> None:
    datos = escuela_base()
    hojas = horarios_excel.leer_libro(CUADRO_GRUPOS)
    datos = horarios_excel.aplicar(datos, hojas, horarios_excel.mapeo_inicial(datos, hojas)).datos
    filas = [[None, None, "MS. ANA"], [None, "Monday", "Tuesday"],
             ["5:00-5:45", "Math 1A", None], ["rango raro", None, "Math 1B"]]  # fmt: skip
    bloques = maestros_excel.leer_hoja(filas)
    mapeo = maestros_excel.mapeo_inicial(datos, bloques)
    mapeo.con_horarios = True
    resultado = maestros_excel.aplicar(datos, bloques, mapeo)
    assert len(resultado.sin_colocar) == 2
    assert any("17:00–17:45" in s for s in resultado.sin_colocar)
    assert any("sin hora" in s for s in resultado.sin_colocar)


# ---------------------------------------------------------------------------
# Proyecto v6 (§15.3)
# ---------------------------------------------------------------------------


def test_lee_el_proyecto_v6() -> None:
    assert proyecto_v6.es_v6(PROYECTO_V6) and not proyecto_v6.es_v6(CUADRO_GRUPOS)
    lectura = proyecto_v6.leer(PROYECTO_V6)
    datos = lectura.datos
    assert lectura.version == 6
    criterios = datos.configuracion.criterios
    assert criterios.perfil == "equilibrado" and not criterios.modo_avanzado
    assert criterios.pesos_avanzados["B1"] == 10 and criterios.pesos_avanzados["B8"] == 4
    assert criterios.pesos_avanzados["B10"] > 0
    primaria, preescolar = datos.niveles
    assert preescolar.preferir_titular and not primaria.preferir_titular
    assert preescolar.huecos_alumnos == "prohibidos" and primaria.huecos_alumnos == "penalizar"
    assert preescolar.duraciones_especiales == {3: 35}
    assert [(e.nombre, e.dia) for e in primaria.eventos] == [("Hora cívica", "L")]
    mate = next(a for a in datos.asignaturas if a.nombre == "Matemáticas")
    preferida = mate.reglas_por_nivel[0].franjas_preferidas
    assert mate.reglas_por_nivel[0].nivel_id == 1 and preferida is not None
    assert (preferida[0].desde, preferida[0].hasta) == (480, 580)  # primera mitad
    arte = next(a for a in datos.asignaturas if a.nombre == "Arte")
    assert arte.reglas_por_defecto.bloque_doble == "preferido"
    profesores = {p.nombre: p for p in datos.profesores}
    assert profesores["Ana Pérez"].disponible_toda_la_jornada  # v6 sin rangos
    assert not profesores["Bruno Díaz"].disponible_toda_la_jornada
    assert [e.nombre for e in profesores["Bruno Díaz"].eventos] == ["Hora cívica (Primaria)"]
    assert profesores["Fabián León"].suplencia_grados == [2]
    assert profesores["Carla Ruiz"].max_minutos_continuos == 3 * 45
    assert len(datos.clases) == 18 and all(c.profesores for c in datos.clases)
    assert datos.grupos[3].titular_id == profesores["Elena Mora"].id
    assert any("Ana Pérez" in n for n in lectura.no_importado)


def test_importar_v6_crea_un_proyecto_nuevo(tmp_path: Path) -> None:
    destino = tmp_path / "nuevo.horario"
    informe = importar_v6(PROYECTO_V6, destino)
    assert "Proyecto v6 (esquema versión 6)" in informe.texto()
    with Repositorio.abrir(destino, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        assert not hay_errores(validar(datos))
        resumenes = {s.nombre: s for s in repo.listar_soluciones()}
        vigente = repo.cargar_solucion(repo.solucion_vigente_id() or 0)
        fijas = repo.cargar_solucion(resumenes["Asignaciones fijas importadas"].id or 0)
    assert vigente.nombre == "Importada del 20/08/2026 10:30" and vigente.origen == "importado"
    assert vigente.estado == EstadoSolucion.FACTIBLE and not vigente.violaciones
    assert vigente.fecha.year == 2026 and "total" in vigente.penalizaciones
    assert len(vigente.franjas) == 40 and len(vigente.asignaciones) == 72
    assert fijas.estado == EstadoSolucion.BORRADOR
    assert [(a.asignatura_nombre, a.bloqueada) for a in fijas.asignaciones] == [
        ("Matemáticas", True)
    ]
    # El anterior no se toca y el destino no se sobrescribe.
    assert proyecto_v6.es_v6(PROYECTO_V6)
    with pytest.raises(ErrorImportacion, match="Ya existe"):
        importar_v6(PROYECTO_V6, destino)
    with pytest.raises(ErrorImportacion):
        importar_v6(CUADRO_GRUPOS, tmp_path / "otro.horario")
    assert not (tmp_path / "otro.horario").exists()


def test_vigente_invalido_en_v2_no_se_marca(tmp_path: Path) -> None:
    copia = tmp_path / "anterior.horario"
    copia.write_bytes(PROYECTO_V6.read_bytes())
    con = sqlite3.connect(copia)
    # Una clase de Ana el lunes a la hora cívica: válido en v6 sin eventos, no en la v2.
    con.execute("UPDATE asignaciones SET indice = 0 WHERE id = (SELECT MIN(id) FROM asignaciones "
                "WHERE dia = 'L' AND nivel_id = 1)")  # fmt: skip
    con.commit()
    con.close()
    informe = importar_v6(copia, tmp_path / "nuevo.horario")
    assert any("no es válido en la v2" in n for n in informe.no_importado)
    with Repositorio.abrir(tmp_path / "nuevo.horario", respaldo_diario=False) as repo:
        assert repo.solucion_vigente_id() is None
        assert [s.estado for s in repo.listar_soluciones()][-1] == EstadoSolucion.INVALIDA


def test_esquemas_v6_antiguos_sin_tablas_nuevas(tmp_path: Path) -> None:
    """Las versiones 1–5 del esquema anterior no tienen eventos, suplencias ni docentes."""
    copia = tmp_path / "v1.horario"
    copia.write_bytes(PROYECTO_V6.read_bytes())
    con = sqlite3.connect(copia)
    for tabla in ("eventos", "profesor_evento", "profesor_suplencia_asignatura",
                  "profesor_suplencia_grado", "docentes_asignados"):  # fmt: skip
        con.execute(f"DROP TABLE {tabla}")
    con.execute("UPDATE esquema_version SET version = 1")
    con.commit()
    con.close()
    lectura = proyecto_v6.leer(copia)
    assert lectura.version == 1 and lectura.datos.niveles[0].eventos == []
    assert all(not c.profesores for c in lectura.datos.clases)


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------


def test_cli_importaciones(proyecto: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    mapeo = tmp_path / "mapeo.json"
    r = runner.invoke(app, ["importar-excel", str(proyecto), str(CUADRO_GRUPOS),
                            "--guardar-mapeo", str(mapeo)])  # fmt: skip
    assert r.exit_code == 0, r.output
    crudo = json.loads(mapeo.read_text("utf-8"))
    crudo["asignaturas"]["Math"] = crudo["asignaturas"]["MATH"] = "Matemáticas"
    mapeo.write_text(json.dumps(crudo), "utf-8")
    r = runner.invoke(app, ["importar-excel", str(proyecto), str(CUADRO_GRUPOS),
                            "--mapeo", str(mapeo)])  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "Matemáticas" in r.output
    r = runner.invoke(app, ["importar-maestros", str(proyecto), str(CUADRO_MAESTROS),
                            "--con-horarios"])  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "Borrador guardado como «Horarios del cuadro de maestros»" in r.output
    nuevo = tmp_path / "v2.horario"
    r = runner.invoke(app, ["importar-v6", str(PROYECTO_V6), str(nuevo)])
    assert r.exit_code == 0 and nuevo.exists(), r.output
    r = runner.invoke(app, ["importar-v6", str(PROYECTO_V6), str(nuevo)])
    assert r.exit_code == 2 and "Ya existe" in r.output
    r = runner.invoke(app, ["importar-excel", str(proyecto), str(tmp_path / "no.xlsx")])
    assert r.exit_code == 2


# ---------------------------------------------------------------------------
# Asistentes de la interfaz
# ---------------------------------------------------------------------------


def test_asistente_de_horarios(ventana: Any, proyecto: Path) -> None:
    ventana.abrir_proyecto(proyecto)

    def recorrer(asistente: Any) -> bool:
        assert not asistente.avanzar()  # sin archivo
        assert "Elija el archivo" in asistente.error_actual()
        asistente.campo_archivo.setText(str(CUADRO_GRUPOS))
        assert asistente.avanzar()  # → vista previa
        assert "Hoja «1st»: 1A (24 celdas), 1B (24 celdas) · hora cívica: 1" in (
            asistente.texto_previa.toPlainText())  # fmt: skip
        assert asistente.avanzar()  # → mapeo
        asistente.poner_grado("1st", "(omitir)")
        asistente.poner_grado("2nd", "(omitir)")
        asistente.poner_grado("kinder", "(omitir)")
        assert not asistente.avanzar()
        assert "al menos una hoja" in asistente.error_actual()
        asistente.poner_grado("1st", "1° (Primaria)")
        asistente.poner_grado("2nd", "Nuevo grado «2nd» en Primaria")
        asistente.poner_asignatura("Math", "Matemáticas")
        asistente.poner_asignatura("MATH", "Matemáticas")
        asistente.poner_asignatura("Gym", "(ignorar)")
        assert asistente.avanzar()  # → resumen
        resumen = asistente.texto_resumen.toPlainText()
        assert "Grados nuevos: 2nd (Primaria)" in resumen and "Matemáticas" in resumen
        asistente.accept()
        return asistente.aplicado

    ventana.dialogos.responder(recorrer)
    assert ventana.importar_cuadro("horarios")
    titulo, informe = ventana.dialogos.mostrados[-1]
    assert titulo == "Importar cuadro de horarios" and "Asignaturas nuevas" in informe
    datos = ventana.contexto.sesion.datos
    assert {a.nombre for a in datos.asignaturas} == {"Matemáticas", "Español", "Science", "Art"}
    assert sorted(g.nombre for g in datos.grados) == ["1°", "2nd", "2°", "Kinder"]
    # «Math» y «MATH» comparten un alias (se comparan sin mayúsculas).
    assert sorted(a.texto.lower() for a in datos.alias) == ["math", "sceince"]


def test_asistente_de_maestros_con_horarios(ventana: Any, proyecto: Path) -> None:
    _importar_horarios(proyecto)
    ventana.abrir_proyecto(proyecto)

    def recorrer(asistente: Any) -> bool:
        asistente.campo_archivo.setText(str(CUADRO_MAESTROS))
        asistente.con_horarios.setChecked(True)
        assert asistente.avanzar() and asistente.avanzar() and asistente.avanzar()
        assert "Borrador con los horarios del cuadro: 72 clases" in (
            asistente.texto_resumen.toPlainText())  # fmt: skip
        asistente.accept()
        return asistente.aplicado

    ventana.dialogos.responder(recorrer)
    assert ventana.importar_cuadro("maestros")
    assert "revíselo en el Editor" in ventana.dialogos.mostrados[-1][1]
    sesion = ventana.contexto.sesion
    assert [s.nombre for s in sesion.soluciones()] == [importacion.NOMBRE_BORRADOR_MAESTROS]
    assert len(sesion.datos.profesores) == 6
    # El borrador se abre en el editor sin conflictos.
    editor: Any = ventana.ir_a("editor")
    editor.abrir_borrador(sesion.soluciones()[0].id)
    assert editor.edicion.estado().conflictos == 0


def test_abrir_un_v6_ofrece_importarlo(ventana: Any, tmp_path: Path) -> None:
    destino = tmp_path / "convertido.horario"

    def recorrer(asistente: Any) -> bool:
        assert asistente.campo_origen.text() == str(PROYECTO_V6)
        asistente.campo_destino.setText(str(destino))
        assert asistente.avanzar()
        assert "Horarios guardados: 1" in asistente.texto_resumen.toPlainText()
        asistente.accept()
        return asistente.aplicado

    ventana.dialogos.responder(True, recorrer)
    sesion = ventana.abrir_proyecto(PROYECTO_V6)
    assert sesion is not None and sesion.ruta == destino
    assert ventana.dialogos.mostrados[-1][0] == "Proyecto importado"
    assert sesion.vigente() is not None


def test_menu_importar_proyecto_anterior_valida(ventana: Any, tmp_path: Path) -> None:
    def recorrer(asistente: Any) -> bool:
        assert not asistente.avanzar()
        assert "Elija el proyecto" in asistente.error_actual()
        asistente.campo_origen.setText(str(CUADRO_GRUPOS))
        assert not asistente.avanzar()
        assert "no es un proyecto de la versión anterior" in asistente.error_actual()
        return False

    ventana.dialogos.responder(recorrer)
    ventana.accion_importar.trigger()
    assert ventana.contexto.sesion is None
    assert not ventana.accion_importar_horarios.isEnabled()
