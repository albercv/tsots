from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline import pipeline
from videopipeline.config import PipelineConfig


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

    def falso_remux(video_, audio, salida):
        llamadas.append("remux")
        salida.write_bytes(b"MP4")

    def falso_cortar(entrada, salida, margen, umbral, silencios, velocidad,
                     on_percent=None, on_aviso=None):
        llamadas.append(f"cortar:{margen}:{umbral}:{silencios}:{velocidad}")
        if on_aviso is not None and "_avisa" in entrada.stem:
            on_aviso("reencodado por auto-editor")
        salida.write_bytes(b"MP4FINAL")

    monkeypatch.setattr(pipeline, "extraer_audio", falso_extraer)
    monkeypatch.setattr(pipeline, "limpiar_audio", falso_limpiar)
    monkeypatch.setattr(pipeline, "remux", falso_remux)
    monkeypatch.setattr(pipeline, "cortar_silencios", falso_cortar)
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    return llamadas, video, tmp_path


def test_modo_completo(entorno, tmp_path):
    llamadas, video, base = entorno
    salida = tmp_path / "final.mp4"
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida), eventos.append
    )
    assert resultado == salida
    assert salida.read_bytes() == b"MP4FINAL"
    assert llamadas == [
        "extraer:48000",
        "limpiar:speech_enhancement:MossFormer2_SE_48K",
        "remux",
        "cortar:0.2s:4%:cortar:4",
    ]
    assert [e["step"] for e in eventos] == [1, 2, 3, 4]
    assert all(e["total"] == 4 for e in eventos)
    # Intermedios en audio_procesado/<nombre>/
    assert (base / "audio_procesado" / "charla" / "charla_original.wav").is_file()
    assert (base / "audio_procesado" / "charla" / "charla_audio_limpio.wav").is_file()


def test_modo_solo_audio(entorno, tmp_path):
    llamadas, video, _ = entorno
    salida = tmp_path / "final.mp4"
    pipeline.run(
        PipelineConfig(video=video, salida=salida, modo="solo_audio"),
        None,
    )
    assert [l.split(":")[0] for l in llamadas] == ["extraer", "limpiar", "remux"]
    assert salida.read_bytes() == b"MP4"


def test_modo_solo_silencios(entorno, tmp_path):
    llamadas, video, _ = entorno
    salida = tmp_path / "final.mp4"
    pipeline.run(
        PipelineConfig(video=video, salida=salida, modo="solo_silencios"),
        None,
    )
    assert [l.split(":")[0] for l in llamadas] == ["cortar"]


def test_sample_rate_por_modelo(entorno, tmp_path):
    llamadas, video, _ = entorno
    pipeline.run(
        PipelineConfig(
            video=video,
            salida=tmp_path / "f.mp4",
            modo="solo_audio",
            modelo="FRCRN_SE_16K",
        ),
        None,
    )
    assert llamadas[0] == "extraer:16000"


def test_valida_antes_de_ejecutar(entorno, tmp_path):
    llamadas, video, _ = entorno
    with pytest.raises(ValueError):
        pipeline.run(PipelineConfig(video=video, modo="turbo"), None)
    assert llamadas == []


def test_video_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline.run(PipelineConfig(video=tmp_path / "nada.mp4"), None)


def test_salida_igual_a_entrada(entorno):
    _, video, _ = entorno
    with pytest.raises(ValueError, match="salida"):
        pipeline.run(PipelineConfig(video=video, salida=video), None)


def test_salida_alias_relativo_de_entrada(entorno, monkeypatch):
    _, video, _ = entorno
    monkeypatch.chdir(video.parent)
    with pytest.raises(ValueError, match="salida"):
        pipeline.run(
            PipelineConfig(video=video, salida=Path(video.name)), None
        )


def test_resultado_atomico(entorno, tmp_path):
    """El final se escribe vía tmp oculto + replace; no queda el temporal."""
    _, video, _ = entorno
    salida = tmp_path / "final.mp4"
    pipeline.run(PipelineConfig(video=video, salida=salida), None)
    temporales = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert temporales == []


@pytest.fixture()
def entorno_subs(entorno, monkeypatch, tmp_path):
    """Extiende `entorno` mockeando la fase de subtítulos."""
    llamadas, video, base = entorno

    def falso_transcribir(video_, idioma, modelo):
        llamadas.append(f"transcribir:{idioma}:{modelo}")
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

    def falso_quemar(video_, ass, salida, on_percent=None):
        llamadas.append("quemar")
        salida.write_bytes(b"MP4SUBS")

    monkeypatch.setattr(pipeline, "transcribir", falso_transcribir)
    monkeypatch.setattr(pipeline, "agrupar", falso_agrupar)
    monkeypatch.setattr(pipeline, "generar_srt", falso_srt)
    monkeypatch.setattr(pipeline, "generar_ass", falso_ass)
    monkeypatch.setattr(pipeline, "resolucion_video", falso_resolucion)
    monkeypatch.setattr(pipeline, "quemar_subtitulos", falso_quemar)
    return llamadas, video, base


def test_subs_off_no_toca_nada(entorno_subs, tmp_path):
    llamadas, video, _ = entorno_subs
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4"), None)
    assert not any(
        l.startswith(("transcribir", "agrupar", "srt", "ass", "quemar"))
        for l in llamadas
    )


def test_subs_on_modo_completo(entorno_subs, tmp_path):
    llamadas, video, _ = entorno_subs
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True,
                       diseno="caja", posicion_subs=80, tamano_subs=120),
        eventos.append,
    )
    assert resultado == salida
    assert salida.read_bytes() == b"MP4SUBS"
    assert "transcribir:es:small" in llamadas
    assert "agrupar:caja" in llamadas
    assert "ass:80:(1080, 1920):120" in llamadas
    assert llamadas[-1] == "quemar"
    assert (tmp_path / "f.srt").is_file()
    pasos = [e["step"] for e in eventos if "step" in e]
    assert pasos == [1, 2, 3, 4, 5, 6]
    assert all(e["total"] == 6 for e in eventos if "step" in e)
    etiquetas = [e["label"] for e in eventos if "step" in e]
    assert "transcribiendo" in etiquetas[4].lower()
    assert "Quemando subtítulos" in etiquetas[5]


def test_subs_on_solo_silencios_total_3(entorno_subs, tmp_path):
    llamadas, video, _ = entorno_subs
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                       modo="solo_silencios", subtitulos=True),
        eventos.append,
    )
    assert all(e["total"] == 3 for e in eventos if "step" in e)


def test_transcripcion_falla_degrada_con_warning(entorno_subs, tmp_path,
                                                 monkeypatch):
    llamadas, video, _ = entorno_subs

    def revienta(video_, idioma, modelo):
        raise RuntimeError("sin GPU")

    monkeypatch.setattr(pipeline, "transcribir", revienta)
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True),
        eventos.append,
    )
    assert resultado == salida
    assert salida.read_bytes() == b"MP4FINAL"  # vídeo sin subs publicado
    assert not (tmp_path / "f.srt").exists()   # sin srt
    warnings = [e for e in eventos if "warning" in e]
    assert len(warnings) == 1 and "sin GPU" in warnings[0]["warning"]


def test_cero_palabras_degrada_con_warning(entorno_subs, tmp_path, monkeypatch):
    llamadas, video, _ = entorno_subs
    monkeypatch.setattr(pipeline, "transcribir", lambda v, i, m: [])
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True),
        eventos.append,
    )
    assert salida.read_bytes() == b"MP4FINAL"
    assert any("warning" in e for e in eventos)


def test_quemado_falla_conserva_srt(entorno_subs, tmp_path, monkeypatch):
    llamadas, video, _ = entorno_subs
    from videopipeline.steps import PasoFallido

    def revienta(video_, ass, salida, on_percent=None):
        raise PasoFallido("ffmpeg explotó")

    monkeypatch.setattr(pipeline, "quemar_subtitulos", revienta)
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True),
        eventos.append,
    )
    assert salida.read_bytes() == b"MP4FINAL"  # sin subs
    assert (tmp_path / "f.srt").is_file()      # srt conservado
    assert any("warning" in e for e in eventos)


def test_quemado_falla_limpia_temporales(entorno_subs, tmp_path, monkeypatch):
    llamadas, video, base = entorno_subs
    from videopipeline.steps import PasoFallido

    def revienta_parcial(video_, ass, salida, on_percent=None):
        salida.write_bytes(b"PARCIAL")
        raise PasoFallido("ffmpeg explotó")

    monkeypatch.setattr(pipeline, "quemar_subtitulos", revienta_parcial)
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True),
        eventos.append,
    )
    assert salida.read_bytes() == b"MP4FINAL"  # vídeo final publicado sin subs
    assert (tmp_path / "f.srt").is_file()      # srt conservado
    ocultos = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert ocultos == []
    assert not list((base / "audio_procesado").rglob("subs.ass"))


def test_aviso_de_cortar_silencios_llega_como_warning(entorno, tmp_path):
    """El reintento con vídeo reencodado debe quedar visible (⚠ + log)."""
    llamadas, video, base = entorno
    video_avisa = video.with_name("charla_avisa.mov")
    video_avisa.write_bytes(b"VID")
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video_avisa, salida=tmp_path / "f.mp4"),
        eventos.append,
    )
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert avisos == ["reencodado por auto-editor"]


def test_aviso_de_cortar_silencios_modo_solo_silencios(entorno, tmp_path):
    llamadas, video, base = entorno
    video_avisa = video.with_name("charla_avisa.mov")
    video_avisa.write_bytes(b"VID")
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video_avisa, salida=tmp_path / "f.mp4",
                       modo="solo_silencios"),
        eventos.append,
    )
    assert [e["warning"] for e in eventos if "warning" in e] == [
        "reencodado por auto-editor"
    ]
