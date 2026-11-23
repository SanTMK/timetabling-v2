"""Creado con Claude.

Validación global (§10): cada revisión con su mensaje, sobre variaciones del ejemplo pequeño
(primaria de 5 grupos, 7 franjas diarias de 50 min, receso de 10:00 a 10:30).
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from timetabling.cli import app
from timetabling.dominio.modelos import (
    AsignacionFija,
    Asignatura,
    BloqueoGrupo,
    Clase,
    DatosEscuela,
    Destinatario,
    Disponibilidad,
    Division,
    Espacio,
    Evento,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    RangoFranjas,
    ReglasAsignatura,
)
from timetabling.dominio.tiempo import a_minutos
from timetabling.ejemplo import crear_ejemplo, ejemplo_mediano, ejemplo_pequeno
from timetabling.nucleo.validacion import Problema, hay_errores, validar

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _datos() -> DatosEscuela:
    return ejemplo_pequeno()


def _asignatura(datos: DatosEscuela, nombre: str) -> Asignatura:
    return next(a for a in datos.asignaturas if a.nombre == nombre)


def _profesor(datos: DatosEscuela, nombre: str) -> Profesor:
    return next(p for p in datos.profesores if p.nombre == nombre)


def _grupo(datos: DatosEscuela, nombre: str) -> Grupo:
    return next(g for g in datos.grupos if datos.nombre_grupo(g.id or 0) == nombre)


def _clase(datos: DatosEscuela, asignatura: str, grupo: str) -> Clase:
    a = _asignatura(datos, asignatura)
    g = _grupo(datos, grupo)
    return next(
        c
        for c in datos.clases
        if c.asignatura_id == a.id and any(d.grupo_id == g.id for d in c.destinatarios)
    )


def _errores(datos: DatosEscuela) -> list[Problema]:
    return [p for p in validar(datos) if p.es_error]


def _advertencias(datos: DatosEscuela) -> list[Problema]:
    return [p for p in validar(datos) if not p.es_error]


def _uno(problemas: list[Problema], fragmento: str) -> Problema:
    coincidencias = [p for p in problemas if fragmento in p.mensaje]
    assert coincidencias, (
        f"Ningún problema contiene «{fragmento}»: {[p.mensaje for p in problemas]}"
    )
    return coincidencias[0]


# ---------------------------------------------------------------------------
# Sin problemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fabrica", [ejemplo_pequeno, ejemplo_mediano])
def test_ejemplos_sin_problemas(fabrica: Callable[[], DatosEscuela]) -> None:
    assert validar(fabrica()) == []


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


def test_cobertura_horas_de_mas() -> None:
    datos = _datos()
    _clase(datos, "Español", "1°A").horas_semanales = 7
    problema = _uno(_errores(datos), "1°A recibe 7 h de Español y el plan pide 6 h (sobran 1 h)")
    assert problema.entidad == "grupo" and "Sincronizar con el plan" in problema.accion


def test_cobertura_horas_de_menos() -> None:
    datos = _datos()
    _clase(datos, "Español", "1°A").horas_semanales = 4
    _uno(_errores(datos), "1°A recibe 4 h de Español y el plan pide 6 h (faltan 2 h)")


def test_clase_huerfana() -> None:
    datos = _datos()
    datos.asignaturas.append(Asignatura(id=99, nombre="Robótica"))
    datos.clases.append(
        Clase(id=999, asignatura_id=99, destinatarios=[Destinatario(grupo_id=1)],
              horas_semanales=1)
    )  # fmt: skip
    problema = _uno(_errores(datos), "Robótica · 1°A no corresponde al plan de estudios")
    assert problema.entidad == "clase" and problema.id == 999


def test_conjunta_de_distinto_nivel() -> None:
    datos = _datos()
    datos.niveles.append(Nivel(id=2, nombre="Secundaria", inicio_jornada=420, fin_jornada=840))
    datos.grados.append(Grado(id=20, nivel_id=2, nombre="7°"))
    datos.grupos.append(Grupo(id=20, grado_id=20, seccion="A"))
    clase = _clase(datos, "Artes", "1°A")
    clase.destinatarios = [*clase.destinatarios, Destinatario(grupo_id=20)]
    _uno(_errores(datos), "La clase conjunta Artes · 1°A, 7°A junta grupos de distintos niveles")


def test_division_de_otro_grupo_y_parte_inexistente() -> None:
    datos = _datos()
    datos.divisiones.append(Division(id=1, grupo_id=2, partes=["Básico", "Avanzado"]))
    clase = _clase(datos, "Inglés", "1°A")
    clase.destinatarios = [Destinatario(grupo_id=1, division_id=1, parte="Básico")]
    _uno(_errores(datos), "usa una división que no pertenece a 1°A")
    otra = _clase(datos, "Inglés", "2°A")
    otra.destinatarios = [Destinatario(grupo_id=2, division_id=1, parte="Medio")]
    _uno(_errores(datos), "usa la parte «Medio», que no existe")


def test_clase_sin_profesor_posible() -> None:
    datos = _datos()
    for profesor in datos.profesores:
        profesor.asignaturas = [a for a in profesor.asignaturas
                                if a != _asignatura(datos, "Artes").id]  # fmt: skip
    problema = _uno(
        _errores(datos), "Ningún profesor activo está habilitado para impartir Artes · 3°A"
    )
    assert "Habilite a un profesor para Artes" in problema.accion


def test_profesor_fijo_no_habilitado_o_inactivo() -> None:
    datos = _datos()
    _clase(datos, "Artes", "1°A").profesores = [_profesor(datos, "Ana López").id or 0]
    _uno(_errores(datos), "Ana López es profesor fijo de Artes · 1°A pero no está habilitado")
    jorge = _profesor(datos, "Jorge Peña")
    _clase(datos, "Artes", "2°A").profesores = [jorge.id or 0]
    jorge.activo = False
    _uno(_errores(datos), "Jorge Peña está inactivo y es profesor fijo de Artes · 2°A")


def test_horas_del_grupo_superan_sus_franjas() -> None:
    datos = _datos()
    _grupo(datos, "1°A").bloqueos = [
        BloqueoGrupo(dia=d, inicio=a_minutos("07:30"), fin=a_minutos("14:00"))
        for d in ("L", "M", "X", "J")
    ]
    _uno(_errores(datos), "1°A necesita 25 h de clase a la semana y solo tiene 7 franjas útiles")


def test_horas_con_division_simultanea_cuentan_una_vez() -> None:
    datos = _datos()
    datos.divisiones.append(Division(id=1, grupo_id=1, partes=["Básico", "Avanzado"]))
    ingles = _clase(datos, "Inglés", "1°A")
    ingles.destinatarios = [Destinatario(grupo_id=1, division_id=1, parte="Básico")]
    datos.clases.append(
        ingles.model_copy(update={
            "id": 500,
            "destinatarios": [Destinatario(grupo_id=1, division_id=1, parte="Avanzado")],
        })
    )  # fmt: skip
    assert validar(datos) == []
    datos.divisiones[0].simultanea = False
    datos.clases.append(
        Clase(id=501, asignatura_id=_asignatura(datos, "Artes").id or 0, horas_semanales=6,
              destinatarios=[Destinatario(grupo_id=1)])
    )  # fmt: skip
    # 21 h de grupo completo + 6 extra + 4 + 4 (las partes ya no se empalman) = 35: aún cabe.
    assert not any("necesita" in p.mensaje for p in _errores(datos))
    datos.clases[-1].horas_semanales = 7
    _uno(_errores(datos), "1°A necesita 36 h de clase a la semana y solo tiene 35 franjas útiles")


def test_capacidad_docente() -> None:
    datos = _datos()
    for nombre in ("Irene Castro", "Luis Navarro"):
        _profesor(datos, nombre).carga_max_semanal_min = 100
    problema = _uno(
        _errores(datos),
        "Ed. Física en Primaria requiere 500 min de clase a la semana y los profesores "
        "habilitados solo pueden cubrir 200 min",
    )
    assert problema.entidad == "asignatura"


def test_profesor_carga_fija_excesiva() -> None:
    datos = _datos()
    ana = _profesor(datos, "Ana López")
    ana.carga_max_semanal_min = 200
    _clase(datos, "Español", "1°A").profesores = [ana.id or 0]
    _uno(
        _errores(datos),
        "Ana López tiene 300 min de clases con profesor fijo y su carga máxima semanal es de "
        "200 min",
    )


def test_profesor_horas_fijas_contra_su_disponibilidad() -> None:
    datos = _datos()
    ana = _profesor(datos, "Ana López")
    ana.disponible_toda_la_jornada = False
    ana.disponibilidad = [
        Disponibilidad(dia="L", inicio=a_minutos("07:30"), fin=a_minutos("09:10"))
    ]
    _clase(datos, "Español", "1°A").profesores = [ana.id or 0]
    _uno(
        _errores(datos),
        "Ana López tiene 6 h fijas en Primaria pero solo está disponible en 2 franjas",
    )


def test_carga_minima_imposible() -> None:
    datos = _datos()
    _profesor(datos, "Irene Castro").carga_min_semanal_min = 600
    _uno(
        _errores(datos),
        "Irene Castro debe tener al menos 600 min de clase, pero las clases que puede impartir "
        "suman 500 min",
    )


def test_espacio_inexistente() -> None:
    datos = _datos()
    _asignatura(datos, "Artes").espacio_requerido = "taller"
    problema = _uno(_errores(datos), "Artes requiere un espacio de tipo «taller» y no hay ninguno")
    assert problema.entidad == "espacio"


def test_demanda_de_espacios() -> None:
    datos = _datos()
    datos.espacios.append(Espacio(id=1, nombre="Aula de cómputo", tipo="computo"))
    _asignatura(datos, "Español").espacio_requerido = "computo"
    _asignatura(datos, "Matemáticas").espacio_requerido = "computo"
    _uno(
        _errores(datos),
        "En Primaria se necesitan 60 h de espacios de tipo «computo» y solo caben 35 h",
    )


def _fija(datos: DatosEscuela, ident: int, clase: Clase, dia: str, indice: int,
          profesor: int | None = None) -> None:  # fmt: skip
    datos.fijas.append(
        AsignacionFija(
            id=ident, clase_id=clase.id or 0, profesor_id=profesor, dia=dia,  # type: ignore[arg-type]
            indice_franja=indice,
        )
    )  # fmt: skip


def test_fija_en_franja_inexistente_o_no_util() -> None:
    datos = _datos()
    datos.niveles[0].eventos = [Evento(dia="L", inicio=a_minutos("07:30"), fin=a_minutos("08:20"))]
    espanol = _clase(datos, "Español", "1°A")
    _fija(datos, 1, espanol, "L", 9)
    _fija(datos, 2, espanol, "L", 0)
    errores = _errores(datos)
    _uno(errores, "La clase fija Español · 1°A está en la hora 10 del lunes, que no existe")
    _uno(errores, "lunes de 07:30–08:20, que no es una franja útil")


def test_fija_en_franja_prohibida() -> None:
    datos = _datos()
    _fija(datos, 1, _clase(datos, "Ed. Física", "1°A"), "M", 0)
    _uno(_errores(datos), "franja prohibida para Ed. Física")


def test_fija_con_profesor_imposible_o_no_disponible() -> None:
    datos = _datos()
    espanol = _clase(datos, "Español", "1°A")
    _fija(datos, 1, espanol, "M", 1, profesor=_profesor(datos, "Irene Castro").id)
    _uno(_errores(datos), "Irene Castro no puede impartir la clase fija Español · 1°A")

    datos = _datos()
    ana = _profesor(datos, "Ana López")
    ana.disponibilidad = [
        Disponibilidad(dia="M", inicio=a_minutos("08:00"), fin=a_minutos("09:00"),
                       tipo="no_disponible")
    ]  # fmt: skip
    _fija(datos, 1, _clase(datos, "Español", "1°A"), "M", 1, profesor=ana.id)
    _uno(_errores(datos), "Ana López no está disponible de 08:00–09:00")

    datos = _datos()
    espanol = _clase(datos, "Español", "1°A")
    espanol.profesores = [_profesor(datos, "Ana López").id or 0]
    _fija(datos, 1, espanol, "M", 1, profesor=_profesor(datos, "Bruno Díaz").id)
    _uno(_errores(datos), "indica profesor, pero la clase ya tiene profesores fijos")


def test_mas_fijas_que_horas() -> None:
    datos = _datos()
    civica = _clase(datos, "Formación Cívica", "1°A")
    _fija(datos, 1, civica, "L", 1)
    _fija(datos, 2, civica, "M", 1)
    _uno(_errores(datos), "Formación Cívica · 1°A tiene 2 asignaciones fijas y solo 1 h")


def test_fijas_que_chocan() -> None:
    datos = _datos()
    ana = _profesor(datos, "Ana López").id
    _fija(datos, 1, _clase(datos, "Español", "1°A"), "L", 1, profesor=ana)
    _fija(datos, 2, _clase(datos, "Matemáticas", "1°A"), "L", 1)
    _fija(datos, 3, _clase(datos, "Español", "2°A"), "L", 1, profesor=ana)
    errores = _errores(datos)
    _uno(errores, "Las clases fijas Español · 1°A y Matemáticas · 1°A coinciden")
    _uno(errores, "Ana López tendría a la vez las clases fijas Español · 1°A y Español · 2°A")


def test_maximo_diario_insuficiente() -> None:
    datos = _datos()
    _asignatura(datos, "Español").reglas_por_defecto.max_horas_dia = 1
    _uno(
        _errores(datos),
        "Español · 1°A tiene 6 h y con un máximo de 1 h al día en 5 días solo caben 5 h",
    )


def test_bloque_doble_obligatorio_con_maximo_1() -> None:
    datos = _datos()
    _asignatura(datos, "Artes").reglas_por_defecto = ReglasAsignatura(
        max_horas_dia=1, bloque_doble="obligatorio"
    )
    problema = _uno(_errores(datos), "Artes exige bloque doble en Primaria")
    assert problema.entidad == "asignatura"
    assert sum("exige bloque doble" in p.mensaje for p in _errores(datos)) == 1


def test_division_simultanea_con_horas_distintas() -> None:
    datos = _datos()
    datos.divisiones.append(Division(id=1, grupo_id=1, partes=["Básico", "Avanzado"]))
    ingles = _clase(datos, "Inglés", "1°A")
    ingles.destinatarios = [Destinatario(grupo_id=1, division_id=1, parte="Básico")]
    datos.clases.append(
        ingles.model_copy(update={
            "id": 500, "horas_semanales": 3,
            "destinatarios": [Destinatario(grupo_id=1, division_id=1, parte="Avanzado")],
        })
    )  # fmt: skip
    _uno(
        _errores(datos),
        "Las partes de «Inglés por nivel» de 1°A tienen horas distintas de Inglés "
        "(Básico: 4 h, Avanzado: 3 h)",
    )


def test_franjas_prohibidas_insuficientes() -> None:
    datos = _datos()
    _asignatura(datos, "Ed. Física").reglas_por_defecto.franjas_prohibidas = [
        RangoFranjas(desde_indice=0, hasta_indice=5),
        RangoFranjas(dias=("L", "M", "X", "J"), desde_indice=6, hasta_indice=6),
    ]
    _uno(
        _errores(datos),
        "Las franjas prohibidas de Ed. Física dejan a Ed. Física · 1°A con 1 franja para 2 h",
    )


# ---------------------------------------------------------------------------
# Advertencias
# ---------------------------------------------------------------------------


def test_advertencias_de_tiempo() -> None:
    datos = _datos()
    nivel = datos.niveles[0]
    nivel.eventos = [Evento(nombre="Festival", dia="S", inicio=600, fin=660)]
    nivel.duraciones_especiales = {12: 30}
    _grupo(datos, "2°A").bloqueos = [BloqueoGrupo(nombre="Coro", dia="L", inicio=1000, fin=1100)]
    _profesor(datos, "Ana López").disponibilidad = [
        Disponibilidad(dia="L", inicio=a_minutos("18:00"), fin=a_minutos("19:00"),
                       tipo="no_disponible")
    ]  # fmt: skip
    advertencias = _advertencias(datos)
    assert not hay_errores(validar(datos))
    _uno(advertencias, "El evento «Festival» de Primaria (Sábado 10:00–11:00) no toca ninguna")
    _uno(advertencias, "duración especial para la hora 13, pero el día solo tiene 7 horas")
    _uno(advertencias, "El bloqueo «Coro» de 2°A (Lunes 16:40–18:20) no toca ninguna franja")
    _uno(advertencias, "El rango Lunes 18:00–19:00 de Ana López no cubre ninguna franja")


def test_advertencias_de_incompletos() -> None:
    datos = _datos()
    datos.niveles.append(Nivel(id=2, nombre="Taller", inicio_jornada=600, fin_jornada=620))
    datos.grados.append(Grado(id=30, nivel_id=1, nombre="6°"))
    datos.profesores.append(Profesor(id=50, nombre="Nuevo Profesor"))
    advertencias = _advertencias(datos)
    _uno(advertencias, "El grado 6° (Primaria) no tiene grupos")
    _uno(advertencias, "El grado 6° (Primaria) no tiene plan de estudios")
    _uno(advertencias, "Taller no tiene franjas útiles")
    _uno(advertencias, "Nuevo Profesor no tiene asignaturas habilitados")
    datos.plan.append(PlanEstudios(grado_id=30, asignatura_id=1, horas_semanales=1))
    assert not any("6° (Primaria) no tiene plan" in p.mensaje for p in _advertencias(datos))


def test_problemas_traen_accion_y_entidad() -> None:
    datos = _datos()
    _clase(datos, "Español", "1°A").horas_semanales = 9
    _asignatura(datos, "Artes").espacio_requerido = "taller"
    for problema in validar(datos):
        assert problema.accion and problema.elemento and problema.entidad


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------


def test_cli_validar(tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "m.horario", "mediano")
    resultado = CliRunner().invoke(app, ["validar", str(ruta)])
    assert resultado.exit_code == 0, resultado.output
    assert "0 errores, 0 advertencias." in resultado.output


def test_cli_validar_con_errores(tmp_path: Path) -> None:
    from timetabling.persistencia.repositorio import Repositorio

    ruta = crear_ejemplo(tmp_path / "p.horario")
    with Repositorio.abrir(ruta, respaldo_diario=False) as repo:
        datos = repo.cargar_datos()
        clase = _clase(datos, "Español", "1°A")
        clase.horas_semanales = 2
        repo.guardar(clase)
    resultado = CliRunner().invoke(app, ["validar", str(ruta)])
    assert resultado.exit_code == 1
    assert "✖ Error: 1°A recibe 2 h de Español" in resultado.output
    assert "1 error, 0 advertencias." in resultado.output


def test_cli_validar_archivo_inexistente(tmp_path: Path) -> None:
    resultado = CliRunner().invoke(app, ["validar", str(tmp_path / "no.horario")])
    assert resultado.exit_code == 2
