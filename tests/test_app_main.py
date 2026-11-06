from __future__ import annotations

import sys

import pytest

import json
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from app.main import VentanaPrincipal
from app.queue_model import EstadoTrabajo
from app.settings import Ajustes
from videopipeline import shorts
from videopipeline.caption import leer_md
from videopipeline.config import PipelineConfig
from videopipeline.ficha import (
    BASE, CAPTION, VERTICAL, Artefacto, Huella, cargar, guardar, ocupa,
    olvidar, reconocer,
)
from videopipeline.reproceso_plan import (
    Decisiones, ajustes_audio, ajustes_silencios,
)


def _videos(tmp_path, *nombres) -> list[Path]:
    """Vídeos de mentira en tmp_path: la ficha necesita que existan."""
    rutas = [tmp_path / nombre for nombre in nombres]
    for ruta in rutas:
        ruta.write_bytes(b"VIDEO")
    return rutas


def _ventana(qtbot, tmp_path, monkeypatch) -> VentanaPrincipal:
    # Las fichas de los tests nunca van al proyecto.
    monkeypatch.setattr("videopipeline.ficha.DIR_FICHAS", tmp_path / "fichas")
    ajustes = Ajustes(
        QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    )
    monkeypatch.setattr("app.main._tiene_pista_audio", lambda ruta: True)
    ventana = VentanaPrincipal(ajustes=ajustes)
    qtbot.addWidget(ventana)
    return ventana


def test_anadir_videos_encola(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mov"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    assert (datos["paso_audio"], datos["paso_silencios"]) == (True, True)
    assert "modo" not in datos
    # iniciar está mockeado, así que trabajo_iniciado no se emite todavía:
    # la fila permanece en ESPERA hasta que el ejecutor la arranca de verdad.
    assert ventana.modelo_cola.trabajo(fila).estado == EstadoTrabajo.ESPERA
    ventana.ejecutor.trabajo_iniciado.emit(fila)
    assert ventana.modelo_cola.trabajo(fila).estado == EstadoTrabajo.PROCESANDO


def test_progreso_actualiza_cola(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.ejecutor.progreso.emit(
        0, {"step": 2, "total": 4, "label": "Limpiando audio", "percent": 50.0}
    )
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.etiqueta == "Limpiando audio"
    assert trabajo.percent == 50.0


def test_trabajo_terminado_ok_y_error(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    ventana.ejecutor.trabajo_terminado.emit(0, True, "/tmp/a_limpio.mp4", "")
    ventana.ejecutor.trabajo_terminado.emit(1, False, "", "explotó")
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.HECHO
    assert ventana.modelo_cola.trabajo(0).salida == Path("/tmp/a_limpio.mp4")
    assert ventana.modelo_cola.trabajo(1).estado == EstadoTrabajo.ERROR
    assert "explotó" in ventana.modelo_cola.trabajo(1).error


def test_cancelado_limpia_temporal(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lambda t: None)
    ventana.procesar()
    assert "Cancelar" in ventana.boton_procesar.text()
    ventana.ejecutor.cola_terminada.emit()
    assert "Procesar" in ventana.boton_procesar.text()


def test_quitar_y_limpiar_bloqueados_durante_proceso(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
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
    ventana._reprocesar_seleccionado()
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.HECHO

    assert not ventana.boton_quitar.isEnabled()
    assert not ventana.boton_limpiar.isEnabled()
    assert not ventana.boton_reprocesar.isEnabled()
    assert not ventana.boton_olvidar.isEnabled()

    ventana.ejecutor.cola_terminada.emit()

    assert ventana.boton_quitar.isEnabled()
    assert ventana.boton_limpiar.isEnabled()
    assert ventana.boton_reprocesar.isEnabled()
    assert ventana.boton_olvidar.isEnabled()

    # Guard lifted: the still-HECHO row can now be cleared.
    ventana._limpiar_hechos()
    assert ventana.modelo_cola.rowCount() == 1


def test_limpiar_hechos_funciona_en_reposo(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    ventana.ejecutor.trabajo_terminado.emit(0, True, "/tmp/x.mp4", "")

    ventana._limpiar_hechos()

    assert ventana.modelo_cola.rowCount() == 1


def test_aviso_actualiza_fila(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.ejecutor.aviso.emit(0, "subs fallaron")
    assert ventana.modelo_cola.trabajo(0).aviso == "subs fallaron"


def test_seleccion_cola_alimenta_preview(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    recibido = []
    monkeypatch.setattr(
        ventana.vista_previa, "establecer_video",
        lambda ruta: recibido.append(ruta),
    )
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert recibido and recibido[-1] == tmp_path / "a.mp4"


def test_diagnostico_se_guarda_y_dialogo_lo_muestra(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    salida_a = tmp_path / "a_limpio.mp4"
    salida_a.write_bytes(b"MP4")
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(salida_a), "")
    ventana.ejecutor.trabajo_terminado.emit(1, True, str(tmp_path / "b_limpio.mp4"), "")
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.panel_caption.caption is not None
    assert ventana.panel_caption.etiqueta_vacia.isHidden()
    assert ventana.panel_caption.etiqueta_titulo.text() == "Título X"
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(1))  # sin .md
    assert ventana.panel_caption.caption is None
    assert not ventana.panel_caption.etiqueta_vacia.isHidden()


def test_terminar_trabajo_seleccionado_refresca_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.panel_caption.caption is None
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    assert ventana.panel_caption.caption is not None
    assert ventana.panel_caption.etiqueta_vacia.isHidden()


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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
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


class _DialogoFalso:
    """Sustituye a DialogoPublicar / DialogoRedes y registra con qué se abrió."""

    abiertos: list = []

    def __init__(self, *args, parent=None, **kwargs):
        type(self).abiertos.append(args)
        self.configurar_redes = type("S", (), {"connect": lambda s, f: None})()

    publicando = False

    def exec(self):
        return 0

    def deleteLater(self):
        pass


def _hecho_con_caption(ventana, tmp_path):
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    salida = tmp_path / "a_limpio.mp4"
    salida.write_bytes(b"MP4")
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(salida), "")
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    return salida


def test_boton_publicar_activo_con_caption_del_video_terminado(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    salida = _hecho_con_caption(ventana, tmp_path)
    assert ventana.panel_caption.boton_publicar.isEnabled()
    # Redes es configuración de la app, no del vídeo: no vive en este panel.
    assert not hasattr(ventana.panel_caption, "boton_redes")
    assert ventana.panel_caption.video == salida
    ventana.panel_caption.mostrar(None)
    assert not ventana.panel_caption.boton_publicar.isEnabled()


def test_publicar_abre_dialogo_con_video_y_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    salida = _hecho_con_caption(ventana, tmp_path)

    class Falso(_DialogoFalso):
        abiertos: list = []

    monkeypatch.setattr("app.main.DialogoPublicar", Falso)
    ventana.panel_caption.boton_publicar.click()
    [(video, caption, ajustes)] = Falso.abiertos
    assert video == salida
    assert caption.titulo == "Título X"
    assert ajustes is ventana.ajustes


def test_publicar_sin_video_en_disco_avisa(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    salida = _hecho_con_caption(ventana, tmp_path)
    salida.unlink()
    avisos = []
    monkeypatch.setattr("app.main.QMessageBox.warning", lambda *a, **k: avisos.append(a))
    monkeypatch.setattr("app.main.DialogoPublicar",
                        lambda *a, **k: pytest.fail("no debe abrir el diálogo"))
    ventana.panel_caption.boton_publicar.click()
    assert len(avisos) == 1


def test_publicar_sin_caption_avisa(qtbot, tmp_path, monkeypatch):
    """Si la señal llega sin vídeo o sin caption, se dice (no vuelve en silencio)."""
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    avisos = []
    monkeypatch.setattr("app.main.QMessageBox.warning", lambda *a, **k: avisos.append(a))
    monkeypatch.setattr("app.main.DialogoPublicar",
                        lambda *a, **k: pytest.fail("no debe abrir el diálogo"))
    ventana._publicar()
    assert len(avisos) == 1 and "caption" in avisos[0][2]


def test_no_sale_mientras_se_publica(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    avisos = []
    monkeypatch.setattr("app.main.QMessageBox.information", lambda *a, **k: avisos.append(a))
    monkeypatch.setattr("app.main.dialogo_publicar.hilos_vivos", lambda: 1)
    ventana.show()
    ventana.close()
    assert ventana.isVisible() and len(avisos) == 1
    monkeypatch.setattr("app.main.dialogo_publicar.hilos_vivos", lambda: 0)
    ventana.close()
    assert not ventana.isVisible()


def _layout_de(layout, widget):
    """El layout (anidado o no) que contiene directamente a `widget`."""
    if layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        hijo = layout.itemAt(i).layout()
        if hijo is not None and (encontrado := _layout_de(hijo, widget)):
            return encontrado
    return None


def test_boton_redes_visible_sin_videos_junto_al_idioma(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.show()
    assert ventana.boton_redes.isVisible()
    assert ventana.boton_redes.isEnabled()
    fila = _layout_de(ventana.centralWidget().layout(), ventana.combo_idioma_ui)
    assert fila is not None
    assert fila.indexOf(ventana.boton_redes) == fila.indexOf(ventana.combo_idioma_ui) + 1


def test_boton_redes_abre_configuracion(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)

    class Falso(_DialogoFalso):
        abiertos: list = []

    monkeypatch.setattr("app.main.DialogoRedes", Falso)
    ventana.boton_redes.click()
    assert Falso.abiertos == [(ventana.ajustes,)]


# --- pestañas fijas: previsualización y caption ---


def _es_descendiente(widget, ancestro) -> bool:
    padre = widget.parentWidget()
    while padre is not None:
        if padre is ancestro:
            return True
        padre = padre.parentWidget()
    return False


def test_pestanas_fijas_fuera_del_scroll(qtbot, tmp_path, monkeypatch):
    """Solo las secciones de opciones hacen scroll; la previsualización y el
    caption quedan debajo, siempre a la vista."""
    from PySide6.QtCore import QPoint, QRect

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.resize(700, 600)
    ventana.show()
    qtbot.waitExposed(ventana)
    assert _es_descendiente(ventana.panel, ventana.scroll_derecha)
    for widget in (ventana.pestanas, ventana.vista_previa, ventana.panel_caption):
        assert not _es_descendiente(widget, ventana.scroll_derecha)
    assert _es_descendiente(ventana.vista_previa, ventana.pestanas)
    assert _es_descendiente(ventana.panel_caption, ventana.pestanas)
    central = ventana.centralWidget()

    def rect(widget):
        return QRect(widget.mapTo(central, QPoint(0, 0)), widget.size())

    assert rect(ventana.scroll_derecha).bottom() < rect(ventana.pestanas).top()
    assert ventana.pestanas.isVisible()
    # A 700 × 600 las secciones no caben: hacen scroll, las pestañas no.
    ventana.panel.abrir_seccion("subtitulos")
    qtbot.wait(20)
    assert ventana.scroll_derecha.verticalScrollBar().maximum() > 0
    visible = rect(ventana.pestanas)
    assert visible.bottom() <= central.height()
    assert ventana.vista_previa.etiqueta.height() >= 180


def test_pestanas_siempre_presentes_con_marcador(qtbot, tmp_path, monkeypatch):
    from videopipeline.caption import Caption

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.show()
    qtbot.waitExposed(ventana)
    pestanas = ventana.pestanas
    assert pestanas.count() == 2
    assert [pestanas.tabText(i) for i in range(2)] == ["Previsualización", "Caption"]
    assert pestanas.widget(0) is ventana.vista_previa
    assert pestanas.widget(1) is ventana.panel_caption
    assert pestanas.currentWidget() is ventana.vista_previa
    assert "Selecciona un vídeo" in ventana.vista_previa.etiqueta.text()
    # Sin caption: la pestaña existe y enseña un marcador, no se oculta.
    pestanas.setCurrentWidget(ventana.panel_caption)
    assert ventana.panel_caption.isVisible()
    assert ventana.panel_caption.etiqueta_vacia.isVisible()
    assert ventana.panel_caption.etiqueta_vacia.text()
    alto_vacio = pestanas.height()
    ventana.panel_caption.mostrar(Caption("t", "c", ["#a"], ["k"]))
    qtbot.wait(20)
    assert not ventana.panel_caption.etiqueta_vacia.isVisible()
    assert ventana.panel_caption.etiqueta_titulo.isVisible()
    # El hueco no cambia con o sin contenido, ni con la otra pestaña.
    assert pestanas.height() == alto_vacio
    pestanas.setCurrentWidget(ventana.vista_previa)
    qtbot.wait(20)
    assert pestanas.height() == alto_vacio


def test_seleccion_cambia_de_pestana_segun_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    salida_a = tmp_path / "a_limpio.mp4"
    salida_a.write_bytes(b"MP4")
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(salida_a), "")
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.pestanas.currentWidget() is ventana.panel_caption
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(1))  # pendiente
    assert ventana.pestanas.currentWidget() is ventana.vista_previa


def test_terminar_con_caption_muestra_pestana_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.pestanas.currentWidget() is ventana.vista_previa
    # Termina otro vídeo (no el seleccionado): no cambia nada.
    _md_ejemplo(tmp_path / "b_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(1, True, str(tmp_path / "b_limpio.mp4"), "")
    assert ventana.pestanas.currentWidget() is ventana.vista_previa
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    assert ventana.pestanas.currentWidget() is ventana.panel_caption


def test_opciones_subs_vuelven_a_previsualizacion(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.pestanas.setCurrentWidget(ventana.panel_caption)
    ventana.panel.check_subtitulos.setChecked(True)
    assert ventana.pestanas.currentWidget() is ventana.vista_previa
    ventana.pestanas.setCurrentWidget(ventana.panel_caption)
    ventana.panel.slider_tamano.setValue(120)
    assert ventana.pestanas.currentWidget() is ventana.vista_previa


def test_audio_abierto_al_arrancar_en_la_ventana(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    assert ventana.panel.seccion_abierta() == "audio"


def test_abrir_seccion_la_desplaza_a_la_vista(qtbot, tmp_path, monkeypatch):
    """En ventanas bajas, la sección que se abre queda a la vista."""
    from PySide6.QtCore import Qt

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.resize(700, 600)
    ventana.show()
    qtbot.waitExposed(ventana)
    scroll = ventana.scroll_derecha
    for clave in ("caption", "subtitulos", "audio", "vertical"):
        seccion = ventana.panel.secciones[clave]
        qtbot.mouseClick(seccion.cabecera, Qt.MouseButton.LeftButton)
        barra = scroll.verticalScrollBar()

        def a_la_vista():
            arriba = seccion.y() - barra.value()
            visible = scroll.viewport().height()
            assert arriba >= 0
            # Entera si cabe; si no, desde su cabecera.
            if seccion.height() <= visible:
                assert arriba + seccion.height() <= visible
            else:
                assert arriba == 0

        qtbot.waitUntil(a_la_vista, timeout=1000)


def test_procesar_deshabilitado_sin_pasos(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    assert ventana.boton_procesar.isEnabled()
    ventana.panel.check_audio.setChecked(False)
    ventana.panel.check_silencios.setChecked(False)
    assert not ventana.boton_procesar.isEnabled()
    assert ventana.boton_procesar.toolTip() != ""
    ventana.panel.check_vertical.setChecked(True)
    assert ventana.boton_procesar.isEnabled()


def test_salida_vertical_actualiza_fila(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.ejecutor.salida_vertical.emit(0, str(tmp_path / "a_limpio_vertical.mp4"))
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    assert ventana.modelo_cola.trabajo(0).salida_vertical == (
        tmp_path / "a_limpio_vertical.mp4")


def test_cancelado_limpia_temporales_vertical(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    horizontal = tmp_path / "a_limpio.mp4"
    horizontal.write_bytes(b"OK")
    temporales = [tmp_path / ".a_limpio_vertical_tmp.mp4",
                  tmp_path / ".a_vertical_tmp.mp4",
                  tmp_path / ".a_vertical_subs_tmp.mp4"]
    for temporal in temporales:
        temporal.write_bytes(b"MEDIO")
    ventana.ejecutor.trabajo_terminado.emit(0, False, "", "Cancelado")
    assert horizontal.exists()
    assert not any(t.exists() for t in temporales)


def test_procesar_guarda_modo_equivalente(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    # Al cerrar con _procesando=True se abre un diálogo modal: responderlo.
    monkeypatch.setattr("app.main.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lambda trabajos: None)
    ventana.panel.check_audio.setChecked(False)  # solo silencios
    ventana.procesar()
    guardado = ventana.ajustes.cargar_panel()
    assert guardado["modo"] == "solo_silencios"
    assert str(guardado["paso_audio"]).lower() in ("false", "0")


@pytest.fixture
def traductores_qt(qapp):
    """Quita los traductores de Qt que instale el test, para no cambiar los
    botones de los demás."""
    from PySide6.QtCore import QTranslator

    antes = set(qapp.findChildren(QTranslator))
    yield
    for traductor in set(qapp.findChildren(QTranslator)) - antes:
        qapp.removeTranslator(traductor)
        traductor.setParent(None)


def test_la_aplicacion_lleva_el_logo(qapp, traductores_qt):
    """En macOS el icono de la aplicación es el de los avisos nativos y el
    del Dock: sin él sale el de Python al arrancar sin el bundle .app."""
    from PySide6.QtGui import QIcon

    from app.main import preparar_aplicacion

    qapp.setWindowIcon(QIcon())
    preparar_aplicacion(qapp)
    assert not qapp.windowIcon().pixmap(64, 64).isNull()


@pytest.mark.parametrize("idioma, si, cancelar", [("es", "&Sí", "Cancelar"),
                                                  ("en", "&Yes", "Cancel")])
def test_botones_de_qt_en_el_idioma_de_la_interfaz(qapp, traductores_qt, idioma, si, cancelar):
    from videopipeline import i18n

    from app.main import preparar_aplicacion

    i18n.instalar(idioma)
    preparar_aplicacion(qapp)
    caja = QMessageBox()
    caja.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    assert caja.button(QMessageBox.StandardButton.Yes).text() == si
    assert caja.button(QMessageBox.StandardButton.Cancel).text() == cancelar


# --- fichas: reconocer, volver a procesar, olvidar, caption y Publicar ---


def _ficha_hecha(tmp_path, con_caption=True):
    """La ficha de a.mp4 ya procesado: con su final y, si se pide, el caption
    en la ficha pero sin `.md` junto al final."""
    [original] = _videos(tmp_path, "a.mp4")
    ficha, _aviso = reconocer(original, tmp_path / "salidas")
    final = tmp_path / "salidas" / "a_limpio.mp4"
    final.parent.mkdir()
    final.write_bytes(b"FINAL")
    ficha.final = Huella.de(final)
    if con_caption:
        _md_ejemplo(ficha.ruta("caption.md"))
        ficha.artefactos[CAPTION] = Artefacto("k", "caption.md")
    guardar(ficha)
    return ficha


def _respondiendo(monkeypatch, respuesta):
    """Sustituye QMessageBox.question; devuelve las preguntas hechas."""
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args)
        return respuesta

    monkeypatch.setattr("app.main.QMessageBox.question", pregunta)
    return preguntas


def _capturando(monkeypatch, estatico):
    """Sustituye un QMessageBox estático; devuelve los argumentos recibidos."""
    recibidos = []
    monkeypatch.setattr(f"app.main.QMessageBox.{estatico}",
                        lambda *args, **kwargs: recibidos.append(args))
    return recibidos


def test_anadir_dos_veces_el_mismo_video_no_duplica(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    [video] = _videos(tmp_path, "a.mp4")
    ventana.anadir_videos([video])
    ventana.anadir_videos([video])
    assert ventana.modelo_cola.rowCount() == 1
    ficha_id = ventana.modelo_cola.trabajo(0).ficha_id
    assert ficha_id is not None and cargar(ficha_id) is not None
    # Terminado, arrastrarlo otra vez lo vuelve a poner en espera.
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    ventana.anadir_videos([video])
    assert ventana.modelo_cola.rowCount() == 1
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.ESPERA


def test_anadir_salida_reconoce_su_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.anadir_videos([ficha.final.ruta])
    assert ventana.modelo_cola.rowCount() == 1
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.ficha_id == ficha.id
    assert trabajo.resumen == "✓ caption"
    assert trabajo.ocupa == ocupa(ficha) > 0
    # El original y la salida son el mismo vídeo: sigue habiendo una fila.
    ventana.anadir_videos([tmp_path / "a.mp4", ficha.final.ruta])
    assert ventana.modelo_cola.rowCount() == 1


def test_anadir_sin_poder_reconocer_salta_ese_archivo(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)

    def reconocer_roto(ruta, carpeta):
        if ruta.name == "mala.mp4":
            raise OSError("disco roto")
        return reconocer(ruta, carpeta)

    monkeypatch.setattr("app.main.reconocer", reconocer_roto)
    avisos = _capturando(monkeypatch, "warning")
    ventana.anadir_videos(_videos(tmp_path, "mala.mp4", "buena.mp4"))
    nombres = [ventana.modelo_cola.trabajo(f).ruta.name
               for f in range(ventana.modelo_cola.rowCount())]
    assert nombres == ["buena.mp4"]
    [(_padre, _titulo, texto)] = avisos
    assert "mala.mp4" in texto and "disco roto" in texto


def test_anadir_videos_editados_avisa_junto_y_no_duplica(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    a, b = _videos(tmp_path, "a.mp4", "b.mp4")
    ventana.anadir_videos([a, b])
    antes = [ventana.modelo_cola.trabajo(f).ficha_id for f in (0, 1)]
    a.write_bytes(b"EDITADO A")
    b.write_bytes(b"EDITADO B, MAS LARGO")
    informaciones = _capturando(monkeypatch, "information")
    ventana.anadir_videos([a, b])
    [(_padre, _titulo, texto)] = informaciones  # un solo aviso con los dos
    assert "a.mp4" in texto and "b.mp4" in texto
    assert ventana.modelo_cola.rowCount() == 2
    # Un original editado sigue en su ficha: no se borra ni se duplica.
    despues = [ventana.modelo_cola.trabajo(f).ficha_id for f in (0, 1)]
    assert despues == antes
    assert all(cargar(ficha_id) is not None for ficha_id in despues)


def test_volver_a_procesar_pone_en_espera(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    ventana.ejecutor.trabajo_terminado.emit(1, False, "", "explotó")
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    ventana.boton_reprocesar.click()
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.ESPERA
    assert ventana.modelo_cola.trabajo(1).estado == EstadoTrabajo.ERROR  # no estaba seleccionada


def test_olvidar_borra_datos_tras_confirmar(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ficha.ruta("audio.flac").write_bytes(b"x" * 2_000_000)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.modelo_cola.trabajo(0).ocupa > 2_000_000
    preguntas = _respondiendo(monkeypatch, QMessageBox.StandardButton.Yes)
    ventana.boton_olvidar.click()
    [(_padre, _titulo, texto, _botones, por_defecto)] = preguntas
    assert '"a.mp4"' in texto and "2 MB" in texto and "no se tocan" in texto
    assert por_defecto == QMessageBox.StandardButton.No
    assert not ficha.carpeta.exists()
    assert ficha.final.ruta.is_file()  # las salidas no se tocan
    trabajo = ventana.modelo_cola.trabajo(0)
    assert (trabajo.ficha_id, trabajo.resumen, trabajo.ocupa) == (None, "", 0)


def test_olvidar_cancelado_no_borra(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    _respondiendo(monkeypatch, QMessageBox.StandardButton.No)
    ventana.boton_olvidar.click()
    assert ficha.carpeta.exists()
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.ficha_id == ficha.id and trabajo.ocupa > 0


@pytest.mark.parametrize("es_el_original", [True, False],
                         ids=["sin_original", "con_original_adoptado"])
def test_olvidar_avisa_si_la_ficha_guarda_una_version_anterior(
        qtbot, tmp_path, monkeypatch, es_el_original):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    antiguo = ficha.ruta("original.mov")  # una versión anterior movida a la ficha
    antiguo.write_bytes(b"VIEJO")
    if es_el_original:
        ficha.original = Huella.de(antiguo)
    guardar(ficha)  # si no, el original verdadero se adoptó después
    ventana.anadir_videos([ficha.final.ruta])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    preguntas = _respondiendo(monkeypatch, QMessageBox.StandardButton.Yes)
    ventana.boton_olvidar.click()
    assert "original.mov" in preguntas[0][2]
    assert not antiguo.exists()


def test_olvidar_y_arrastrar_otra_vez_no_duplica_la_fila(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    [video] = _videos(tmp_path, "a.mp4")
    ventana.anadir_videos([video])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    _respondiendo(monkeypatch, QMessageBox.StandardButton.Yes)
    ventana.boton_olvidar.click()
    assert ventana.modelo_cola.trabajo(0).ficha_id is None
    ventana.anadir_videos([video])
    assert ventana.modelo_cola.rowCount() == 1
    assert ventana.modelo_cola.trabajo(0).ficha_id is not None


def test_publicar_disponible_con_caption_en_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    md = ficha.final.ruta.with_suffix(".md")
    assert not md.exists()
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.ESPERA
    assert ventana.panel_caption.caption.titulo == "Título X"
    assert ventana.panel_caption.video == ficha.final.ruta
    assert ventana.panel_caption.boton_publicar.isEnabled()
    assert ventana.pestanas.currentWidget() is ventana.panel_caption
    assert leer_md(md).titulo == "Título X"  # se vuelve a escribir junto al final

    class Falso(_DialogoFalso):
        abiertos: list = []

    monkeypatch.setattr("app.main.DialogoPublicar", Falso)
    ventana.panel_caption.boton_publicar.click()
    [(video, caption, _ajustes)] = Falso.abiertos
    assert video == ficha.final.ruta and caption.titulo == "Título X"


def test_caption_de_la_ficha_no_pisa_el_md_existente(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    md = ficha.final.ruta.with_suffix(".md")
    md.write_text("editado a mano", encoding="utf-8")
    ventana.anadir_videos([tmp_path / "a.mp4"])
    assert ventana._caption_de(ventana.modelo_cola.trabajo(0)).titulo == "Título X"
    assert md.read_text(encoding="utf-8") == "editado a mano"


def test_procesando_no_muestra_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.ejecutor.trabajo_iniciado.emit(0)
    assert ventana._caption_de(ventana.modelo_cola.trabajo(0)) is None


def test_terminar_trabajo_recarga_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    [video] = _videos(tmp_path, "a.mp4")
    ventana.anadir_videos([video])
    trabajo = ventana.modelo_cola.trabajo(0)
    assert (trabajo.resumen, trabajo.salida_vertical) == ("", None)
    # Lo que la pasada deja en la ficha.
    ficha = cargar(trabajo.ficha_id)
    salidas = tmp_path / "salidas"
    salidas.mkdir()
    final, vertical = salidas / "a_limpio.mp4", salidas / "a_limpio_vertical.mp4"
    final.write_bytes(b"FINAL")
    vertical.write_bytes(b"VERTICAL")
    ficha.final, ficha.vertical = Huella.de(final), Huella.de(vertical)
    ficha.artefactos[CAPTION] = Artefacto("k", "caption.md")
    ficha.artefactos[VERTICAL] = Artefacto("k", None)
    guardar(ficha)
    ventana.ejecutor.trabajo_terminado.emit(0, True, "/otra/ruta.mp4", "")
    assert trabajo.estado == EstadoTrabajo.HECHO
    assert trabajo.salida == ficha.final.ruta
    assert trabajo.salida_vertical == ficha.vertical.ruta
    assert trabajo.resumen == "✓ caption · vertical"
    assert trabajo.ocupa == ocupa(ficha) > 0


def test_cancelar_limpia_temporales_de_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    parcial = ficha.carpeta / "tmp" / "parcial.wav"
    parcial.parent.mkdir()
    parcial.write_bytes(b"MEDIO")
    # La carpeta de salida es la de la ficha, no la de los ajustes (sin fijar).
    temporal = ficha.carpeta_salida / ".a_limpio_tmp.mp4"
    temporal.write_bytes(b"MEDIO")
    ventana.ejecutor.trabajo_terminado.emit(0, False, "", "Cancelado")
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.CANCELADO
    assert not parcial.parent.exists()
    assert not temporal.exists()
    assert ficha.final.ruta.is_file() and cargar(ficha.id) is not None


# --- procesar: avisos de lo que ya está hecho y «solo caption» ---


def _solo_caption(ventana):
    ventana.panel.check_audio.setChecked(False)
    ventana.panel.check_silencios.setChecked(False)
    ventana.panel.check_caption.setChecked(True)


def _con_audio_y_silencios(ventana, tmp_path, con_caption=False):
    """a.mp4 procesado: audio y silencios hechos con los ajustes del panel."""
    ficha = _ficha_hecha(tmp_path, con_caption=con_caption)
    config = PipelineConfig(video=ficha.original.ruta, **ventana.panel.valores())
    ficha.artefactos[BASE] = Artefacto("k", None, {
        "audio": ajustes_audio(config),
        "silencios": ajustes_silencios(config)}, "linea")
    guardar(ficha)
    return ficha


def _preguntando(monkeypatch, respuesta):
    """Sustituye el diálogo; devuelve las (consultas, hay_vertical) recibidas.
    `respuesta` es None (cancelar) o una función de las consultas."""
    llamadas = []

    def preguntar(padre, consultas, hay_vertical):
        llamadas.append((consultas, hay_vertical))
        return None if respuesta is None else respuesta(consultas)

    monkeypatch.setattr("app.main.preguntar_reproceso", preguntar)
    return llamadas


def _mantener(consultas):
    return {ficha_id: Decisiones() for ficha_id in consultas}


def _sin_preguntar(monkeypatch):
    def no_debe_preguntar(*args):
        raise AssertionError("no hay nada que preguntar")

    monkeypatch.setattr("app.main.preguntar_reproceso", no_debe_preguntar)


def _lanzando(ventana, monkeypatch):
    """Sustituye al ejecutor; devuelve los (fila, json) lanzados."""
    lanzados = []
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lanzados.extend)
    return lanzados


def test_procesar_pregunta_si_ya_tiene_pasos(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _con_audio_y_silencios(ventana, tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    llamadas = _preguntando(monkeypatch, lambda consultas: {
        ficha.id: Decisiones(frozenset({"audio"}))})
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    [(consultas, hay_vertical)] = llamadas
    nombre, lista = consultas[ficha.id]
    assert nombre == "a.mp4"
    assert [(c.paso, c.tipo) for c in lista] == [
        ("audio", "hecho"), ("silencios", "hecho")]
    assert hay_vertical == set()
    [(fila, texto)] = lanzados  # la decisión llega al runner
    assert json.loads(texto)["reproceso"] == {
        "ficha": ficha.id, "rehacer": ["audio"], "regenerar_vertical": False}
    assert ventana._procesando


def test_procesar_ofrece_regenerar_el_vertical_si_puede_cambiar(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path, con_caption=False)
    vertical = ficha.final.ruta.with_name("a_limpio_vertical.mp4")
    vertical.write_bytes(b"VERTICAL")
    ficha.vertical = Huella.de(vertical)  # sin artefacto: no hay nada que preguntar
    guardar(ficha)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    llamadas = _preguntando(monkeypatch, lambda c: {
        ficha.id: Decisiones(regenerar_vertical=True)})
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()  # audio y silencios: el vertical podría quedar viejo
    [(consultas, hay_vertical)] = llamadas
    assert consultas == {ficha.id: ("a.mp4", [])} and hay_vertical == {ficha.id}
    assert json.loads(lanzados[0][1])["reproceso"]["regenerar_vertical"] is True
    # Con solo caption el vertical no cambia: ni se pregunta.
    _solo_caption(ventana)
    _sin_preguntar(monkeypatch)
    ventana.procesar()


def test_procesar_cancelado_no_lanza(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    _con_audio_y_silencios(ventana, tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _preguntando(monkeypatch, None)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert lanzados == [] and not ventana._procesando
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.ESPERA
    assert "Procesar" in ventana.boton_procesar.text()


def test_procesar_plan_vacio_avisa_y_no_lanza(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha_a = _ficha_hecha(tmp_path)  # caption hecho y con vídeo final
    [b] = _videos(tmp_path, "b.mp4")
    ficha_b, _aviso = reconocer(b, tmp_path / "salidas")  # caption sin final
    _md_ejemplo(ficha_b.ruta("caption.md"))
    ficha_b.artefactos[CAPTION] = Artefacto("k", "caption.md")
    guardar(ficha_b)
    ventana.anadir_videos([tmp_path / "a.mp4", b])
    _solo_caption(ventana)
    _preguntando(monkeypatch, _mantener)  # Mantener: no queda nada que hacer
    informaciones = _capturando(monkeypatch, "information")
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert lanzados == [] and not ventana._procesando
    [(_padre, _titulo, texto)] = informaciones  # un solo aviso
    assert texto == "Nada que hacer en: a.mp4, b.mp4"
    trabajo_a, trabajo_b = (ventana.modelo_cola.trabajo(f) for f in (0, 1))
    assert trabajo_a.estado == EstadoTrabajo.HECHO  # tiene vídeo que mostrar
    assert trabajo_a.salida == ficha_a.final.ruta
    assert trabajo_b.estado == EstadoTrabajo.ESPERA  # no hay nada que mostrar


def test_procesar_solo_caption_sin_final_marca_error(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    # b ya tiene vídeo procesado; a no.
    ficha_b = cargar(ventana.modelo_cola.trabajo(1).ficha_id)
    final = tmp_path / "salidas" / "b_limpio.mp4"
    final.parent.mkdir()
    final.write_bytes(b"FINAL")
    ficha_b.final = Huella.de(final)
    guardar(ficha_b)
    _solo_caption(ventana)
    _sin_preguntar(monkeypatch)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    a = ventana.modelo_cola.trabajo(0)
    assert a.estado == EstadoTrabajo.ERROR
    assert "aún no tiene vídeo procesado" in a.error
    assert [fila for fila, _texto in lanzados] == [1]  # la otra fila sigue
    assert ventana._procesando


def test_procesar_json_lleva_reproceso(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path, con_caption=False)
    ventana.anadir_videos([ficha.final.ruta])  # arrastrada la salida, no el original
    assert ventana.modelo_cola.trabajo(0).ruta.name == "a_limpio.mp4"
    _solo_caption(ventana)
    _sin_preguntar(monkeypatch)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    [(fila, texto)] = lanzados
    datos = json.loads(texto)
    assert datos["reproceso"] == {
        "ficha": ficha.id, "rehacer": [], "regenerar_vertical": False}
    assert (datos["caption_seo"], datos["paso_audio"]) == (True, False)


def test_procesar_fila_sin_ficha_la_reconoce_antes(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.modelo_cola.actualizar(0, ficha_id=None)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    [(fila, texto)] = lanzados
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.ficha_id is not None and trabajo.ocupa > 0
    # Nunca por pipeline.run: siempre por la ficha.
    assert json.loads(texto)["reproceso"]["ficha"] == trabajo.ficha_id


def test_olvidar_y_procesar_otra_vez_una_salida_antigua_no_la_duplica(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    [video] = _videos(tmp_path, "x_limpio.mp4")  # una salida antigua arrastrada
    _md_ejemplo(video.with_suffix(".md"))
    ventana.anadir_videos([video])
    ventana.modelo_cola.actualizar(0, estado=EstadoTrabajo.HECHO)
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    _respondiendo(monkeypatch, QMessageBox.StandardButton.Yes)
    ventana.boton_olvidar.click()
    ventana.boton_reprocesar.click()
    ventana.panel.check_caption.setChecked(False)
    _sin_preguntar(monkeypatch)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    [(fila, texto)] = lanzados
    ficha = cargar(ventana.modelo_cola.trabajo(0).ficha_id)
    # Se sobrescribe a sí misma (no x_limpio_limpio.mp4) y su caption sigue.
    assert ficha.final.ruta == video.resolve()
    assert json.loads(texto)["reproceso"]["ficha"] == ficha.id
    assert video.with_suffix(".md").is_file()


def test_procesar_fila_sin_ficha_avisa_como_al_arrastrarla(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    [video] = _videos(tmp_path, "x.mov")
    (tmp_path / "x_limpio.mp4").write_bytes(b"ANTIGUA")  # nadie la arrastró
    informaciones = _capturando(monkeypatch, "information")
    ventana.anadir_videos([video])
    olvidar(cargar(ventana.modelo_cola.trabajo(0).ficha_id))
    ventana.modelo_cola.actualizar(0, ficha_id=None)
    _sin_preguntar(monkeypatch)
    _lanzando(ventana, monkeypatch)
    ventana.procesar()
    [al_anadir, al_procesar] = [texto for _padre, _titulo, texto in informaciones]
    assert '"x_limpio.mp4"' in al_procesar and al_procesar == al_anadir
    ventana.ejecutor.cola_terminada.emit()  # la ventana sigue viva: sin pasada en curso


def test_procesar_solo_caption_en_fila_sin_ficha_no_lanza_un_video_nuevo(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.modelo_cola.actualizar(0, ficha_id=None)
    _solo_caption(ventana)
    _sin_preguntar(monkeypatch)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert lanzados == []
    assert "aún no tiene vídeo procesado" in ventana.modelo_cola.trabajo(0).error


def test_procesar_fila_sin_ficha_que_ya_no_existe_marca_error(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    [video] = _videos(tmp_path, "a.mp4")
    ventana.anadir_videos([video])
    ventana.modelo_cola.actualizar(0, ficha_id=None)
    video.unlink()
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert lanzados == []
    trabajo = ventana.modelo_cola.trabajo(0)
    assert trabajo.estado == EstadoTrabajo.ERROR and trabajo.ficha_id is None


def test_procesar_ficha_sin_salidas_toma_la_carpeta_actual(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path / "uno"
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ficha_id = ventana.modelo_cola.trabajo(0).ficha_id
    assert cargar(ficha_id).carpeta_salida == tmp_path / "uno"
    _lanzando(ventana, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path / "dos"
    ventana.procesar()
    assert cargar(ficha_id).carpeta_salida == tmp_path / "dos"
    ventana.ajustes.carpeta_salida = None  # junto al original
    ventana.procesar()
    assert cargar(ficha_id).carpeta_salida == tmp_path


def test_procesar_ficha_sin_salidas_no_pisa_otra_en_la_carpeta_nueva(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path / "uno"
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ficha_id = ventana.modelo_cola.trabajo(0).ficha_id
    otro = tmp_path / "otra" / "a.mp4"  # otro vídeo con el mismo nombre
    otro.parent.mkdir()
    otro.write_bytes(b"OTRO")
    otra, _aviso = reconocer(otro, tmp_path / "dos")
    _lanzando(ventana, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path / "dos"
    ventana.procesar()
    ficha = cargar(ficha_id)
    assert ficha.carpeta_salida == tmp_path / "dos"
    assert ficha.nombre == "a (2)" and otra.nombre == "a"
    ventana.ajustes.carpeta_salida = tmp_path / "uno"  # vuelve donde no choca
    ventana.procesar()
    assert cargar(ficha_id).nombre == "a"


def test_procesar_ficha_con_salidas_conserva_su_carpeta(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.ajustes.carpeta_salida = tmp_path / "otra"
    _preguntando(monkeypatch, _mantener)
    _capturando(monkeypatch, "information")
    _lanzando(ventana, monkeypatch)
    _solo_caption(ventana)
    ventana.procesar()
    assert cargar(ficha.id).carpeta_salida == ficha.carpeta_salida


def test_procesar_ficha_perdida_se_lanza_igual_por_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ficha_id = ventana.modelo_cola.trabajo(0).ficha_id
    olvidar(cargar(ficha_id))  # alguien borró su carpeta; la fila aún la nombra
    _sin_preguntar(monkeypatch)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    # El runner explica que falta la ficha; no se procesa como un original.
    [(fila, texto)] = lanzados
    assert json.loads(texto)["reproceso"]["ficha"] == ficha_id


def test_boton_procesar_con_solo_caption_habilitado(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.panel.check_audio.setChecked(False)
    ventana.panel.check_silencios.setChecked(False)
    assert not ventana.boton_procesar.isEnabled()
    assert ventana.boton_procesar.toolTip() == "Marca al menos un paso."
    ventana.panel.check_caption.setChecked(True)
    assert ventana.boton_procesar.isEnabled()
    assert ventana.boton_procesar.toolTip() == ""


def test_boton_programadas_junto_a_redes_y_abre_el_calendario(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    fila = _layout_de(ventana.centralWidget().layout(), ventana.boton_redes)
    assert fila.indexOf(ventana.boton_programadas) == fila.indexOf(ventana.boton_redes) + 1

    class Falso(_DialogoFalso):
        abiertos: list = []

    monkeypatch.setattr("app.main.DialogoProgramadas", Falso)
    ventana.boton_programadas.click()
    assert Falso.abiertos == [(ventana.ajustes,)]


# --- shorts ---

def _con_shorts_hechos(ficha) -> Path:
    """La carpeta de shorts de la ficha, con un short y su `shorts.json`."""
    carpeta = shorts.carpeta_shorts(ficha)
    carpeta.mkdir(parents=True)
    (carpeta / "01 - Uno.mp4").write_bytes(b"SHORT")
    (carpeta / "shorts.json").write_text('{"archivos": ["01 - Uno.mp4"]}')
    return carpeta


def _eligiendo_la_fila(ventana, fila=0):
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(fila))


def test_boton_crear_shorts_activo_solo_con_fila_y_sin_procesar(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    boton = ventana.panel.boton_crear_shorts
    assert not boton.isEnabled()  # cola vacía
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    assert not boton.isEnabled()  # sin fila elegida
    _eligiendo_la_fila(ventana)
    assert boton.isEnabled()
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lambda t: None)
    ventana.procesar()
    assert not boton.isEnabled()  # mientras procesa
    ventana.ejecutor.cola_terminada.emit()
    assert boton.isEnabled()
    ventana.vista_cola.selectionModel().clearSelection()
    assert not boton.isEnabled()


def test_boton_publicar_shorts_activo_solo_con_una_fila_con_shorts(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    boton = ventana.panel.boton_publicar_shorts
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    _eligiendo_la_fila(ventana, 0)
    assert not boton.isEnabled()  # fila sin shorts
    ventana.modelo_cola.actualizar(1, shorts=tmp_path / "b", n_shorts=2)
    assert not boton.isEnabled()  # la elegida sigue siendo la primera
    _eligiendo_la_fila(ventana, 1)
    assert boton.isEnabled()


def test_publicar_shorts_abre_el_dialogo_con_los_de_la_carpeta(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    carpeta = _con_shorts_hechos(ficha)
    (carpeta / "shorts.json").write_text(json.dumps({"candidatos": [
        {"archivo": "01 - Uno.mp4", "titulo": "Uno", "inicio": 0, "fin": 70}]}))
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.modelo_cola.actualizar(0, shorts=carpeta, n_shorts=1)
    _eligiendo_la_fila(ventana)
    abiertos = []
    monkeypatch.setattr(
        "app.widgets.dialogo_publicar_shorts.DialogoPublicarShorts.exec",
        lambda self: abiertos.append([f.corto.mp4.name for f in self.filas]))
    ventana.panel.boton_publicar_shorts.click()
    assert abiertos == [["01 - Uno.mp4"]]


def test_crear_shorts_lanza_un_trabajo_de_shorts(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _eligiendo_la_fila(ventana)
    ventana.panel.check_shorts_subtitulos.setChecked(False)
    panel = ventana.panel
    panel.combo_encuadre_shorts.setCurrentIndex(
        panel.combo_encuadre_shorts.findData("barras"))
    lanzados = _lanzando(ventana, monkeypatch)
    panel.boton_crear_shorts.click()
    [(fila, texto)] = lanzados
    datos = json.loads(texto)
    assert fila == 0
    assert datos["shorts"] == {
        "ficha": ficha.id, "subtitulos": False, "encuadre": "barras"}
    assert "reproceso" not in datos
    assert ventana._procesando
    guardado = ventana.ajustes.cargar_panel()
    assert (guardado["shorts_encuadre"], guardado["modo"]) == ("barras", "completo")


def test_crear_shorts_limpia_el_error_el_aviso_y_el_diagnostico_viejos(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.modelo_cola.actualizar(
        0, estado=EstadoTrabajo.HECHO,
        error="x", aviso="Los shorts fallaron: Ollama no responde.",
        diagnostico={"titulo": "t"})
    _eligiendo_la_fila(ventana)
    _lanzando(ventana, monkeypatch)
    ventana.panel.boton_crear_shorts.click()
    trabajo = ventana.modelo_cola.trabajo(0)
    assert (trabajo.error, trabajo.aviso, trabajo.diagnostico) == ("", "", None)


def test_crear_shorts_no_hace_nada_sin_fila_o_procesando(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    lanzados = _lanzando(ventana, monkeypatch)
    ventana._crear_shorts()  # sin fila elegida
    _eligiendo_la_fila(ventana)
    ventana._procesando = True
    ventana._crear_shorts()
    assert lanzados == []


def test_crear_shorts_reconoce_la_fila_sin_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    ventana.modelo_cola.actualizar(0, ficha_id=None)
    _eligiendo_la_fila(ventana)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.panel.boton_crear_shorts.click()
    [(fila, texto)] = lanzados
    ficha_id = ventana.modelo_cola.trabajo(0).ficha_id
    assert ficha_id is not None
    assert json.loads(texto)["shorts"]["ficha"] == ficha_id


def test_crear_shorts_lleva_las_salidas_de_una_ficha_nueva_a_la_carpeta_de_ahora(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.carpeta_salida = tmp_path / "otra"
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    _eligiendo_la_fila(ventana)
    _lanzando(ventana, monkeypatch)
    ventana.panel.boton_crear_shorts.click()
    ficha = cargar(ventana.modelo_cola.trabajo(0).ficha_id)
    assert shorts.carpeta_shorts(ficha) == tmp_path / "otra" / "a"


@pytest.mark.parametrize("respuesta, se_lanza", [
    (QMessageBox.StandardButton.No, False),
    (QMessageBox.StandardButton.Yes, True),
], ids=["no", "si"])
def test_crear_shorts_pregunta_si_ya_hay_shorts(
        qtbot, tmp_path, monkeypatch, respuesta, se_lanza):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    carpeta = _con_shorts_hechos(ficha)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _eligiendo_la_fila(ventana)
    preguntas = _respondiendo(monkeypatch, respuesta)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.panel.boton_crear_shorts.click()
    [(_padre, titulo, texto, _botones, por_defecto)] = preguntas
    assert titulo == "Crear shorts"
    assert '"a.mp4"' in texto and str(carpeta) in texto
    assert por_defecto == QMessageBox.StandardButton.No
    assert len(lanzados) == int(se_lanza)
    assert ventana._procesando is se_lanza


def test_crear_shorts_sin_shorts_previos_no_pregunta(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _eligiendo_la_fila(ventana)
    monkeypatch.setattr("app.main.QMessageBox.question", lambda *a, **k: 1 / 0)
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.panel.boton_crear_shorts.click()
    assert len(lanzados) == 1


@pytest.mark.parametrize("al_procesar", [False, True])
def test_procesar_con_shorts_al_procesar_los_anade(
        qtbot, tmp_path, monkeypatch, al_procesar):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos(_videos(tmp_path, "a.mp4", "b.mp4"))
    panel = ventana.panel
    panel.check_shorts_al_procesar.setChecked(al_procesar)
    panel.check_shorts_subtitulos.setChecked(False)
    panel.combo_encuadre_shorts.setCurrentIndex(
        panel.combo_encuadre_shorts.findData("central"))
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert len(lanzados) == 2
    for fila, texto in lanzados:
        datos = json.loads(texto)
        assert "reproceso" in datos
        if al_procesar:
            assert datos["shorts"] == {
                "ficha": ventana.modelo_cola.trabajo(fila).ficha_id,
                "subtitulos": False, "encuadre": "central"}
        else:
            assert "shorts" not in datos


def test_procesar_con_shorts_envia_aunque_no_haya_nada_que_hacer(
        qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)  # caption hecho y con vídeo final
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _solo_caption(ventana)
    ventana.panel.check_shorts_al_procesar.setChecked(True)
    _preguntando(monkeypatch, _mantener)  # Mantener: el plan queda vacío
    informaciones = _capturando(monkeypatch, "information")
    lanzados = _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert informaciones == []  # no hay «Nada que hacer»
    [(fila, texto)] = lanzados
    assert json.loads(texto)["shorts"]["ficha"] == ficha.id
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.ESPERA
    assert ventana._procesando


def test_cancelar_borra_la_carpeta_temporal_de_shorts(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    carpeta = _con_shorts_hechos(ficha)  # shorts de una pasada anterior
    temporal = carpeta / shorts.TMP
    temporal.mkdir()
    (temporal / "02 - A medias.mp4").write_bytes(b"MEDIO")
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.ejecutor.trabajo_terminado.emit(0, False, "", "Cancelado")
    assert ventana.modelo_cola.trabajo(0).estado == EstadoTrabajo.CANCELADO
    assert not temporal.exists()
    assert sorted(p.name for p in carpeta.iterdir()) == ["01 - Uno.mp4", "shorts.json"]


def test_salida_shorts_actualiza_la_fila(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    carpeta = tmp_path / "salidas" / "a"
    ventana.ejecutor.salida_shorts.emit(0, str(carpeta), 3)
    # Con el botón el runner da la carpeta de shorts como salida: la fila sigue
    # abriendo el vídeo final de su ficha.
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(carpeta), "")
    trabajo = ventana.modelo_cola.trabajo(0)
    assert (trabajo.shorts, trabajo.n_shorts) == (carpeta, 3)
    assert trabajo.estado == EstadoTrabajo.HECHO
    assert trabajo.salida == ficha.final.ruta
    assert "+ 3 shorts" in ventana.modelo_cola.data(ventana.modelo_cola.index(0))
