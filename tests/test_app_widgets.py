from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from app.widgets.panel_opciones import PanelOpciones
from app.widgets.zona_drop import ZonaDrop
from videopipeline.config import PipelineConfig


def test_zona_drop_filtra_extensiones(qtbot):
    zona = ZonaDrop()
    qtbot.addWidget(zona)
    recibido = []
    zona.archivos_soltados.connect(recibido.extend)
    mime = QMimeData()
    mime.setUrls([
        QUrl.fromLocalFile("/v/bueno.MOV"),
        QUrl.fromLocalFile("/v/malo.txt"),
        QUrl.fromLocalFile("/v/otro.mp4"),
    ])
    zona._procesar_mime(mime)  # helper interno testeable
    assert recibido == [Path("/v/bueno.MOV"), Path("/v/otro.mp4")]


def test_panel_valores_defecto_construyen_config(qtbot, tmp_path):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    valores = panel.valores()
    config = PipelineConfig(video=tmp_path / "v.mp4", **valores)
    config.validar()
    assert config.modo == "completo"
    assert config.modelo == "MossFormer2_SE_48K"
    assert config.margen == "0.2s"
    assert config.umbral == "4%"


def test_panel_modelo_sigue_a_tarea(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.combo_tarea.setCurrentText("Separación de hablantes")
    assert panel.valores()["tarea"] == "speech_separation"
    assert panel.valores()["modelo"] == "MossFormer2_SS_16K"


def test_panel_deshabilita_por_modo(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.radio_solo_silencios.setChecked(True)
    assert not panel.combo_tarea.isEnabled()
    panel.radio_solo_audio.setChecked(True)
    assert panel.combo_tarea.isEnabled()
    assert not panel.campo_margen.isEnabled()


def test_panel_velocidad_solo_con_acelerar(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    assert not panel.spin_velocidad.isEnabled()
    panel.combo_silencios.setCurrentText("Acelerar")
    assert panel.spin_velocidad.isEnabled()
    assert panel.valores()["silencios"] == "acelerar"


def test_panel_aviso_checkpoint(qtbot, tmp_path, monkeypatch):
    from app.widgets import panel_opciones

    monkeypatch.setattr(panel_opciones, "CHECKPOINTS_DIR", tmp_path)
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    # Ningún checkpoint en tmp_path → aviso visible
    assert not panel.aviso_modelo.isHidden() or panel.aviso_modelo.text() != ""
    (tmp_path / "MossFormer2_SE_48K").mkdir()
    panel._refrescar_aviso_modelo()
    assert panel.aviso_modelo.text() == ""


def test_panel_cargar_restaura(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.cargar({"modo": "solo_audio", "margen": "0.5s",
                  "silencios": "acelerar", "velocidad_silencios": 8})
    valores = panel.valores()
    assert valores["modo"] == "solo_audio"
    assert valores["margen"] == "0.5s"
    assert valores["velocidad_silencios"] == 8


def test_panel_subtitulos_defecto_off_y_deshabilitado(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    valores = panel.valores()
    assert valores["subtitulos"] is False
    assert valores["diseno"] == "reels_bold"
    assert valores["posicion_subs"] == 75
    assert valores["idioma_subs"] == "es"
    assert valores["modelo_whisper"] == "small"
    assert not panel.combo_diseno.isEnabled()
    assert not panel.spin_posicion.isEnabled()


def test_panel_subtitulos_toggle_habilita(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(True)
    assert panel.combo_diseno.isEnabled()
    assert panel.spin_posicion.isEnabled()
    assert panel.valores()["subtitulos"] is True


def test_panel_subtitulos_mapeos(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(True)
    panel.combo_diseno.setCurrentText("Caja negra")
    panel.combo_idioma_subs.setCurrentText("Autodetectar")
    panel.combo_modelo_whisper.setCurrentText("medium (más preciso)")
    panel.spin_posicion.setValue(85)
    valores = panel.valores()
    assert valores["diseno"] == "caja"
    assert valores["idioma_subs"] == "auto"
    assert valores["modelo_whisper"] == "medium"
    assert valores["posicion_subs"] == 85


def test_panel_subtitulos_config_valida(qtbot, tmp_path):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(True)
    config = PipelineConfig(video=tmp_path / "v.mp4", **panel.valores())
    config.validar()


def test_panel_subtitulos_cargar_tolera_claves_ausentes(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.cargar({"modo": "completo"})  # config vieja sin claves de subs
    assert panel.valores()["subtitulos"] is False
    panel.cargar({"subtitulos": True, "diseno": "caja", "posicion_subs": 90})
    valores = panel.valores()
    assert valores["subtitulos"] is True
    assert valores["diseno"] == "caja"
    assert valores["posicion_subs"] == 90


def test_panel_aviso_whisper(qtbot, tmp_path, monkeypatch):
    from app.widgets import panel_opciones

    monkeypatch.setattr(panel_opciones, "WHISPER_CACHE_DIR", tmp_path)
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(True)
    panel._refrescar_aviso_whisper()
    assert panel.aviso_whisper.text() != ""
    (tmp_path / "models--Systran--faster-whisper-small").mkdir()
    panel._refrescar_aviso_whisper()
    assert panel.aviso_whisper.text() == ""


def test_panel_cargar_recalcula_aviso(qtbot, tmp_path, monkeypatch):
    from app.widgets import panel_opciones

    monkeypatch.setattr(panel_opciones, "WHISPER_CACHE_DIR", tmp_path)
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.cargar({"subtitulos": True, "modelo_whisper": "small"})
    assert panel.aviso_whisper.text() != ""  # sin caché → aviso visible tras cargar


def test_panel_slider_tamano(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    assert panel.slider_tamano.minimum() == 50
    assert panel.slider_tamano.maximum() == 150
    assert panel.valores()["tamano_subs"] == 100
    panel.check_subtitulos.setChecked(True)
    panel.slider_tamano.setValue(130)
    assert panel.valores()["tamano_subs"] == 130
    assert panel.etiqueta_tamano.text() == "130 %"


def test_panel_slider_tamano_cargar_y_deshabilitado(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    assert not panel.slider_tamano.isEnabled()  # toggle off
    panel.cargar({"subtitulos": True, "tamano_subs": 80})
    assert panel.valores()["tamano_subs"] == 80
    assert panel.slider_tamano.isEnabled()


def test_panel_emite_opciones_subs_cambiadas(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.opciones_subs_cambiadas, timeout=1000):
        panel.check_subtitulos.setChecked(True)
    with qtbot.waitSignal(panel.opciones_subs_cambiadas, timeout=1000):
        panel.slider_tamano.setValue(120)
    with qtbot.waitSignal(panel.opciones_subs_cambiadas, timeout=1000):
        panel.spin_posicion.setValue(80)
    with qtbot.waitSignal(panel.opciones_subs_cambiadas, timeout=1000):
        panel.combo_diseno.setCurrentText("Caja negra")


def test_dialogo_marca_devuelve_texto(qtbot):
    from app.widgets.dialogo_marca import DialogoMarca

    d = DialogoMarca("inicial")
    qtbot.addWidget(d)
    assert d.texto() == "inicial"
    d.editor.setPlainText("  Soy Alberto  ")
    assert d.texto() == "Soy Alberto"


def test_panel_caption_defecto_off_y_en_valores(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    assert panel.valores()["caption_seo"] is False
    panel.check_caption.setChecked(True)
    assert panel.valores()["caption_seo"] is True
    PipelineConfig(video=Path("/v.mp4"), **panel.valores()).validar()


def test_panel_caption_cargar_desde_qsettings(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.cargar({"caption_seo": "true"})
    assert panel.check_caption.isChecked()
    panel.cargar({"caption_seo": False})
    assert not panel.check_caption.isChecked()
    panel.cargar({})  # clave ausente → sigue como estaba
    assert not panel.check_caption.isChecked()


def test_panel_boton_marca_emite_senal(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.editar_marca, timeout=1000):
        panel.boton_marca.click()


def _caption_ejemplo():
    from videopipeline.caption import Caption
    return Caption(titulo="Título X", caption="Cuerpo\ndos líneas",
                   hashtags=["#a", "#b"], palabras_clave=["k"])


def test_panel_caption_oculto_sin_datos_y_muestra_con_datos(qtbot):
    from app.widgets.panel_caption import PanelCaption

    panel = PanelCaption()
    qtbot.addWidget(panel)
    panel.mostrar(None)
    assert panel.isHidden()
    panel.mostrar(_caption_ejemplo())
    assert not panel.isHidden()
    assert panel.etiqueta_titulo.text() == "Título X"
    assert panel.texto_caption.toPlainText() == "Cuerpo\ndos líneas"
    assert panel.etiqueta_hashtags.text() == "#a #b"


def test_panel_caption_etiquetas_no_interpretan_html(qtbot):
    from PySide6.QtCore import Qt
    from app.widgets.panel_caption import PanelCaption
    from videopipeline.caption import Caption

    panel = PanelCaption()
    qtbot.addWidget(panel)
    panel.mostrar(Caption(titulo="<b>x</b>", caption="c", hashtags=["#a"],
                          palabras_clave=["k"]))
    assert panel.etiqueta_titulo.text() == "<b>x</b>"
    assert panel.etiqueta_titulo.textFormat() == Qt.TextFormat.PlainText
    assert panel.etiqueta_hashtags.textFormat() == Qt.TextFormat.PlainText


def test_panel_caption_copia_al_portapapeles(qtbot):
    from PySide6.QtWidgets import QApplication
    from app.widgets.panel_caption import PanelCaption

    panel = PanelCaption()
    qtbot.addWidget(panel)
    panel.mostrar(_caption_ejemplo())
    portapapeles = QApplication.clipboard()
    panel.boton_copiar_titulo.click()
    assert portapapeles.text() == "Título X"
    panel.boton_copiar_caption.click()
    assert portapapeles.text() == "Cuerpo\ndos líneas"
    panel.boton_copiar_hashtags.click()
    assert portapapeles.text() == "#a #b"
    panel.boton_copiar_todo.click()
    assert portapapeles.text() == "Título X\n\nCuerpo\ndos líneas\n\n#a #b\n"


def test_panel_caption_copiar_sin_datos_no_revienta(qtbot):
    from PySide6.QtWidgets import QApplication
    from app.widgets.panel_caption import PanelCaption

    panel = PanelCaption()
    qtbot.addWidget(panel)
    QApplication.clipboard().setText("intacto")
    panel.mostrar(None)
    for boton in (panel.boton_copiar_titulo, panel.boton_copiar_caption,
                  panel.boton_copiar_hashtags, panel.boton_copiar_todo):
        boton.click()  # no debe lanzar ni tocar el portapapeles
    assert QApplication.clipboard().text() == "intacto"
