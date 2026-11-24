"""Creado con Claude.

Asistentes de importación (§15): 1) elegir el archivo, 2) vista previa con lo detectado,
3) mapeo editable, 4) resumen de lo que se creará o cambiará, 5) aplicar (en una transacción,
con respaldo previo). Para el proyecto v6 el mapeo no hace falta: archivo → resumen → aplicar.

Cada asistente expone métodos para recorrerlo sin ventana (las pruebas los usan) y `aplicar`,
que hace la importación al pulsar «Aplicar».
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from timetabling.dominio.modelos import por_id
from timetabling.gui.dialogos import FILTRO, Dialogos
from timetabling.gui.pantallas.base import ESTILO_ERROR
from timetabling.importacion import horarios_excel, maestros_excel, proyecto_v6
from timetabling.importacion.comun import Resultado
from timetabling.persistencia.migraciones import ErrorProyecto
from timetabling.servicios import importacion
from timetabling.servicios.sesion import SesionProyecto

FILTRO_EXCEL = "Libros de Excel (*.xlsx *.xlsm)"
IGNORAR = "(ignorar)"
OMITIR = "(omitir)"


def _lista(texto: str) -> list[str]:
    return [t.strip() for t in texto.split(",") if t.strip()]


class Pagina(QWizardPage):
    """Página con funciones para entrar (`al_entrar`) y validar al avanzar (`validar`, que
    devuelve un mensaje de error o `None`)."""

    def __init__(
        self,
        titulo: str,
        subtitulo: str = "",
        al_entrar: Callable[[], None] | None = None,
        validar: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__()
        self.setTitle(titulo)
        self.setSubTitle(subtitulo)
        self._al_entrar = al_entrar
        self._validar = validar
        self.capa = QVBoxLayout(self)
        self.error = QLabel()
        self.error.setStyleSheet(ESTILO_ERROR)
        self.error.setWordWrap(True)
        self.error.hide()

    def terminar(self) -> None:
        self.capa.addWidget(self.error)

    def initializePage(self) -> None:  # noqa: N802
        self.error.hide()
        if self._al_entrar is not None:
            self._al_entrar()

    def validatePage(self) -> bool:  # noqa: N802
        mensaje = self._validar() if self._validar is not None else None
        if mensaje:
            self.error.setText(f"⚠ {mensaje}")
            self.error.show()
            return False
        self.error.hide()
        return True


def _formulario() -> QFormLayout:
    """Formulario alineado a la izquierda y con campos que crecen (en macOS se centra)."""
    formulario = QFormLayout()
    formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    formulario.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    formulario.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    return formulario


def _ajustar_alto(tabla: QTableWidget, maximo: int = 240) -> None:
    """Alto suficiente para ver todas las filas (hasta `maximo`)."""
    alto = tabla.horizontalHeader().height() + 2 * tabla.frameWidth()
    alto += sum(tabla.rowHeight(f) for f in range(tabla.rowCount()))
    tabla.setFixedHeight(min(maximo, alto))


def _texto_solo_lectura(nombre: str) -> QPlainTextEdit:
    caja = QPlainTextEdit()
    caja.setReadOnly(True)
    caja.setAccessibleName(nombre)
    return caja


def _tabla(columnas: list[str], nombre: str) -> QTableWidget:
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    tabla.verticalHeader().hide()
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setAccessibleName(nombre)
    return tabla


class Asistente(QWizard):
    titulo = "Importar"

    def __init__(self, dialogos: Dialogos, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dialogos = dialogos
        self.setWindowTitle(self.titulo)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        for boton, texto in (
            (QWizard.WizardButton.NextButton, "&Siguiente >"),
            (QWizard.WizardButton.BackButton, "< &Atrás"),
            (QWizard.WizardButton.FinishButton, "&Aplicar"),
            (QWizard.WizardButton.CancelButton, "Cancelar"),
        ):
            self.setButtonText(boton, texto)
        self.setButtonLayout([
            QWizard.WizardButton.Stretch, QWizard.WizardButton.CancelButton,
            QWizard.WizardButton.BackButton, QWizard.WizardButton.NextButton,
            QWizard.WizardButton.FinishButton,
        ])  # fmt: skip
        self.resize(820, 600)
        self.informe = ""
        self.aplicado = False

    # ------------------------------------------------------------------ para pruebas y teclado

    def iniciar(self) -> None:
        """Pone el asistente en su primera página (lo hace `show`; sin ventana, hace falta)."""
        if self.currentId() == -1:
            self.restart()

    def avanzar(self) -> bool:
        """Equivale a «Siguiente»: verdadero si cambió de página."""
        self.iniciar()
        antes = self.currentId()
        self.next()
        return self.currentId() != antes

    def error_actual(self) -> str:
        self.iniciar()
        pagina = self.currentPage()
        return pagina.error.text() if isinstance(pagina, Pagina) and pagina.error.isVisibleTo(
            pagina
        ) else ""  # fmt: skip

    def aplicar(self) -> str:
        raise NotImplementedError

    def accept(self) -> None:
        try:
            self.informe = self.aplicar()
        except (ErrorProyecto, OSError, ValueError) as error:
            self.dialogos.error(self.titulo, str(error))
            return
        self.aplicado = True
        super().accept()

    # ------------------------------------------------------------------ piezas

    def _pagina_archivo(
        self, titulo: str, filtro: str, cargar: Callable[[Path], str | None]
    ) -> tuple[Pagina, QLineEdit]:
        campo = QLineEdit()
        campo.setAccessibleName("Archivo")

        def validar() -> str | None:
            texto = campo.text().strip()
            if not texto:
                return "Elija el archivo."
            ruta = Path(texto)
            if not ruta.exists():
                return f"No existe «{ruta}»."
            return cargar(ruta)

        pagina = Pagina(titulo, "Paso 1 de 4: elija el archivo.", validar=validar)
        fila = QHBoxLayout()
        fila.addWidget(campo, 1)
        elegir = QPushButton("&Elegir…")

        def buscar() -> None:
            ruta = self.dialogos.ruta_abrir(titulo, filtro)
            if ruta is not None:
                campo.setText(str(ruta))

        elegir.clicked.connect(buscar)
        fila.addWidget(elegir)
        pagina.capa.addLayout(fila)
        pagina.capa.addStretch()
        pagina.terminar()
        return pagina, campo


def _combo_editable(opciones: list[str], actual: str, nombre: str) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(opciones)
    combo.setCurrentText(actual)
    combo.setAccessibleName(nombre)
    return combo


# ---------------------------------------------------------------------------
# Cuadro de horarios por grado (§15.1)
# ---------------------------------------------------------------------------


class AsistenteHorarios(Asistente):
    titulo = "Importar cuadro de horarios"

    def __init__(self, sesion: SesionProyecto, dialogos: Dialogos,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(dialogos, parent)
        self.sesion = sesion
        self.hojas: list[horarios_excel.HojaLeida] = []
        self.mapeo = horarios_excel.MapeoHorarios()
        self.resultado: Resultado | None = None

        archivo, self.campo_archivo = self._pagina_archivo(self.titulo, FILTRO_EXCEL, self._leer)
        self.addPage(archivo)

        previa = Pagina("Vista previa", "Paso 2 de 4: lo que se detectó en el cuadro.",
                        al_entrar=self._previa)  # fmt: skip
        self.texto_previa = _texto_solo_lectura("Vista previa")
        previa.capa.addWidget(self.texto_previa)
        previa.terminar()
        self.addPage(previa)

        mapeo = Pagina("Mapeo", "Paso 3 de 4: a qué grado va cada hoja y a qué asignatura cada "
                       "texto. Los textos que se mapean a otro nombre se guardan como alias.",
                       al_entrar=self._llenar_mapeo, validar=self._leer_mapeo)  # fmt: skip
        self.tabla_hojas = _tabla(["Hoja", "Grado"], "Hojas y grados")
        self.tabla_textos = _tabla(["Texto del cuadro", "Celdas", "Asignatura"],
                                   "Textos y asignaturas")  # fmt: skip
        self.recesos = QLineEdit()
        self.recesos.setAccessibleName("Textos de receso")
        self.tutorias = QLineEdit()
        self.tutorias.setAccessibleName("Textos de tutoría")
        mapeo.capa.addWidget(self.tabla_hojas)
        mapeo.capa.addWidget(self.tabla_textos, 1)
        formulario = _formulario()
        formulario.addRow("Recesos (no cuentan):", self.recesos)
        formulario.addRow("Tutorías (no cuentan):", self.tutorias)
        mapeo.capa.addLayout(formulario)
        mapeo.terminar()
        self.addPage(mapeo)

        resumen = Pagina("Resumen", "Paso 4 de 4: revise y pulse «Aplicar». Antes se hace un "
                         "respaldo y todo se guarda en una sola transacción.",
                         al_entrar=self._resumen)  # fmt: skip
        self.texto_resumen = _texto_solo_lectura("Resumen")
        resumen.capa.addWidget(self.texto_resumen)
        resumen.terminar()
        self.addPage(resumen)

    def _leer(self, ruta: Path) -> str | None:
        try:
            self.hojas = importacion.leer_horarios(ruta)
        except ErrorProyecto as error:
            return str(error)
        if not any(g.celdas for h in self.hojas for g in h.grupos):
            return "No se encontraron bloques de horario (una fila con Monday … Friday)."
        self.mapeo = horarios_excel.mapeo_inicial(self.sesion.datos, self.hojas)
        return None

    def _previa(self) -> None:
        renglones = []
        for hoja in self.hojas:
            grupos = ", ".join(f"{g.etiqueta or g.seccion} ({len(g.celdas)} celdas)"
                               for g in hoja.grupos)  # fmt: skip
            civica = f" · hora cívica: {len(hoja.eventos)}" if hoja.eventos else ""
            renglones.append(f"Hoja «{hoja.nombre}»: {grupos or 'sin bloques'}{civica}")
        renglones += ["", "Textos detectados (celdas):"]
        for texto, n in sorted(horarios_excel.textos(self.hojas, self.mapeo).items()):
            renglones.append(f"  {texto}: {n}")
        self.texto_previa.setPlainText("\n".join(renglones))

    def _llenar_mapeo(self) -> None:
        datos = self.sesion.datos
        niveles = por_id(datos.niveles)
        hojas = [h for h in self.hojas if h.nombre in self.mapeo.hojas]
        self.tabla_hojas.setRowCount(len(hojas))
        for fila, hoja in enumerate(hojas):
            self.tabla_hojas.setItem(fila, 0, QTableWidgetItem(hoja.nombre))
            combo = QComboBox()
            combo.setAccessibleName(f"Grado de la hoja {hoja.nombre}")
            for g in datos.grados:
                nivel = niveles.get(g.nivel_id)
                combo.addItem(f"{g.nombre} ({nivel.nombre if nivel else '?'})",
                              horarios_excel.DestinoHoja(grado_id=g.id))  # fmt: skip
            for n in datos.niveles:
                nuevo = horarios_excel.DestinoHoja(nuevo_grado=hoja.nombre, nivel_id=n.id)
                combo.addItem(f"Nuevo grado «{hoja.nombre}» en {n.nombre}", nuevo)
            combo.addItem(OMITIR, horarios_excel.DestinoHoja())
            actual = self.mapeo.hojas[hoja.nombre]
            indice = next((i for i in range(combo.count()) if combo.itemData(i) == actual),
                          combo.count() - 1)  # fmt: skip
            combo.setCurrentIndex(indice)
            self.tabla_hojas.setCellWidget(fila, 1, combo)
        conteo = horarios_excel.textos(self.hojas, self.mapeo)
        nombres = {a.nombre for a in datos.asignaturas}
        nombres |= {v for v in self.mapeo.asignaturas.values() if v}
        opciones = [*sorted(nombres), IGNORAR]
        self.tabla_textos.setRowCount(len(conteo))
        for fila, (texto, n) in enumerate(sorted(conteo.items())):
            self.tabla_textos.setItem(fila, 0, QTableWidgetItem(texto))
            celdas = QTableWidgetItem(str(n))
            celdas.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabla_textos.setItem(fila, 1, celdas)
            actual = self.mapeo.asignaturas.get(texto, texto) or IGNORAR
            self.tabla_textos.setCellWidget(
                fila, 2, _combo_editable(opciones, actual, f"Asignatura para {texto}")
            )
        _ajustar_alto(self.tabla_hojas)
        self.recesos.setText(", ".join(self.mapeo.recesos))
        self.tutorias.setText(", ".join(self.mapeo.tutorias))

    def _leer_mapeo(self) -> str | None:
        for fila in range(self.tabla_hojas.rowCount()):
            combo = self.tabla_hojas.cellWidget(fila, 1)
            assert isinstance(combo, QComboBox)
            self.mapeo.hojas[self.tabla_hojas.item(fila, 0).text()] = combo.currentData()
        for fila in range(self.tabla_textos.rowCount()):
            combo = self.tabla_textos.cellWidget(fila, 2)
            assert isinstance(combo, QComboBox)
            valor = combo.currentText().strip()
            self.mapeo.asignaturas[self.tabla_textos.item(fila, 0).text()] = (
                "" if valor in ("", IGNORAR) else valor
            )
        self.mapeo.recesos = _lista(self.recesos.text())
        self.mapeo.tutorias = _lista(self.tutorias.text())
        if all(d.omitir for d in self.mapeo.hojas.values()):
            return "Asigne al menos una hoja a un grado."
        return None

    # Para pruebas: cambiar el mapeo antes de avanzar.
    def poner_grado(self, hoja: str, texto: str) -> None:
        for fila in range(self.tabla_hojas.rowCount()):
            if self.tabla_hojas.item(fila, 0).text() == hoja:
                combo = self.tabla_hojas.cellWidget(fila, 1)
                assert isinstance(combo, QComboBox)
                combo.setCurrentIndex(combo.findText(texto))
                return
        raise KeyError(hoja)

    def poner_asignatura(self, texto: str, asignatura: str) -> None:
        for fila in range(self.tabla_textos.rowCount()):
            if self.tabla_textos.item(fila, 0).text() == texto:
                combo = self.tabla_textos.cellWidget(fila, 2)
                assert isinstance(combo, QComboBox)
                combo.setCurrentText(asignatura)
                return
        raise KeyError(texto)

    def _resumen(self) -> None:
        self.resultado = horarios_excel.aplicar(self.sesion.datos, self.hojas, self.mapeo)
        self.texto_resumen.setPlainText(self.resultado.texto())

    def aplicar(self) -> str:
        return self.sesion.importar_horarios(self.hojas, self.mapeo).texto()


# ---------------------------------------------------------------------------
# Cuadro de maestros (§15.2)
# ---------------------------------------------------------------------------


class AsistenteMaestros(Asistente):
    titulo = "Importar cuadro de maestros"

    def __init__(self, sesion: SesionProyecto, dialogos: Dialogos,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(dialogos, parent)
        self.sesion = sesion
        self.bloques: list[maestros_excel.BloqueMaestro] = []
        self.mapeo = maestros_excel.MapeoMaestros()

        archivo, self.campo_archivo = self._pagina_archivo(self.titulo, FILTRO_EXCEL, self._leer)
        self.con_horarios = QCheckBox("Importar también los &horarios como borrador")
        self.con_horarios.setToolTip(
            "Cada celda se coloca en la franja de mayor traslape de su nivel; el borrador se "
            "revisa en el Editor y puede marcarse como vigente."
        )
        archivo.capa.insertWidget(1, self.con_horarios)
        self.addPage(archivo)

        previa = Pagina("Vista previa", "Paso 2 de 4: bloques de maestro detectados.",
                        al_entrar=self._previa)  # fmt: skip
        self.texto_previa = _texto_solo_lectura("Vista previa")
        previa.capa.addWidget(self.texto_previa)
        previa.terminar()
        self.addPage(previa)

        mapeo = Pagina("Mapeo", "Paso 3 de 4: nombre de cada maestro (se completa el profesor "
                       "existente o se crea uno nuevo) y asignatura de cada texto.",
                       al_entrar=self._llenar_mapeo, validar=self._leer_mapeo)  # fmt: skip
        self.tabla_maestros = _tabla(["Bloque del cuadro", "Profesor"], "Maestros")
        self.tabla_textos = _tabla(["Texto de la celda", "Asignatura"], "Textos y asignaturas")
        mapeo.capa.addWidget(self.tabla_maestros, 1)
        mapeo.capa.addWidget(self.tabla_textos, 1)
        mapeo.terminar()
        self.addPage(mapeo)

        resumen = Pagina("Resumen", "Paso 4 de 4: revise y pulse «Aplicar». Antes se hace un "
                         "respaldo y todo se guarda en una sola transacción.",
                         al_entrar=self._resumen)  # fmt: skip
        self.texto_resumen = _texto_solo_lectura("Resumen")
        resumen.capa.addWidget(self.texto_resumen)
        resumen.terminar()
        self.addPage(resumen)

    def _leer(self, ruta: Path) -> str | None:
        try:
            self.bloques = importacion.leer_maestros(ruta)
        except ErrorProyecto as error:
            return str(error)
        if not self.bloques:
            return "No se encontraron bloques de maestro (un nombre sobre la fila de días)."
        self.mapeo = maestros_excel.mapeo_inicial(self.sesion.datos, self.bloques)
        self.mapeo.con_horarios = self.con_horarios.isChecked()
        return None

    def _previa(self) -> None:
        renglones = []
        for b in self.bloques:
            ejemplo = ", ".join(c.texto for c in b.celdas[:4])
            renglones.append(f"{b.nombre or '(sin nombre)'}: {len(b.celdas)} celdas · {ejemplo}…")
        self.texto_previa.setPlainText("\n".join(renglones))

    def _llenar_mapeo(self) -> None:
        nombres = sorted(p.nombre for p in self.sesion.datos.profesores)
        self.tabla_maestros.setRowCount(len(self.mapeo.maestros))
        for fila, (bloque, destino) in enumerate(self.mapeo.maestros.items()):
            self.tabla_maestros.setItem(fila, 0, QTableWidgetItem(bloque))
            opciones = sorted(set(nombres) | {destino} - {""}) + [OMITIR]
            self.tabla_maestros.setCellWidget(
                fila, 1, _combo_editable(opciones, destino or OMITIR, f"Profesor para {bloque}")
            )
        asignaturas = sorted(a.nombre for a in self.sesion.datos.asignaturas) + [IGNORAR]
        self.tabla_textos.setRowCount(len(self.mapeo.asignaturas))
        for fila, (texto, destino) in enumerate(sorted(self.mapeo.asignaturas.items())):
            self.tabla_textos.setItem(fila, 0, QTableWidgetItem(texto))
            combo = QComboBox()
            combo.addItems(asignaturas)
            combo.setCurrentText(destino or IGNORAR)
            combo.setAccessibleName(f"Asignatura para {texto}")
            self.tabla_textos.setCellWidget(fila, 1, combo)

    def _leer_mapeo(self) -> str | None:
        for fila in range(self.tabla_maestros.rowCount()):
            combo = self.tabla_maestros.cellWidget(fila, 1)
            assert isinstance(combo, QComboBox)
            valor = combo.currentText().strip()
            self.mapeo.maestros[self.tabla_maestros.item(fila, 0).text()] = (
                "" if valor in ("", OMITIR) else valor
            )
        for fila in range(self.tabla_textos.rowCount()):
            combo = self.tabla_textos.cellWidget(fila, 1)
            assert isinstance(combo, QComboBox)
            valor = combo.currentText()
            self.mapeo.asignaturas[self.tabla_textos.item(fila, 0).text()] = (
                "" if valor == IGNORAR else valor
            )
        self.mapeo.con_horarios = self.con_horarios.isChecked()
        if not any(self.mapeo.maestros.values()):
            return "Asigne al menos un bloque a un profesor."
        return None

    def _resumen(self) -> None:
        resultado = maestros_excel.aplicar(self.sesion.datos, self.bloques, self.mapeo)
        self.texto_resumen.setPlainText(resultado.texto())

    def aplicar(self) -> str:
        resultado, borrador = self.sesion.importar_maestros(self.bloques, self.mapeo)
        texto = resultado.texto()
        if borrador is not None:
            texto += f"\n\nBorrador «{borrador.nombre}» guardado: revíselo en el Editor."
        return texto


# ---------------------------------------------------------------------------
# Proyecto de la versión anterior (§15.3)
# ---------------------------------------------------------------------------


class AsistenteV6(Asistente):
    titulo = "Importar proyecto anterior"

    def __init__(self, dialogos: Dialogos, origen: Path | None = None,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(dialogos, parent)
        self.lectura: proyecto_v6.ImportacionV6 | None = None
        self.destino: Path | None = None

        archivo = Pagina(self.titulo, "Paso 1 de 2: el proyecto de la versión anterior y dónde "
                         "guardar el proyecto nuevo (el anterior no se modifica).",
                         validar=self._validar_archivo)  # fmt: skip
        formulario = _formulario()
        self.campo_origen = QLineEdit(str(origen) if origen else "")
        self.campo_origen.setAccessibleName("Proyecto anterior")
        self.campo_destino = QLineEdit(str(origen.with_name(f"{origen.stem} (v2).horario"))
                                       if origen else "")  # fmt: skip
        self.campo_destino.setAccessibleName("Proyecto nuevo")
        for campo, etiqueta, elegir in (
            (self.campo_origen, "Proyecto anterior:", self._elegir_origen),
            (self.campo_destino, "Proyecto nuevo:", self._elegir_destino),
        ):
            fila = QHBoxLayout()
            fila.addWidget(campo, 1)
            boton = QPushButton("Elegir…")
            boton.clicked.connect(elegir)
            fila.addWidget(boton)
            formulario.addRow(etiqueta, fila)
        archivo.capa.addLayout(formulario)
        archivo.capa.addStretch()
        archivo.terminar()
        self.addPage(archivo)

        resumen = Pagina("Resumen", "Paso 2 de 2: lo que se importará. Pulse «Aplicar» para crear "
                         "el proyecto nuevo.", al_entrar=self._resumen)  # fmt: skip
        self.texto_resumen = _texto_solo_lectura("Resumen")
        resumen.capa.addWidget(self.texto_resumen)
        resumen.terminar()
        self.addPage(resumen)

    def _elegir_origen(self) -> None:
        ruta = self.dialogos.ruta_abrir(self.titulo, FILTRO)
        if ruta is not None:
            self.campo_origen.setText(str(ruta))
            if not self.campo_destino.text():
                self.campo_destino.setText(str(ruta.with_name(f"{ruta.stem} (v2).horario")))

    def _elegir_destino(self) -> None:
        ruta = self.dialogos.ruta_nueva("Proyecto nuevo")
        if ruta is not None:
            self.campo_destino.setText(str(ruta))

    def _validar_archivo(self) -> str | None:
        origen = Path(self.campo_origen.text().strip())
        destino_texto = self.campo_destino.text().strip()
        if not self.campo_origen.text().strip() or not origen.exists():
            return "Elija el proyecto de la versión anterior."
        if not proyecto_v6.es_v6(origen):
            return "El archivo no es un proyecto de la versión anterior (esquema v6)."
        if not destino_texto:
            return "Elija dónde guardar el proyecto nuevo."
        destino = Path(destino_texto)
        if destino.suffix != ".horario":
            destino = destino.with_suffix(".horario")
        if destino.exists():
            return f"Ya existe «{destino.name}»: elija otro nombre."
        try:
            self.lectura = proyecto_v6.leer(origen)
        except (proyecto_v6.ErrorV6, ValueError, KeyError) as error:
            return f"No se pudo leer el proyecto: {error}"
        self.destino = destino
        return None

    def _resumen(self) -> None:
        assert self.lectura is not None
        _, avisos = importacion.soluciones_v6(self.lectura)
        informe = importacion.InformeV6(self.lectura.importado,
                                        [*self.lectura.no_importado, *avisos])  # fmt: skip
        self.texto_resumen.setPlainText(informe.texto(previo=True))

    def aplicar(self) -> str:
        assert self.destino is not None
        return importacion.importar_v6(self.campo_origen.text().strip(), self.destino).texto()
