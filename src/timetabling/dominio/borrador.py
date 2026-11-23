"""Creado con Claude.

Horario editable (§12.1). Una `Colocacion` es una clase puesta en una franja con sus
profesores; un `Borrador` es la lista de colocaciones. Las operaciones del editor (colocar,
quitar, intercambiar, deshacer) se completan en F8.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from timetabling.dominio.modelos import DatosEscuela


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


@dataclass
class Borrador:
    colocaciones: list[Colocacion] = field(default_factory=list)

    @classmethod
    def de(cls, colocaciones: Iterable[Colocacion]) -> "Borrador":
        return cls(list(colocaciones))

    def de_clase(self, clase_id: int) -> list[Colocacion]:
        return [c for c in self.colocaciones if c.clase_id == clase_id]

    def en_franja(self, franja_id: str) -> list[Colocacion]:
        return [c for c in self.colocaciones if c.franja_id == franja_id]

    def colocar(self, colocacion: Colocacion) -> None:
        self.colocaciones.append(colocacion)

    def quitar(self, colocacion: Colocacion) -> None:
        self.colocaciones.remove(colocacion)

    def pendientes(self, datos: DatosEscuela) -> dict[int, int]:
        """Horas que faltan por colocar, por clase (solo las que tienen faltantes)."""
        colocadas = Counter(c.clase_id for c in self.colocaciones)
        return {
            clase.id: clase.horas_semanales - colocadas[clase.id]
            for clase in datos.clases
            if clase.id is not None and colocadas[clase.id] < clase.horas_semanales
        }
