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
    assert valores["modelo_whisper"] == "turbo"
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

    from videopipeline import subtitles

    monkeypatch.setattr(panel_opciones, "WHISPER_CACHE_DIR", tmp_path)
    monkeypatch.setattr(subtitles, "usa_mlx", lambda: True)
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(True)
    panel._refrescar_aviso_whisper()
    assert "1,6 GB" in panel.aviso_whisper.text()  # turbo por defecto
    (tmp_path / "models--mlx-community--whisper-large-v3-turbo").mkdir()
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


def _modelos():
    from videopipeline.ollama import Modelo
    GB = 1024 ** 3
    return [Modelo("chico:1b", 1 * GB), Modelo("grande:70b", 40 * GB),
            Modelo("medio:9b", 10 * GB)]


def test_panel_modelos_pobla_deshabilita_grandes_y_selecciona(qtbot):
    from PySide6.QtCore import Qt

    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.poblar_modelos(_modelos(), memoria=27 * 1024 ** 3, seleccionado="medio:9b")
    combo = panel.combo_modelo_caption
    assert [combo.itemData(i) for i in range(combo.count())] == [
        "chico:1b", "grande:70b", "medio:9b"
    ]
    assert combo.itemText(1).startswith("grande:70b")
    item_grande = combo.model().item(1)
    assert not (item_grande.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert "GB" in item_grande.toolTip() and "27" in item_grande.toolTip()
    assert combo.model().item(0).flags() & Qt.ItemFlag.ItemIsEnabled
    assert panel.modelo_caption() == "medio:9b"


def test_panel_modelos_sin_ollama_conserva_el_guardado(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.poblar_modelos([], memoria=27 * 1024 ** 3, seleccionado="qwen3.5:9b")
    assert panel.modelo_caption() == "qwen3.5:9b"
    assert "Ollama" in panel.aviso_modelos.text()


def test_panel_modelos_guardado_no_instalado_aparece_marcado(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.poblar_modelos(_modelos(), memoria=27 * 1024 ** 3, seleccionado="viejo:x")
    assert panel.modelo_caption() == "viejo:x"
    assert "no instalado" in panel.combo_modelo_caption.currentText()


def test_panel_modelos_cambio_emite_senal(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.poblar_modelos(_modelos(), memoria=27 * 1024 ** 3, seleccionado="chico:1b")
    with qtbot.waitSignal(panel.modelo_caption_cambiado, timeout=1000) as bloque:
        panel.combo_modelo_caption.setCurrentIndex(2)
    assert bloque.args == ["medio:9b"]
    with qtbot.waitSignal(panel.refrescar_modelos, timeout=1000):
        panel.boton_refrescar_modelos.click()


def test_panel_combos_funcionan_via_currentdata(qtbot):
    """Los combos con etiquetas traducibles guardan el valor interno en la
    `data` del ítem: los lookups deben ir por currentData(), no currentText()."""
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.combo_silencios.setCurrentIndex(
        panel.combo_silencios.findData("acelerar")
    )
    assert panel.valores()["silencios"] == "acelerar"
    panel.combo_diseno.setCurrentIndex(panel.combo_diseno.findData("caja"))
    assert panel.valores()["diseno"] == "caja"
    panel.combo_idioma_subs.setCurrentIndex(
        panel.combo_idioma_subs.findData("en")
    )
    assert panel.valores()["idioma_subs"] == "en"
    panel.combo_modelo_whisper.setCurrentIndex(
        panel.combo_modelo_whisper.findData("medium")
    )
    assert panel.valores()["modelo_whisper"] == "medium"
    panel.combo_tarea.setCurrentIndex(
        panel.combo_tarea.findData("speech_separation")
    )
    assert panel.valores()["tarea"] == "speech_separation"


def test_estado_trabajo_display_usa_traduccion(qtbot):
    """El valor mostrado en la cola pasa por _() (los valores del enum están
    marcados con N_ para su extracción, no traducidos de por sí)."""
    from PySide6.QtCore import Qt
    from app.queue_model import EstadoTrabajo, ModeloCola

    m = ModeloCola()
    m.anadir([Path("/v/a.mp4")])
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert EstadoTrabajo.ESPERA.value in texto  # español = idioma fuente


def test_combo_diseno_ofrece_todos_los_estilos(qtbot):
    from videopipeline.config import DISENOS

    panel = PanelOpciones()
    qtbot.addWidget(panel)
    datos = [panel.combo_diseno.itemData(i) for i in range(panel.combo_diseno.count())]
    assert datos == list(DISENOS)


def test_etiquetas_de_estilo_traducidas_al_ingles():
    """Cada estilo tiene traducción en el catálogo inglés (puede coincidir)."""
    import re

    from app.widgets.panel_opciones import ETIQUETA_DISENO

    po = (Path(__file__).parent.parent / "locale/en/LC_MESSAGES/tsots.po").read_text(
        encoding="utf-8")
    traducidas = dict(re.findall(r'^msgid "(.+)"\nmsgstr "(.+)"$', po, re.M))
    assert [e for e in ETIQUETA_DISENO if e not in traducidas] == []


def test_combo_whisper_ofrece_turbo_primero(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    datos = [panel.combo_modelo_whisper.itemData(i)
             for i in range(panel.combo_modelo_whisper.count())]
    assert datos[0] == "turbo"
    assert set(datos) == {"turbo", "small", "medium"}


# --- glosario de términos ----------------------------------------------------------

def test_dialogo_glosario_devuelve_texto_y_resumen(qtbot):
    from app.widgets.dialogo_glosario import DialogoGlosario

    d = DialogoGlosario("Claude Code = Cloud Code, Claus Code\nAnthropic")
    qtbot.addWidget(d)
    assert d.texto() == "Claude Code = Cloud Code, Claus Code\nAnthropic"
    assert "2" in d.resumen.text() and "2" in d.resumen.text().split("·")[1]
    d.editor.setPlainText("  TSOTS  ")
    assert d.texto() == "TSOTS"
    assert "1" in d.resumen.text()
    assert d.aviso.text() == ""


def test_dialogo_glosario_avisa_si_no_cabe_en_la_pista(qtbot):
    from app.widgets.dialogo_glosario import DialogoGlosario

    d = DialogoGlosario("\n".join(f"termino{i:03d}" for i in range(200)))
    qtbot.addWidget(d)
    assert d.aviso.text() != ""


def test_panel_boton_glosario_emite_senal(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(True)
    with qtbot.waitSignal(panel.editar_glosario, timeout=1000):
        panel.boton_glosario.click()


def test_panel_boton_glosario_activo_con_subtitulos_o_caption(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.check_subtitulos.setChecked(False)
    panel.check_caption.setChecked(False)
    assert not panel.boton_glosario.isEnabled()
    panel.check_subtitulos.setChecked(True)
    assert panel.boton_glosario.isEnabled()
    panel.check_subtitulos.setChecked(False)
    panel.check_caption.setChecked(True)
    assert panel.boton_glosario.isEnabled()


# --- cabecera ---


def test_cabecera_carga_logo(qtbot):
    from app.widgets.cabecera import LADO_LOGO, Cabecera

    cabecera = Cabecera()
    qtbot.addWidget(cabecera)
    cabecera.show()
    pixmap = cabecera.logo.pixmap()
    assert not pixmap.isNull()
    assert cabecera.logo.isVisible()
    assert cabecera.logo.size().width() == LADO_LOGO
    assert cabecera.logo.size().height() == LADO_LOGO


def test_pixmap_logo_escala_con_dpr():
    from PySide6.QtGui import QImage

    from app.main import RUTA_ICONO
    from app.widgets.cabecera import pixmap_logo

    imagen = QImage(str(RUTA_ICONO))
    pixmap = pixmap_logo(imagen, 44, 2.0)
    assert pixmap.width() == 88 and pixmap.height() == 88
    assert pixmap.devicePixelRatio() == 2.0
    assert pixmap_logo(imagen, 44, 1.0).width() == 44


def test_cabecera_muestra_nombre_y_lema(qtbot):
    from app.widgets.cabecera import Cabecera

    cabecera = Cabecera()
    qtbot.addWidget(cabecera)
    assert cabecera.titulo.text() == "The Silence of the Shorts"
    assert cabecera.lema.text() == "Edita en silencio. Crea a lo grande."


def test_cabecera_sin_logo_no_falla(qtbot, tmp_path):
    from app.widgets.cabecera import Cabecera

    cabecera = Cabecera(ruta_logo=tmp_path / "no_existe.png")
    qtbot.addWidget(cabecera)
    cabecera.show()
    assert not cabecera.logo.isVisible()
    assert cabecera.titulo.isVisible()
    assert not cabecera.grab().isNull()


def test_cabecera_sigue_la_paleta(qtbot):
    """Sin colores fijos: el título se pinta con el WindowText de la paleta,
    así el modo oscuro de macOS funciona."""
    from PySide6.QtGui import QColor, QPalette

    from app.widgets.cabecera import Cabecera

    cabecera = Cabecera()
    qtbot.addWidget(cabecera)
    assert cabecera.styleSheet() == ""
    assert all(
        not hijo.styleSheet() for hijo in (cabecera.titulo, cabecera.lema)
    )
    oscura = QPalette(cabecera.palette())
    for grupo in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        oscura.setColor(grupo, QPalette.ColorRole.Window, QColor("#1e1e1e"))
        oscura.setColor(grupo, QPalette.ColorRole.WindowText, QColor("#ffffff"))
    cabecera.setPalette(oscura)
    cabecera.titulo.setAutoFillBackground(True)
    cabecera.show()
    imagen = cabecera.titulo.grab().toImage()
    mas_clara = max(
        QColor(imagen.pixel(x, y)).lightness()
        for x in range(imagen.width())
        for y in range(imagen.height())
    )
    assert mas_clara > 200


def test_cabecera_lema_traducible(qtbot, tmp_path):
    import subprocess

    from videopipeline import i18n

    from app.widgets.cabecera import Cabecera

    carpeta = tmp_path / "en" / "LC_MESSAGES"
    carpeta.mkdir(parents=True)
    po = carpeta / "tsots.po"
    po.write_text(
        'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
        'msgid "Edita en silencio. Crea a lo grande."\n'
        'msgstr "Edit quieter. Create louder."\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["msgfmt", "-o", str(carpeta / "tsots.mo"), str(po)], check=True
    )
    i18n.instalar("en", dir_locale=tmp_path)
    cabecera = Cabecera()
    qtbot.addWidget(cabecera)
    assert cabecera.lema.text() == "Edit quieter. Create louder."
    assert cabecera.titulo.text() == "The Silence of the Shorts"
