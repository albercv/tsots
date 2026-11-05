"""Falsos de los pasos del pipeline: registran el orden de llamada y no
ejecutan ffmpeg ni modelos. Los usan los tests del pipeline y del ejecutor."""
from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline import pipeline, reproceso


def _parchear(monkeypatch, nombre: str, valor) -> None:
    """El ejecutor importa algunos pasos por su cuenta: se sustituyen en los dos."""
    for modulo in (pipeline, reproceso):
        if hasattr(modulo, nombre):
            monkeypatch.setattr(modulo, nombre, valor)


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    """Mockea todos los pasos y registra el orden de llamada."""
    llamadas: list[str] = []
    video = tmp_path / "charla.mov"
    video.write_bytes(b"VID")

    def falso_extraer(video_, wav, sample_rate):
        llamadas.append(f"extraer:{sample_rate}")
        wav.write_bytes(b"WAV")

    def falso_limpiar(entrada, salida, tarea, modelo):
        llamadas.append(f"limpiar:{tarea}:{modelo}")
        salida.write_bytes(b"WAVLIMPIO")

    def falso_remux(video_, audio, salida, intermedio=False):
        llamadas.append("remux:intermedio" if intermedio else "remux")
        salida.write_bytes(b"MP4")

    def falso_rellenar(video_, salida):
        llamadas.append("rellenar")
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_bytes(b"MOVRELLENO")

    def falso_cortar(entrada, salida, margen, umbral, silencios, velocidad,
                     on_percent=None, on_aviso=None):
        llamadas.append(f"cortar:{margen}:{umbral}:{silencios}:{velocidad}")
        if on_aviso is not None and "_avisa" in entrada.stem:
            on_aviso("reencodado por auto-editor")
        salida.write_bytes(b"MP4FINAL")

    _parchear(monkeypatch, "extraer_audio", falso_extraer)
    _parchear(monkeypatch, "limpiar_audio", falso_limpiar)
    _parchear(monkeypatch, "remux", falso_remux)
    _parchear(monkeypatch, "rellenar_huecos_audio", falso_rellenar)
    _parchear(monkeypatch, "cortar_silencios", falso_cortar)
    _parchear(monkeypatch, "BASE_DIR", tmp_path)
    return llamadas, video, tmp_path


@pytest.fixture()
def entorno_subs(entorno, monkeypatch, tmp_path):
    """Extiende `entorno` mockeando la fase de subtítulos."""
    llamadas, video, base = entorno

    def falso_transcribir(video_, idioma, modelo, prompt=None):
        llamadas.append(f"transcribir:{idioma}:{modelo}")
        if prompt:
            llamadas.append(f"prompt:{prompt}")
        from videopipeline.subtitles import Palabra
        return [Palabra(texto="hola", inicio=0.0, fin=0.5)]

    def falso_agrupar(palabras, preset_id):
        llamadas.append(f"agrupar:{preset_id}")
        from videopipeline.subtitles import Bloque
        return [Bloque(palabras=palabras, inicio=0.0, fin=0.5)]

    def falso_srt(bloques, ruta):
        llamadas.append("srt")
        ruta.write_text("srt", encoding="utf-8")

    def falso_ass(bloques, preset_id, posicion, resolucion, ruta, tamano=100):
        llamadas.append(f"ass:{posicion}:{resolucion}:{tamano}")
        ruta.write_text("ass", encoding="utf-8")

    def falso_resolucion(video_):
        return (1080, 1920)

    def falso_quemar(video_, ass, salida, on_percent=None, desde_original=False):
        llamadas.append("quemar:original" if desde_original else "quemar")
        salida.write_bytes(b"MP4SUBS")

    _parchear(monkeypatch, "transcribir", falso_transcribir)
    _parchear(monkeypatch, "agrupar", falso_agrupar)
    _parchear(monkeypatch, "generar_srt", falso_srt)
    _parchear(monkeypatch, "generar_ass", falso_ass)
    _parchear(monkeypatch, "resolucion_video", falso_resolucion)
    _parchear(monkeypatch, "quemar_subtitulos", falso_quemar)
    return llamadas, video, base


@pytest.fixture()
def entorno_caption(entorno_subs, monkeypatch):
    """Extiende `entorno_subs` mockeando Ollama y el generador de caption."""
    llamadas, video, base = entorno_subs

    class ServidorFalso:
        def cerrar(self):
            llamadas.append("ollama:cerrar")

    def falso_asegurar(*args, **kwargs):
        llamadas.append("ollama:asegurar")
        return ServidorFalso()

    def falso_generar(transcripcion, contexto_marca, modelo, cliente=None,
                      idioma="es", terminos=()):
        llamadas.append(f"generar:{modelo}:{contexto_marca}:{transcripcion}")
        if terminos:
            llamadas.append(f"terminos:{','.join(terminos)}")
        llamadas.append(f"idioma_caption:{idioma}")
        from videopipeline.caption import Caption
        return Caption(titulo="T", caption="C", hashtags=["#a"], palabras_clave=["k"])

    _parchear(monkeypatch, "asegurar_servidor", falso_asegurar)
    _parchear(monkeypatch, "generar_caption", falso_generar)
    return llamadas, video, base


@pytest.fixture()
def entorno_vertical(entorno_subs, monkeypatch):
    """Extiende `entorno_subs` mockeando la conversión y el seguimiento."""
    llamadas, video, base = entorno_subs
    resolucion = {"valor": (1920, 1080)}
    _parchear(monkeypatch, "resolucion_video", lambda v: resolucion["valor"])

    def falso_convertir(video_, salida, filtro, cwd, usa_ass, desde_original=False,
                        on_percent=None, tramo=None):
        if tramo is not None:  # antes de la llamada: `llamadas[-1]` sigue siendo ella
            llamadas.append(f"tramo:{tramo[0]}:{tramo[1]}")
        llamadas.append(
            f"vertical:{Path(video_).name}:{usa_ass}:{desde_original}:{filtro}")
        salida.write_bytes(b"VERTICAL")

    def falso_seguimiento(video_, ancho, alto, ruta_cmd, on_percent=None,
                          detector=None):
        llamadas.append("caras")
        ruta_cmd.write_text("0.000 crop@v x 10;")
        return 10

    _parchear(monkeypatch, "convertir_vertical", falso_convertir)
    _parchear(monkeypatch, "preparar_seguimiento", falso_seguimiento)
    return llamadas, video, base, resolucion
