"""Creado con Claude.

Borradores (§12.1): colocar, quitar, mover, intercambiar, bloquear, cambiar profesor,
pendientes y tarjetas, deshacer y rehacer (operaciones inversas), guardado inmediato,
«Completar el resto», «Validar y guardar como definitivo» y fijas para generar (§12.5).
"""

from pathlib import Path

import pytest

from pruebas.escuelas import (
    ANA,
    BETO,
    CARO,
    FISICA_A,
    INGLES_A,
    MATE,
    MATE_A,
    MATE_B,
    escuela_minima,
    f,
    horario_valido,
)
from timetabling.dominio.borrador import Borrador, Colocacion, ErrorBorrador
from timetabling.dominio.modelos import EstadoSolucion, ReglasAsignatura
from timetabling.ejemplo import crear_ejemplo
from timetabling.nucleo.verificador import verificar
from timetabling.servicios.edicion import (
    EdicionBorrador,
    ErrorEdicion,
    bloqueadas_para_generar,
    nuevo_borrador,
)
from timetabling.servicios.generacion import generar_en_memoria, opciones_de
from timetabling.servicios.sesion import SesionProyecto
from timetabling.servicios.soluciones import a_colocaciones, a_solucion

# ---------------------------------------------------------------------------
# Operaciones puras
# ---------------------------------------------------------------------------


def test_colocar_quitar_mover() -> None:
    borrador = Borrador()
    a = Colocacion(MATE_A, f("L", 0), (ANA,))
    borrador.aplicar(borrador.colocar(a))
    assert borrador.colocaciones == [a]
    movida = borrador.mover(a, f("M", 1))
    borrador.aplicar(movida)
    assert borrador.colocaciones == [Colocacion(MATE_A, f("M", 1), (ANA,))]
    borrador.aplicar(movida.inversa())
    assert borrador.colocaciones == [a]
    borrador.aplicar(borrador.quitar(a))
    assert borrador.colocaciones == []


def test_intercambiar_y_deshacer() -> None:
    borrador = Borrador.de(horario_valido())
    a = borrador.buscar(MATE_A, f("L", 1))
    b = borrador.buscar(FISICA_A, f("L", 2))
    assert a is not None and b is not None
    operacion = borrador.intercambiar(a, b)
    antes = list(borrador.colocaciones)
    borrador.aplicar(operacion)
    assert borrador.buscar(MATE_A, f("L", 2)) is not None
    assert borrador.buscar(FISICA_A, f("L", 1)) is not None
    borrador.aplicar(operacion.inversa())  # deshacer
    assert borrador.colocaciones == antes
    borrador.aplicar(operacion)  # rehacer
    assert borrador.buscar(FISICA_A, f("L", 1)) is not None


def test_bloquear_y_cambiar_profesor() -> None:
    borrador = Borrador.de(horario_valido())
    c = borrador.buscar(MATE_B, f("L", 0))
    assert c is not None
    borrador.aplicar(borrador.bloquear(c))
    assert borrador.buscar(MATE_B, f("L", 0)).bloqueada  # type: ignore[union-attr]
    assert len(borrador.bloqueadas()) == 1
    operacion = borrador.cambiar_profesor(MATE_B, [ANA])
    borrador.aplicar(operacion)
    assert {c.profesores for c in borrador.de_clase(MATE_B)} == {(ANA,)}
    assert borrador.buscar(MATE_B, f("L", 0)).bloqueada  # type: ignore[union-attr]
    borrador.aplicar(operacion.inversa())
    assert {c.profesores for c in borrador.de_clase(MATE_B)} == {(BETO,)}


def test_errores_dejan_el_borrador_intacto() -> None:
    borrador = Borrador.de(horario_valido())
    antes = list(borrador.colocaciones)
    with pytest.raises(ErrorBorrador):
        borrador.aplicar(borrador.quitar(Colocacion(MATE_A, f("V", 0), (ANA,))))
    with pytest.raises(ErrorBorrador, match="ya está en esa franja"):
        borrador.aplicar(borrador.colocar(Colocacion(MATE_A, f("L", 0), (ANA,))))
    assert borrador.colocaciones == antes


def test_reemplazar_toca_solo_lo_que_cambia() -> None:
    borrador = Borrador.de(horario_valido())
    nuevas = [c if c.clase_id != INGLES_A else c.en(f("M", 3)) for c in borrador.colocaciones]
    operacion = borrador.reemplazar(nuevas, "Reacomodo")
    assert len(operacion.quitar) == 1 and len(operacion.poner) == 1
    borrador.aplicar(operacion)
    assert sorted(borrador.colocaciones) == sorted(nuevas)


def test_pendientes_y_tarjetas() -> None:
    datos = escuela_minima()
    datos.asignaturas[MATE - 1].reglas_por_defecto = ReglasAsignatura(bloque_doble="obligatorio")
    borrador = Borrador.de([Colocacion(INGLES_A, f("L", 0), (CARO,))])
    assert borrador.pendientes(datos) == {MATE_A: 2, MATE_B: 2, FISICA_A: 1, 14: 1}
    tarjetas = {t.clase_id: t for t in borrador.tarjetas(datos)}
    assert tarjetas[MATE_A].texto == "Matemáticas · 1°A · faltan 2 de 2 · bloque de 2"
    assert tarjetas[MATE_A].franjas == 2
    assert tarjetas[FISICA_A].texto == "Ed. Física · 1°A · faltan 1 de 1"
    datos.clases[0].profesores = [ANA]
    assert "· Ana ·" in Borrador().tarjetas(datos)[0].texto


# ---------------------------------------------------------------------------
# Edición con guardado
# ---------------------------------------------------------------------------


@pytest.fixture
def sesion(tmp_path: Path) -> SesionProyecto:
    ruta = tmp_path / "m.horario"
    sesion = SesionProyecto.nuevo(ruta, "Mínima")
    sesion.repo.reemplazar_datos(escuela_minima())
    sesion._cambio()
    yield sesion
    sesion.cerrar()


def _borrador(sesion: SesionProyecto, colocaciones: list[Colocacion]) -> int:
    solucion = a_solucion(sesion.datos, colocaciones, nombre="Mi borrador",
                          estado=EstadoSolucion.BORRADOR, origen="manual")  # fmt: skip
    return sesion.guardar_solucion(solucion).id or 0


def test_cada_operacion_se_guarda(sesion: SesionProyecto) -> None:
    ident = _borrador(sesion, horario_valido()[:3])
    edicion = EdicionBorrador(sesion, ident)
    colocacion = Colocacion(INGLES_A, f("M", 0), (CARO,), bloqueada=True)
    edicion.aplicar(edicion.borrador.colocar(colocacion))
    guardada = sesion.cargar_solucion(ident)
    assert colocacion in a_colocaciones(guardada)
    assert guardada.estado is EstadoSolucion.BORRADOR and guardada.nombre == "Mi borrador"
    assert edicion.estado().pendientes == 3
    # Los índices de conflictos siguen al borrador.
    assert edicion.conflictos.colocaciones_de(INGLES_A) == [colocacion]


def test_estado_en_vivo(sesion: SesionProyecto) -> None:
    edicion = EdicionBorrador(sesion, _borrador(sesion, horario_valido()))
    estado = edicion.estado()
    assert (estado.pendientes, estado.conflictos) == (0, 0)
    choque = Colocacion(MATE_B, f("L", 1), (ANA,))  # Ana ya da 1°A a esa hora
    edicion.aplicar(edicion.borrador.colocar(choque))
    estado = edicion.estado()
    assert estado.conflictos >= 1 and any("Ana ya da" in v for v in estado.violaciones)


def test_solo_se_editan_borradores(sesion: SesionProyecto) -> None:
    solucion = a_solucion(sesion.datos, horario_valido(), nombre="Generado",
                          estado=EstadoSolucion.OPTIMO, origen="generado")  # fmt: skip
    ident = sesion.guardar_solucion(solucion).id or 0
    with pytest.raises(ErrorEdicion, match="Solo se pueden editar los borradores"):
        EdicionBorrador(sesion, ident)
    copia = nuevo_borrador(sesion, copia_de=ident)
    assert copia.nombre == "Copia de Generado" and copia.base_id == ident
    assert copia.origen == "editado"
    edicion = EdicionBorrador(sesion, copia.id or 0)
    assert edicion.cambiadas() == set()
    c = edicion.borrador.buscar(INGLES_A, f("M", 0))
    assert c is not None
    edicion.aplicar(edicion.borrador.mover(c, f("M", 3)))
    assert edicion.cambiadas() == {(INGLES_A, f("M", 3))}
    vacio = nuevo_borrador(sesion, "Desde cero")
    assert vacio.asignaciones == [] and vacio.origen == "manual"


def test_borrador_desactualizado_no_se_edita(sesion: SesionProyecto) -> None:
    ident = _borrador(sesion, horario_valido())
    nivel = sesion.datos.niveles[0]
    sesion.guardar(nivel.model_copy(update={"duracion_min": 45}))
    with pytest.raises(ErrorEdicion, match="otra configuración de niveles"):
        EdicionBorrador(sesion, ident)


def test_validar_y_guardar_como_definitivo(sesion: SesionProyecto) -> None:
    edicion = EdicionBorrador(sesion, _borrador(sesion, horario_valido()[:-1]))
    incompleto = edicion.validar_definitivo()
    assert not incompleto.valida and incompleto.violaciones[0].restriccion == "D1"
    assert sesion.cargar_solucion(edicion.solucion.id or 0).estado is EstadoSolucion.BORRADOR
    edicion.aplicar(edicion.borrador.colocar(horario_valido()[-1]))
    assert edicion.validar_definitivo().valida
    definitivo = sesion.cargar_solucion(edicion.solucion.id or 0)
    assert definitivo.estado is EstadoSolucion.FACTIBLE
    assert "total" in definitivo.penalizaciones
    sesion.marcar_vigente(definitivo.id)
    assert sesion.vigente() is not None


def test_completar_el_resto(sesion: SesionProyecto) -> None:
    bloqueada = Colocacion(MATE_A, f("M", 2), (ANA,), bloqueada=True)
    libre = Colocacion(INGLES_A, f("L", 3), (CARO,))
    ident = _borrador(sesion, [bloqueada, libre])
    edicion = EdicionBorrador(sesion, ident)
    nuevo = edicion.completar(tiempo_limite_s=10)
    assert nuevo is not None and nuevo.id != ident
    assert nuevo.estado is EstadoSolucion.BORRADOR and nuevo.base_id == ident
    colocaciones = a_colocaciones(nuevo)
    assert bloqueada in colocaciones  # sigue fija y bloqueada
    assert libre in colocaciones  # la base se respeta mientras no estorbe (B9)
    assert verificar(sesion.datos, colocaciones).valida
    # El original no se toca.
    assert a_colocaciones(sesion.cargar_solucion(ident)) == sorted([bloqueada, libre])
    otra = EdicionBorrador(sesion, nuevo.id or 0)
    assert otra.cambiadas() == {(c.clase_id, c.franja_id) for c in colocaciones} - {
        (MATE_A, f("M", 2)), (INGLES_A, f("L", 3))
    }  # fmt: skip


def test_bloqueadas_entran_como_fijas_al_generar(sesion: SesionProyecto) -> None:
    assert bloqueadas_para_generar(sesion) == ([], "")
    bloqueada = Colocacion(INGLES_A, f("M", 3), (ANA,), bloqueada=True)
    _borrador(sesion, [bloqueada])
    fijas, origen = bloqueadas_para_generar(sesion)
    assert fijas == [bloqueada] and origen == "Mi borrador"
    assert "1 clases bloqueadas en «Mi borrador»" in sesion.origen_fijas(1, origen)
    opciones = opciones_de(sesion.datos, tiempo_limite_s=10, hilos=2)
    opciones.fijar = fijas
    resultado = generar_en_memoria(sesion.datos, opciones)
    assert resultado.solucion is not None
    assert Colocacion(INGLES_A, f("M", 3), (ANA,)) in a_colocaciones(resultado.solucion)


def test_ejemplo_mediano_copia_y_edicion(tmp_path: Path) -> None:
    ruta = crear_ejemplo(tmp_path / "m.horario", "mediano")
    sesion = SesionProyecto.abrir(ruta)
    try:
        opciones = opciones_de(sesion.datos, tiempo_limite_s=20, hilos=4)
        opciones.optimizar = False
        generado = generar_en_memoria(sesion.datos, opciones).solucion
        assert generado is not None
        ident = sesion.guardar_solucion(generado).id or 0
        copia = nuevo_borrador(sesion, copia_de=ident)
        edicion = EdicionBorrador(sesion, copia.id or 0)
        assert len(edicion.borrador.colocaciones) == 858
        primera = edicion.borrador.colocaciones[0]
        edicion.aplicar(edicion.borrador.quitar(primera))
        assert edicion.estado().pendientes == 1
    finally:
        sesion.cerrar()
