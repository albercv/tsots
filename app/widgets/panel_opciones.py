from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videopipeline import subtitles
from videopipeline.config import MODELOS_POR_TAREA, pasos_desde_modo
from videopipeline.i18n import N_, _
from videopipeline.ollama import (
    Modelo, cabe, motivo_no_cabe, motivo_pesado, pesado,
)

from .seccion_plegable import Acordeon, SeccionPlegable

# clearvoice/app/widgets/panel_opciones.py → clearvoice/checkpoints
CHECKPOINTS_DIR = Path(__file__).resolve().parents[2] / "checkpoints"

WHISPER_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"

# Las claves son los msgid (N_ las marca para extracción); el combo se puebla
# con addItem(_(etiqueta), valor) — texto traducido, dato = valor interno.
ETIQUETA_TAREA = {
    N_("Mejora de voz"): "speech_enhancement",
    N_("Separación de hablantes"): "speech_separation",
    N_("Super-resolución"): "speech_super_resolution",
}

ETIQUETA_SILENCIOS = {N_("Cortar"): "cortar", N_("Acelerar"): "acelerar"}

ETIQUETA_DISENO = {
    N_("Reels Bold"): "reels_bold",
    N_("Reels Karaoke"): "reels_karaoke",
    N_("Caja negra"): "caja",
    N_("Impacto"): "impacto",
    N_("Amarillo"): "amarillo",
    N_("Karaoke verde"): "karaoke_verde",
    N_("Minimalista"): "minimal",
    N_("Caja blanca"): "caja_blanca",
}

# "Español" y "English" son nombres de idioma: no se traducen.
ETIQUETA_IDIOMA = {"Español": "es", N_("Autodetectar"): "auto", "English": "en"}

ETIQUETA_ENCUADRE = {
    N_("Recorte central"): "central",
    N_("Fondo difuminado"): "difuminado",
    N_("Barras negras"): "barras",
    N_("Seguir la cara"): "cara",
}

ETIQUETA_MODELO_WHISPER = {
    N_("turbo (recomendado)"): "turbo",
    N_("small (rápido)"): "small",
    N_("medium (más preciso)"): "medium",
}


# Sangría del contenido de cada sección (px lógicos), bajo el título.
MARGEN_CONTENIDO = 22

# Marca en la cabecera de las secciones cuyo paso está activo: con el acordeón
# solo se ve una abierta y así se sabe qué pasos van a correr.
MARCA_ACTIVO = "✓ "


def _como_bool(valor, defecto: bool) -> bool:
    """Booleano de QSettings: puede llegar como bool o como "true"/"1"."""
    if valor is None:
        return defecto
    if isinstance(valor, bool):
        return valor
    return str(valor).lower() in ("true", "1")


class PanelOpciones(QWidget):
    opciones_subs_cambiadas = Signal()
    editar_marca = Signal()
    editar_glosario = Signal()
    modelo_caption_cambiado = Signal(str)  # nombre del modelo elegido
    refrescar_modelos = Signal()
    seccion_abierta_cambiada = Signal(str)  # clave de la sección abierta
    pasos_cambiados = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Secciones plegables en acordeón: solo una abierta, Audio al arrancar.
        self.secciones: dict[str, SeccionPlegable] = {}
        self._titulos: dict[str, str] = {}
        self._acordeon = Acordeon(self)
        self._acordeon.cambiada.connect(self._emitir_seccion_abierta)

        # Tres estados: todos los pasos, algunos o ninguno. Pulsarla marca
        # todos (o los desmarca si ya estaban todos).
        self.check_completo = QCheckBox(_("Pipeline completo"))
        self.check_completo.setTristate(True)
        self.check_completo.clicked.connect(self._marcar_todo)
        fila_completo = QHBoxLayout()
        fila_completo.setContentsMargins(8, 6, 4, 6)
        fila_completo.addWidget(self.check_completo)
        layout.addLayout(fila_completo)

        form_audio = self._seccion(
            "audio", _("Limpieza de audio"), QFormLayout
        )
        self.check_audio = QCheckBox(_("Mejorar audio"))
        self.check_audio.setChecked(True)
        form_audio.addRow(self.check_audio)
        self.combo_tarea = QComboBox()
        for etiqueta, valor in ETIQUETA_TAREA.items():
            self.combo_tarea.addItem(_(etiqueta), valor)
        self.combo_modelo = QComboBox()
        self.combo_tarea.currentIndexChanged.connect(self._repoblar_modelos)
        self.aviso_modelo = QLabel("")
        self.aviso_modelo.setStyleSheet("color: #b8860b;")
        self.aviso_modelo.setWordWrap(True)
        self.combo_modelo.currentTextChanged.connect(
            self._refrescar_aviso_modelo
        )
        form_audio.addRow(_("Tarea:"), self.combo_tarea)
        form_audio.addRow(_("Modelo:"), self.combo_modelo)
        form_audio.addRow("", self.aviso_modelo)
        self._repoblar_modelos()
        self._refrescar_aviso_modelo()

        form_sil = self._seccion(
            "silencios", _("Corte de silencios"), QFormLayout
        )
        self.check_silencios = QCheckBox(_("Recortar silencios"))
        self.check_silencios.setChecked(True)
        form_sil.addRow(self.check_silencios)
        self.campo_margen = QLineEdit("0.2s")
        self.campo_umbral = QLineEdit("4%")
        self.combo_silencios = QComboBox()
        for etiqueta, valor in ETIQUETA_SILENCIOS.items():
            self.combo_silencios.addItem(_(etiqueta), valor)
        self.spin_velocidad = QSpinBox()
        self.spin_velocidad.setRange(2, 99)
        self.spin_velocidad.setValue(4)
        self.combo_silencios.currentIndexChanged.connect(
            self._actualizar_habilitados
        )
        form_sil.addRow(_("Margen:"), self.campo_margen)
        form_sil.addRow(_("Umbral:"), self.campo_umbral)
        form_sil.addRow(_("Silencios:"), self.combo_silencios)
        form_sil.addRow(_("Velocidad:"), self.spin_velocidad)

        form_subs = self._seccion(
            "subtitulos", _("Subtítulos"), QFormLayout
        )
        self.check_subtitulos = QCheckBox(_("Añadir subtítulos"))
        self.combo_diseno = QComboBox()
        for etiqueta, valor in ETIQUETA_DISENO.items():
            self.combo_diseno.addItem(_(etiqueta), valor)
        self.spin_posicion = QSpinBox()
        self.spin_posicion.setRange(50, 95)
        self.spin_posicion.setValue(75)
        self.spin_posicion.setSuffix(" %")
        self.slider_tamano = QSlider(Qt.Orientation.Horizontal)
        self.slider_tamano.setRange(50, 150)
        self.slider_tamano.setValue(100)
        self.slider_tamano.setSingleStep(5)
        self.slider_tamano.setPageStep(10)
        self.etiqueta_tamano = QLabel("100 %")
        self.slider_tamano.valueChanged.connect(
            lambda v: self.etiqueta_tamano.setText(f"{v} %")
        )
        self.combo_idioma_subs = QComboBox()
        for etiqueta, valor in ETIQUETA_IDIOMA.items():
            self.combo_idioma_subs.addItem(_(etiqueta), valor)
        self.combo_modelo_whisper = QComboBox()
        for etiqueta, valor in ETIQUETA_MODELO_WHISPER.items():
            self.combo_modelo_whisper.addItem(_(etiqueta), valor)
        self.aviso_whisper = QLabel("")
        self.aviso_whisper.setStyleSheet("color: #b8860b;")
        self.aviso_whisper.setWordWrap(True)
        form_subs.addRow(self.check_subtitulos)
        form_subs.addRow(_("Diseño:"), self.combo_diseno)
        form_subs.addRow(_("Posición vertical:"), self.spin_posicion)
        fila_tamano = QHBoxLayout()
        fila_tamano.addWidget(self.slider_tamano, 1)
        fila_tamano.addWidget(self.etiqueta_tamano)
        form_subs.addRow(_("Tamaño:"), fila_tamano)
        form_subs.addRow(_("Idioma:"), self.combo_idioma_subs)
        self.boton_glosario = QPushButton(_("Términos…"))
        self.boton_glosario.setToolTip(
            _("Marcas y nombres propios que Whisper debe escribir bien.")
        )
        self.boton_glosario.clicked.connect(self.editar_glosario)
        form_subs.addRow(_("Modelo:"), self.combo_modelo_whisper)
        form_subs.addRow("", self.aviso_whisper)
        # Fila propia: junto al combo ensancharía la columna de opciones.
        form_subs.addRow("", self.boton_glosario)
        self.check_subtitulos.toggled.connect(self._actualizar_subtitulos)
        self.combo_modelo_whisper.currentIndexChanged.connect(
            self._refrescar_aviso_whisper
        )
        self._actualizar_subtitulos()

        caption_layout = self._seccion(
            "caption", _("Caption SEO"), QVBoxLayout
        )
        fila_caption = QHBoxLayout()
        self.check_caption = QCheckBox(_("Título, caption y hashtags"))
        self.check_caption.setToolTip(
            _(
                "Genera nombre_limpio.md con un modelo local (Ollama) a partir "
                "de la transcripción."
            )
        )
        self.boton_marca = QPushButton(_("Marca…"))
        self.boton_marca.setToolTip(_("Contexto de marca que se añade al prompt."))
        self.boton_marca.clicked.connect(self.editar_marca)
        fila_caption.addWidget(self.check_caption, 1)
        fila_caption.addWidget(self.boton_marca)
        caption_layout.addLayout(fila_caption)
        # El glosario sirve a subtítulos y caption: activo si hay alguno.
        self.check_subtitulos.toggled.connect(self._actualizar_glosario)
        self.check_caption.toggled.connect(self._actualizar_glosario)
        self._actualizar_glosario()
        # Selector de modelo: se rellena con los modelos instalados en Ollama
        # (poblar_modelos); los que no caben en memoria quedan deshabilitados.
        fila_modelo = QHBoxLayout()
        self.combo_modelo_caption = QComboBox()
        self.combo_modelo_caption.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.combo_modelo_caption.setMinimumContentsLength(18)
        self.boton_refrescar_modelos = QPushButton("↻")
        self.boton_refrescar_modelos.setToolTip(
            _("Volver a leer los modelos instalados en Ollama (tras un ollama pull).")
        )
        self.boton_refrescar_modelos.setFixedWidth(32)
        self.boton_refrescar_modelos.clicked.connect(self.refrescar_modelos)
        fila_modelo.addWidget(QLabel(_("Modelo:")))
        fila_modelo.addWidget(self.combo_modelo_caption, 1)
        fila_modelo.addWidget(self.boton_refrescar_modelos)
        caption_layout.addLayout(fila_modelo)
        self.aviso_modelos = QLabel("")
        self.aviso_modelos.setStyleSheet("color: #b8860b;")
        self.aviso_modelos.setWordWrap(True)
        caption_layout.addWidget(self.aviso_modelos)
        self._hay_modelos = False
        self._modelos_pesados: dict[str, str] = {}
        self._modelos_no_caben = 0
        self.combo_modelo_caption.currentIndexChanged.connect(
            self._emitir_cambio_modelo
        )
        self.combo_modelo_caption.currentIndexChanged.connect(
            self._refrescar_aviso_modelos
        )

        form_vertical = self._seccion(
            "vertical", _("Formato vertical"), QFormLayout
        )
        self.check_vertical = QCheckBox(_("Convertir a vertical (9:16)"))
        self.check_vertical.setToolTip(
            _("Además del horizontal, guarda nombre_limpio_vertical.mp4 para "
              "Reels y TikTok (solo el vertical si no hay audio ni silencios).")
        )
        self.combo_encuadre = QComboBox()
        for etiqueta, valor in ETIQUETA_ENCUADRE.items():
            self.combo_encuadre.addItem(_(etiqueta), valor)
        self.aviso_encuadre = QLabel("")
        self.aviso_encuadre.setStyleSheet("color: #b8860b;")
        self.aviso_encuadre.setWordWrap(True)
        form_vertical.addRow(self.check_vertical)
        form_vertical.addRow(_("Encuadre:"), self.combo_encuadre)
        form_vertical.addRow("", self.aviso_encuadre)
        self.combo_encuadre.currentIndexChanged.connect(
            self._refrescar_aviso_encuadre
        )

        for seccion in self.secciones.values():
            layout.addWidget(seccion)
            self._acordeon.anadir(seccion)
        layout.addStretch(1)

        self._grupo_audio = self.secciones["audio"].contenido
        self._grupo_silencios = self.secciones["silencios"].contenido
        for casilla in self._casillas_pasos().values():
            casilla.toggled.connect(self._actualizar_pasos)
        self._actualizar_pasos()

        self.check_subtitulos.toggled.connect(self._emitir_cambio_subs)
        self.combo_diseno.currentIndexChanged.connect(self._emitir_cambio_subs)
        self.spin_posicion.valueChanged.connect(self._emitir_cambio_subs)
        self.slider_tamano.valueChanged.connect(self._emitir_cambio_subs)

    def _seccion(self, clave: str, titulo: str, tipo_layout):
        """Crea la sección plegable `clave` y devuelve el layout de su contenido.

        Los controles van en `contenido`: la lógica de habilitados lo recorre
        entero sin tocar nunca la cabecera."""
        seccion = SeccionPlegable(titulo)
        self.secciones[clave] = seccion
        self._titulos[clave] = titulo
        layout = tipo_layout(seccion.contenido)
        # Sangría para alinear los controles con el título, tras la flecha.
        layout.setContentsMargins(MARGEN_CONTENIDO, 2, 4, 10)
        return layout

    def seccion_abierta(self) -> str:
        abierta = self._acordeon.abierta()
        return next(
            (clave for clave, s in self.secciones.items() if s is abierta), ""
        )

    def abrir_seccion(self, clave: str) -> None:
        self._acordeon.abrir(self.secciones[clave])

    def _emitir_seccion_abierta(self, *args) -> None:
        self.seccion_abierta_cambiada.emit(self.seccion_abierta())

    def _repoblar_modelos(self) -> None:
        tarea = self.combo_tarea.currentData()
        self.combo_modelo.clear()
        self.combo_modelo.addItems(MODELOS_POR_TAREA[tarea])

    def _refrescar_aviso_modelo(self) -> None:
        modelo = self.combo_modelo.currentText()
        if modelo and not (CHECKPOINTS_DIR / modelo).is_dir():
            self.aviso_modelo.setText(
                _("El modelo se descargará al primer uso.")
            )
        else:
            self.aviso_modelo.setText("")

    def _casillas_pasos(self) -> dict[str, QCheckBox]:
        """Casilla de cada paso, por la clave de su sección."""
        return {
            "audio": self.check_audio,
            "silencios": self.check_silencios,
            "subtitulos": self.check_subtitulos,
            "caption": self.check_caption,
            "vertical": self.check_vertical,
        }

    def hay_pasos_de_video(self) -> bool:
        """Hay algo que hacer con el vídeo (el caption solo no basta)."""
        return any(c.isChecked() for c in (
            self.check_audio, self.check_silencios, self.check_subtitulos,
            self.check_vertical,
        ))

    def _marcar_todo(self, *args) -> None:
        casillas = self._casillas_pasos().values()
        marcar = not all(c.isChecked() for c in casillas)
        for casilla in casillas:
            casilla.setChecked(marcar)
        self._actualizar_pasos()

    def _actualizar_pasos(self, *args) -> None:
        casillas = self._casillas_pasos()
        for clave, casilla in casillas.items():
            marca = MARCA_ACTIVO if casilla.isChecked() else ""
            self.secciones[clave].cabecera.setText(marca + self._titulos[clave])
        marcadas = sum(c.isChecked() for c in casillas.values())
        estado = (
            Qt.CheckState.Checked if marcadas == len(casillas)
            else Qt.CheckState.Unchecked if marcadas == 0
            else Qt.CheckState.PartiallyChecked
        )
        self.check_completo.blockSignals(True)
        self.check_completo.setCheckState(estado)
        self.check_completo.blockSignals(False)
        self._actualizar_habilitados()
        self.pasos_cambiados.emit()

    def _actualizar_habilitados(self, *args) -> None:
        audio = self.check_audio.isChecked()
        for hijo in self._grupo_audio.findChildren(QWidget):
            if hijo is not self.check_audio:
                hijo.setEnabled(audio)
        silencios = self.check_silencios.isChecked()
        for hijo in self._grupo_silencios.findChildren(QWidget):
            if hijo is not self.check_silencios:
                hijo.setEnabled(silencios)
        if silencios:
            acelerar = self.combo_silencios.currentData() == "acelerar"
            self.spin_velocidad.setEnabled(acelerar)
        self.combo_encuadre.setEnabled(self.check_vertical.isChecked())
        self._refrescar_aviso_encuadre()

    def _refrescar_aviso_encuadre(self, *args) -> None:
        cara = (
            self.check_vertical.isChecked()
            and self.combo_encuadre.currentData() == "cara"
        )
        self.aviso_encuadre.setText(_("Más lento: analiza el vídeo.") if cara else "")

    def _actualizar_subtitulos(self, *args) -> None:
        activo = self.check_subtitulos.isChecked()
        for control in (
            self.combo_diseno, self.spin_posicion, self.slider_tamano,
            self.combo_idioma_subs, self.combo_modelo_whisper,
        ):
            control.setEnabled(activo)
        self._refrescar_aviso_whisper()

    def _actualizar_glosario(self, *args) -> None:
        self.boton_glosario.setEnabled(
            self.check_subtitulos.isChecked() or self.check_caption.isChecked()
        )

    def _emitir_cambio_subs(self, *args) -> None:
        self.opciones_subs_cambiadas.emit()

    def _refrescar_aviso_whisper(self, *args) -> None:
        if not self.check_subtitulos.isChecked():
            self.aviso_whisper.setText("")
            return
        modelo = self.combo_modelo_whisper.currentData()
        self.aviso_whisper.setText(
            "" if subtitles.modelo_en_cache(modelo, WHISPER_CACHE_DIR)
            else _("El modelo Whisper se descargará al primer uso ({tamano}).").format(
                tamano=subtitles.TAMANO_DESCARGA[modelo])
        )

    # --- selector de modelo de caption ---

    def poblar_modelos(self, modelos: list[Modelo], memoria: int,
                       seleccionado: str) -> None:
        """Rellena el desplegable con los modelos instalados.

        Los que no caben en `memoria` quedan deshabilitados con el motivo en
        el tooltip; los pesados se pueden elegir, pero con aviso. Si
        `seleccionado` no está instalado (o no hay lista), se añade marcado
        para no perder el ajuste guardado.
        """
        combo = self.combo_modelo_caption
        combo.blockSignals(True)
        combo.clear()
        self._hay_modelos = bool(modelos)
        self._modelos_pesados = {}
        self._modelos_no_caben = 0
        for modelo in modelos:
            combo.addItem(modelo.etiqueta, modelo.nombre)
            item = combo.model().item(combo.count() - 1)
            if not cabe(modelo, memoria):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(motivo_no_cabe(modelo, memoria))
                self._modelos_no_caben += 1
            elif pesado(modelo, memoria):
                motivo = motivo_pesado(modelo, memoria)
                item.setToolTip(motivo)
                self._modelos_pesados[modelo.nombre] = motivo
        if seleccionado and combo.findData(seleccionado) < 0:
            combo.insertItem(
                0, _("{modelo} (no instalado)").format(modelo=seleccionado),
                seleccionado,
            )
        combo.setCurrentIndex(max(0, combo.findData(seleccionado)))
        combo.blockSignals(False)
        if not modelos:
            self.aviso_modelos.setText(
                _(
                    "Ollama no responde: no se pueden listar los modelos. "
                    "Ábrelo y pulsa ↻."
                )
            )
        else:
            self._refrescar_aviso_modelos()

    def _refrescar_aviso_modelos(self, *args) -> None:
        if not self._hay_modelos:
            return  # el aviso de Ollama caído lo pone poblar_modelos
        avisos = []
        motivo = self._modelos_pesados.get(self.modelo_caption())
        if motivo:
            avisos.append(motivo)
        if self._modelos_no_caben:
            avisos.append(
                _("{n} modelo(s) no caben en memoria (ver tooltip).").format(
                    n=self._modelos_no_caben
                )
            )
        self.aviso_modelos.setText("\n".join(avisos))

    def modelo_caption(self) -> str:
        return str(self.combo_modelo_caption.currentData() or "")

    def _emitir_cambio_modelo(self, *args) -> None:
        modelo = self.modelo_caption()
        if modelo:
            self.modelo_caption_cambiado.emit(modelo)

    def valores(self) -> dict:
        return {
            "paso_audio": self.check_audio.isChecked(),
            "paso_silencios": self.check_silencios.isChecked(),
            "paso_vertical": self.check_vertical.isChecked(),
            "encuadre": self.combo_encuadre.currentData(),
            "tarea": self.combo_tarea.currentData(),
            "modelo": self.combo_modelo.currentText(),
            "margen": self.campo_margen.text().strip() or "0.2s",
            "umbral": self.campo_umbral.text().strip() or "4%",
            "silencios": self.combo_silencios.currentData(),
            "velocidad_silencios": self.spin_velocidad.value(),
            "subtitulos": self.check_subtitulos.isChecked(),
            "diseno": self.combo_diseno.currentData(),
            "posicion_subs": self.spin_posicion.value(),
            "tamano_subs": self.slider_tamano.value(),
            "idioma_subs": self.combo_idioma_subs.currentData(),
            "modelo_whisper": self.combo_modelo_whisper.currentData(),
            "caption_seo": self.check_caption.isChecked(),
        }

    def cargar(self, valores: dict) -> None:
        if "paso_audio" in valores or "paso_silencios" in valores:
            pasos = {
                "paso_audio": _como_bool(valores.get("paso_audio"), True),
                "paso_silencios": _como_bool(valores.get("paso_silencios"), True),
            }
        else:
            # Ajustes de una versión anterior: solo guardaban el modo.
            try:
                pasos = pasos_desde_modo(str(valores.get("modo", "completo")))
            except ValueError:
                pasos = pasos_desde_modo("completo")
        self.check_audio.setChecked(pasos["paso_audio"])
        self.check_silencios.setChecked(pasos["paso_silencios"])
        # El vertical es un paso ocasional: nunca se restaura; el encuadre sí.
        self.check_vertical.setChecked(False)
        indice = self.combo_encuadre.findData(valores.get("encuadre", "central"))
        if indice >= 0:
            self.combo_encuadre.setCurrentIndex(indice)
        tarea = valores.get("tarea", "speech_enhancement")
        indice = self.combo_tarea.findData(tarea)
        if indice >= 0:
            self.combo_tarea.setCurrentIndex(indice)
        modelo = valores.get("modelo")
        if modelo and modelo in MODELOS_POR_TAREA.get(tarea, []):
            self.combo_modelo.setCurrentText(modelo)
        if valores.get("margen"):
            self.campo_margen.setText(str(valores["margen"]))
        if valores.get("umbral"):
            self.campo_umbral.setText(str(valores["umbral"]))
        silencios = valores.get("silencios", "cortar")
        indice = self.combo_silencios.findData(silencios)
        if indice >= 0:
            self.combo_silencios.setCurrentIndex(indice)
        if valores.get("velocidad_silencios"):
            self.spin_velocidad.setValue(int(valores["velocidad_silencios"]))
        self.check_subtitulos.setChecked(
            str(valores.get("subtitulos", "")).lower() in ("true", "1")
            if not isinstance(valores.get("subtitulos"), bool)
            else valores.get("subtitulos", False)
        )
        diseno = valores.get("diseno", "reels_bold")
        indice = self.combo_diseno.findData(diseno)
        if indice >= 0:
            self.combo_diseno.setCurrentIndex(indice)
        if valores.get("posicion_subs"):
            self.spin_posicion.setValue(int(valores["posicion_subs"]))
        if valores.get("tamano_subs"):
            self.slider_tamano.setValue(int(valores["tamano_subs"]))
        idioma = valores.get("idioma_subs", "es")
        indice = self.combo_idioma_subs.findData(idioma)
        if indice >= 0:
            self.combo_idioma_subs.setCurrentIndex(indice)
        modelo = valores.get("modelo_whisper", "turbo")
        indice = self.combo_modelo_whisper.findData(modelo)
        if indice >= 0:
            self.combo_modelo_whisper.setCurrentIndex(indice)
        if "caption_seo" in valores:
            valor = valores["caption_seo"]
            self.check_caption.setChecked(
                valor if isinstance(valor, bool)
                else str(valor).lower() in ("true", "1")
            )
        self._actualizar_pasos()
        self._actualizar_subtitulos()
