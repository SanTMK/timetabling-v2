"""Creado con Claude.

Rendimiento (§2, §20): en el ejemplo mediano, primera solución factible en menos de 60 s y
resultado final en menos de 5 min con 4 hilos. Guarda los tiempos en `rendimiento.json`
(artefacto de CI).
"""

import json
import os
import platform
import time
from pathlib import Path

import pytest

from timetabling.dominio.modelos import EstadoSolucion
from timetabling.ejemplo import ejemplo_mediano
from timetabling.nucleo.resolver import OpcionesResolucion, resolver
from timetabling.nucleo.verificador import verificar

LIMITE_PRIMERA_S = 60
LIMITE_TOTAL_S = 300
SALIDA = Path(__file__).resolve().parent.parent / "rendimiento.json"


@pytest.mark.rendimiento
def test_mediano_dentro_de_los_umbrales() -> None:
    datos = ejemplo_mediano()
    inicio = time.monotonic()
    resultado = resolver(datos, OpcionesResolucion(tiempo_limite_s=LIMITE_TOTAL_S - 20, hilos=4))
    total = time.monotonic() - inicio
    SALIDA.write_text(
        json.dumps(
            {
                "sistema": platform.platform(),
                "procesador": platform.processor() or platform.machine(),
                "nucleos": os.cpu_count(),
                "hilos": 4,
                "estado": resultado.estado.value,
                "primera_s": round(resultado.tiempo_primera_s or -1, 2),
                "total_s": round(total, 2),
                "penalizaciones": {k: round(v, 2) for k, v in resultado.penalizaciones.items()},
                "son_cota": resultado.penalizaciones_son_cota,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert resultado.tiempo_primera_s is not None
    assert resultado.tiempo_primera_s < LIMITE_PRIMERA_S
    assert total < LIMITE_TOTAL_S
    assert verificar(datos, resultado.colocaciones).valida
