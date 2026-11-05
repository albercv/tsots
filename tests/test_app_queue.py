from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt

from app.queue_model import EstadoTrabajo, ModeloCola, resumen_de
from app.settings import Ajustes
from videopipeline.ficha import BASE, CAPTION, HORIZONTAL, VERTICAL, Artefacto, Ficha


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
    añadidos = m.anadir([(Path("/v/a.mp4"), None), (Path("/v/b.mp4"), None)])
    assert len(añadidos) == 2
    assert m.rowCount() == 2
    # Duplicado pendiente ignorado
    assert m.anadir([(Path("/v/a.mp4"), None)]) == []
    assert m.rowCount() == 2


def test_cola_estados_y_display(qtbot):
    m = ModeloCola()
    m.anadir([(Path("/v/a.mp4"), None)])
    assert m.trabajo(0).estado == EstadoTrabajo.ESPERA
    m.actualizar(0, estado=EstadoTrabajo.PROCESANDO, percent=42.0,
                 etiqueta="Limpiando audio")
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert "a.mp4" in texto and "42" in texto and "Limpiando audio" in texto


def test_cola_pendientes_y_limpiar_hechos(qtbot):
    m = ModeloCola()
    m.anadir([(Path(f"/v/{n}.mp4"), None) for n in "abc"])
    m.actualizar(0, estado=EstadoTrabajo.HECHO)
    m.actualizar(1, estado=EstadoTrabajo.ERROR, error="boom")
    assert m.pendientes() == [2]
    m.limpiar_hechos()
    assert m.rowCount() == 2  # ERROR y ESPERA se conservan


def test_cola_quitar(qtbot):
    m = ModeloCola()
    m.anadir([(Path("/v/a.mp4"), None), (Path("/v/b.mp4"), None)])
    m.quitar(0)
    assert m.rowCount() == 1
    assert m.trabajo(0).ruta == Path("/v/b.mp4")


def test_cola_quitar_fuera_de_rango(qtbot):
    m = ModeloCola()
    m.anadir([(Path("/v/a.mp4"), None)])
    assert m.rowCount() == 1
    # Out-of-range quitar should not raise and model should remain valid
    m.quitar(5)
    assert m.rowCount() == 1
    # Model should still be usable
    m.quitar(0)
    assert m.rowCount() == 0


def test_cola_anadir_duplicado_en_mismo_lote(qtbot):
    m = ModeloCola()
    añadidos = m.anadir([(Path("/v/a.mp4"), None), (Path("/v/a.mp4"), None)])
    assert len(añadidos) == 1
    assert m.rowCount() == 1


def test_foreground_por_estado(qtbot):
    m = ModeloCola()
    m.anadir([(Path(f"/v/{n}.mp4"), None) for n in "abcd"])
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
    m.anadir([(Path("/v/a.mp4"), None)])
    m.actualizar(0, estado=EstadoTrabajo.HECHO, aviso="subs fallaron")
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert "⚠" in texto
    assert "subs fallaron" in m.data(m.index(0), Qt.ItemDataRole.ToolTipRole)


def test_error_muestra_titulo_en_la_fila(qtbot):
    m = ModeloCola()
    m.anadir([(Path("/v/a.mp4"), None)])
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


def test_ajustes_glosario_persistido(tmp_path):
    a = _ajustes(tmp_path)
    assert a.glosario == ""
    a.glosario = "Claude Code = Cloud Code\nAnthropic"
    assert _ajustes(tmp_path).glosario == "Claude Code = Cloud Code\nAnthropic"


def test_fila_muestra_vertical():
    modelo = ModeloCola()
    modelo.anadir([(Path("/v/a.mp4"), None)])
    modelo.actualizar(0, estado=EstadoTrabajo.HECHO, salida=Path("/v/a_limpio.mp4"),
                      salida_vertical=Path("/v/a_limpio_vertical.mp4"))
    indice = modelo.index(0)
    assert "+ vertical" in modelo.data(indice, Qt.ItemDataRole.DisplayRole)
    assert "/v/a_limpio_vertical.mp4" in modelo.data(
        indice, Qt.ItemDataRole.ToolTipRole)


def test_fila_hecha_muestra_los_shorts():
    modelo = ModeloCola()
    modelo.anadir([(Path("/v/a.mp4"), None)])
    modelo.actualizar(0, estado=EstadoTrabajo.HECHO, salida=Path("/v/a_limpio.mp4"),
                      salida_vertical=Path("/v/a_limpio_vertical.mp4"),
                      shorts=Path("/s/a"), n_shorts=3)
    indice = modelo.index(0)
    texto = modelo.data(indice, Qt.ItemDataRole.DisplayRole)
    assert "+ vertical + 3 shorts" in texto
    assert "Shorts: /s/a" in modelo.data(indice, Qt.ItemDataRole.ToolTipRole)


def test_fila_sin_shorts_no_los_muestra():
    modelo = ModeloCola()
    modelo.anadir([(Path("/v/a.mp4"), None)])
    modelo.actualizar(0, estado=EstadoTrabajo.HECHO, salida=Path("/v/a_limpio.mp4"))
    indice = modelo.index(0)
    assert "shorts" not in modelo.data(indice, Qt.ItemDataRole.DisplayRole)
    assert modelo.data(indice, Qt.ItemDataRole.ToolTipRole) is None


TERMINADOS = (EstadoTrabajo.HECHO, EstadoTrabajo.ERROR, EstadoTrabajo.CANCELADO)


@pytest.mark.parametrize("estado", TERMINADOS)
def test_anadir_misma_ficha_reactiva_en_vez_de_duplicar(qtbot, estado):
    m = ModeloCola()
    assert m.anadir([(Path("/v/a.mp4"), "f1"), (Path("/v/b.mp4"), "f2")]) == [0, 1]
    m.actualizar(1, estado=estado, error="boom", aviso="ojo", percent=40.0)
    assert m.anadir([(Path("/v/b.mp4"), "f2")]) == [1]
    assert m.rowCount() == 2
    t = m.trabajo(1)
    assert (t.estado, t.error, t.aviso, t.percent) == (
        EstadoTrabajo.ESPERA, "", "", None)


@pytest.mark.parametrize(
    "estado", (EstadoTrabajo.ESPERA, EstadoTrabajo.PROCESANDO))
def test_anadir_misma_ficha_en_espera_no_cambia(qtbot, estado):
    m = ModeloCola()
    m.anadir([(Path("/v/a.mp4"), "f1")])
    m.actualizar(0, estado=estado, percent=40.0, aviso="ojo")
    assert m.anadir([(Path("/v/a.mp4"), "f1")]) == []
    assert m.rowCount() == 1
    t = m.trabajo(0)
    assert (t.estado, t.percent, t.aviso) == (estado, 40.0, "ojo")


def test_anadir_ficha_no_deduplica_por_ruta_y_si_en_el_mismo_lote(qtbot):
    m = ModeloCola()
    # Otra ficha con la misma ruta es otra fila; la misma ficha dos veces, no.
    assert m.anadir([(Path("/v/a.mp4"), "f1"), (Path("/v/a.mp4"), "f2"),
                     (Path("/v/a.mp4"), "f1")]) == [0, 1]
    assert [m.fila_de_ficha(i) for i in ("f1", "f2", "nada")] == [0, 1, None]
    # Sin ficha se sigue deduplicando por ruta contra lo pendiente.
    assert m.anadir([(Path("/v/a.mp4"), None)]) == []


def test_volver_a_espera_solo_terminados(qtbot):
    m = ModeloCola()
    m.anadir([(Path(f"/v/{n}.mp4"), None) for n in "abcde"])
    m.actualizar(1, estado=EstadoTrabajo.PROCESANDO, percent=10.0)
    m.actualizar(2, estado=EstadoTrabajo.HECHO, aviso="ojo")
    m.actualizar(3, estado=EstadoTrabajo.ERROR, error="boom", diagnostico={"x": 1})
    m.actualizar(4, estado=EstadoTrabajo.CANCELADO, error="Cancelado")
    m.volver_a_espera([0, 1, 2, 3, 4])
    assert [m.trabajo(i).estado for i in range(5)] == [
        EstadoTrabajo.ESPERA, EstadoTrabajo.PROCESANDO, EstadoTrabajo.ESPERA,
        EstadoTrabajo.ESPERA, EstadoTrabajo.ESPERA]
    assert m.trabajo(1).percent == 10.0  # el que procesa no se toca
    assert (m.trabajo(2).aviso, m.trabajo(3).error, m.trabajo(3).diagnostico,
            m.trabajo(4).error) == ("", "", None, "")


def test_fila_muestra_resumen_y_tamano(qtbot):
    m = ModeloCola()
    m.anadir([(Path("/v/a.mp4"), "f1"), (Path("/v/b.mp4"), "f2")])
    m.actualizar(0, resumen="✓ audio · silencios", ocupa=312_400_000)
    texto = m.data(m.index(0), Qt.ItemDataRole.DisplayRole)
    assert "✓ audio · silencios" in texto and "· 312 MB" in texto
    # Sin resumen ni tamaño la fila queda como siempre.
    assert m.data(m.index(1), Qt.ItemDataRole.DisplayRole) == "b.mp4 — en espera"


def _ficha(artefactos, desactualizado=()):
    return Ficha(id="f1", nombre="a", carpeta_salida=Path("/v"),
                 artefactos=artefactos, desactualizado=set(desactualizado))


def test_resumen_de_ficha():
    assert resumen_de(_ficha({})) == ""
    completa = {
        BASE: Artefacto("k", None, {"audio": {}, "silencios": {}}),
        HORIZONTAL: Artefacto("k", "h.mp4", {"subtitulos": {}}),
        CAPTION: Artefacto("k", "caption.md"),
    }
    assert resumen_de(_ficha(completa)) == "✓ audio · silencios · subtítulos · caption"
    con_vertical = {**completa, VERTICAL: Artefacto("k", "v.mp4")}
    assert resumen_de(_ficha(con_vertical)) == (
        "✓ audio · silencios · subtítulos · caption · vertical")
    # Un vertical desactualizado se avisa una sola vez, haya artefacto o no.
    esperado = "✓ audio · silencios · subtítulos · caption · vertical desactualizado"
    assert resumen_de(_ficha(completa, {"vertical"})) == esperado
    assert resumen_de(_ficha(con_vertical, {"vertical"})) == esperado
