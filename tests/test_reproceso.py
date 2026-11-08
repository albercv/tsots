from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from videopipeline import ficha as modulo_ficha
from videopipeline import linkedin, pipeline, reproceso
from videopipeline.caption import Caption, escribir_md
from videopipeline.config import PipelineConfig
from videopipeline.difusion import Resultado
from videopipeline.ficha import (
    BASE, CAPTION, DIFUSION, HORIZONTAL, SEGUIMIENTO, TITULO, TRANSCRIPCION,
    VERTICAL, Artefacto, Ficha, cargar, guardar, reconocer,
)
from videopipeline.reproceso import ejecutar
from videopipeline.reproceso_plan import (
    Accion, Decisiones, Plan, ajustes_silencios, clave_seguimiento,
    planificar, revisar,
)
from videopipeline.steps import PasoFallido

from tests.falsos_pipeline import (  # noqa: F401 — fixtures
    entorno, entorno_caption, entorno_subs, entorno_titulo, entorno_vertical,
)

A = Accion
REHACER_SUBS = Decisiones(rehacer=frozenset({"subtitulos"}))


@pytest.fixture(autouse=True)
def falsos(entorno_vertical, entorno_caption, entorno_titulo, tmp_path,
           monkeypatch):
    """Todos los pasos falsos; las fichas y las salidas, dentro de tmp_path."""
    llamadas, video, _, _ = entorno_vertical
    monkeypatch.setattr(modulo_ficha, "DIR_FICHAS", tmp_path / "fichas")

    def falso_flac(wav, flac):
        llamadas.append("flac")
        flac.write_bytes(b"FLAC")

    monkeypatch.setattr(reproceso, "a_flac", falso_flac)
    return llamadas


def _revienta(*args, **kwargs):
    raise PasoFallido("ffmpeg explotó")


def _ficha(tmp_path) -> Ficha:
    """La ficha nueva de `charla.mov`, con las salidas en `salida/`."""
    return reconocer(tmp_path / "charla.mov", tmp_path / "salida")[0]


def _panel(**valores) -> PipelineConfig:
    """Lo que pide el panel: ningún paso marcado salvo los que se pasan."""
    marcas = dict(paso_audio=False, paso_silencios=False, subtitulos=False,
                  caption_seo=False, paso_vertical=False, difusion=False)
    marcas.update(valores)
    return PipelineConfig(video=Path("/no/importa.mov"), **marcas)


def _pasada(ficha: Ficha, esperado: list[Accion],
            decisiones: Decisiones = Decisiones(), eventos: list | None = None,
            **panel) -> Ficha:
    """Planifica y ejecuta lo que pide el panel; devuelve la ficha guardada.
    Sin `eventos`, ningún paso puede degradarse con un aviso."""
    plan = planificar(ficha, _panel(**panel), decisiones)
    assert plan.acciones == esperado
    recibidos = [] if eventos is None else eventos
    ejecutar(ficha, plan, recibidos.append)
    if eventos is None:
        assert [e["warning"] for e in recibidos if "warning" in e] == []
    return cargar(ficha.id)


def _sin_restos(ficha: Ficha) -> bool:
    """Ni la carpeta tmp de la ficha ni temporales ocultos junto a las salidas."""
    salida = ficha.carpeta_salida
    ocultos = ([p for p in salida.iterdir() if p.name.startswith(".")]
               if salida.is_dir() else [])
    return not (ficha.carpeta / "tmp").exists() and ocultos == []


def test_anadir_caption_no_codifica_video(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path),
                    [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO, A.ESCRIBIR_FINAL],
                    paso_audio=True)
    final = ficha.final.ruta
    antes = final.read_bytes()
    falsos.clear()
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.CAPTION], eventos=eventos,
                    caption_seo=True)

    assert not any(l.startswith(("quemar", "cortar", "remux")) for l in falsos)
    assert final.read_bytes() == antes and ficha.final.coincide(final)
    assert ficha.ruta("caption.md").is_file()
    assert final.with_suffix(".md").read_bytes() == ficha.ruta("caption.md").read_bytes()
    pasos = [e for e in eventos if "step" in e]
    assert {e["step"] for e in pasos} == {1, 2}
    assert {e["total"] for e in pasos} == {2}
    assert _sin_restos(ficha)


def test_anadir_silencios_reutiliza_audio_limpio(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO,
                                       A.TRANSCRIBIR, A.QUEMAR],
                    paso_audio=True, subtitulos=True)
    falsos.clear()

    _pasada(ficha, [A.CORTAR, A.TRANSCRIBIR, A.QUEMAR],
            paso_audio=True, paso_silencios=True, subtitulos=True)

    assert not any(l.startswith("limpiar:") for l in falsos)
    assert "remux:intermedio" in falsos  # el audio guardado entra en auto-editor
    assert any(l.startswith("cortar:") for l in falsos)
    assert any(l.startswith("transcribir:") for l in falsos)
    assert "quemar" in falsos


def test_rehacer_subtitulos_mantiene_caption(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path),
                    [A.CORTAR, A.TRANSCRIBIR, A.QUEMAR, A.CAPTION],
                    paso_silencios=True, subtitulos=True, caption_seo=True)
    copia = ficha.ruta("caption.md").read_bytes()
    md = ficha.final.ruta.with_suffix(".md").read_bytes()
    falsos.clear()

    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.QUEMAR], REHACER_SUBS,
                    subtitulos=True)

    assert "quemar" in falsos
    assert not any(l.startswith("generar:") for l in falsos)
    assert ficha.ruta("caption.md").read_bytes() == copia
    assert ficha.final.ruta.with_suffix(".md").read_bytes() == md


def test_quemar_guarda_la_base_aparte(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)
    antes = ficha.final.ruta.read_bytes()

    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.QUEMAR], subtitulos=True)

    assert ficha.artefactos[BASE].archivo == "base.mp4"
    assert ficha.ruta("base.mp4").read_bytes() == antes
    assert ficha.final.ruta.read_bytes() == b"MP4SUBS"
    assert ficha.final.ruta.with_suffix(".srt").is_file()
    assert _sin_restos(ficha)


def test_sin_subtitulos_no_duplica_base(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)

    assert ficha.artefactos[BASE].archivo is None
    assert ficha.artefactos[BASE].ajustes == {"silencios": ajustes_silencios(_panel())}
    assert not ficha.ruta("base.mp4").exists()
    assert ficha.final.ruta.read_bytes() == b"MP4FINAL"
    assert _sin_restos(ficha)


def test_fallo_a_mitad_conserva_salidas_y_ficha(tmp_path, monkeypatch):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)
    final = ficha.final.ruta
    horizontal = ficha.artefactos[HORIZONTAL]
    monkeypatch.setattr(pipeline, "quemar_subtitulos", _revienta)
    plan = planificar(ficha, _panel(subtitulos=True), Decisiones())
    assert plan.acciones == [A.TRANSCRIBIR, A.QUEMAR]

    with pytest.raises(PasoFallido):
        ejecutar(ficha, plan)

    guardada = cargar(ficha.id)
    assert final.read_bytes() == b"MP4FINAL" and guardada.final.coincide(final)
    assert TRANSCRIPCION in guardada.artefactos
    assert guardada.ruta("transcripcion.json").is_file()
    assert guardada.artefactos[HORIZONTAL] == horizontal
    assert guardada.artefactos[BASE].archivo is None
    assert not guardada.ruta("base.mp4").exists()
    assert not final.with_suffix(".srt").exists()
    assert _sin_restos(guardada)


def test_mover_entre_discos(tmp_path, monkeypatch):
    renombrados: list[str] = []

    def otro_disco(origen, destino):
        renombrados.append(Path(destino).name)
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", otro_disco)
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)

    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.QUEMAR], subtitulos=True)

    assert "base.mp4" in renombrados  # se copió y se borró
    assert ficha.ruta("base.mp4").read_bytes() == b"MP4FINAL"
    assert ficha.final.ruta.read_bytes() == b"MP4SUBS"
    assert _sin_restos(ficha)


def test_legado_mueve_el_archivo_a_la_ficha_antes_de_sobrescribir(tmp_path):
    legado = tmp_path / "salida" / "charla_limpio.mp4"
    legado.parent.mkdir()
    legado.write_bytes(b"LEGADO")
    ficha, _aviso = reconocer(legado, None)
    assert ficha.legado and ficha.original is None

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL], paso_silencios=True)

    assert ficha.original.ruta == ficha.ruta("original.mp4").resolve()
    assert ficha.original.ruta.read_bytes() == b"LEGADO"
    assert ficha.legado  # sigue sin original de verdad (ruling de la tarea 2)
    assert legado.read_bytes() == b"MP4FINAL" and ficha.final.coincide(legado)
    assert _sin_restos(ficha)


def test_copia_fallida_a_otro_disco_deja_el_final_en_su_sitio(tmp_path,
                                                             monkeypatch):
    legado = tmp_path / "salida" / "charla_limpio.mp4"
    legado.parent.mkdir()
    legado.write_bytes(b"LEGADO")
    ficha, _aviso = reconocer(legado, None)
    mover = shutil.move

    def disco_lleno(origen, destino, *args, **kwargs):
        if Path(destino).name.startswith("."):  # el temporal junto a la salida
            Path(destino).write_bytes(b"A MEDIAS")
            raise OSError(errno.ENOSPC, "No space left on device")
        return mover(origen, destino, *args, **kwargs)

    monkeypatch.setattr(shutil, "move", disco_lleno)
    plan = planificar(ficha, _panel(paso_silencios=True), Decisiones())

    with pytest.raises(OSError):
        ejecutar(ficha, plan)

    assert legado.read_bytes() == b"LEGADO"
    guardada = cargar(ficha.id)
    assert guardada.original is None and guardada.final.coincide(legado)
    assert _sin_restos(guardada)


def test_r10_renombra_vertical_y_mueve_md_srt(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.TRANSCRIBIR, A.CAPTION, A.VERTICAL],
                    subtitulos=True, caption_seo=True, paso_vertical=True)
    unico = ficha.final.ruta
    assert unico.name == "charla_vertical.mp4"
    md = unico.with_suffix(".md").read_bytes()
    assert unico.with_suffix(".srt").is_file()

    ficha = _pasada(ficha, [A.QUEMAR, A.RENOMBRAR_VERTICAL], subtitulos=True)

    salida = (tmp_path / "salida").resolve()
    assert ficha.final.ruta == salida / "charla_limpio.mp4"
    assert ficha.vertical.ruta == salida / "charla_limpio_vertical.mp4"
    assert ficha.vertical.ruta.read_bytes() == b"VERTICAL"
    assert ficha.vertical.coincide(ficha.vertical.ruta)
    assert ficha.final.ruta.with_suffix(".md").read_bytes() == md
    assert ficha.final.ruta.with_suffix(".srt").is_file()
    assert not unico.exists()
    assert not unico.with_suffix(".md").exists()
    assert not unico.with_suffix(".srt").exists()
    assert _sin_restos(ficha)


def test_r10_retira_el_vertical_unico_al_regenerarlo(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.VERTICAL], paso_vertical=True)
    unico = ficha.final.ruta

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL, A.VERTICAL,
                            A.RETIRAR_VERTICAL_UNICO], paso_silencios=True)

    assert not unico.exists()
    assert ficha.final.ruta.name == "charla_limpio.mp4"
    assert ficha.vertical.ruta.name == "charla_limpio_vertical.mp4"
    assert ficha.vertical.coincide(ficha.vertical.ruta)
    assert _sin_restos(ficha)


def test_vertical_con_seguimiento_guardado_no_detecta_otra_vez(
        falsos, tmp_path, monkeypatch):
    ficha = _pasada(_ficha(tmp_path),
                    [A.CORTAR, A.ESCRIBIR_FINAL, A.SEGUIMIENTO, A.VERTICAL],
                    paso_silencios=True, paso_vertical=True, encuadre="cara")
    assert falsos.count("caras") == 1
    assert ficha.artefactos[SEGUIMIENTO].ajustes == {"x_inicial": 10}
    assert ficha.artefactos[SEGUIMIENTO].clave == clave_seguimiento(
        ficha.artefactos[BASE].linea_tiempo)
    falsos.clear()
    comandos: list[str] = []
    convertir = pipeline.convertir_vertical

    def convertir_leyendo_comandos(video_, salida, filtro, cwd, *args, **kwargs):
        comandos.append((Path(cwd) / "cara.cmd").read_text())
        convertir(video_, salida, filtro, cwd, *args, **kwargs)

    monkeypatch.setattr(pipeline, "convertir_vertical", convertir_leyendo_comandos)

    _pasada(ficha, [A.VERTICAL], Decisiones(rehacer=frozenset({"vertical"})),
            paso_vertical=True, encuadre="cara")

    assert "caras" not in falsos
    assert "crop@v=1440:1080:10:0" in falsos[-1]
    assert comandos == ["0.000 crop@v x 10;"]


def test_vertical_con_seguimiento_de_la_ventana_9_16_lo_recalcula(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path),
                    [A.CORTAR, A.ESCRIBIR_FINAL, A.SEGUIMIENTO, A.VERTICAL],
                    paso_silencios=True, paso_vertical=True, encuadre="cara")
    # Lo que guardaban las versiones con la ventana de 9:16: clave = línea.
    ficha.artefactos[SEGUIMIENTO].clave = ficha.artefactos[BASE].linea_tiempo
    guardar(ficha)
    falsos.clear()

    ficha = _pasada(cargar(ficha.id), [A.SEGUIMIENTO, A.VERTICAL],
                    Decisiones(rehacer=frozenset({"vertical"})),
                    paso_vertical=True, encuadre="cara")

    assert falsos.count("caras") == 1  # no se reutilizan las x de la ventana vieja
    assert ficha.artefactos[SEGUIMIENTO].clave == clave_seguimiento(
        ficha.artefactos[BASE].linea_tiempo)


def test_vertical_sin_caras_centra_la_ventana_ancha(falsos, tmp_path, monkeypatch):
    monkeypatch.setattr(reproceso, "preparar_seguimiento", lambda *a, **k: None)
    _pasada(_ficha(tmp_path), [A.SEGUIMIENTO, A.VERTICAL], eventos=[],
            paso_vertical=True, encuadre="cara")

    assert "[0:v]crop=1440:1080,split" in falsos[-1] and "sendcmd" not in falsos[-1]


def test_desactualizado_se_marca_y_se_limpia_al_regenerar(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO,
                                       A.ESCRIBIR_FINAL, A.VERTICAL],
                    paso_audio=True, paso_vertical=True)

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_audio=True, paso_silencios=True)
    assert ficha.desactualizado == {"vertical"}
    assert ficha.vertical.coincide(ficha.vertical.ruta)  # no se ha tocado

    ficha = _pasada(ficha, [A.VERTICAL], paso_vertical=True)
    assert ficha.desactualizado == set()


def test_reprocesar_sin_caption_conserva_md(tmp_path):
    ficha = _pasada(_ficha(tmp_path),
                    [A.CORTAR, A.TRANSCRIBIR, A.ESCRIBIR_FINAL, A.CAPTION],
                    paso_silencios=True, caption_seo=True)
    md = ficha.final.ruta.with_suffix(".md")
    antes, copia = md.read_bytes(), ficha.ruta("caption.md").read_bytes()

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL],
                    Decisiones(rehacer=frozenset({"silencios"})),
                    paso_silencios=True, margen="0.4s")

    assert md.read_bytes() == antes
    assert ficha.ruta("caption.md").read_bytes() == copia
    assert CAPTION in ficha.artefactos


def test_cambiar_estilo_quema_sobre_la_base(tmp_path, monkeypatch):
    fuentes: list[tuple[Path, bytes]] = []

    def falso_quemar(video_, ass, salida, on_percent=None, desde_original=False):
        fuentes.append((Path(video_), Path(video_).read_bytes()))
        salida.write_bytes(b"MP4SUBS")

    monkeypatch.setattr(pipeline, "quemar_subtitulos", falso_quemar)
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)
    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.QUEMAR], subtitulos=True)

    ficha = _pasada(ficha, [A.QUEMAR], REHACER_SUBS, subtitulos=True,
                    diseno="caja")

    assert fuentes[-1] == (ficha.ruta("base.mp4"), b"MP4FINAL")
    assert ficha.artefactos[HORIZONTAL].ajustes["subtitulos"]["diseno"] == "caja"


def test_no_sobrescribe_un_archivo_que_la_ficha_no_registra(tmp_path):
    ficha = _ficha(tmp_path)
    plan = planificar(ficha, _panel(paso_silencios=True), Decisiones())
    # Aparece después de reconocer el vídeo: si ya estuviera, se adoptaría.
    ajeno = tmp_path / "salida" / "charla_limpio.mp4"
    ajeno.parent.mkdir()
    ajeno.write_bytes(b"AJENO")

    with pytest.raises(PasoFallido, match="fuera de la app"):
        ejecutar(ficha, plan)

    assert ajeno.read_bytes() == b"AJENO"
    guardada = cargar(ficha.id)
    assert HORIZONTAL not in guardada.artefactos and guardada.final is None
    assert _sin_restos(guardada)


def test_no_usa_ni_sobrescribe_un_final_cambiado_fuera_de_la_app(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)
    ficha.final.ruta.write_bytes(b"EDITADO")
    plan = planificar(ficha, _panel(subtitulos=True), Decisiones())

    with pytest.raises(PasoFallido, match="fuera de la app"):
        ejecutar(ficha, plan)

    assert ficha.final.ruta.read_bytes() == b"EDITADO"
    assert not ficha.ruta("base.mp4").exists()
    assert TRANSCRIPCION not in cargar(ficha.id).artefactos


def test_subtitulos_fallidos_al_recortar_guardan_el_video_sin_ellos(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "quemar_subtitulos", _revienta)
    eventos: list[dict] = []

    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.TRANSCRIBIR, A.QUEMAR],
                    eventos=eventos, paso_silencios=True, subtitulos=True)

    assert ficha.final.ruta.read_bytes() == b"MP4FINAL"
    assert ficha.artefactos[HORIZONTAL].ajustes == {}
    assert ficha.artefactos[BASE].archivo is None
    assert ficha.final.ruta.with_suffix(".srt").is_file()  # como hoy
    assert any("Subtítulos fallaron" in e.get("warning", "") for e in eventos)
    assert _sin_restos(ficha)


def test_caption_fallido_conserva_el_anterior(tmp_path, monkeypatch):
    ficha = _pasada(_ficha(tmp_path),
                    [A.CORTAR, A.TRANSCRIBIR, A.ESCRIBIR_FINAL, A.CAPTION],
                    paso_silencios=True, caption_seo=True)
    md = ficha.final.ruta.with_suffix(".md")
    antes = md.read_bytes()
    monkeypatch.setattr(pipeline, "generar_caption", _revienta)
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.CAPTION], Decisiones(rehacer=frozenset({"caption"})),
                    eventos=eventos, caption_seo=True)

    assert md.read_bytes() == antes
    assert ficha.ruta("caption.md").read_bytes() == antes
    assert any(e.get("warning", "").startswith("Caption SEO falló")
               for e in eventos)


def test_transcripcion_fallida_solo_se_traga_si_la_reintenta_el_caption(
        tmp_path, monkeypatch):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)
    monkeypatch.setattr(pipeline, "transcribir", _revienta)
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.CAPTION], eventos=eventos,
                    caption_seo=True)

    assert any(e.get("warning", "").startswith("Caption SEO falló")
               for e in eventos)
    assert TRANSCRIPCION not in ficha.artefactos
    # Sin caption que la reintente, el fallo sube con su causa.
    with pytest.raises(PasoFallido, match="ffmpeg explotó"):
        ejecutar(ficha, Plan([A.TRANSCRIBIR], _panel(), []))
    assert _sin_restos(ficha)


def test_transcripcion_fallida_se_traga_si_la_reintenta_el_titulo(
        tmp_path, monkeypatch):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL],
                    paso_silencios=True)
    monkeypatch.setattr(pipeline, "transcribir", _revienta)
    eventos: list[dict] = []

    # Sin caption ni subtítulos, solo el título absorbe el fallo con su aviso.
    ejecutar(ficha, Plan([A.TRANSCRIBIR, A.TITULO], _panel(titulo=True), []),
             eventos.append)

    assert any("No se pudo transcribir para el título" in e.get("warning", "")
               for e in eventos)
    ficha = cargar(ficha.id)
    assert TRANSCRIPCION not in ficha.artefactos and TITULO not in ficha.artefactos
    assert _sin_restos(ficha)


# --- Ronda de arreglos 1 -------------------------------------------------------

def test_vertical_fallido_tras_cambiar_el_final_queda_desactualizado(
        tmp_path, monkeypatch):
    ficha = _pasada(_ficha(tmp_path), [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO,
                                       A.ESCRIBIR_FINAL, A.VERTICAL],
                    paso_audio=True, paso_vertical=True)
    monkeypatch.setattr(pipeline, "convertir_vertical", _revienta)
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL, A.VERTICAL],
                    Decisiones(regenerar_vertical=True), eventos=eventos,
                    paso_audio=True, paso_silencios=True)

    assert any(e.get("warning", "").startswith("Versión vertical falló")
               for e in eventos)
    assert ficha.desactualizado == {"vertical"}
    plan = planificar(ficha, _panel(paso_vertical=True), Decisiones())
    assert plan.acciones == [A.VERTICAL]


def test_r10_no_pierde_el_caption_si_ya_habia_un_md_en_el_destino(tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.TRANSCRIBIR, A.CAPTION, A.VERTICAL],
                    caption_seo=True, paso_vertical=True)
    caption = ficha.ruta("caption.md").read_bytes()
    unico_md = ficha.final.ruta.with_suffix(".md")
    viejo = tmp_path / "salida" / "charla_limpio.md"
    viejo.write_text("de otra pasada", encoding="utf-8")

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL, A.VERTICAL,
                            A.RETIRAR_VERTICAL_UNICO], paso_silencios=True)

    assert ficha.final.ruta.with_suffix(".md").read_bytes() == caption
    assert unico_md.read_bytes() == caption  # nada que no escribió se borra
    assert ficha.ruta("caption.md").read_bytes() == caption


def _danar_transcripcion(ficha: Ficha) -> None:
    ficha.ruta("transcripcion.json").write_text("{roto", encoding="utf-8")


def test_caption_con_transcripcion_danada_vuelve_a_transcribir(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path),
                    [A.CORTAR, A.TRANSCRIBIR, A.ESCRIBIR_FINAL, A.CAPTION],
                    paso_silencios=True, caption_seo=True)
    _danar_transcripcion(ficha)
    falsos.clear()
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.CAPTION], Decisiones(rehacer=frozenset({"caption"})),
                    eventos=eventos, caption_seo=True)

    assert any("dañada" in e.get("warning", "") for e in eventos)
    assert any(l.startswith("transcribir:") for l in falsos)
    assert any(l.startswith("generar:") for l in falsos)
    assert ficha.final.ruta.with_suffix(".md").is_file()


@pytest.mark.parametrize("panel, decisiones, esperado", [
    (dict(subtitulos=True, diseno="caja"), REHACER_SUBS, [A.QUEMAR]),
    (dict(subtitulos=True, paso_vertical=True), Decisiones(), [A.VERTICAL]),
], ids=["quemar", "vertical"])
def test_transcripcion_danada_para_subtitulos_falla_con_un_texto_claro(
        tmp_path, panel, decisiones, esperado):
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.TRANSCRIBIR, A.QUEMAR],
                    paso_silencios=True, subtitulos=True)
    final = ficha.final.ruta.read_bytes()
    _danar_transcripcion(ficha)
    plan = planificar(ficha, _panel(**panel), decisiones)
    assert plan.acciones == esperado

    with pytest.raises(PasoFallido, match="transcripción guardada .* dañada"):
        ejecutar(ficha, plan)

    assert ficha.final.ruta.read_bytes() == final
    assert _sin_restos(cargar(ficha.id))


@pytest.mark.parametrize("panel, decisiones, esperado", [
    (dict(subtitulos=True), Decisiones(), [A.TRANSCRIBIR, A.QUEMAR]),
    (dict(caption_seo=True), Decisiones(rehacer=frozenset({"caption"})),
     [A.TRANSCRIBIR, A.CAPTION]),
], ids=["subtitulos", "caption"])
def test_salida_antigua_sin_ficha_se_adopta_y_se_reprocesa(
        tmp_path, panel, decisiones, esperado):
    antigua = tmp_path / "salida" / "charla_limpio.mp4"
    antigua.parent.mkdir()
    antigua.write_bytes(b"ANTIGUA")
    (tmp_path / "salida" / "charla_limpio.md").write_text(
        "# T\n\n## Caption\nC\n\n## Hashtags\n#a\n\n## Palabras clave\n- k\n",
        encoding="utf-8")
    ficha = _ficha(tmp_path)
    assert ficha.final.coincide(antigua) and CAPTION in ficha.artefactos

    ficha = _pasada(ficha, esperado, decisiones, **panel)

    assert ficha.final.ruta == antigua.resolve()
    assert ficha.final.coincide(antigua)


def test_vertical_antiguo_adoptado_se_regenera_sin_preguntar(tmp_path):
    salida = tmp_path / "salida"
    salida.mkdir()
    (salida / "charla_limpio.mp4").write_bytes(b"ANTIGUA")
    vertical = salida / "charla_limpio_vertical.mp4"
    vertical.write_bytes(b"VERTICAL ANTIGUO")
    ficha = _ficha(tmp_path)
    assert revisar(ficha, _panel(paso_vertical=True)) == []  # sin «ya tiene vertical»

    ficha = _pasada(ficha, [A.VERTICAL], paso_vertical=True)

    assert vertical.read_bytes() == b"VERTICAL"
    assert ficha.vertical.coincide(vertical)
    assert ficha.desactualizado == set()


# --- Revisión final -----------------------------------------------------------

def _antigua(tmp_path, nombre="charla_limpio.mp4", con_srt=False) -> Path:
    """Una salida de antes de las fichas en `salida/`, con su .md (y su .srt)."""
    antigua = tmp_path / "salida" / nombre
    antigua.parent.mkdir(exist_ok=True)
    antigua.write_bytes(b"ANTIGUA")
    antigua.with_suffix(".md").write_text(
        "# T\n\n## Caption\nC\n\n## Hashtags\n#a\n\n## Palabras clave\n- k\n",
        encoding="utf-8")
    if con_srt:
        antigua.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhola mundo\n", encoding="utf-8")
    return antigua


def test_original_tras_reprocesar_una_salida_antigua_se_une_a_ella(tmp_path):
    legado = _pasada(reconocer(_antigua(tmp_path, con_srt=True), None)[0],
                     [A.CORTAR, A.ESCRIBIR_FINAL], paso_silencios=True)
    guardado = legado.original.ruta
    assert guardado.parent == legado.carpeta.resolve()

    # «Arrastra el original para rehacerlos»: se une a la misma ficha.
    ficha = _ficha(tmp_path)

    assert ficha.id == legado.id
    assert ficha.original.ruta == (tmp_path / "charla.mov").resolve()
    assert not ficha.legado and guardado.is_file()
    plan = planificar(ficha, _panel(subtitulos=True), Decisiones())
    assert plan.avisos == [] and A.QUEMAR in plan.acciones


def test_editar_fuera_una_salida_antigua_no_borra_la_version_guardada(tmp_path):
    antigua = _antigua(tmp_path, con_srt=True)
    legado = _pasada(reconocer(antigua, None)[0], [A.CORTAR, A.ESCRIBIR_FINAL],
                     paso_silencios=True)
    guardado = legado.original.ruta

    antigua.write_bytes(b"RECORTADO EN QUICKTIME")
    nueva, aviso = reconocer(antigua, None)

    assert aviso and nueva.id != legado.id
    assert nueva.final.coincide(antigua)
    assert guardado.read_bytes() == b"ANTIGUA"
    guardada = cargar(legado.id)
    assert guardada.original == legado.original and guardada.final is None
    assert CAPTION in guardada.artefactos


@pytest.mark.parametrize("nombre", ["charla_limpio.mp4", "charla_vertical.mp4"])
def test_transcripcion_de_una_salida_antigua_es_de_su_linea(tmp_path, nombre):
    (tmp_path / "salida").mkdir()
    antigua = tmp_path / "salida" / nombre
    antigua.write_bytes(b"ANTIGUA RECORTADA")
    legado, _ = reconocer(antigua, None)

    legado = _pasada(legado, [A.TRANSCRIBIR, A.CAPTION], caption_seo=True)

    assert legado.artefactos[TRANSCRIPCION].linea_tiempo == "legado"


def test_transcripcion_de_una_salida_antigua_no_vale_para_el_original(tmp_path):
    (tmp_path / "salida").mkdir()
    antigua = tmp_path / "salida" / "charla_limpio.mp4"
    antigua.write_bytes(b"ANTIGUA RECORTADA")
    _pasada(reconocer(antigua, None)[0], [A.TRANSCRIBIR, A.CAPTION],
            caption_seo=True)

    ficha = _ficha(tmp_path)  # el original se une a ella

    # La transcripción tiene los tiempos de la salida antigua: subtítulos
    # sincronizados piden transcribir el original; el caption se queda.
    plan = planificar(ficha, _panel(paso_audio=True, subtitulos=True), Decisiones())
    assert A.TRANSCRIBIR in plan.acciones
    assert ficha.artefactos[TRANSCRIPCION].linea_tiempo == "legado"
    assert CAPTION in ficha.artefactos


def test_seguimiento_de_una_salida_antigua_no_vale_para_el_original(tmp_path):
    (tmp_path / "salida").mkdir()
    antigua = tmp_path / "salida" / "charla_limpio.mp4"
    antigua.write_bytes(b"ANTIGUA RECORTADA")
    _pasada(reconocer(antigua, None)[0], [A.SEGUIMIENTO, A.VERTICAL],
            paso_vertical=True, encuadre="cara")

    ficha = _ficha(tmp_path)

    assert SEGUIMIENTO not in ficha.artefactos
    plan = planificar(ficha, _panel(paso_audio=True, paso_vertical=True,
                                    encuadre="cara"),
                      Decisiones(regenerar_vertical=True))
    assert A.SEGUIMIENTO in plan.acciones


def test_limpiar_el_audio_de_una_salida_antigua_no_vuelve_a_transcribir(
        falsos, tmp_path):
    # Sin recorte la línea de tiempo no cambia: planificador y ejecutor la
    # llaman igual ("legado") y la transcripción sigue valiendo.
    (tmp_path / "salida").mkdir()
    antigua = tmp_path / "salida" / "charla_limpio.mp4"
    antigua.write_bytes(b"ANTIGUA")
    legado = _pasada(reconocer(antigua, None)[0], [A.TRANSCRIBIR, A.QUEMAR],
                     subtitulos=True)
    falsos.clear()

    legado = _pasada(legado, [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO, A.QUEMAR],
                     paso_audio=True)

    assert not any(l.startswith("transcribir:") for l in falsos)
    assert legado.artefactos[BASE].linea_tiempo == "legado"
    assert _sin_restos(legado)


@pytest.mark.parametrize("con_ficha", [True, False])
def test_vertical_antiguo_como_unica_salida_gana_un_horizontal(tmp_path, con_ficha):
    salida = tmp_path / "salida"
    salida.mkdir()
    vertical = salida / "charla_limpio_vertical.mp4"
    vertical.write_bytes(b"VERTICAL ANTIGUO")
    if con_ficha:
        reconocer(vertical, None)
    ficha = _ficha(tmp_path)
    assert ficha.final.coincide(vertical)

    # R10 con el vertical ya en su sitio: se sustituye, sin avisos de ajeno.
    ficha = _pasada(ficha, [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO,
                            A.ESCRIBIR_FINAL, A.VERTICAL, A.RETIRAR_VERTICAL_UNICO],
                    paso_audio=True, paso_vertical=True)

    assert ficha.final.ruta == (salida / "charla_limpio.mp4").resolve()
    assert vertical.read_bytes() == b"VERTICAL" and ficha.vertical.coincide(vertical)
    assert ficha.desactualizado == set()
    assert _sin_restos(ficha)


def test_comprueba_los_destinos_antes_de_empezar(falsos, tmp_path):
    ficha = _ficha(tmp_path)
    plan = planificar(ficha, _panel(paso_silencios=True, paso_vertical=True),
                      Decisiones())
    assert A.VERTICAL in plan.acciones
    ajeno = tmp_path / "salida" / "charla_limpio_vertical.mp4"
    ajeno.parent.mkdir()
    ajeno.write_bytes(b"AJENO")
    falsos.clear()

    with pytest.raises(PasoFallido, match="fuera de la app"):
        ejecutar(ficha, plan)

    assert falsos == []  # ni auto-editor ni conversión: nada caro
    assert ajeno.read_bytes() == b"AJENO"
    assert cargar(ficha.id).final is None


def test_audio_limpio_a_medias_no_queda_registrado(tmp_path):
    ficha = _pasada(_ficha(tmp_path),
                    [A.LIMPIAR_AUDIO_ORIGINAL, A.PONER_AUDIO, A.ESCRIBIR_FINAL],
                    paso_audio=True)
    # Un directorio donde va el FLAC: sustituirlo falla.
    flac = ficha.ruta("audio_limpio.flac")
    flac.unlink()
    (flac / "ocupado").mkdir(parents=True)
    plan = planificar(ficha, _panel(paso_audio=True),
                      Decisiones(rehacer=frozenset({"audio"})))

    with pytest.raises(OSError):
        ejecutar(ficha, plan)

    assert "audio" not in cargar(ficha.id).artefactos


# --- Título de inicio ---------------------------------------------------------

CON_TITULO = [A.CORTAR, A.TRANSCRIBIR, A.TITULO, A.QUEMAR]


def _avisos(eventos: list[dict]) -> list[str]:
    return [e["warning"] for e in eventos if "warning" in e]


def test_titulo_se_guarda_y_se_quema(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path), CON_TITULO, paso_silencios=True,
                    titulo=True)

    assert ficha.artefactos[TITULO].ajustes == {"texto": "Audio limpio ya"}
    assert ficha.artefactos[HORIZONTAL].ajustes == {"titulo": "Audio limpio ya"}
    assert ficha.ruta("base.mp4").read_bytes() == b"MP4FINAL"  # R3
    assert ficha.final.ruta.read_bytes() == b"MP4SUBS"
    assert "ass:titulo" in falsos
    assert not ficha.final.ruta.with_suffix(".srt").exists()
    assert _sin_restos(ficha)


def test_titulo_fallido_sale_sin_titulo(entorno_titulo, tmp_path):
    entorno_titulo[3]["falla"] = True
    eventos: list[dict] = []

    ficha = _pasada(_ficha(tmp_path), CON_TITULO, eventos=eventos,
                    paso_silencios=True, titulo=True)

    avisos = _avisos(eventos)
    assert len(avisos) == 1 and "título" in avisos[0]
    assert TITULO not in ficha.artefactos
    assert "titulo" not in ficha.artefactos[HORIZONTAL].ajustes
    assert ficha.final.ruta.read_bytes() == b"MP4FINAL"
    assert _sin_restos(ficha)


def test_transcripcion_fallida_solo_para_el_titulo_avisa(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribir", _revienta)
    eventos: list[dict] = []

    ficha = _pasada(_ficha(tmp_path), CON_TITULO, eventos=eventos,
                    paso_silencios=True, titulo=True)

    avisos = _avisos(eventos)
    assert len(avisos) == 1 and "transcribir para el título" in avisos[0]
    assert TITULO not in ficha.artefactos
    assert ficha.final.ruta.read_bytes() == b"MP4FINAL"


def test_quitar_el_titulo_sin_subtitulos_escribe_el_final_desde_la_base(
        tmp_path):
    ficha = _pasada(_ficha(tmp_path), CON_TITULO, paso_silencios=True,
                    titulo=True)

    ficha = _pasada(ficha, [A.ESCRIBIR_FINAL], titulo=False)

    assert ficha.final.ruta.read_bytes() == b"MP4FINAL"
    assert ficha.final.coincide(ficha.final.ruta)
    assert not ficha.ruta("base.mp4").exists()
    assert ficha.artefactos[BASE].archivo is None
    assert ficha.artefactos[HORIZONTAL].ajustes == {}
    assert TITULO in ficha.artefactos  # R1: se reutiliza si se vuelve a marcar
    assert _sin_restos(ficha)


def test_titulo_en_el_vertical_se_registra(falsos, tmp_path):
    ficha = _pasada(_ficha(tmp_path), [*CON_TITULO, A.VERTICAL],
                    paso_silencios=True, paso_vertical=True, titulo=True)

    assert ficha.artefactos[VERTICAL].ajustes["titulo"] == "Audio limpio ya"
    assert falsos.count("ass:titulo") == 2  # horizontal y vertical


def test_titulo_que_falla_al_regenerar_conserva_el_anterior(
        entorno_titulo, tmp_path, monkeypatch):
    falso = pipeline.pedir_titulo
    monkeypatch.setattr(pipeline, "pedir_titulo",
                        lambda *args, **kwargs: "Viejo título aquí")
    ficha = _pasada(_ficha(tmp_path), CON_TITULO, paso_silencios=True,
                    subtitulos=True, titulo=True)
    monkeypatch.setattr(pipeline, "pedir_titulo", falso)
    entorno_titulo[3]["falla"] = True
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.TRANSCRIBIR, A.TITULO, A.QUEMAR], REHACER_SUBS,
                    eventos=eventos, subtitulos=True, titulo=True)

    avisos = _avisos(eventos)
    assert len(avisos) == 1 and "título" in avisos[0]
    assert ficha.artefactos[TITULO].ajustes == {"texto": "Viejo título aquí"}
    horizontal = ficha.artefactos[HORIZONTAL].ajustes
    assert horizontal["titulo"] == "Viejo título aquí"
    assert "subtitulos" in horizontal


def test_titulo_sin_texto_en_la_ficha_no_se_quema(entorno_titulo, tmp_path):
    ficha = _pasada(_ficha(tmp_path), CON_TITULO, paso_silencios=True,
                    subtitulos=True, titulo=True)
    ficha.artefactos[TITULO].ajustes = {}  # ficha.json editada a mano
    guardar(ficha)
    entorno_titulo[3]["falla"] = True
    eventos: list[dict] = []

    ficha = _pasada(ficha, [A.TITULO, A.QUEMAR], eventos=eventos,
                    subtitulos=True, titulo=True)

    assert len(_avisos(eventos)) == 1
    assert set(ficha.artefactos[HORIZONTAL].ajustes) == {"subtitulos"}


# --- Blog y LinkedIn ----------------------------------------------------------

@pytest.fixture()
def difusion(tmp_path, monkeypatch):
    """`preparar` y el título falsos: apuntan lo que reciben y `preparar`
    escribe el .linkedin.md junto al final. `corto` es lo que da el modelo
    del título. `agente` cuenta las veces que se lanzaría el agente del blog."""
    blog = tmp_path / "blog" / "pendientes" / "charla"
    recibido = {"preparar": [], "titulo": [], "blog": blog, "corto": "Charla corta",
                "agente": 0}

    def falso_preparar(**kwargs):
        recibido["preparar"].append(kwargs)
        linkedin.escribir("Gancho.", kwargs["final"])
        return Resultado(linkedin.rutas(kwargs["final"])[0], blog)

    def falso_titulo(transcripcion, idioma, modelo, cliente=None):
        recibido["titulo"].append(transcripcion)
        return recibido["corto"]

    def falso_agente():
        recibido["agente"] += 1
        return True

    monkeypatch.setattr(reproceso, "lanzar_agente", falso_agente)
    monkeypatch.setattr(reproceso, "preparar_difusion", falso_preparar)
    monkeypatch.setattr(reproceso, "generar_titulo", falso_titulo)
    return recibido


SILENCIOS_Y_DIFUSION = [A.CORTAR, A.TRANSCRIBIR, A.ESCRIBIR_FINAL, A.DIFUSION]


def test_difusion_guarda_artefacto(falsos, difusion, tmp_path):
    ficha = _pasada(_ficha(tmp_path), SILENCIOS_Y_DIFUSION, paso_silencios=True,
                    difusion=True, contexto_marca="Soy Alberto")

    [recibido] = difusion["preparar"]
    final = ficha.final.ruta
    assert recibido["final"].resolve() == final
    assert recibido["video_blog"].resolve() == final
    assert recibido["base"].resolve() == final  # sin subtítulos es la base (R3)
    assert [p.texto for p in recibido["palabras"]] == ["hola"]
    # Sin título en la ficha se pide uno.
    assert difusion["titulo"] == ["hola"] and recibido["titulo"] == "Charla corta"
    assert (recibido["nombre"], recibido["idioma"]) == ("charla", "es")
    assert recibido["contexto_marca"] == "Soy Alberto"
    assert recibido["modelo"] == "qwen3.5:9b"
    assert ficha.artefactos[DIFUSION] == Artefacto("hecho", None, {
        "blog": str(difusion["blog"]),
        "linkedin": str(linkedin.rutas(recibido["final"])[0])})
    assert falsos[-2:] == ["ollama:asegurar", "ollama:cerrar"]
    assert difusion["agente"] == 1  # la carpeta nueva va al agente del blog
    assert planificar(ficha, _panel(difusion=True), Decisiones()).vacio
    assert _sin_restos(ficha)


def test_difusion_usa_el_titulo_guardado_aunque_no_se_queme(
        falsos, difusion, tmp_path):
    ficha = _pasada(_ficha(tmp_path), CON_TITULO, paso_silencios=True,
                    titulo=True)

    _pasada(ficha, [A.ESCRIBIR_FINAL, A.DIFUSION], difusion=True)

    assert difusion["preparar"][0]["titulo"] == "Audio limpio ya"
    assert difusion["titulo"] == []


def test_difusion_sin_titulo_usa_el_titulo_seo(falsos, difusion, tmp_path):
    difusion["corto"] = None
    ficha = _pasada(_ficha(tmp_path), [A.CORTAR, A.ESCRIBIR_FINAL], paso_silencios=True)
    escribir_md(Caption("Cómo ahorrar tokens con Claude Code", "C", ["#ia"], []),
                ficha.final.ruta.with_suffix(".md"))

    _pasada(ficha, [A.TRANSCRIBIR, A.DIFUSION], paso_silencios=True, difusion=True)

    assert difusion["preparar"][0]["titulo"] == "Cómo ahorrar tokens con Claude"


def test_difusion_sin_titulo_ni_caption_falla_y_se_reintenta(falsos, difusion,
                                                              tmp_path):
    difusion["corto"] = None
    eventos: list[dict] = []

    ficha = _pasada(_ficha(tmp_path), SILENCIOS_Y_DIFUSION, eventos=eventos,
                    paso_silencios=True, difusion=True)

    [aviso] = _avisos(eventos)
    assert aviso.startswith("Blog y LinkedIn fallaron: No hay título para la portada")
    assert difusion["preparar"] == [] and difusion["agente"] == 0
    assert DIFUSION not in ficha.artefactos
    plan = planificar(ficha, _panel(paso_silencios=True, difusion=True), Decisiones())
    assert A.DIFUSION in plan.acciones


def test_difusion_sin_texto_de_linkedin_guarda_el_blog_y_avisa(
        falsos, difusion, tmp_path, monkeypatch):
    def preparar_sin_linkedin(**kwargs):
        difusion["preparar"].append(kwargs)
        return Resultado(None, difusion["blog"], PasoFallido("Ollama no responde"))

    monkeypatch.setattr(reproceso, "preparar_difusion", preparar_sin_linkedin)
    eventos: list[dict] = []

    ficha = _pasada(_ficha(tmp_path), SILENCIOS_Y_DIFUSION, eventos=eventos,
                    paso_silencios=True, difusion=True)

    [aviso] = _avisos(eventos)
    assert aviso.startswith("El texto de LinkedIn falló: Ollama no responde.")
    assert str(linkedin.rutas(ficha.final.ruta)[0]) in aviso
    # Se registra igual: reintentar crearía otro borrador del blog.
    assert ficha.artefactos[DIFUSION].ajustes == {
        "blog": str(difusion["blog"]), "linkedin": None}
    assert difusion["agente"] == 1
    assert planificar(ficha, _panel(difusion=True), Decisiones()).vacio


def test_difusion_falla_sin_tumbar_el_video(falsos, difusion, tmp_path,
                                            monkeypatch):
    monkeypatch.setattr(reproceso, "preparar_difusion", _revienta)
    ficha = _ficha(tmp_path)
    plan = planificar(ficha, _panel(paso_silencios=True, difusion=True),
                      Decisiones())
    eventos: list[dict] = []

    salida = ejecutar(ficha, plan, eventos.append)

    avisos = _avisos(eventos)
    assert len(avisos) == 1
    assert avisos[0].startswith("Blog y LinkedIn fallaron: ffmpeg explotó.")
    ficha = cargar(ficha.id)
    assert salida == ficha.final.ruta and salida.read_bytes() == b"MP4FINAL"
    assert DIFUSION not in ficha.artefactos and difusion["agente"] == 0
    assert falsos[-1] == "ollama:cerrar"
    assert _sin_restos(ficha)


def test_transcripcion_fallida_para_la_difusion_avisa(falsos, difusion,
                                                      tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribir", _revienta)
    eventos: list[dict] = []

    ficha = _pasada(_ficha(tmp_path), SILENCIOS_Y_DIFUSION, eventos=eventos,
                    paso_silencios=True, difusion=True)

    avisos = _avisos(eventos)
    assert len(avisos) == 1
    assert avisos[0].startswith("Blog y LinkedIn fallaron: ffmpeg explotó.")
    assert difusion["preparar"] == []
    assert DIFUSION not in ficha.artefactos
    assert ficha.final.ruta.read_bytes() == b"MP4FINAL"


def test_r10_mueve_acompanantes_de_linkedin(falsos, difusion, tmp_path):
    ficha = _pasada(_ficha(tmp_path), [A.TRANSCRIBIR, A.VERTICAL, A.DIFUSION],
                    paso_vertical=True, difusion=True)
    md, fotos = linkedin.rutas(ficha.final.ruta)
    (fotos / "01_portada.png").write_bytes(b"PNG")

    ficha = _pasada(ficha, [A.CORTAR, A.ESCRIBIR_FINAL, A.VERTICAL,
                            A.RETIRAR_VERTICAL_UNICO], paso_silencios=True)

    nuevo_md, nuevas_fotos = linkedin.rutas(ficha.final.ruta)
    assert nuevo_md.read_text(encoding="utf-8") == "Gancho."
    assert (nuevas_fotos / "01_portada.png").read_bytes() == b"PNG"
    assert not md.exists() and not fotos.exists()
    assert _sin_restos(ficha)
