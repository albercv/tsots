from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videopipeline import subtitles
from videopipeline.config import MODELOS_POR_TAREA
from videopipeline.i18n import N_, _
from videopipeline.ollama import Modelo, cabe, motivo_no_cabe

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

ETIQUETA_MODELO_WHISPER = {
    N_("turbo (recomendado)"): "turbo",
    N_("small (rápido)"): "small",
    N_("medium (más preciso)"): "medium",
}


class PanelOpciones(QWidget):
    opciones_subs_cambiadas = Signal()
    editar_marca = Signal()
    modelo_caption_cambiado = Signal(str)  # nombre del modelo elegido
    refrescar_modelos = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        grupo_modo = QGroupBox(_("Modo"))
        modo_layout = QVBoxLayout(grupo_modo)
        self.radio_completo = QRadioButton(_("Pipeline completo"))
        self.radio_solo_audio = QRadioButton(_("Solo limpiar audio"))
        self.radio_solo_silencios = QRadioButton(_("Solo cortar silencios"))
        self.radio_completo.setChecked(True)
        for radio in (
            self.radio_completo, self.radio_solo_audio, self.radio_solo_silencios
        ):
            modo_layout.addWidget(radio)
            radio.toggled.connect(self._actualizar_habilitados)
        layout.addWidget(grupo_modo)

        grupo_audio = QGroupBox(_("Limpieza de audio"))
        form_audio = QFormLayout(grupo_audio)
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
        layout.addWidget(grupo_audio)
        self._repoblar_modelos()
        self._refrescar_aviso_modelo()

        grupo_silencios = QGroupBox(_("Corte de silencios"))
        form_sil = QFormLayout(grupo_silencios)
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
        layout.addWidget(grupo_silencios)

        grupo_subs = QGroupBox(_("Subtítulos"))
        form_subs = QFormLayout(grupo_subs)
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
        form_subs.addRow(_("Modelo:"), self.combo_modelo_whisper)
        form_subs.addRow("", self.aviso_whisper)
        layout.addWidget(grupo_subs)
        self._grupo_subs = grupo_subs
        self.check_subtitulos.toggled.connect(self._actualizar_subtitulos)
        self.combo_modelo_whisper.currentIndexChanged.connect(
            self._refrescar_aviso_whisper
        )
        self._actualizar_subtitulos()

        grupo_caption = QGroupBox(_("Caption SEO"))
        caption_layout = QVBoxLayout(grupo_caption)
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
        self.combo_modelo_caption.currentIndexChanged.connect(
            self._emitir_cambio_modelo
        )
        layout.addWidget(grupo_caption)

        layout.addStretch(1)

        self._grupo_audio = grupo_audio
        self._grupo_silencios = grupo_silencios
        self._actualizar_habilitados()

        self.check_subtitulos.toggled.connect(self._emitir_cambio_subs)
        self.combo_diseno.currentIndexChanged.connect(self._emitir_cambio_subs)
        self.spin_posicion.valueChanged.connect(self._emitir_cambio_subs)
        self.slider_tamano.valueChanged.connect(self._emitir_cambio_subs)

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

    def _modo(self) -> str:
        if self.radio_solo_audio.isChecked():
            return "solo_audio"
        if self.radio_solo_silencios.isChecked():
            return "solo_silencios"
        return "completo"

    def _actualizar_habilitados(self) -> None:
        modo = self._modo()
        for hijo in self._grupo_audio.findChildren(QWidget):
            hijo.setEnabled(modo != "solo_silencios")
        for hijo in self._grupo_silencios.findChildren(QWidget):
            hijo.setEnabled(modo != "solo_audio")
        if modo != "solo_audio":
            acelerar = self.combo_silencios.currentData() == "acelerar"
            self.spin_velocidad.setEnabled(acelerar)

    def _actualizar_subtitulos(self, *args) -> None:
        activo = self.check_subtitulos.isChecked()
        for control in (
            self.combo_diseno, self.spin_posicion, self.slider_tamano,
            self.combo_idioma_subs, self.combo_modelo_whisper,
        ):
            control.setEnabled(activo)
        self._refrescar_aviso_whisper()

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
        el tooltip. Si `seleccionado` no está instalado (o no hay lista), se
        añade marcado para no perder el ajuste guardado.
        """
        combo = self.combo_modelo_caption
        combo.blockSignals(True)
        combo.clear()
        for modelo in modelos:
            combo.addItem(modelo.etiqueta, modelo.nombre)
            if not cabe(modelo, memoria):
                item = combo.model().item(combo.count() - 1)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(motivo_no_cabe(modelo, memoria))
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
            deshabilitados = sum(
                1 for i in range(combo.count())
                if not combo.model().item(i).flags() & Qt.ItemFlag.ItemIsEnabled
            )
            self.aviso_modelos.setText(
                _("{n} modelo(s) no caben en memoria (ver tooltip).").format(
                    n=deshabilitados
                )
                if deshabilitados else ""
            )

    def modelo_caption(self) -> str:
        return str(self.combo_modelo_caption.currentData() or "")

    def _emitir_cambio_modelo(self, *args) -> None:
        modelo = self.modelo_caption()
        if modelo:
            self.modelo_caption_cambiado.emit(modelo)

    def valores(self) -> dict:
        return {
            "modo": self._modo(),
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
        modo = valores.get("modo", "completo")
        {"completo": self.radio_completo,
         "solo_audio": self.radio_solo_audio,
         "solo_silencios": self.radio_solo_silencios}[modo].setChecked(True)
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
        self._actualizar_habilitados()
        self._actualizar_subtitulos()
