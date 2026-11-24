"""Creado con Claude.

Comprobaciones incrementales por clase y franja (§11.2), compartidas por el editor y el
verificador. `Conflictos` mantiene índices de ocupación por grupo, profesor, asignatura y tipo
de espacio sobre la línea de tiempo, para responder en menos de 2 ms por celda.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from timetabling.dominio.borrador import Colocacion
from timetabling.dominio.clases import (
    chocan_destinatarios,
    grupos_de_clase,
    profesores_posibles,
    texto_destinatarios,
)
from timetabling.dominio.modelos import (
    Clase,
    DatosEscuela,
    Destinatario,
    Profesor,
    ReglasAsignatura,
    por_id,
)
from timetabling.dominio.tiempo import NOMBRES_DIAS, Dia, texto_rango
from timetabling.nucleo.franjas import (
    Calendario,
    Franja,
    adyacentes,
    evaluar_franja,
    preferida,
    prohibida,
    se_traslapan_franjas,
)

Severidad = Literal["dura", "blanda"]
EstadoCelda = Literal["valida", "penalizada", "invalida"]


@dataclass(frozen=True)
class Motivo:
    """Por qué una clase no puede (dura) o no debería (blanda) ir en una franja."""

    severidad: Severidad
    restriccion: str
    texto: str
    clase_id: int | None = None

    @property
    def es_dura(self) -> bool:
        return self.severidad == "dura"


@dataclass(frozen=True)
class InfoClase:
    clase: Clase
    nivel_id: int | None
    asignatura: str
    reglas: ReglasAsignatura
    tipo_espacio: str | None
    texto: str
    utiles: frozenset[str]
    posibles: tuple[int, ...]


def ocupacion_maxima(intervalos: Iterable[tuple[int, int]], inicio: int, fin: int) -> int:
    """Máximo de intervalos simultáneos dentro de `[inicio, fin)`."""
    dentro = [(max(a, inicio), min(b, fin)) for a, b in intervalos if a < fin and inicio < b]
    puntos = {a for a, _ in dentro} | {inicio}
    return max((sum(1 for a, b in dentro if a <= t < b) for t in puntos), default=0)


def excede_continuo(intervalos: Iterable[tuple[int, int]], maximo: int, descanso: int) -> bool:
    """D8: en alguna ventana de `maximo + descanso` minutos hay más de `maximo` ocupados. El
    máximo se alcanza con la ventana empezando al inicio de un intervalo o terminando al final
    de uno, así que basta revisar esas ventanas."""
    lista = sorted(set(intervalos))
    ventana = maximo + descanso
    candidatos = {a for a, _ in lista} | {b - ventana for _, b in lista}
    for t in candidatos:
        minutos: set[int] = set()
        for a, b in lista:
            minutos.update(range(max(a, t), min(b, t + ventana)))
        if len(minutos) > maximo:
            return True
    return False


class Conflictos:
    """Índices de ocupación de un horario con comprobaciones incrementales."""

    def __init__(self, datos: DatosEscuela, calendario: Calendario | None = None) -> None:
        self.datos = datos
        self.calendario = calendario or Calendario.de(datos)
        self.margen = datos.configuracion.margen_traslado_min
        self.descanso = datos.configuracion.descanso_minimo_min
        self.profesores = por_id(datos.profesores)
        self.niveles = por_id(datos.niveles)
        self.grupos = por_id(datos.grupos)
        self.simultaneas = {d.id for d in datos.divisiones if d.simultanea and d.id is not None}
        self.capacidad: dict[str, int] = defaultdict(int)
        for espacio in datos.espacios:
            self.capacidad[espacio.tipo] += espacio.cantidad
        asignaturas = por_id(datos.asignaturas)
        grados = por_id(datos.grados)
        self.info: dict[int, InfoClase] = {}
        for clase in datos.clases:
            if clase.id is None or clase.asignatura_id not in asignaturas:
                continue
            asignatura = asignaturas[clase.asignatura_id]
            niveles = {
                grados[self.grupos[g].grado_id].nivel_id
                for g in grupos_de_clase(clase)
                if g in self.grupos and self.grupos[g].grado_id in grados
            }
            nivel_id = next(iter(niveles)) if len(niveles) == 1 else None
            self.info[clase.id] = InfoClase(
                clase=clase,
                nivel_id=nivel_id,
                asignatura=asignatura.nombre,
                reglas=asignatura.reglas_efectivas(nivel_id),
                tipo_espacio=clase.espacio_efectivo(asignatura),
                texto=f"{asignatura.nombre} · {self._texto_destinatarios(clase)}",
                utiles=frozenset(
                    f.id for f in self.calendario.utiles_comunes(grupos_de_clase(clase))
                ),
                posibles=tuple(profesores_posibles(datos, clase)),
            )
        self._clase: dict[int, list[Colocacion]] = defaultdict(list)
        self._grupo: dict[tuple[int, str], list[tuple[Colocacion, Destinatario]]] = defaultdict(
            list
        )
        self._profesor: dict[tuple[int, str], list[tuple[Franja, Colocacion]]] = defaultdict(list)
        self._tipo: dict[tuple[str, str], list[tuple[Franja, Colocacion]]] = defaultdict(list)
        self._asignatura: dict[
            tuple[int, int, str], list[tuple[Franja, Destinatario, Colocacion]]
        ] = defaultdict(list)
        self._minutos_dia: dict[tuple[int, str], int] = defaultdict(int)
        self._minutos: dict[int, int] = defaultdict(int)

    def _texto_destinatarios(self, clase: Clase) -> str:
        try:
            return texto_destinatarios(self.datos, clase)
        except KeyError:
            return "grupos inexistentes"

    # ------------------------------------------------------------------ índices

    def agregar(self, colocacion: Colocacion) -> None:
        franja = self.calendario.franjas.get(colocacion.franja_id)
        info = self.info.get(colocacion.clase_id)
        if franja is None or info is None:
            return
        self._clase[colocacion.clase_id].append(colocacion)
        for d in info.clase.destinatarios:
            self._grupo[(d.grupo_id, franja.id)].append((colocacion, d))
            self._asignatura[(d.grupo_id, info.clase.asignatura_id, franja.dia)].append(
                (franja, d, colocacion)
            )
        for p in colocacion.profesores:
            self._profesor[(p, franja.dia)].append((franja, colocacion))
            self._minutos_dia[(p, franja.dia)] += franja.duracion
            self._minutos[p] += franja.duracion
        if info.tipo_espacio:
            self._tipo[(info.tipo_espacio, franja.dia)].append((franja, colocacion))

    def quitar(self, colocacion: Colocacion) -> None:
        franja = self.calendario.franjas.get(colocacion.franja_id)
        info = self.info.get(colocacion.clase_id)
        if franja is None or info is None:
            return

        def sin(lista: list, colocada_en: int) -> None:  # type: ignore[type-arg]
            for i, elemento in enumerate(lista):
                if elemento[colocada_en] is colocacion or elemento[colocada_en] == colocacion:
                    del lista[i]
                    return

        self._clase[colocacion.clase_id].remove(colocacion)
        for d in info.clase.destinatarios:
            sin(self._grupo[(d.grupo_id, franja.id)], 0)
            sin(self._asignatura[(d.grupo_id, info.clase.asignatura_id, franja.dia)], 2)
        for p in colocacion.profesores:
            sin(self._profesor[(p, franja.dia)], 1)
            self._minutos_dia[(p, franja.dia)] -= franja.duracion
            self._minutos[p] -= franja.duracion
        if info.tipo_espacio:
            sin(self._tipo[(info.tipo_espacio, franja.dia)], 1)

    def cargar(self, colocaciones: Iterable[Colocacion]) -> "Conflictos":
        for colocacion in colocaciones:
            self.agregar(colocacion)
        return self

    def colocaciones_de(self, clase_id: int) -> list[Colocacion]:
        return list(self._clase.get(clase_id, []))

    @contextmanager
    def sin(self, *colocaciones: Colocacion | None) -> Iterator["Conflictos"]:
        """Evalúa como si esas colocaciones no estuvieran (al mover o intercambiar)."""
        quitadas = [c for c in colocaciones if c is not None]
        for c in quitadas:
            self.quitar(c)
        try:
            yield self
        finally:
            for c in quitadas:
                self.agregar(c)

    def estado(
        self, clase_id: int, franja: Franja, profesor: int | None = None
    ) -> tuple[EstadoCelda, list[Motivo]]:
        """🟩 válida, 🟨 válida con penalización o 🟥 inválida (§12.2), con sus motivos."""
        motivos = self.motivos(clase_id, franja, profesor)
        if any(m.es_dura for m in motivos):
            return "invalida", motivos
        return ("penalizada" if motivos else "valida"), motivos

    def profesor_sugerido(self, clase_id: int, franja: Franja) -> int | None:
        """Profesor para colocar la clase en la franja: los fijos, el que ya la imparte o el
        candidato sin motivos duros con menos motivos blandos (por nombre si empatan)."""
        info = self.info.get(clase_id)
        if info is None:
            return None
        if info.clase.profesores:
            return info.clase.profesores[0]
        actuales = {p for c in self._clase.get(clase_id, []) for p in c.profesores}
        if actuales:
            return min(actuales)
        opciones = []
        for p in info.posibles:
            motivos = self._motivos_profesor(p, info, franja)
            if not any(m.es_dura for m in motivos):
                opciones.append((len(motivos), self._nombre(p), p))
        return min(opciones)[2] if opciones else None

    def candidatos_validos(self, clase_id: int, franja: Franja) -> list[tuple[int, list[Motivo]]]:
        """Candidatos sin motivos duros para una clase sin profesores fijos, en el orden de
        §11.4: sin «preferible no» primero, luego con menos clases ese día, luego por nombre."""
        info = self.info.get(clase_id)
        if info is None or info.clase.profesores:
            return []
        opciones = []
        for p in info.posibles:
            motivos = self._motivos_profesor(p, info, franja)
            if any(m.es_dura for m in motivos):
                continue
            ese_dia = len(self._profesor.get((p, franja.dia), []))
            opciones.append(((bool(motivos), ese_dia, self._nombre(p)), p, motivos))
        return [(p, motivos) for _, p, motivos in sorted(opciones)]

    def profesores_de(self, clase_id: int, franja: Franja) -> tuple[int, ...]:
        """Profesores con los que se colocaría la clase en la franja."""
        info = self.info.get(clase_id)
        if info is not None and info.clase.profesores:
            return tuple(info.clase.profesores)
        sugerido = self.profesor_sugerido(clase_id, franja)
        return (sugerido,) if sugerido is not None else ()

    # ------------------------------------------------------------------ textos

    def _cuando(self, franja: Franja) -> str:
        return f"el {NOMBRES_DIAS[franja.dia].lower()} de {texto_rango(franja.inicio, franja.fin)}"

    def _texto_de(self, colocacion: Colocacion) -> str:
        info = self.info.get(colocacion.clase_id)
        return info.texto if info else f"la clase {colocacion.clase_id}"

    # ------------------------------------------------------------------ comprobaciones

    def motivos(self, clase_id: int, franja: Franja, profesor: int | None = None) -> list[Motivo]:
        """Motivos para la clase en la franja. Si `profesor` es `None` y la clase no tiene
        profesores fijos, se usa el profesor que ya la imparte o, si aún no tiene, el mejor
        candidato libre."""
        info = self.info.get(clase_id)
        if info is None:
            return [Motivo("dura", "D1", f"La clase {clase_id} no existe.")]
        motivos = self._motivos_clase(info, franja)
        if info.clase.profesores:
            for p in info.clase.profesores:
                motivos += self._motivos_profesor(p, info, franja)
            return motivos
        actuales = {p for c in self._clase.get(clase_id, []) for p in c.profesores}
        if profesor is not None:
            motivos += self._competencia(profesor, info, actuales)
            return motivos + self._motivos_profesor(profesor, info, franja)
        if actuales:
            return motivos + self._motivos_profesor(min(actuales), info, franja)
        if len(info.posibles) == 1:
            return motivos + self._motivos_profesor(info.posibles[0], info, franja)
        return motivos + self._mejor_candidato(info, franja)

    def motivos_colocacion(self, colocacion: Colocacion) -> list[Motivo]:
        """Motivos de una colocación concreta (con sus profesores) contra lo ya indexado."""
        info = self.info.get(colocacion.clase_id)
        franja = self.calendario.franjas.get(colocacion.franja_id)
        if info is None:
            return [Motivo("dura", "D1", f"La clase {colocacion.clase_id} no existe.")]
        if franja is None:
            return [
                Motivo(
                    "dura", "D14", f"{info.texto} está en una franja que no existe.", info.clase.id
                )
            ]
        motivos = self._motivos_clase(info, franja)
        if info.clase.profesores:
            if set(colocacion.profesores) != set(info.clase.profesores):
                motivos.append(
                    Motivo(
                        "dura",
                        "D6",
                        f"{info.texto} debe impartirse por todos sus profesores fijos.",
                        info.clase.id,
                    )
                )
        elif len(colocacion.profesores) != 1:
            motivos.append(
                Motivo("dura", "D6", f"{info.texto} debe tener un solo profesor.", info.clase.id)
            )
        else:
            actuales = {p for c in self._clase.get(info.clase.id or 0, []) for p in c.profesores}
            motivos += self._competencia(colocacion.profesores[0], info, actuales)
        for p in colocacion.profesores:
            motivos += self._motivos_profesor(p, info, franja)
        return motivos

    def _competencia(self, profesor: int, info: InfoClase, actuales: set[int]) -> list[Motivo]:
        motivos: list[Motivo] = []
        nombre = self._nombre(profesor)
        if profesor not in info.posibles:
            motivos.append(
                Motivo(
                    "dura",
                    "D4",
                    f"{nombre} no está habilitado o activo para {info.texto}.",
                    info.clase.id,
                )
            )
        otros = actuales - {profesor}
        if otros:
            motivos.append(
                Motivo(
                    "dura",
                    "D6",
                    f"{info.texto} ya la imparte {self._nombre(min(otros))}.",
                    info.clase.id,
                )
            )
        return motivos

    def _nombre(self, profesor: int) -> str:
        p = self.profesores.get(profesor)
        return p.nombre if p else f"Profesor {profesor}"

    def _mejor_candidato(self, info: InfoClase, franja: Franja) -> list[Motivo]:
        if not info.posibles:
            return [Motivo("dura", "D4", f"Nadie puede impartir {info.texto}.", info.clase.id)]
        mejor: list[Motivo] | None = None
        primeros: list[str] = []
        for p in info.posibles:
            propios = self._motivos_profesor(p, info, franja)
            duros = [m for m in propios if m.es_dura]
            if not duros:
                if mejor is None or len(propios) < len(mejor):
                    mejor = propios
                if not propios:
                    break
            elif len(primeros) < 3:
                primeros.append(duros[0].texto)
        if mejor is not None:
            return mejor
        return [
            Motivo(
                "dura",
                "D3",
                "Ningún profesor posible está libre: " + "; ".join(primeros),
                info.clase.id,
            )
        ]

    def _motivos_clase(self, info: InfoClase, franja: Franja) -> list[Motivo]:
        clase = info.clase
        motivos: list[Motivo] = []
        cuando = self._cuando(franja)
        if franja.nivel_id != info.nivel_id:
            return [Motivo("dura", "D14", f"{info.texto} no es de ese nivel.", clase.id)]
        if franja.id not in info.utiles:
            motivos.append(Motivo("dura", "D14", self._causa_no_util(info, franja), clase.id))
        if prohibida(info.reglas, franja):
            motivos.append(
                Motivo(
                    "dura",
                    "D15",
                    f"{info.asignatura} no puede ir {cuando} (franja prohibida).",
                    clase.id,
                )
            )
        ya = self._clase.get(clase.id or 0, [])
        if any(c.franja_id == franja.id for c in ya):
            motivos.append(Motivo("dura", "D2", f"{info.texto} ya está {cuando}.", clase.id))
        elif len(ya) >= clase.horas_semanales:
            motivos.append(
                Motivo(
                    "dura",
                    "D1",
                    f"{info.texto} ya tiene sus {clase.horas_semanales} horas colocadas.",
                    clase.id,
                )
            )
        # D2: el grupo (o la parte) ya tiene clase.
        for d in clase.destinatarios:
            for otra, d2 in self._grupo.get((d.grupo_id, franja.id), []):
                if otra.clase_id != clase.id and chocan_destinatarios(d, d2, self.simultaneas):
                    motivos.append(
                        Motivo(
                            "dura",
                            "D2",
                            f"{self._texto_grupo(d)} ya tiene {self._texto_de(otra)} {cuando}.",
                            otra.clase_id,
                        )
                    )
        motivos += self._motivos_diarios(info, franja)
        motivos += self._motivos_espacio(info, franja)
        if not preferida(info.reglas, franja):
            motivos.append(
                Motivo(
                    "blanda",
                    "B3",
                    f"{cuando[0].upper()}{cuando[1:]} está fuera de las franjas preferidas de "
                    f"{info.asignatura}.",
                    clase.id,
                )
            )
        return motivos

    def _texto_grupo(self, d: Destinatario) -> str:
        nombre = self.datos.nombre_grupo(d.grupo_id) if d.grupo_id in self.grupos else "?"
        return nombre if d.parte is None else f"{nombre} ({d.parte})"

    def _causa_no_util(self, info: InfoClase, franja: Franja) -> str:
        nivel = self.niveles.get(franja.nivel_id)
        if nivel:
            for evento in nivel.eventos:
                if evento.dia == franja.dia and franja.toca(evento.inicio, evento.fin):
                    return f"{nivel.nombre} tiene «{evento.nombre}» {self._cuando(franja)}."
        for g in grupos_de_clase(info.clase):
            grupo = self.grupos.get(g)
            for bloqueo in grupo.bloqueos if grupo else []:
                if bloqueo.dia == franja.dia and franja.toca(bloqueo.inicio, bloqueo.fin):
                    return (
                        f"{self.datos.nombre_grupo(g)} tiene «{bloqueo.nombre}» "
                        f"{self._cuando(franja)}."
                    )
        return f"{self._cuando(franja)} no es una franja útil de {info.texto}."

    def _motivos_diarios(self, info: InfoClase, franja: Franja) -> list[Motivo]:
        """D10: máximo diario por destinatario y asignatura; con máximo 2, juntas."""
        clase = info.clase
        maximo = info.reglas.max_horas_dia
        motivos: list[Motivo] = []
        dia = NOMBRES_DIAS[franja.dia].lower()
        for d in clase.destinatarios:
            relevantes = [
                (f, c)
                for f, d2, c in self._asignatura.get(
                    (d.grupo_id, clase.asignatura_id, franja.dia), []
                )
                if f.id != franja.id
                and (d.division_id is None or d2.division_id is None or d2 == d)
            ]
            franjas = {f.id: f for f, _ in relevantes}
            if len(franjas) + 1 > maximo:
                motivos.append(
                    Motivo(
                        "dura",
                        "D10",
                        f"{self._texto_grupo(d)} ya tiene {len(franjas)} h de {info.asignatura} "
                        f"el {dia} (máximo {maximo}).",
                        clase.id,
                    )
                )
            elif maximo == 2 and any(not adyacentes(f, franja) for f in franjas.values()):
                motivos.append(
                    Motivo(
                        "dura",
                        "D10",
                        f"Las 2 h de {info.asignatura} de {self._texto_grupo(d)} el {dia} "
                        "deben ir juntas.",
                        clase.id,
                    )
                )
        return motivos

    def _motivos_espacio(self, info: InfoClase, franja: Franja) -> list[Motivo]:
        """D9 con la ocupación física real (sin margen)."""
        tipo = info.tipo_espacio
        if tipo is None:
            return []
        capacidad = self.capacidad.get(tipo, 0)
        otros = [
            (f, c)
            for f, c in self._tipo.get((tipo, franja.dia), [])
            if c.clase_id != info.clase.id and f.toca(franja.inicio, franja.fin)
        ]
        ocupados = ocupacion_maxima(
            ((f.inicio, f.fin) for f, _ in otros), franja.inicio, franja.fin
        )
        if ocupados + 1 <= capacidad:
            return []
        quienes = ", ".join(sorted({self._texto_de(c) for _, c in otros})[:3])
        texto = f"No hay espacio de tipo «{tipo}» libre {self._cuando(franja)}" + (
            f": lo usan {quienes}." if quienes else "."
        )
        return [Motivo("dura", "D9", texto, otros[0][1].clase_id if otros else None)]

    def _motivos_profesor(self, p: int, info: InfoClase, franja: Franja) -> list[Motivo]:
        profesor = self.profesores.get(p)
        if profesor is None:
            return [Motivo("dura", "D4", f"El profesor {p} no existe.", info.clase.id)]
        motivos: list[Motivo] = []
        evaluacion = evaluar_franja(profesor, franja)
        if not evaluacion.valida:
            motivos.append(Motivo("dura", "D5", f"{evaluacion.motivo}.", info.clase.id))
        elif evaluacion.validez == "preferible_no":
            motivos.append(Motivo("blanda", "B4", f"{evaluacion.motivo}.", info.clase.id))
        del_dia = [
            (f, c)
            for f, c in self._profesor.get((p, franja.dia), [])
            if not (f.id == franja.id and c.clase_id == info.clase.id)
        ]
        for f, c in del_dia:
            if se_traslapan_franjas(franja, f, self.margen):
                otra = self.info.get(c.clase_id)
                grupos = self._texto_destinatarios(otra.clase) if otra else "otra clase"
                motivos.append(
                    Motivo(
                        "dura",
                        "D3",
                        f"{profesor.nombre} ya da {grupos} de "
                        f"{texto_rango(f.inicio, f.fin)}"
                        + (
                            " (sin tiempo de traslado)"
                            if not f.toca(franja.inicio, franja.fin)
                            else ""
                        )
                        + ".",
                        c.clase_id,
                    )
                )
        motivos += self._motivos_carga(profesor, franja, del_dia, info)
        return motivos

    def _motivos_carga(
        self,
        profesor: Profesor,
        franja: Franja,
        del_dia: list[tuple[Franja, Colocacion]],
        info: InfoClase,
    ) -> list[Motivo]:
        p = profesor.id or 0
        motivos: list[Motivo] = []
        semana = self._minutos.get(p, 0) + franja.duracion
        if semana > profesor.carga_max_semanal_min:
            motivos.append(
                Motivo(
                    "dura",
                    "D7",
                    f"{profesor.nombre} pasaría de su carga máxima semanal "
                    f"({profesor.carga_max_semanal_min} min).",
                    info.clase.id,
                )
            )
        dia = self._minutos_dia.get((p, franja.dia), 0) + franja.duracion
        if dia > profesor.carga_max_diaria_min:
            motivos.append(
                Motivo(
                    "dura",
                    "D7",
                    f"{profesor.nombre} pasaría de su carga máxima diaria "
                    f"({profesor.carga_max_diaria_min} min).",
                    info.clase.id,
                )
            )
        if profesor.max_dias is not None and not del_dia:
            dias = {d for (q, d), lista in self._profesor.items() if q == p and lista}
            if len(dias | {franja.dia}) > profesor.max_dias:
                motivos.append(
                    Motivo(
                        "dura",
                        "D7",
                        f"{profesor.nombre} ya da clase {len(dias)} días (máximo "
                        f"{profesor.max_dias}).",
                        info.clase.id,
                    )
                )
        intervalos = [(f.inicio, f.fin) for f, _ in del_dia] + [(franja.inicio, franja.fin)]
        if excede_continuo(intervalos, profesor.max_minutos_continuos, self.descanso):
            motivos.append(
                Motivo(
                    "dura",
                    "D8",
                    f"{profesor.nombre} pasaría de {profesor.max_minutos_continuos} min seguidos "
                    f"sin un descanso de {self.descanso} min.",
                    info.clase.id,
                )
            )
        return motivos

    def dias_con_clase(self, profesor: int) -> set[Dia]:
        return {d for (q, d), lista in self._profesor.items() if q == profesor and lista}  # type: ignore[misc]


def motivos(
    datos: DatosEscuela,
    colocaciones: Iterable[Colocacion],
    clase_id: int,
    franja: Franja,
    profesor: int | None = None,
) -> list[Motivo]:
    """Atajo sin índices precalculados (para uso puntual); el editor usa `Conflictos`."""
    return Conflictos(datos).cargar(colocaciones).motivos(clase_id, franja, profesor)
