"""Creado con Claude.

Validación global (§10). Cada `Problema` nombra entidades concretas y trae una acción sugerida.
Con al menos un error no se resuelve. Las revisiones son condiciones necesarias (§22).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from timetabling.dominio.clases import (
    chocan_destinatarios,
    clases_huerfanas,
    cobertura_del_plan,
    grupos_de_clase,
    profesor_habilitado,
    profesores_posibles,
    texto_destinatario,
    texto_destinatarios,
)
from timetabling.dominio.modelos import (
    AsignacionFija,
    Clase,
    DatosEscuela,
    Destinatario,
    Nivel,
    Profesor,
    por_id,
)
from timetabling.dominio.tiempo import NOMBRES_DIAS, texto_rango
from timetabling.nucleo.franjas import (
    Calendario,
    Franja,
    evaluar_franja,
    prohibida,
    se_traslapan_franjas,
)

Severidad = Literal["error", "advertencia"]


@dataclass(frozen=True)
class Problema:
    entidad: str
    """Tipo de entidad: «clase», «grupo», «profesor», «asignatura», «nivel», «grado», «espacio»,
    «fija» o «division»."""
    id: int | None
    elemento: str
    severidad: Severidad
    mensaje: str
    accion: str

    @property
    def es_error(self) -> bool:
        return self.severidad == "error"


def hay_errores(problemas: Iterable[Problema]) -> bool:
    return any(p.es_error for p in problemas)


def _horas(n: int) -> str:
    return f"{n} h"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


class _Validador:
    def __init__(self, datos: DatosEscuela) -> None:
        self.datos = datos
        self.calendario = Calendario.de(datos)
        self.problemas: list[Problema] = []
        self.niveles = por_id(datos.niveles)
        self.grados = por_id(datos.grados)
        self.grupos = por_id(datos.grupos)
        self.divisiones = por_id(datos.divisiones)
        self.asignaturas = por_id(datos.asignaturas)
        self.profesores = por_id(datos.profesores)
        self.clases = por_id(datos.clases)
        self.simultaneas = {d.id for d in datos.divisiones if d.simultanea and d.id is not None}
        self.posibles: dict[int, list[int]] = {
            c.id: profesores_posibles(datos, c) for c in datos.clases if c.id is not None
        }

    # ------------------------------------------------------------------ utilidades

    def error(
        self, entidad: str, ident: int | None, elemento: str, mensaje: str, accion: str
    ) -> None:
        self.problemas.append(Problema(entidad, ident, elemento, "error", mensaje, accion))

    def advertencia(
        self, entidad: str, ident: int | None, elemento: str, mensaje: str, accion: str
    ) -> None:
        self.problemas.append(Problema(entidad, ident, elemento, "advertencia", mensaje, accion))

    def nombre_asignatura(self, ident: int) -> str:
        asignatura = self.asignaturas.get(ident)
        return asignatura.nombre if asignatura else f"asignatura {ident}"

    def nombre_grupo(self, ident: int) -> str:
        return self.datos.nombre_grupo(ident) if ident in self.grupos else f"grupo {ident}"

    def texto_clase(self, clase: Clase) -> str:
        try:
            destinatarios = texto_destinatarios(self.datos, clase)
        except KeyError:
            destinatarios = "grupos inexistentes"
        return f"{self.nombre_asignatura(clase.asignatura_id)} · {destinatarios}"

    def niveles_de_clase(self, clase: Clase) -> set[int]:
        niveles: set[int] = set()
        for grupo_id in grupos_de_clase(clase):
            grupo = self.grupos.get(grupo_id)
            grado = self.grados.get(grupo.grado_id) if grupo else None
            if grado:
                niveles.add(grado.nivel_id)
        return niveles

    def nivel_de_clase(self, clase: Clase) -> Nivel | None:
        """El nivel de la clase, o `None` si sus grupos son de varios niveles."""
        niveles = self.niveles_de_clase(clase)
        return self.niveles.get(next(iter(niveles))) if len(niveles) == 1 else None

    def franjas_posibles(self, clase: Clase) -> list[Franja]:
        """Útiles para todos sus grupos y no prohibidas para la asignatura en su nivel."""
        nivel = self.nivel_de_clase(clase)
        asignatura = self.asignaturas.get(clase.asignatura_id)
        if nivel is None or asignatura is None:
            return []
        reglas = asignatura.reglas_efectivas(nivel.id)
        comunes = self.calendario.utiles_comunes(grupos_de_clase(clase))
        return [f for f in comunes if not prohibida(reglas, f)]

    def minutos_clase(self, clase: Clase) -> int:
        nivel = self.nivel_de_clase(clase)
        return clase.horas_semanales * (nivel.duracion_min if nivel else 0)

    def minutos_disponibles(self, profesor: Profesor, nivel_id: int) -> int:
        return sum(
            f.duracion
            for f in self.calendario.utiles_nivel.get(nivel_id, [])
            if evaluar_franja(profesor, f).valida
        )

    def franjas_validas(self, profesor: Profesor, nivel_id: int) -> int:
        return sum(
            1
            for f in self.calendario.utiles_nivel.get(nivel_id, [])
            if evaluar_franja(profesor, f).valida
        )

    # ------------------------------------------------------------------ revisiones

    def ejecutar(self) -> list[Problema]:
        self.cobertura()
        self.destinatarios()
        self.profesor_posible()
        self.horas_por_grupo()
        self.capacidad_docente()
        self.por_profesor()
        self.carga_minima()
        self.espacios()
        self.fijas()
        self.maximo_diario()
        self.bloque_doble()
        self.divisiones_simultaneas()
        self.franjas_prohibidas()
        self.advertencias_de_tiempo()
        self.incompletos()
        return self.problemas

    def cobertura(self) -> None:
        for d in cobertura_del_plan(self.datos):
            grupo = self.nombre_grupo(d.grupo_id)
            quien = grupo if d.parte is None else f"{grupo} ({d.parte})"
            asignatura = self.nombre_asignatura(d.asignatura_id)
            exceso = d.diferencia
            detalle = f"sobran {_horas(exceso)}" if exceso > 0 else f"faltan {_horas(-exceso)}"
            self.error(
                "grupo",
                d.grupo_id,
                quien,
                f"{quien} recibe {_horas(d.recibido)} de {asignatura} y el plan pide "
                f"{_horas(d.esperado)} ({detalle}).",
                f"Ajuste las horas de las clases de {asignatura} de {grupo} o use "
                "«Sincronizar con el plan».",
            )
        for clase in clases_huerfanas(self.datos):
            asignatura = self.nombre_asignatura(clase.asignatura_id)
            self.error(
                "clase",
                clase.id,
                self.texto_clase(clase),
                f"La clase {self.texto_clase(clase)} no corresponde al plan de estudios: "
                f"{asignatura} no está en el plan de alguno de sus grados.",
                f"Agregue {asignatura} al plan de ese grado o elimine la clase.",
            )

    def destinatarios(self) -> None:
        for clase in self.datos.clases:
            for d in clase.destinatarios:
                if d.division_id is None:
                    continue
                division = self.divisiones.get(d.division_id)
                if division is None or division.grupo_id != d.grupo_id:
                    self.error(
                        "clase",
                        clase.id,
                        self.texto_clase(clase),
                        f"La clase {self.texto_clase(clase)} usa una división que no pertenece "
                        f"a {self.nombre_grupo(d.grupo_id)}.",
                        "Elija una división del mismo grupo.",
                    )
                elif d.parte not in division.partes:
                    self.error(
                        "clase",
                        clase.id,
                        self.texto_clase(clase),
                        f"La clase {self.texto_clase(clase)} usa la parte «{d.parte}», que no "
                        f"existe en la división «{division.nombre}».",
                        f"Elija una de: {', '.join(division.partes)}.",
                    )
            niveles = self.niveles_de_clase(clase)
            if len(niveles) > 1:
                nombres = ", ".join(sorted(self.niveles[n].nombre for n in niveles))
                self.error(
                    "clase",
                    clase.id,
                    self.texto_clase(clase),
                    f"La clase conjunta {self.texto_clase(clase)} junta grupos de distintos "
                    f"niveles ({nombres}).",
                    "Una clase conjunta solo puede unir grupos del mismo nivel.",
                )

    def profesor_posible(self) -> None:
        for clase in self.datos.clases:
            asignatura = self.nombre_asignatura(clase.asignatura_id)
            if clase.profesores:
                for profesor_id in clase.profesores:
                    profesor = self.profesores.get(profesor_id)
                    if profesor is None:
                        continue
                    if not profesor.activo:
                        self.error(
                            "clase",
                            clase.id,
                            self.texto_clase(clase),
                            f"{profesor.nombre} está inactivo y es profesor fijo de "
                            f"{self.texto_clase(clase)}.",
                            "Active al profesor o cambie el profesor de la clase.",
                        )
                    elif not profesor_habilitado(self.datos, profesor, clase):
                        self.error(
                            "clase",
                            clase.id,
                            self.texto_clase(clase),
                            f"{profesor.nombre} es profesor fijo de {self.texto_clase(clase)} "
                            f"pero no está habilitado para {asignatura} en todos sus grados.",
                            f"Habilite a {profesor.nombre} para {asignatura} y esos grados, o "
                            "cambie el profesor de la clase.",
                        )
            elif not self.posibles.get(clase.id or 0):
                self.error(
                    "clase",
                    clase.id,
                    self.texto_clase(clase),
                    f"Ningún profesor activo está habilitado para impartir "
                    f"{self.texto_clase(clase)}.",
                    f"Habilite a un profesor para {asignatura} y para el grado de cada grupo.",
                )

    def horas_por_grupo(self) -> None:
        completo: dict[int, int] = defaultdict(int)
        partes: dict[int, dict[int, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        for clase in self.datos.clases:
            for d in clase.destinatarios:
                if d.division_id is None or d.parte is None:
                    completo[d.grupo_id] += clase.horas_semanales
                else:
                    partes[d.grupo_id][d.division_id][d.parte] += clase.horas_semanales
        for grupo in self.datos.grupos:
            assert grupo.id is not None
            necesarias = completo[grupo.id]
            for division_id, horas in partes[grupo.id].items():
                if division_id in self.simultaneas:
                    necesarias += max(horas.values())
                else:
                    necesarias += sum(horas.values())
            utiles = len(self.calendario.utiles_grupo.get(grupo.id, []))
            if necesarias > utiles:
                nombre = self.nombre_grupo(grupo.id)
                self.error(
                    "grupo",
                    grupo.id,
                    nombre,
                    f"{nombre} necesita {_horas(necesarias)} de clase a la semana y solo tiene "
                    f"{_plural(utiles, 'franja útil', 'franjas útiles')}.",
                    "Reduzca horas del plan, quite bloqueos o eventos, o amplíe la jornada.",
                )

    def capacidad_docente(self) -> None:
        requeridos: dict[tuple[int, int], int] = defaultdict(int)
        candidatos: dict[tuple[int, int], set[int]] = defaultdict(set)
        for clase in self.datos.clases:
            nivel = self.nivel_de_clase(clase)
            posibles = self.posibles.get(clase.id or 0, [])
            if nivel is None or nivel.id is None or not posibles:
                continue
            clave = (clase.asignatura_id, nivel.id)
            requeridos[clave] += self.minutos_clase(clase) * max(1, len(clase.profesores))
            candidatos[clave].update(posibles)
        for (asignatura_id, nivel_id), requerido in sorted(requeridos.items()):
            capacidad = sum(
                min(p.carga_max_semanal_min, self.minutos_disponibles(p, nivel_id))
                for p in (self.profesores[i] for i in candidatos[(asignatura_id, nivel_id)])
            )
            if requerido > capacidad:
                asignatura = self.nombre_asignatura(asignatura_id)
                nivel = self.niveles[nivel_id].nombre
                self.error(
                    "asignatura",
                    asignatura_id,
                    f"{asignatura} ({nivel})",
                    f"{asignatura} en {nivel} requiere {requerido} min de clase a la semana y "
                    f"los profesores habilitados solo pueden cubrir {capacidad} min.",
                    "Habilite a más profesores o aumente su carga máxima o su disponibilidad.",
                )

    def por_profesor(self) -> None:
        for profesor in self.datos.profesores:
            assert profesor.id is not None
            fijas = [c for c in self.datos.clases if profesor.id in c.profesores]
            if not fijas:
                continue
            minutos = sum(self.minutos_clase(c) for c in fijas)
            if minutos > profesor.carga_max_semanal_min:
                self.error(
                    "profesor",
                    profesor.id,
                    profesor.nombre,
                    f"{profesor.nombre} tiene {minutos} min de clases con profesor fijo y su "
                    f"carga máxima semanal es de {profesor.carga_max_semanal_min} min.",
                    f"Aumente la carga máxima de {profesor.nombre} o reparta sus clases.",
                )
            por_nivel: dict[int, int] = defaultdict(int)
            for clase in fijas:
                nivel = self.nivel_de_clase(clase)
                if nivel is not None and nivel.id is not None:
                    por_nivel[nivel.id] += clase.horas_semanales
            for nivel_id, horas in sorted(por_nivel.items()):
                validas = self.franjas_validas(profesor, nivel_id)
                if horas > validas:
                    nivel = self.niveles[nivel_id].nombre
                    self.error(
                        "profesor",
                        profesor.id,
                        profesor.nombre,
                        f"{profesor.nombre} tiene {_horas(horas)} fijas en {nivel} pero solo "
                        f"está disponible en {_plural(validas, 'franja', 'franjas')} de ese nivel.",
                        f"Amplíe la disponibilidad de {profesor.nombre} o reparta sus clases.",
                    )

    def carga_minima(self) -> None:
        for profesor in self.datos.profesores:
            if not profesor.activo or profesor.carga_min_semanal_min == 0:
                continue
            alcanzable = sum(
                self.minutos_clase(c)
                for c in self.datos.clases
                if profesor.id in self.posibles.get(c.id or 0, [])
            )
            if alcanzable < profesor.carga_min_semanal_min:
                self.error(
                    "profesor",
                    profesor.id,
                    profesor.nombre,
                    f"{profesor.nombre} debe tener al menos {profesor.carga_min_semanal_min} min "
                    f"de clase, pero las clases que puede impartir suman {alcanzable} min.",
                    f"Habilite a {profesor.nombre} para más asignaturas o grados, o baje su "
                    "carga mínima.",
                )

    def espacios(self) -> None:
        capacidad: dict[str, int] = defaultdict(int)
        for espacio in self.datos.espacios:
            capacidad[espacio.tipo] += espacio.cantidad
        demanda: dict[tuple[str, int], int] = defaultdict(int)
        sin_espacio: set[tuple[str, int]] = set()
        for clase in self.datos.clases:
            asignatura = self.asignaturas.get(clase.asignatura_id)
            nivel = self.nivel_de_clase(clase)
            tipo = clase.espacio_efectivo(asignatura) if asignatura else None
            if tipo is None or nivel is None or nivel.id is None:
                continue
            if capacidad[tipo] == 0:
                sin_espacio.add((tipo, clase.asignatura_id))
            demanda[(tipo, nivel.id)] += clase.horas_semanales
        for tipo, asignatura_id in sorted(sin_espacio):
            asignatura = self.nombre_asignatura(asignatura_id)
            self.error(
                "espacio",
                None,
                tipo,
                f"{asignatura} requiere un espacio de tipo «{tipo}» y no hay ninguno.",
                f"Agregue un espacio de tipo «{tipo}» o quite el requisito de {asignatura}.",
            )
        for (tipo, nivel_id), horas in sorted(demanda.items()):
            if capacidad[tipo] == 0:
                continue
            franjas = len(self.calendario.utiles_nivel.get(nivel_id, []))
            disponible = franjas * capacidad[tipo]
            if horas > disponible:
                nivel = self.niveles[nivel_id].nombre
                self.error(
                    "espacio",
                    None,
                    tipo,
                    f"En {nivel} se necesitan {_horas(horas)} de espacios de tipo «{tipo}» y "
                    f"solo caben {_horas(disponible)} ({franjas} franjas × {capacidad[tipo]}).",
                    f"Agregue espacios de tipo «{tipo}» o reduzca las clases que lo requieren.",
                )

    def _profesores_de_fija(self, fija: AsignacionFija, clase: Clase) -> list[int]:
        if fija.profesor_id is not None:
            return [fija.profesor_id]
        return list(clase.profesores)

    def fijas(self) -> None:
        validas: list[tuple[AsignacionFija, Clase, Franja]] = []
        por_clase: dict[int, int] = defaultdict(int)
        for fija in self.datos.fijas:
            clase = self.clases.get(fija.clase_id)
            if clase is None:
                continue
            texto = self.texto_clase(clase)
            dia = NOMBRES_DIAS[fija.dia].lower()
            por_clase[fija.clase_id] += 1
            nivel = self.nivel_de_clase(clase)
            if nivel is None or nivel.id is None:
                continue
            franja = self.calendario.franja(nivel.id, fija.dia, fija.indice_franja)
            if franja is None:
                self.error(
                    "fija",
                    fija.id,
                    texto,
                    f"La clase fija {texto} está en la hora {fija.indice_franja + 1} del {dia}, "
                    f"que no existe en {nivel.nombre}.",
                    "Mueva o desbloquee la clase.",
                )
                continue
            if franja not in self.calendario.utiles_comunes(grupos_de_clase(clase)):
                self.error(
                    "fija",
                    fija.id,
                    texto,
                    f"La clase fija {texto} está el {dia} de "
                    f"{texto_rango(franja.inicio, franja.fin)}, que no es una franja útil de "
                    "sus grupos (evento o bloqueo).",
                    "Mueva la clase a otra franja.",
                )
                continue
            asignatura = self.asignaturas.get(clase.asignatura_id)
            if asignatura and prohibida(asignatura.reglas_efectivas(nivel.id), franja):
                self.error(
                    "fija",
                    fija.id,
                    texto,
                    f"La clase fija {texto} está el {dia} de "
                    f"{texto_rango(franja.inicio, franja.fin)}, franja prohibida para "
                    f"{asignatura.nombre}.",
                    "Mueva la clase o cambie las franjas prohibidas de la asignatura.",
                )
            if fija.profesor_id is not None and clase.profesores:
                self.error(
                    "fija",
                    fija.id,
                    texto,
                    f"La clase fija {texto} indica profesor, pero la clase ya tiene profesores "
                    "fijos.",
                    "Quite el profesor de la asignación fija.",
                )
            elif fija.profesor_id is not None and fija.profesor_id not in self.posibles.get(
                clase.id or 0, []
            ):
                profesor = self.profesores.get(fija.profesor_id)
                nombre = profesor.nombre if profesor else "El profesor"
                self.error(
                    "fija",
                    fija.id,
                    texto,
                    f"{nombre} no puede impartir la clase fija {texto}.",
                    "Elija un profesor habilitado y activo.",
                )
            for profesor_id in self._profesores_de_fija(fija, clase):
                profesor = self.profesores.get(profesor_id)
                if profesor is None:
                    continue
                evaluacion = evaluar_franja(profesor, franja)
                if not evaluacion.valida:
                    self.error(
                        "fija",
                        fija.id,
                        texto,
                        f"La clase fija {texto} está el {dia} de "
                        f"{texto_rango(franja.inicio, franja.fin)}: {evaluacion.motivo}.",
                        "Mueva la clase o cambie la disponibilidad del profesor.",
                    )
            validas.append((fija, clase, franja))

        for clase_id, cantidad in sorted(por_clase.items()):
            clase = self.clases[clase_id]
            if cantidad > clase.horas_semanales:
                self.error(
                    "clase",
                    clase_id,
                    self.texto_clase(clase),
                    f"{self.texto_clase(clase)} tiene {cantidad} asignaciones fijas y solo "
                    f"{_horas(clase.horas_semanales)} a la semana.",
                    "Desbloquee algunas de sus clases.",
                )

        margen = self.datos.configuracion.margen_traslado_min
        for (fa, ca, sa), (fb, cb, sb) in combinations(validas, 2):
            texto = f"{self.texto_clase(ca)} y {self.texto_clase(cb)}"
            cuando = f"el {NOMBRES_DIAS[sa.dia].lower()} de {texto_rango(sa.inicio, sa.fin)}"
            if sa == sb and ca.id == cb.id:
                self.error(
                    "fija",
                    fb.id,
                    self.texto_clase(cb),
                    f"{self.texto_clase(ca)} está fija dos veces {cuando}.",
                    "Quite una de las dos asignaciones fijas.",
                )
                continue
            if sa == sb and any(
                chocan_destinatarios(da, db, self.simultaneas)
                for da in ca.destinatarios
                for db in cb.destinatarios
            ):
                self.error(
                    "fija",
                    fb.id,
                    self.texto_clase(cb),
                    f"Las clases fijas {texto} coinciden {cuando} con el mismo grupo.",
                    "Mueva una de las dos clases.",
                )
            comunes = set(self._profesores_de_fija(fa, ca)) & set(self._profesores_de_fija(fb, cb))
            if comunes and se_traslapan_franjas(sa, sb, margen):
                nombres = ", ".join(sorted(self.profesores[p].nombre for p in comunes))
                self.error(
                    "fija",
                    fb.id,
                    self.texto_clase(cb),
                    f"{nombres} tendría a la vez las clases fijas {texto} ({sa.texto()} y "
                    f"{sb.texto()}).",
                    "Mueva una de las dos clases o cambie su profesor.",
                )

    def maximo_diario(self) -> None:
        for clase in self.datos.clases:
            nivel = self.nivel_de_clase(clase)
            asignatura = self.asignaturas.get(clase.asignatura_id)
            if nivel is None or asignatura is None:
                continue
            maximo = asignatura.reglas_efectivas(nivel.id).max_horas_dia
            dias = len({f.dia for f in self.calendario.utiles_comunes(grupos_de_clase(clase))})
            if maximo * dias < clase.horas_semanales:
                self.error(
                    "clase",
                    clase.id,
                    self.texto_clase(clase),
                    f"{self.texto_clase(clase)} tiene {_horas(clase.horas_semanales)} y con un "
                    f"máximo de {_horas(maximo)} al día en {_plural(dias, 'día', 'días')} solo "
                    f"caben {_horas(maximo * dias)}.",
                    f"Suba el máximo diario de {asignatura.nombre} en {nivel.nombre} o reduzca "
                    "sus horas.",
                )

    def bloque_doble(self) -> None:
        vistos: set[tuple[int, int]] = set()
        for clase in self.datos.clases:
            nivel = self.nivel_de_clase(clase)
            asignatura = self.asignaturas.get(clase.asignatura_id)
            if nivel is None or nivel.id is None or asignatura is None:
                continue
            reglas = asignatura.reglas_efectivas(nivel.id)
            clave = (clase.asignatura_id, nivel.id)
            if reglas.bloque_doble == "obligatorio" and reglas.max_horas_dia < 2:
                if clave not in vistos:
                    vistos.add(clave)
                    self.error(
                        "asignatura",
                        asignatura.id,
                        f"{asignatura.nombre} ({nivel.nombre})",
                        f"{asignatura.nombre} exige bloque doble en {nivel.nombre} pero su "
                        f"máximo diario es de {_horas(reglas.max_horas_dia)}.",
                        "Suba el máximo diario a 2 o más, o quite el bloque doble obligatorio.",
                    )

    def divisiones_simultaneas(self) -> None:
        horas: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for clase in self.datos.clases:
            for d in clase.destinatarios:
                if d.division_id in self.simultaneas and d.parte is not None:
                    horas[(d.division_id, clase.asignatura_id)][d.parte] += clase.horas_semanales
        for (division_id, asignatura_id), por_parte in sorted(horas.items()):
            division = self.divisiones[division_id]
            valores = {p: por_parte.get(p, 0) for p in division.partes}
            if len(set(valores.values())) > 1:
                grupo = self.nombre_grupo(division.grupo_id)
                detalle = ", ".join(f"{p}: {_horas(h)}" for p, h in valores.items())
                asignatura = self.nombre_asignatura(asignatura_id)
                self.error(
                    "division",
                    division_id,
                    f"{division.nombre} ({grupo})",
                    f"Las partes de «{division.nombre}» de {grupo} tienen horas distintas de "
                    f"{asignatura} ({detalle}) y la división es simultánea.",
                    "Iguale las horas de las partes o marque la división como no simultánea.",
                )

    def franjas_prohibidas(self) -> None:
        for clase in self.datos.clases:
            nivel = self.nivel_de_clase(clase)
            asignatura = self.asignaturas.get(clase.asignatura_id)
            if nivel is None or asignatura is None:
                continue
            if not asignatura.reglas_efectivas(nivel.id).franjas_prohibidas:
                continue
            posibles = len(self.franjas_posibles(clase))
            if posibles < clase.horas_semanales:
                self.error(
                    "clase",
                    clase.id,
                    self.texto_clase(clase),
                    f"Las franjas prohibidas de {asignatura.nombre} dejan a "
                    f"{self.texto_clase(clase)} con {_plural(posibles, 'franja', 'franjas')} "
                    f"para {_horas(clase.horas_semanales)}.",
                    f"Reduzca las franjas prohibidas de {asignatura.nombre} en {nivel.nombre}.",
                )

    def advertencias_de_tiempo(self) -> None:
        for nivel in self.datos.niveles:
            assert nivel.id is not None
            todas = self.calendario.franjas_nivel.get(nivel.id, [])
            for evento in nivel.eventos:
                if not any(
                    f.dia == evento.dia and f.toca(evento.inicio, evento.fin) for f in todas
                ):
                    self.advertencia(
                        "nivel",
                        nivel.id,
                        nivel.nombre,
                        f"El evento «{evento.nombre}» de {nivel.nombre} "
                        f"({NOMBRES_DIAS[evento.dia]} {texto_rango(evento.inicio, evento.fin)}) "
                        "no toca ninguna franja.",
                        "Revise el día y la hora del evento.",
                    )
            por_dia = defaultdict(int)
            for f in todas:
                por_dia[f.dia] += 1
            maximo = max(por_dia.values(), default=0)
            for indice in nivel.duraciones_especiales:
                if indice >= maximo:
                    self.advertencia(
                        "nivel",
                        nivel.id,
                        nivel.nombre,
                        f"{nivel.nombre} define una duración especial para la hora {indice + 1}, "
                        f"pero el día solo tiene {maximo} horas.",
                        "Quite esa duración especial o amplíe la jornada.",
                    )
        for grupo in self.datos.grupos:
            assert grupo.id is not None
            grado = self.grados.get(grupo.grado_id)
            utiles = self.calendario.utiles_nivel.get(grado.nivel_id, []) if grado else []
            for bloqueo in grupo.bloqueos:
                if not any(
                    f.dia == bloqueo.dia and f.toca(bloqueo.inicio, bloqueo.fin) for f in utiles
                ):
                    nombre = self.nombre_grupo(grupo.id)
                    self.advertencia(
                        "grupo",
                        grupo.id,
                        nombre,
                        f"El bloqueo «{bloqueo.nombre}» de {nombre} "
                        f"({NOMBRES_DIAS[bloqueo.dia]} {texto_rango(bloqueo.inicio, bloqueo.fin)}) "
                        "no toca ninguna franja.",
                        "Revise el día y la hora del bloqueo.",
                    )
        for profesor in self.datos.profesores:
            niveles = {self.grados[g].nivel_id for g in profesor.grados if g in self.grados}
            franjas = [f for n in niveles for f in self.calendario.utiles_nivel.get(n, [])]
            for rango in profesor.disponibilidad:
                if not any(f.dia == rango.dia and f.toca(rango.inicio, rango.fin) for f in franjas):
                    self.advertencia(
                        "profesor",
                        profesor.id,
                        profesor.nombre,
                        f"El rango {NOMBRES_DIAS[rango.dia]} "
                        f"{texto_rango(rango.inicio, rango.fin)} de {profesor.nombre} no cubre "
                        "ninguna franja de sus niveles.",
                        "Revise la disponibilidad del profesor.",
                    )

    def incompletos(self) -> None:
        con_grupos = {g.grado_id for g in self.datos.grupos}
        con_plan = {f.grado_id for f in self.datos.plan if f.horas_semanales > 0}
        for grado in self.datos.grados:
            nivel = self.niveles.get(grado.nivel_id)
            nombre = f"{grado.nombre} ({nivel.nombre if nivel else '?'})"
            if grado.id not in con_grupos:
                self.advertencia(
                    "grado", grado.id, nombre, f"El grado {nombre} no tiene grupos.",
                    "Agregue grupos o elimine el grado.",
                )  # fmt: skip
            if grado.id not in con_plan:
                self.advertencia(
                    "grado", grado.id, nombre, f"El grado {nombre} no tiene plan de estudios.",
                    "Capture sus horas en «Plan de estudios».",
                )  # fmt: skip
        for nivel in self.datos.niveles:
            if not self.calendario.utiles_nivel.get(nivel.id or 0):
                self.advertencia(
                    "nivel", nivel.id, nivel.nombre, f"{nivel.nombre} no tiene franjas útiles.",
                    "Revise la jornada, la duración de la hora, los recesos y los eventos.",
                )  # fmt: skip
        for profesor in self.datos.profesores:
            if not profesor.activo:
                continue
            if not profesor.asignaturas or not profesor.grados:
                falta = "asignaturas" if not profesor.asignaturas else "grados"
                self.advertencia(
                    "profesor",
                    profesor.id,
                    profesor.nombre,
                    f"{profesor.nombre} no tiene {falta} habilitados.",
                    f"Indique las {falta} que puede impartir.",
                )


def validar(datos: DatosEscuela) -> list[Problema]:
    """Revisa los datos antes de resolver (§10)."""
    return _Validador(datos).ejecutar()


def texto_destinatario_seguro(datos: DatosEscuela, destinatario: Destinatario) -> str:
    try:
        return texto_destinatario(datos, destinatario)
    except KeyError:
        return f"grupo {destinatario.grupo_id}"
