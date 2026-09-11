from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt

from app.queue_model import EstadoTrabajo, ModeloCola
from app.settings import Ajustes


def _ajustes(tmp_path) -> Ajustes:
    q = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    return Ajustes(q)


def test_carpeta_salida_persistida(tmp_path):
    a = _ajustes(tmp_path)
    assert a.carpeta_salida is None
    a.carpeta_salida = tmp_path / "salidas"
    assert a.carpeta_salida == tmp_path / "salidas"
    a.carpeta_salida = None
    assert a.carpeta_salida is None


def test_panel_persistido(tmp_path):
    a = _ajustes(tmp_path)
    valores = {"modo": "solo_audio", "margen": "0.3s", "velocidad_silencios": 8}
    a.guardar_panel(valores)
    cargado = a.cargar_panel()
    assert cargado["modo"] == "solo_audio"
    assert cargado["margen"] == "0.3s"
    assert int(cargado["velocidad_silencios"]) == 8


def test_cola_anadir_y_duplicados(qtbot):
    m = ModeloCola()
    añadidos = m.anadir([Path("/v/a.mp4"), Path("/v/b.mp4")])
    assert len(añadidos) == 2
    assert m.rowCount() == 2
    # Duplicado pendiente ignorado
    assert m.anadir([Path("/v/a.mp4")]) == []
    assert m.rowCount() == 2


def test_cola_estados_y_display(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4")])
    assert m.trabajo(0).estado == EstadoTrabajo.ESPERA
    m.actualizar(0, estado=EstadoTrabajo.PROCESANDO, percent=42.0,
                 etiqueta="Limpiando audio")
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert "a.mp4" in texto and "42" in texto and "Limpiando audio" in texto


def test_cola_pendientes_y_limpiar_hechos(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4"), Path("/v/b.mp4"), Path("/v/c.mp4")])
    m.actualizar(0, estado=EstadoTrabajo.HECHO)
    m.actualizar(1, estado=EstadoTrabajo.ERROR, error="boom")
    assert m.pendientes() == [2]
    m.limpiar_hechos()
    assert m.rowCount() == 2  # ERROR y ESPERA se conservan


def test_cola_quitar(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4"), Path("/v/b.mp4")])
    m.quitar(0)
    assert m.rowCount() == 1
    assert m.trabajo(0).ruta == Path("/v/b.mp4")


def test_cola_quitar_fuera_de_rango(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4")])
    assert m.rowCount() == 1
    # Out-of-range quitar should not raise and model should remain valid
    m.quitar(5)
    assert m.rowCount() == 1
    # Model should still be usable
    m.quitar(0)
    assert m.rowCount() == 0


def test_cola_anadir_duplicado_en_mismo_lote(qtbot):
    m = ModeloCola()
    añadidos = m.anadir([Path("/v/a.mp4"), Path("/v/a.mp4")])
    assert len(añadidos) == 1
    assert m.rowCount() == 1


def test_foreground_por_estado(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4"), Path("/v/b.mp4"), Path("/v/c.mp4"), Path("/v/d.mp4")])
    m.actualizar(0, estado=EstadoTrabajo.ERROR, error="boom")
    m.actualizar(1, estado=EstadoTrabajo.CANCELADO)
    # fila 2 queda en ESPERA, fila 3 pasa a HECHO
    m.actualizar(3, estado=EstadoTrabajo.HECHO)

    rojo = m.data(m.index(0), Qt.ItemDataRole.ForegroundRole)
    gris = m.data(m.index(1), Qt.ItemDataRole.ForegroundRole)
    espera = m.data(m.index(2), Qt.ItemDataRole.ForegroundRole)
    hecho = m.data(m.index(3), Qt.ItemDataRole.ForegroundRole)

    assert rojo is not None and rojo.color().name() == "#c62828"
    assert gris is not None and gris.color().name() == "#888888"
    assert espera is None
    assert hecho is None


def test_aviso_en_display_y_tooltip(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4")])
    m.actualizar(0, estado=EstadoTrabajo.HECHO, aviso="subs fallaron")
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert "⚠" in texto
    assert "subs fallaron" in m.data(m.index(0), Qt.ItemDataRole.ToolTipRole)


def test_error_muestra_titulo_en_la_fila(qtbot):
    m = ModeloCola()
    m.anadir([Path("/v/a.mp4")])
    m.actualizar(
        0, estado=EstadoTrabajo.ERROR,
        error="auto-editor no pudo escribir el vídeo\nCausa: X\nQué hacer: Y",
    )
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert "auto-editor no pudo escribir el vídeo" in texto
    assert "Causa" not in texto  # solo la primera línea en la fila
    assert "Causa: X" in m.data(m.index(0), Qt.ItemDataRole.ToolTipRole)


def test_ajustes_caption_persistidos(tmp_path):
    a = _ajustes(tmp_path)
    assert a.contexto_marca == ""
    assert a.modelo_caption == "qwen3.5:9b"
    a.contexto_marca = "Soy Alberto\ntono cercano"
    a.modelo_caption = "qwen3.5:9b-q8_0"
    b = _ajustes(tmp_path)  # misma ruta .ini → mismos datos
    assert b.contexto_marca == "Soy Alberto\ntono cercano"
    assert b.modelo_caption == "qwen3.5:9b-q8_0"


def test_ajustes_idioma_ui_defecto_y_persistido(tmp_path):
    a = _ajustes(tmp_path)
    assert a.idioma_ui == "sistema"
    a.idioma_ui = "en"
    b = _ajustes(tmp_path)  # misma ruta .ini → mismos datos
    assert b.idioma_ui == "en"
