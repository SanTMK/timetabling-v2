"""Creado con Claude.

Horario editable (§12.1). Una `Colocacion` es una clase puesta en una franja con sus
profesores; un `Borrador` es la lista de colocaciones.

Toda edición es una `Operacion` (qué colocaciones se quitan y cuáles se ponen) que sabe
invertirse, así el editor puede deshacer y rehacer (Ctrl+Z / Ctrl+Y) sin conocer los detalles.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

from timetabling.dominio.clases import texto_destinatarios
from timetabling.dominio.modelos import DatosEscuela, por_id


@dataclass(frozen=True, order=True)
class Colocacion:
    """La clase `clase_id` ocurre en la franja `franja_id` («nivel:día:índice») impartida por
    `profesores` (uno si la clase no tiene profesores fijos; todos los fijos si los tiene)."""

    clase_id: int
    franja_id: str
    profesores: tuple[int, ...]
    bloqueada: bool = False

    @property
    def dia(self) -> str:
        return self.franja_id.split(":")[1]

    def en(self, franja_id: str) -> "Colocacion":
        return replace(self, franja_id=franja_id)


class ErrorBorrador(ValueError):
    """La operación no se puede aplicar al borrador."""


@dataclass(frozen=True)
class Operacion:
    """Quita unas colocaciones y pone otras. `inversa()` la deshace."""

    quitar: tuple[Colocacion, ...] = ()
    poner: tuple[Colocacion, ...] = ()
    descripcion: str = ""

    def inversa(self) -> "Operacion":
        return Operacion(self.poner, self.quitar, f"Deshacer: {self.descripcion}")

    @property
    def vacia(self) -> bool:
        return set(self.quitar) == set(self.poner)


@dataclass(frozen=True)
class Tarjeta:
    """Una tarjeta del panel «Por colocar» (§12.2)."""

    clase_id: int
    texto: str
    faltan: int
    total: int
    franjas: int = 1
    """2 si la clase exige bloque doble y faltan al menos dos horas."""
    asignatura: str = ""
    grupos: tuple[int, ...] = ()
    profesores: tuple[int, ...] = ()


@dataclass
class Borrador:
    colocaciones: list[Colocacion] = field(default_factory=list)

    @classmethod
    def de(cls, colocaciones: Iterable[Colocacion]) -> "Borrador":
        return cls(sorted(colocaciones))

    def copia(self) -> "Borrador":
        return Borrador(list(self.colocaciones))

    # ------------------------------------------------------------------ consultas

    def de_clase(self, clase_id: int) -> list[Colocacion]:
        return [c for c in self.colocaciones if c.clase_id == clase_id]

    def en_franja(self, franja_id: str) -> list[Colocacion]:
        return [c for c in self.colocaciones if c.franja_id == franja_id]

    def buscar(self, clase_id: int, franja_id: str) -> Colocacion | None:
        return next(
            (c for c in self.colocaciones if c.clase_id == clase_id and c.franja_id == franja_id),
            None,
        )

    def bloqueadas(self) -> list[Colocacion]:
        return [c for c in self.colocaciones if c.bloqueada]

    def pendientes(self, datos: DatosEscuela) -> dict[int, int]:
        """Horas que faltan por colocar, por clase (solo las que tienen faltantes)."""
        colocadas = Counter(c.clase_id for c in self.colocaciones)
        return {
            clase.id: clase.horas_semanales - colocadas[clase.id]
            for clase in datos.clases
            if clase.id is not None and colocadas[clase.id] < clase.horas_semanales
        }

    def tarjetas(self, datos: DatosEscuela) -> list[Tarjeta]:
        """Tarjetas del panel «Por colocar»: «Matemáticas · 7°A · López · faltan 3 de 5»."""
        clases = por_id(datos.clases)
        asignaturas = por_id(datos.asignaturas)
        profesores = por_id(datos.profesores)
        resultado: list[Tarjeta] = []
        for clase_id, faltan in self.pendientes(datos).items():
            clase = clases[clase_id]
            asignatura = asignaturas.get(clase.asignatura_id)
            nombre = asignatura.nombre if asignatura else "?"
            actuales = sorted({p for c in self.de_clase(clase_id) for p in c.profesores})
            quienes = clase.profesores or actuales
            texto_profesores = ", ".join(profesores[p].nombre for p in quienes if p in profesores)
            partes = [nombre, texto_destinatarios(datos, clase)]
            if texto_profesores:
                partes.append(texto_profesores)
            partes.append(f"faltan {faltan} de {clase.horas_semanales}")
            doble = 1
            if asignatura is not None:
                try:
                    nivel = datos.nivel_de_grupo(clase.destinatarios[0].grupo_id).id
                except KeyError:
                    nivel = None
                if asignatura.reglas_efectivas(nivel).bloque_doble == "obligatorio" and faltan >= 2:
                    doble = 2
            resultado.append(
                Tarjeta(
                    clase_id=clase_id,
                    texto=" · ".join(partes) + (" · bloque de 2" if doble == 2 else ""),
                    faltan=faltan,
                    total=clase.horas_semanales,
                    franjas=doble,
                    asignatura=nombre,
                    grupos=tuple(d.grupo_id for d in clase.destinatarios),
                    profesores=tuple(quienes),
                )
            )
        return resultado

    # ------------------------------------------------------------------ edición

    def aplicar(self, operacion: Operacion) -> None:
        """Aplica la operación completa o no aplica nada."""
        restantes = Counter(self.colocaciones)
        for c in operacion.quitar:
            if restantes[c] <= 0:
                raise ErrorBorrador(f"La colocación {c} no está en el borrador.")
            restantes[c] -= 1
        resultado = list(restantes.elements())
        ocupadas = {(c.clase_id, c.franja_id) for c in resultado}
        for c in operacion.poner:
            if (c.clase_id, c.franja_id) in ocupadas:
                raise ErrorBorrador("La clase ya está en esa franja.")
            ocupadas.add((c.clase_id, c.franja_id))
            resultado.append(c)
        self.colocaciones = sorted(resultado)

    # Los constructores de operaciones no modifican el borrador: devuelven la operación.

    def colocar(self, colocacion: Colocacion) -> Operacion:
        return Operacion((), (colocacion,), "Colocar")

    def quitar(self, colocacion: Colocacion) -> Operacion:
        return Operacion((colocacion,), (), "Quitar")

    def mover(self, colocacion: Colocacion, franja_id: str) -> Operacion:
        return Operacion((colocacion,), (colocacion.en(franja_id),), "Mover")

    def intercambiar(self, a: Colocacion, b: Colocacion) -> Operacion:
        """`a` pasa a la franja de `b` y `b` a la de `a`."""
        return Operacion((a, b), (a.en(b.franja_id), b.en(a.franja_id)), "Intercambiar")

    def bloquear(self, colocacion: Colocacion, bloqueada: bool = True) -> Operacion:
        texto = "Bloquear" if bloqueada else "Desbloquear"
        return Operacion((colocacion,), (replace(colocacion, bloqueada=bloqueada),), texto)

    def cambiar_profesor(self, clase_id: int, profesores: Sequence[int]) -> Operacion:
        """Cambia el profesor de **todas** las colocaciones de la clase (continuidad, D6)."""
        actuales = tuple(self.de_clase(clase_id))
        nuevas = tuple(replace(c, profesores=tuple(profesores)) for c in actuales)
        return Operacion(actuales, nuevas, "Cambiar profesor")

    def reemplazar(self, nuevas: Iterable[Colocacion], descripcion: str) -> Operacion:
        """Pasa del estado actual a `nuevas` tocando solo lo que cambia (reparación)."""
        actuales = Counter(self.colocaciones)
        objetivo = Counter(nuevas)
        quitar = tuple((actuales - objetivo).elements())
        poner = tuple((objetivo - actuales).elements())
        return Operacion(quitar, poner, descripcion)
