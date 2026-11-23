# Decisiones de detalle

> Creado con Claude.

Registro de decisiones que la especificación (`ESPECIFICACION_V2.md`) no cubre (§0, regla 3).
Formato: fecha · contexto · decisión · alternativa descartada.

## F0 Esqueleto

### 2026-11-23 · Versión de Python fijada
- **Contexto:** §2 pide Python ≥ 3.13 con `.python-version`.
- **Decisión:** `.python-version = 3.13` y `requires-python = ">=3.13"`. 3.13 tiene ruedas
  publicadas de PySide6, OR-Tools y PyInstaller en los tres sistemas.
- **Descartada:** 3.14, por el riesgo de que alguna dependencia binaria aún no publique ruedas.

### 2026-11-23 · Backend de construcción
- **Contexto:** el `pyproject` necesita un backend para instalar el paquete y el script
  `timetabling`.
- **Decisión:** `hatchling` (solo en tiempo de construcción; no es dependencia de ejecución).
- **Descartada:** `setuptools`, más verboso para el diseño `src/`.

### 2026-11-23 · Todas las dependencias declaradas desde F0
- **Contexto:** las dependencias de §3 se usan a partir de F1–F12.
- **Decisión:** declararlas todas desde F0 para que `uv.lock` y el CI validen desde el principio
  que se instalan en Windows, macOS y Linux.
- **Descartada:** agregarlas fase por fase (detectaría tarde un problema de instalación).

### 2026-11-23 · Forma del bloqueo de red
- **Contexto:** §20 pide bloquear `socket.socket` y `socket.create_connection` durante toda la
  suite.
- **Decisión:** un fixture `autouse` de alcance de sesión en `pruebas/conftest.py` sustituye
  ambos por una función que lanza `RedBloqueadaError` (subclase de `RuntimeError`).
  `pruebas/test_esqueleto.py` comprueba que el bloqueo funciona.
- **Descartada:** el plugin `pytest-socket` (dependencia extra fuera de §3).

### 2026-11-23 · Sin verificador de tipos estático
- **Contexto:** §0 pide código con tipos en todas partes, pero §3 no incluye `mypy` ni `pyright`.
- **Decisión:** anotar todo el código sin agregar un verificador al CI, para no salir de §3.
- **Descartada:** agregar `mypy` al grupo dev (se puede proponer más adelante).

### 2026-11-23 · Pruebas lentas en el CI sin pruebas todavía
- **Contexto:** en F0 no existen pruebas `lento` ni `rendimiento`; pytest devuelve el código 5
  («ninguna prueba recolectada»).
- **Decisión:** el trabajo de Windows trata el código 5 como éxito.
- **Descartada:** omitir el trabajo hasta F4 (el flujo de CI quedaría incompleto).

### 2026-11-23 · Comando sin subcomando
- **Contexto:** §18 dice que `timetabling` sin argumentos abre la interfaz, que llega en F6.
- **Decisión:** hasta F6 imprime un aviso y termina con código 0.
- **Descartada:** mostrar la ayuda (cambiaría el comportamiento esperado más adelante).
