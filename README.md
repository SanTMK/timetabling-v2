# Timetabling escolar v2

> Creado con Claude.

Aplicación de escritorio, sin conexión, para generar y **editar a mano** el horario semanal de
una escuela con preescolar, primaria y secundaria. La especificación completa está en
[`ESPECIFICACION_V2.md`](ESPECIFICACION_V2.md) y las decisiones de detalle en
[`DECISIONES.md`](DECISIONES.md).

## Estado

| Fase | Estado |
|---|---|
| F0 Esqueleto | ✔ `uv`, `pyproject`, `ruff`, `pytest`, red bloqueada en pruebas, prueba de cabeceras, CI |
| F1 Dominio y persistencia | ✔ Entidades (§5), archivo SQLite con migraciones, borrados, respaldos y bloqueo (§6), ejemplos |
| F2 Tiempo y validación | ✔ Franjas, recesos, eventos, bloqueos, traslapes, cliques, rejilla Δ, disponibilidad (§7); validación global (§10) |
| F3 Modelo duro y verificador | ✔ Modelo CP-SAT con D1–D16, etapa de factibilidad, conflictos incrementales, verificador independiente; el mediano resuelve en ~1,5 s |
| F4 Objetivo | ✔ Criterios B1–B10 con prioridades y perfiles, etapa de optimización, `timetabling generar` |
| F5 Diagnóstico | ✔ Núcleo de infactibilidad por familias y por entidad, con mensajes concretos |
| F6–F12 | Pendientes |

Lo que ya funciona:
- `timetabling --version` muestra la versión.
- `timetabling ejemplo P.horario [--tamano pequeno|mediano] [--sobrescribir]` crea un proyecto
  de ejemplo.
- `timetabling validar P.horario` lista errores y advertencias con su acción sugerida
  (código de salida 1 si hay errores).
- `timetabling generar P.horario [--tiempo-limite N] [--hilos N]` valida, genera el horario
  (primero una solución factible y luego la optimiza según las prioridades de §9), lo comprueba
  con el verificador independiente y lo guarda en el proyecto con sus penalizaciones. Si no
  hay solución posible, explica el conflicto («El conflicto involucra los límites de carga de
  Ana y las 2 horas de Matemáticas de 1°A…»).
- Al abrir un proyecto se crea un respaldo diario en `.respaldos/`, un archivo de bloqueo
  `P.horario.lock` y, si la carpeta está sincronizada (OneDrive, Dropbox…), un aviso.
- La suite de pruebas bloquea la red en ejecución y verifica las cabeceras «Creado con Claude.».

## Requisitos de desarrollo

- [`uv`](https://docs.astral.sh/uv/) (instala Python 3.13 automáticamente según `.python-version`).

## Cómo probar

```bash
uv sync
```

```bash
uv run timetabling --version
```

```bash
uv run timetabling ejemplo mediano.horario --tamano mediano
```

```bash
uv run timetabling validar mediano.horario
```

```bash
uv run timetabling generar mediano.horario --tiempo-limite 60
```

```bash
uv run pytest -m "not lento and not rendimiento"
```

```bash
uv run pytest
```

```bash
uv run ruff check src pruebas
```

## Integración continua

`.github/workflows/ci.yml` ejecuta `ruff` y las pruebas rápidas en Windows, macOS y Linux
(`QT_QPA_PLATFORM=offscreen` en Linux) en cada push, y las pruebas lentas y de rendimiento en
Windows.
