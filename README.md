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
| F1–F12 | Pendientes |

Lo que ya funciona:
- `timetabling --version` muestra la versión.
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
