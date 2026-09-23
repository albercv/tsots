from __future__ import annotations

import sys

import pytest

import json
from pathlib import Path

from PySide6.QtCore import QSettings

from app.main import VentanaPrincipal
from app.queue_model import EstadoTrabajo
from app.settings import Ajustes


def _ventana(qtbot, tmp_path, monkeypatch) -> VentanaPrincipal:
    ajustes = Ajustes(
        QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    )
    monkeypatch.setattr("app.main._tiene_pista_audio", lambda ruta: True)
    ventana = VentanaPrincipal(ajustes=ajustes)
    qtbot.addWidget(ventana)
    return ventana


def test_anadir_videos_encola(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4", tmp_path / "b.mov"])
    assert ventana.modelo_cola.rowCount() == 2
    assert ventana.boton_procesar.isEnabled()


def test_sin_audio_no_encola(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr("app.main._tiene_pista_audio", lambda ruta: False)
    avisos = []
    monkeypatch.setattr(
        "app.main.QMessageBox.warning",
        lambda *args, **kwargs: avisos.append(args),
    )
    ventana.anadir_videos([tmp_path / "mudo.mp4"])
    assert ventana.modelo_cola.rowCount() == 0
    assert len(avisos) == 1
    assert not ventana.boton_procesar.isEnabled()


def test_procesar_construye_configs(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path / "salidas"
    ventana.anadir_videos([tmp_path / "a.mp4"])
    lanzado = {}
    monkeypatch.setattr(
        ventana.ejecutor, "iniciar", lambda trabajos: lanzado.setdefault("t", trabajos)
    )
    ventana.procesar()
    filas_configs = lanzado["t"]
    assert len(filas_configs) == 1
    fila, config_json = filas_configs[0]
    datos = json.loads(config_json)
    assert datos["video"].endswith("a.mp4")
    assert datos["salida"].endswith("salidas")
    assert datos["modo"] == "completo"
    # iniciar está mockeado, así que trabajo_iniciado no se emite todavía:
    # la fila permanece en ESPERA hasta que el ejecutor la arranca de verdad.
    assert ventana.modelo_cola.trabajo(fila).estado == EstadoTrabajo.ESPERA
    ventana.ejecutor.trabajo_iniciado.emit(fila)
    assert ventana.modelo_cola.trabajo(fila).estado == EstadoTrabajo.PROCESANDO


def test_progreso_actualiza_cola(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.ejecutor.progreso.emit(
        0, {"step": 2, "total": 4, "label": "Limpiando audio", "percent": 50.0}
    )
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.etiqueta == "Limpiando audio"
    assert trabajo.percent == 50.0


def test_trabajo_terminado_ok_y_error(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    ventana.ejecutor.trabajo_terminado.emit(0, True, "/tmp/a_limpio.mp4", "")
    ventana.ejecutor.trabajo_terminado.emit(1, False, "", "explotó")
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.HECHO
    assert ventana.modelo_cola.trabajo(0).salida == Path("/tmp/a_limpio.mp4")
    assert ventana.modelo_cola.trabajo(1).estado == EstadoTrabajo.ERROR
    assert "explotó" in ventana.modelo_cola.trabajo(1).error


def test_cancelado_limpia_temporal(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path
    ventana.anadir_videos([tmp_path / "a.mp4"])
    temporal = tmp_path / ".a_limpio_tmp.mp4"
    temporal.write_bytes(b"MEDIO")
    temporal_subs = tmp_path / ".a_limpio_subs_tmp.mp4"
    temporal_subs.write_bytes(b"MEDIO")
    ventana.ejecutor.trabajo_terminado.emit(0, False, "", "Cancelado")
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.CANCELADO
    assert not temporal.exists()
    assert not temporal_subs.exists()


def test_boton_alterna_procesar_cancelar(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lambda t: None)
    ventana.procesar()
    assert "Cancelar" in ventana.boton_procesar.text()
    ventana.ejecutor.cola_terminada.emit()
    assert "Procesar" in ventana.boton_procesar.text()


def test_quitar_y_limpiar_bloqueados_durante_proceso(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lambda t: None)
    ventana.procesar()

    # Row 0 finishes (HECHO) while row 1 stays PROCESANDO: _procesando is
    # still True because cola_terminada has not fired yet.
    ventana.ejecutor.trabajo_terminado.emit(0, True, "/tmp/x.mp4", "")
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.HECHO
    assert ventana._procesando

    ventana._limpiar_hechos()
    assert ventana.modelo_cola.rowCount() == 2

    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    ventana._quitar_seleccionado()
    assert ventana.modelo_cola.rowCount() == 2

    assert not ventana.boton_quitar.isEnabled()
    assert not ventana.boton_limpiar.isEnabled()

    ventana.ejecutor.cola_terminada.emit()

    assert ventana.boton_quitar.isEnabled()
    assert ventana.boton_limpiar.isEnabled()

    # Guard lifted: the still-HECHO row can now be cleared.
    ventana._limpiar_hechos()
    assert ventana.modelo_cola.rowCount() == 1


def test_limpiar_hechos_funciona_en_reposo(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    ventana.ejecutor.trabajo_terminado.emit(0, True, "/tmp/x.mp4", "")

    ventana._limpiar_hechos()

    assert ventana.modelo_cola.rowCount() == 1


def test_aviso_actualiza_fila(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.ejecutor.aviso.emit(0, "subs fallaron")
    assert ventana.modelo_cola.trabajo(0).aviso == "subs fallaron"


def test_seleccion_cola_alimenta_preview(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    recibido = []
    monkeypatch.setattr(
        ventana.vista_previa, "establecer_video",
        lambda ruta: recibido.append(ruta),
    )
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert recibido and recibido[-1] == tmp_path / "a.mp4"


def test_diagnostico_se_guarda_y_dialogo_lo_muestra(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    log = tmp_path / "a_x.log"
    log.write_text("log", encoding="utf-8")
    diag = {"titulo": "auto-editor no pudo escribir el vídeo",
            "causa": "porque sí", "solucion": "reencodar",
            "detalle": "Error! Could not write packet", "conocido": True,
            "paso": "Recortando silencios", "log": str(log)}
    ventana.ejecutor.diagnostico.emit(0, diag)
    ventana.ejecutor.trabajo_terminado.emit(
        0, False, "", "auto-editor no pudo escribir el vídeo\nCausa: porque sí"
    )
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.estado == EstadoTrabajo.ERROR
    assert trabajo.diagnostico == diag
    dialogo = ventana._dialogo_error(trabajo)
    assert "auto-editor no pudo escribir el vídeo" in dialogo.text()
    assert "porque sí" in dialogo.text()
    assert "reencodar" in dialogo.text()
    assert "Recortando silencios" in dialogo.text()
    assert "Could not write packet" in dialogo.detailedText()
    assert any("log" in b.text().lower() for b in dialogo.buttons())


def test_doble_clic_en_error_abre_dialogo(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.ejecutor.trabajo_terminado.emit(0, False, "", "explotó")
    mostrados = []
    monkeypatch.setattr(ventana, "_mostrar_error",
                        lambda trabajo: mostrados.append(trabajo.error))
    ventana._abrir_resultado(ventana.modelo_cola.index(0))
    assert mostrados == ["explotó"]


def _md_ejemplo(ruta: Path) -> None:
    from videopipeline.caption import Caption, escribir_md
    escribir_md(Caption(titulo="Título X", caption="Cuerpo", hashtags=["#a"],
                        palabras_clave=["k"]), ruta)


def test_seleccion_de_hecho_muestra_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    salida_a = tmp_path / "a_limpio.mp4"
    salida_a.write_bytes(b"MP4")
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(salida_a), "")
    ventana.ejecutor.trabajo_terminado.emit(1, True, str(tmp_path / "b_limpio.mp4"), "")
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert not ventana.panel_caption.isHidden()
    assert ventana.panel_caption.etiqueta_titulo.text() == "Título X"
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(1))  # sin .md
    assert ventana.panel_caption.isHidden()


def test_terminar_trabajo_seleccionado_refresca_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.panel_caption.isHidden()
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    assert not ventana.panel_caption.isHidden()


def test_editar_marca_persiste_en_ajustes(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.contexto_marca = "antes"
    visto = {}

    class DialogoFalso:
        def __init__(self, texto_inicial="", parent=None):
            visto["inicial"] = texto_inicial

        def exec(self):
            return 1  # QDialog.DialogCode.Accepted

        def texto(self):
            return "después"

    monkeypatch.setattr("app.main.DialogoMarca", DialogoFalso)
    ventana.panel.editar_marca.emit()
    assert visto["inicial"] == "antes"
    assert ventana.ajustes.contexto_marca == "después"


def test_procesar_incluye_marca_y_modelo_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.contexto_marca = "Soy Alberto"
    ventana.ajustes.modelo_caption = "qwen3.5:9b-q8_0"
    ventana.panel.check_caption.setChecked(True)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    capturado = {}
    monkeypatch.setattr(ventana.ejecutor, "iniciar",
                        lambda trabajos: capturado.setdefault("t", trabajos))
    ventana.procesar()
    config = json.loads(capturado["t"][0][1])
    assert config["caption_seo"] is True
    assert config["contexto_marca"] == "Soy Alberto"
    assert config["modelo_caption"] == "qwen3.5:9b-q8_0"


def test_ventana_cabe_en_pantallas_pequenas(qtbot, tmp_path, monkeypatch):
    """La columna derecha (opciones + preview + caption) supera los 1100 px
    apilada; la ventana no debe imponer ese mínimo: se hace scroll."""
    from videopipeline.caption import Caption

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.show()
    ventana.panel_caption.mostrar(Caption("t", "c", ["#a"], ["k"]))
    assert ventana.minimumSizeHint().height() <= 600
    assert ventana.minimumSizeHint().width() <= 700


def test_geometria_restaurada_se_limita_a_la_pantalla(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.resize(3000, 2500)
    ventana.ajustes.guardar_geometria(bytes(ventana.saveGeometry()))
    disponible = QApplication.primaryScreen().availableGeometry()
    ventana2 = _ventana(qtbot, tmp_path, monkeypatch)  # restaura la geometría
    ventana2.show()
    assert ventana2.width() <= disponible.width()
    assert ventana2.height() <= disponible.height()


def test_ventana_pobla_modelos_y_persiste_seleccion(qtbot, tmp_path, monkeypatch):
    from videopipeline.ollama import Modelo

    GB = 1024 ** 3
    llamadas = {"n": 0}

    def falso_listar(*a, **k):
        llamadas["n"] += 1
        return [Modelo("a:1", 1 * GB), Modelo("b:2", 2 * GB)]

    monkeypatch.setattr("app.main.listar_modelos", falso_listar)
    monkeypatch.setattr("app.main.memoria_para_modelos", lambda *a, **k: 27 * GB)
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    assert llamadas["n"] == 1
    assert ventana.panel.combo_modelo_caption.count() >= 2
    ventana.panel.combo_modelo_caption.setCurrentIndex(
        ventana.panel.combo_modelo_caption.findData("b:2")
    )
    assert ventana.ajustes.modelo_caption == "b:2"
    ventana.panel.boton_refrescar_modelos.click()
    assert llamadas["n"] == 2
    ventana.anadir_videos([tmp_path / "a.mp4"])
    capturado = {}
    monkeypatch.setattr(ventana.ejecutor, "iniciar",
                        lambda trabajos: capturado.setdefault("t", trabajos))
    ventana.procesar()
    assert json.loads(capturado["t"][0][1])["modelo_caption"] == "b:2"


def test_ventana_tiene_icono(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    assert not ventana.windowIcon().isNull()


def _cambiar_idioma(ventana, monkeypatch, respuesta):
    from PySide6.QtWidgets import QMessageBox

    preguntas = []

    def falsa_pregunta(*args, **kwargs):
        preguntas.append(args[2] if len(args) > 2 else kwargs.get("text", ""))
        return respuesta

    monkeypatch.setattr("app.main.QMessageBox.question", falsa_pregunta)
    relanzados = []
    monkeypatch.setattr(ventana, "_relanzar", lambda: relanzados.append(True))
    salidas = []
    monkeypatch.setattr("app.main.QApplication.quit", lambda *a: salidas.append(True))
    ventana.combo_idioma_ui.setCurrentIndex(ventana.combo_idioma_ui.findData("en"))
    return preguntas, relanzados, salidas


def test_cambiar_idioma_pregunta_y_cancelar_revierte(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    assert ventana.combo_idioma_ui.currentData() == "sistema"
    preguntas, relanzados, salidas = _cambiar_idioma(
        ventana, monkeypatch, QMessageBox.StandardButton.Cancel
    )
    assert len(preguntas) == 1 and "reinici" in preguntas[0].lower()
    assert ventana.ajustes.idioma_ui == "sistema"  # no se guarda
    assert ventana.combo_idioma_ui.currentData() == "sistema"  # combo revertido
    assert relanzados == [] and salidas == []


def test_cambiar_idioma_aceptar_guarda_cancela_y_reinicia(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana._procesando = True
    cancelados = []
    monkeypatch.setattr(ventana.ejecutor, "cancelar", lambda: cancelados.append(True))
    preguntas, relanzados, salidas = _cambiar_idioma(
        ventana, monkeypatch, QMessageBox.StandardButton.Yes
    )
    assert "en marcha" in preguntas[0].lower() or "proceso" in preguntas[0].lower()
    assert ventana.ajustes.idioma_ui == "en"
    assert cancelados == [True]
    assert relanzados == [True] and salidas == [True]
    # Tras aceptar, cerrar la ventana no vuelve a preguntar (bandera de reinicio).
    monkeypatch.setattr("app.main.QMessageBox.question",
                        lambda *a, **k: pytest.fail("no debe preguntar otra vez"))
    ventana.close()


def test_comando_relanzar_prefiere_el_lanzador_del_bundle(qtbot, tmp_path, monkeypatch):
    from app import main as modulo

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    lanzador = tmp_path / "X.app" / "Contents" / "MacOS" / "TheSilenceOfTheShorts"
    monkeypatch.setattr(modulo, "RUTA_LANZADOR", lanzador)
    assert ventana._comando_relanzar() == [sys.executable, "-m", "app"]
    lanzador.parent.mkdir(parents=True)
    lanzador.write_text("#!/bin/sh\n")
    lanzador.chmod(0o755)
    assert ventana._comando_relanzar() == [str(lanzador)]


def test_procesar_incluye_idioma_ui_en_config(qtbot, tmp_path, monkeypatch):
    from videopipeline import i18n

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    capturado = {}
    monkeypatch.setattr(
        ventana.ejecutor, "iniciar",
        lambda trabajos: capturado.setdefault("t", trabajos),
    )
    ventana.procesar()
    config = json.loads(capturado["t"][0][1])
    assert config["idioma_ui"] == i18n.idioma_actual()


def test_ventana_muestra_catalogo_ingles_instalado(qtbot, tmp_path, monkeypatch):
    """Con idioma_ui="en" guardado, la ventana instala el catálogo al abrirse
    (VentanaPrincipal.__init__ hace el mismo instalar() que main())."""
    from videopipeline import i18n
    from tests.test_i18n import _catalogo

    carpeta_locale = tmp_path / "locale"
    _catalogo(carpeta_locale, "en", {"Cola": "Queue"})
    monkeypatch.setattr(i18n, "DIR_LOCALE", carpeta_locale)
    monkeypatch.setattr("app.main._tiene_pista_audio", lambda ruta: True)
    ajustes = Ajustes(
        QSettings(str(tmp_path / "test_en.ini"), QSettings.Format.IniFormat)
    )
    ajustes.idioma_ui = "en"
    try:
        ventana = VentanaPrincipal(ajustes=ajustes)
        qtbot.addWidget(ventana)
        assert ventana.etiqueta_cola.text() == "Queue"
    finally:
        i18n.instalar("es")


def test_editar_glosario_persiste_en_ajustes(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.glosario = "antes"
    visto = {}

    class DialogoFalso:
        def __init__(self, texto_inicial="", parent=None):
            visto["inicial"] = texto_inicial

        def exec(self):
            return 1

        def texto(self):
            return "Claude Code = Cloud Code"

    monkeypatch.setattr("app.main.DialogoGlosario", DialogoFalso)
    ventana.panel.editar_glosario.emit()
    assert visto["inicial"] == "antes"
    assert ventana.ajustes.glosario == "Claude Code = Cloud Code"


def test_procesar_incluye_glosario(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.glosario = "Anthropic"
    ventana.anadir_videos([tmp_path / "a.mp4"])
    capturado = {}
    monkeypatch.setattr(ventana.ejecutor, "iniciar",
                        lambda trabajos: capturado.setdefault("t", trabajos))
    ventana.procesar()
    assert json.loads(capturado["t"][0][1])["glosario"] == "Anthropic"


def test_cabecera_encima_de_zona_drop_y_cola(qtbot, tmp_path, monkeypatch):
    """La cabecera con el logo va arriba, a todo el ancho; la zona de soltar,
    la cola y el panel de opciones quedan debajo."""
    from PySide6.QtCore import QPoint, QRect

    from app.widgets.cabecera import Cabecera

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.resize(900, 560)
    ventana.show()
    qtbot.waitExposed(ventana)
    assert isinstance(ventana.cabecera, Cabecera)
    central = ventana.centralWidget()

    def rect(widget):
        return QRect(widget.mapTo(central, QPoint(0, 0)), widget.size())

    cabecera = rect(ventana.cabecera)
    for widget in (ventana.zona_drop, ventana.vista_cola, ventana.scroll_derecha):
        assert cabecera.bottom() < rect(widget).top()
    assert cabecera.left() <= rect(ventana.zona_drop).left()
    assert cabecera.right() >= rect(ventana.scroll_derecha).right()
