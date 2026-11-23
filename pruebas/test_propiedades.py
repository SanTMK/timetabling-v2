"""Creado con Claude.

Propiedades con Hypothesis (§20): sobre escuelas pequeñas aleatorias, si el resolutor devuelve
una solución, el verificador nunca la rechaza. La segunda propiedad (un INFACTIBLE produce un
núcleo de diagnóstico no vacío o un conflicto estructural) se agrega en F5, junto con el
diagnóstico.
"""

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from timetabling.dominio.clases import sincronizar_con_plan
from timetabling.dominio.modelos import (
    AsignacionFija,
    Asignatura,
    BloqueoGrupo,
    Configuracion,
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
    Receso,
    ReglasAsignatura,
)
from timetabling.dominio.tiempo import DIAS
from timetabling.nucleo.resolver import OpcionesResolucion, resolver
from timetabling.nucleo.verificador import verificar


@st.composite
def escuelas(draw: st.DrawFn) -> DatosEscuela:
    margen = draw(st.sampled_from([0, 5, 10]))
    datos = DatosEscuela(
        configuracion=Configuracion(
            margen_traslado_min=margen,
            descanso_minimo_min=draw(st.sampled_from([0, 10])),
            hilos=2,
        )
    )
    n_niveles = draw(st.integers(1, 2))
    dias = list(DIAS[: draw(st.integers(2, 3))])
    grupo_id = 0
    for n in range(1, n_niveles + 1):
        duracion = draw(st.sampled_from([40, 45, 50]))
        inicio = draw(st.sampled_from([420, 450, 480]))
        franjas = draw(st.integers(4, 6))
        con_receso = draw(st.booleans())
        fin = inicio + franjas * duracion + (20 if con_receso else 0)
        recesos = []
        if con_receso:
            r = inicio + 2 * duracion
            recesos = [Receso(inicio=r, fin=r + 20)]
        eventos = []
        if draw(st.booleans()):
            eventos = [Evento(dia=dias[-1], inicio=inicio, fin=inicio + 10)]
        datos.niveles.append(
            Nivel(
                id=n,
                nombre=f"Nivel {n}",
                duracion_min=duracion,
                inicio_jornada=inicio,
                fin_jornada=fin,
                dias=dias,
                recesos=recesos,
                eventos=eventos,
                huecos_alumnos=draw(st.sampled_from(["permitidos", "penalizar", "prohibidos"])),
            )
        )
        datos.grados.append(Grado(id=n, nivel_id=n, nombre=f"{n}°"))
        for seccion in "ABC"[: draw(st.integers(1, 3))]:
            grupo_id += 1
            bloqueos = []
            if draw(st.integers(0, 4)) == 0:
                bloqueos = [BloqueoGrupo(dia=dias[0], inicio=fin - duracion, fin=fin)]
            datos.grupos.append(Grupo(id=grupo_id, grado_id=n, seccion=seccion, bloqueos=bloqueos))

    n_asignaturas = draw(st.integers(2, 4))
    for a in range(1, n_asignaturas + 1):
        reglas = ReglasAsignatura(
            max_horas_dia=draw(st.integers(1, 3)),
            bloque_doble=draw(st.sampled_from(["no", "no", "obligatorio"])),
            franjas_prohibidas=(
                [RangoFranjas(desde_indice=0, hasta_indice=0)] if draw(st.booleans()) else []
            ),
        )
        datos.asignaturas.append(
            Asignatura(
                id=a,
                nombre=f"Asignatura {a}",
                espacio_requerido="lab" if draw(st.integers(0, 3)) == 0 else None,
                reglas_por_defecto=reglas,
            )
        )
    datos.espacios.append(Espacio(id=1, nombre="Lab", tipo="lab", cantidad=draw(st.integers(1, 2))))
    for grado in datos.grados:
        for asignatura in datos.asignaturas:
            horas = draw(st.integers(0, 2))
            if horas:
                datos.plan.append(
                    PlanEstudios(grado_id=grado.id or 0, asignatura_id=asignatura.id or 0,
                                 horas_semanales=horas)
                )  # fmt: skip

    for p in range(1, draw(st.integers(3, 6)) + 1):
        asignaturas = draw(
            st.lists(st.sampled_from([a.id or 0 for a in datos.asignaturas]), min_size=1,
                     unique=True)
        )  # fmt: skip
        grados = draw(
            st.lists(st.sampled_from([g.id or 0 for g in datos.grados]), min_size=1, unique=True)
        )
        parcial = draw(st.integers(0, 3)) == 0
        disponibilidad = []
        if parcial:
            fin_disponible = draw(st.sampled_from([600, 700]))
            disponibilidad = [Disponibilidad(dia=d, inicio=420, fin=fin_disponible) for d in dias]
        elif draw(st.booleans()):
            tipo = draw(st.sampled_from(["no_disponible", "preferible_no"]))
            disponibilidad = [Disponibilidad(dia=dias[0], inicio=480, fin=530, tipo=tipo)]
        datos.profesores.append(
            Profesor(
                id=p,
                nombre=f"Profesor {p}",
                asignaturas=asignaturas,
                grados=grados,
                disponible_toda_la_jornada=not parcial,
                disponibilidad=disponibilidad,
                max_minutos_continuos=draw(st.sampled_from([90, 120, 200])),
                carga_max_diaria_min=draw(st.sampled_from([200, 480])),
                max_dias=draw(st.sampled_from([None, None, 2])),
            )
        )

    for i, clase in enumerate(sincronizar_con_plan(datos).nuevas, start=1):
        clase.id = i
        datos.clases.append(clase)

    # A veces, un profesor fijo, una división simultánea o una asignación fija.
    if datos.clases and draw(st.booleans()):
        clase = draw(st.sampled_from(datos.clases))
        clase.profesores = [draw(st.sampled_from([p.id or 0 for p in datos.profesores]))]
    if draw(st.integers(0, 3)) == 0 and datos.clases:
        clase = draw(st.sampled_from(datos.clases))
        grupo = clase.destinatarios[0].grupo_id
        datos.divisiones.append(Division(id=1, grupo_id=grupo, partes=["X", "Y"]))
        clase.destinatarios = [Destinatario(grupo_id=grupo, division_id=1, parte="X")]
        datos.clases.append(
            clase.model_copy(
                update={
                    "id": 1000,
                    "destinatarios": [Destinatario(grupo_id=grupo, division_id=1, parte="Y")],
                }
            )
        )
    if draw(st.integers(0, 3)) == 0 and datos.clases:
        clase = draw(st.sampled_from(datos.clases))
        datos.fijas.append(
            AsignacionFija(id=1, clase_id=clase.id or 0, dia=dias[0],
                           indice_franja=draw(st.integers(0, 3)))
        )  # fmt: skip
    return datos


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(escuelas())
def test_el_verificador_acepta_lo_que_resuelve_el_modelo(datos: DatosEscuela) -> None:
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=10, hilos=2, optimizar=False))
    event(resultado.estado.value)
    if resultado.colocaciones:
        verificacion = verificar(datos, resultado.colocaciones)
        assert verificacion.valida, [v.mensaje for v in verificacion.violaciones]
