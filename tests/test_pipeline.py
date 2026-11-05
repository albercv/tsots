from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline import pipeline
from videopipeline.config import PipelineConfig
from videopipeline.steps import PasoFallido, filtro_ass

from tests.falsos_pipeline import (  # noqa: F401 — fixtures
    entorno, entorno_caption, entorno_subs, entorno_titulo, entorno_vertical,
)


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
        "remux:intermedio",  # audio PCM hacia auto-editor
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
    assert llamadas[-1] == "remux"  # salida final: AAC, no PCM
    assert salida.read_bytes() == b"MP4"


def test_modo_solo_silencios(entorno, tmp_path):
    llamadas, video, _ = entorno
    salida = tmp_path / "final.mp4"
    pipeline.run(
        PipelineConfig(video=video, salida=salida, modo="solo_silencios"),
        None,
    )
    assert [l.split(":")[0] for l in llamadas] == ["rellenar", "cortar"]


def test_solo_silencios_corta_la_copia_rellena_y_la_borra(entorno, tmp_path,
                                                          monkeypatch):
    """auto-editor colapsa los huecos del audio del iPhone: debe cortar una
    copia con los huecos rellenos, que no queda en disco ni si falla."""
    llamadas, video, base = entorno
    entradas: list[Path] = []

    def falso_cortar(entrada, salida, *a, **k):
        entradas.append(entrada)
        assert entrada.read_bytes() == b"MOVRELLENO"
        raise RuntimeError("auto-editor roto")

    monkeypatch.setattr(pipeline, "cortar_silencios", falso_cortar)
    with pytest.raises(RuntimeError):
        pipeline.run(
            PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                           modo="solo_silencios"),
            None,
        )
    assert entradas and entradas[0] != video
    assert not entradas[0].exists()


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
    assert "transcribir:es:turbo" in llamadas
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

    def revienta(video_, idioma, modelo, prompt=None):
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


def test_caption_con_subtitulos_reutiliza_transcripcion(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True,
                       caption_seo=True, contexto_marca="marca X"),
        eventos.append,
    )
    assert llamadas.count("transcribir:es:turbo") == 1
    assert "generar:qwen3.5:9b:marca X:hola" in llamadas
    assert llamadas.index("ollama:asegurar") < llamadas.index("ollama:cerrar")
    md = (tmp_path / "f.md").read_text(encoding="utf-8")
    assert md.startswith("# T")
    etiquetas = [e["label"] for e in eventos if "label" in e]
    assert "Generando caption SEO" in etiquetas
    assert etiquetas.count("Transcribiendo") == 1
    assert all(e["total"] == 7 for e in eventos if "total" in e)  # 4 + 2 subs + 1


def test_caption_sin_subtitulos_transcribe(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True),
        eventos.append,
    )
    assert llamadas.count("transcribir:es:turbo") == 1
    assert "srt" not in llamadas and "quemar" not in llamadas
    etiquetas = [e["label"] for e in eventos if "label" in e]
    assert etiquetas[-2:] == ["Transcribiendo", "Generando caption SEO"]
    assert all(e["total"] == 6 for e in eventos if "total" in e)  # 4 + 2


def test_caption_off_borra_md_obsoleto(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    (tmp_path / "f.md").write_text("viejo", encoding="utf-8")
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4"), None)
    assert not any(l.startswith("generar:") or l.startswith("ollama:") for l in llamadas)
    assert not (tmp_path / "f.md").exists()


def test_caption_falla_degrada_con_warning(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, base = entorno_caption

    def revienta(*a, **k):
        raise RuntimeError("modelo caído")

    monkeypatch.setattr(pipeline, "generar_caption", revienta)
    salida = tmp_path / "f.mp4"
    (tmp_path / "f.md").write_text("viejo", encoding="utf-8")
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida, caption_seo=True), eventos.append
    )
    assert resultado == salida and salida.is_file()
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert len(avisos) == 1
    assert avisos[0].startswith("Caption SEO falló: modelo caído")
    assert "sin caption" in avisos[0]
    assert not (tmp_path / "f.md").exists()  # el .md obsoleto se borra
    assert "ollama:cerrar" in llamadas  # el servidor se cierra aunque falle


def test_caption_falla_por_ollama_no_instalado_explica_solucion(entorno_caption, tmp_path,
                                                                 monkeypatch):
    """El diagnóstico de errores.explicar debe llegar al aviso, no solo el mensaje crudo."""
    from videopipeline.steps import PasoFallido

    llamadas, video, base = entorno_caption

    def revienta(*a, **k):
        raise PasoFallido("Ollama no está instalado (no se encuentra 'ollama' en PATH)")

    monkeypatch.setattr(pipeline, "asegurar_servidor", revienta)
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida, caption_seo=True), eventos.append
    )
    assert resultado == salida and salida.is_file()
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert len(avisos) == 1
    assert "Caption SEO falló" in avisos[0]
    assert "brew install ollama" in avisos[0]


def test_caption_con_subtitulos_fallidos_transcribe_de_nuevo(entorno_caption, tmp_path,
                                                             monkeypatch):
    """Si la transcripción de subtítulos falló, el caption lo reintenta él."""
    llamadas, video, base = entorno_caption
    intentos = {"n": 0}

    def transcribir_flaky(video_, idioma, modelo, prompt=None):
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise RuntimeError("whisper caído")
        from videopipeline.subtitles import Palabra
        return [Palabra(texto="hola", inicio=0.0, fin=0.5)]

    monkeypatch.setattr(pipeline, "transcribir", transcribir_flaky)
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", subtitulos=True,
                       caption_seo=True),
        eventos.append,
    )
    assert intentos["n"] == 2
    assert (tmp_path / "f.md").is_file()


def test_caption_avisa_si_cerrar_servidor_falla(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, base = entorno_caption

    class ServidorRoto:
        def cerrar(self):
            raise ProcessLookupError("ya no existe")

    monkeypatch.setattr(pipeline, "asegurar_servidor", lambda *a, **k: ServidorRoto())
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida, caption_seo=True), eventos.append
    )
    assert resultado == salida and salida.is_file()  # el vídeo se publica igual
    assert (tmp_path / "f.md").is_file()  # el caption se generó antes del fallo
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert any("No se pudo cerrar ollama serve" in a for a in avisos)


def test_caption_reutiliza_transcripcion_aunque_falle_el_quemado(entorno_caption, tmp_path,
                                                                  monkeypatch):
    llamadas, video, base = entorno_caption

    def revienta(*a, **k):
        raise RuntimeError("ffmpeg caído")

    monkeypatch.setattr(pipeline, "quemar_subtitulos", revienta)
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", subtitulos=True,
                       caption_seo=True),
        eventos.append,
    )
    assert llamadas.count("transcribir:es:turbo") == 1
    assert (tmp_path / "f.md").is_file()
    assert (tmp_path / "f.srt").is_file()


def test_pasos_extra():
    base = PipelineConfig(video=Path("/v.mp4"))
    assert pipeline.pasos_extra(base) == 0
    assert pipeline.pasos_extra(PipelineConfig(video=Path("/v.mp4"), subtitulos=True)) == 2
    assert pipeline.pasos_extra(PipelineConfig(video=Path("/v.mp4"), caption_seo=True)) == 2
    assert pipeline.pasos_extra(
        PipelineConfig(video=Path("/v.mp4"), subtitulos=True, caption_seo=True)
    ) == 3


def test_caption_usa_idioma_subs_ingles(entorno_caption, tmp_path):
    """config.idioma_subs == 'en' se propaga a generar_caption(idioma=...)."""
    llamadas, video, base = entorno_caption
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True,
                       idioma_subs="en"),
        None,
    )
    assert "idioma_caption:en" in llamadas


def test_caption_usa_es_por_defecto(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True),
        None,
    )
    assert "idioma_caption:es" in llamadas


def test_caption_usa_es_si_idioma_subs_auto(entorno_caption, tmp_path):
    """idioma_subs='auto' no es 'es' ni 'en': el caption cae a español."""
    llamadas, video, base = entorno_caption
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True,
                       idioma_subs="auto"),
        None,
    )
    assert "idioma_caption:es" in llamadas


# --- glosario de términos ----------------------------------------------------------

def _transcripcion_cloud(monkeypatch, llamadas):
    from videopipeline.subtitles import Palabra

    def falso(video_, idioma, modelo, prompt=None):
        llamadas.append(f"prompt:{prompt}")
        return [Palabra("en", 0.0, 0.2), Palabra("Cloud", 0.3, 0.5),
                Palabra("Code.", 0.6, 0.9)]

    agrupadas: list[list[str]] = []

    def falso_agrupar(palabras, preset_id):
        from videopipeline.subtitles import Bloque
        agrupadas.append([p.texto for p in palabras])
        return [Bloque(palabras=palabras, inicio=0.0, fin=0.9)]

    monkeypatch.setattr(pipeline, "transcribir", falso)
    monkeypatch.setattr(pipeline, "agrupar", falso_agrupar)
    return agrupadas


def test_glosario_corrige_subtitulos_y_caption(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, _ = entorno_caption
    agrupadas = _transcripcion_cloud(monkeypatch, llamadas)
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", subtitulos=True,
                       caption_seo=True, glosario="Claude Code = Cloud Code"),
        None,
    )
    assert "prompt:Claude Code." in llamadas
    assert agrupadas == [["en", "Claude", "Code."]]
    assert any(l.endswith(":en Claude Code.") for l in llamadas if l.startswith("generar:"))
    assert "terminos:Claude Code" in llamadas


def test_glosario_corrige_caption_sin_subtitulos(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, _ = entorno_caption
    _transcripcion_cloud(monkeypatch, llamadas)
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True,
                       glosario="Claude Code = Cloud Code"),
        None,
    )
    assert any(l.endswith(":en Claude Code.") for l in llamadas if l.startswith("generar:"))


def test_sin_glosario_no_hay_prompt_ni_terminos(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, _ = entorno_caption
    _transcripcion_cloud(monkeypatch, llamadas)
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True),
        None,
    )
    assert "prompt:None" in llamadas
    assert not any(l.startswith("terminos:") for l in llamadas)


def test_glosario_que_falla_avisa_y_sigue(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, _ = entorno_caption
    agrupadas = _transcripcion_cloud(monkeypatch, llamadas)

    def revienta(palabras, g):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "corregir_glosario", revienta)
    eventos: list[dict] = []
    salida = pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", subtitulos=True,
                       glosario="Claude Code = Cloud Code"),
        eventos.append,
    )
    assert salida.exists()
    assert agrupadas == [["en", "Cloud", "Code."]]
    assert any("boom" in e.get("warning", "") for e in eventos)


def _sin_temporales(carpeta: Path) -> bool:
    return [p for p in carpeta.iterdir() if p.name.startswith(".")] == []


def test_vertical_off_no_convierte(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4"), None)
    assert not any(l.startswith("vertical") for l in llamadas)
    assert not (tmp_path / "f_vertical.mp4").exists()


def test_completo_con_vertical_dos_archivos(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    eventos: list[dict] = []
    r = pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True),
        eventos.append,
    )
    assert r == tmp_path / "f.mp4" and r.read_bytes() == b"MP4FINAL"
    assert (tmp_path / "f_vertical.mp4").read_bytes() == b"VERTICAL"
    assert llamadas[-1].startswith("vertical:f.mp4:False:False:")
    pasos = [e for e in eventos if "step" in e]
    assert [e["step"] for e in pasos] == [1, 2, 3, 4, 5]
    assert {e["total"] for e in pasos} == {5}
    assert pasos[-1]["label"] == "Convirtiendo a vertical"
    assert _sin_temporales(tmp_path)


def test_solo_silencios_con_vertical(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                       paso_audio=False, paso_vertical=True),
        None,
    )
    assert [l.split(":")[0] for l in llamadas] == ["rellenar", "cortar", "vertical"]
    assert (tmp_path / "f.mp4").read_bytes() == b"MP4FINAL"
    assert (tmp_path / "f_vertical.mp4").read_bytes() == b"VERTICAL"
    assert _sin_temporales(tmp_path)


def test_vertical_con_subs_transcribe_una_vez(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True,
                       subtitulos=True),
        eventos.append,
    )
    assert llamadas.count("transcribir:es:turbo") == 1
    assert "ass:75:(1920, 1080):100" in llamadas
    assert "ass:75:(1080, 1920):100" in llamadas
    vertical = next(l for l in llamadas if l.startswith("vertical"))
    assert vertical.startswith("vertical:.f_tmp.mp4:True:False:")
    assert vertical.endswith(f",{filtro_ass('subs_vertical.ass')},format=yuv420p[v]")
    assert (tmp_path / "f.mp4").read_bytes() == b"MP4SUBS"
    assert {e["total"] for e in eventos if "step" in e} == {7}
    assert _sin_temporales(tmp_path)


def test_solo_vertical(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    r = pipeline.run(
        PipelineConfig(video=video, salida=tmp_path, paso_audio=False, paso_silencios=False, paso_vertical=True), None
    )
    assert r == tmp_path / "charla_vertical.mp4" and r.read_bytes() == b"VERTICAL"
    assert [l.split(":")[0] for l in llamadas] == ["vertical"]
    assert llamadas[0].startswith("vertical:charla.mov:False:True:")
    assert _sin_temporales(tmp_path)


def test_solo_vertical_cara_con_subs(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path, paso_audio=False, paso_silencios=False, paso_vertical=True,
                       encuadre="cara", subtitulos=True),
        eventos.append,
    )
    pasos = [e for e in eventos if "step" in e]
    assert sorted({e["step"] for e in pasos}) == [1, 2, 3]
    assert {e["total"] for e in pasos} == {3}
    etiquetas = [e["label"] for e in pasos]
    assert "Detectando caras" in etiquetas
    assert etiquetas[-1] == "Convirtiendo a vertical"
    assert "caras" in llamadas and "crop@v=1440:1080:10:0" in llamadas[-1]
    assert llamadas[-1].split(":")[2] == "True"


def test_vertical_falla_degrada(entorno_vertical, tmp_path, monkeypatch):
    _, video, _, _ = entorno_vertical

    def revienta(video_, salida, *args, **kwargs):
        salida.write_bytes(b"MEDIO")
        raise PasoFallido("boom")

    monkeypatch.setattr(pipeline, "convertir_vertical", revienta)
    eventos: list[dict] = []
    r = pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True),
        eventos.append,
    )
    assert r.read_bytes() == b"MP4FINAL"
    assert any(
        e.get("warning", "").startswith("Versión vertical falló: ") for e in eventos
    )
    assert not (tmp_path / "f_vertical.mp4").exists()
    assert _sin_temporales(tmp_path)


def test_solo_vertical_falla_es_error(entorno_vertical, tmp_path, monkeypatch):
    _, video, _, _ = entorno_vertical

    def revienta(video_, salida, *args, **kwargs):
        salida.write_bytes(b"MEDIO")
        raise PasoFallido("boom")

    monkeypatch.setattr(pipeline, "convertir_vertical", revienta)
    with pytest.raises(PasoFallido):
        pipeline.run(
            PipelineConfig(video=video, salida=tmp_path, paso_audio=False, paso_silencios=False, paso_vertical=True), None
        )
    assert _sin_temporales(tmp_path)


def test_ya_vertical_usa_barras_y_avisa(entorno_vertical, tmp_path):
    llamadas, video, _, resolucion = entorno_vertical
    resolucion["valor"] = (1080, 1920)
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True),
        eventos.append,
    )
    assert "pad=1080:1920" in llamadas[-1]
    assert any(
        e.get("warning", "").startswith("El vídeo ya era vertical") for e in eventos
    )


def test_cara_sin_caras_centra_la_ventana_ancha(entorno_vertical, tmp_path, monkeypatch):
    llamadas, video, _, _ = entorno_vertical
    monkeypatch.setattr(pipeline, "preparar_seguimiento", lambda *a, **k: None)
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True,
                       encuadre="cara"),
        eventos.append,
    )
    # La misma ventana 4:3 con fondo difuminado, quieta en el centro (no el 9:16).
    assert "[0:v]crop=1440:1080,split" in llamadas[-1] and "boxblur" in llamadas[-1]
    assert "sendcmd" not in llamadas[-1] and "crop=606" not in llamadas[-1]
    assert any(
        e.get("warning", "").startswith("No se detectó ninguna cara") for e in eventos
    )


def test_silencios_y_vertical(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    eventos: list[dict] = []
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_audio=False, paso_vertical=True), eventos.append)
    assert [l.split(":")[0] for l in llamadas] == ["rellenar", "cortar", "vertical"]
    assert llamadas[-1].startswith("vertical:f.mp4:False:False:")
    assert {e["total"] for e in eventos if "step" in e} == {2}


def test_audio_y_vertical_sin_silencios(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_silencios=False, paso_vertical=True), None)
    assert [l.split(":")[0] for l in llamadas][-1] == "vertical"
    assert (tmp_path / "f.mp4").exists() and (tmp_path / "f_vertical.mp4").exists()
    assert _sin_temporales(tmp_path)


def test_solo_vertical_desde_original(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(PipelineConfig(video=video, salida=tmp_path, paso_audio=False,
                                paso_silencios=False, paso_vertical=True), None)
    assert llamadas == [l for l in llamadas if l.startswith("vertical")]
    assert llamadas[0].startswith("vertical:charla.mov:False:True:")


def test_solo_subtitulos_quema_desde_original(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    r = pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                    paso_audio=False, paso_silencios=False,
                                    subtitulos=True), None)
    assert r.read_bytes() == b"MP4SUBS" and "quemar:original" in llamadas
    assert _sin_temporales(tmp_path)


def test_solo_subtitulos_falla_si_falla_el_quemado(entorno_vertical, tmp_path,
                                                   monkeypatch):
    _, video, _, _ = entorno_vertical

    def revienta(*args, **kwargs):
        raise PasoFallido("boom")

    monkeypatch.setattr(pipeline, "quemar_subtitulos", revienta)
    with pytest.raises(PasoFallido):
        pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                    paso_audio=False, paso_silencios=False,
                                    subtitulos=True), None)
    assert not (tmp_path / "f.mp4").exists() and _sin_temporales(tmp_path)


def test_solo_vertical_con_caption_lo_genera_sobre_el_vertical(entorno_vertical,
                                                              tmp_path, monkeypatch):
    llamadas, video, _, _ = entorno_vertical

    def falso_caption(config, video_publicable, final, *args):
        llamadas.append(f"caption:{final.name}")

    monkeypatch.setattr(pipeline, "_fase_caption", falso_caption)
    pipeline.run(PipelineConfig(video=video, salida=tmp_path, paso_audio=False,
                                paso_silencios=False, paso_vertical=True,
                                subtitulos=True, caption_seo=True), None)
    assert llamadas[-1] == "caption:charla_vertical.mp4"


def test_cara_sin_detector_centra_la_ventana_ancha(entorno_vertical, tmp_path, monkeypatch):
    llamadas, video, _, _ = entorno_vertical

    def revienta(*args, **kwargs):
        raise PasoFallido("sin pesos")

    monkeypatch.setattr(pipeline, "preparar_seguimiento", revienta)
    eventos: list[dict] = []
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_vertical=True, encuadre="cara"), eventos.append)
    assert "[0:v]crop=1440:1080,split" in llamadas[-1] and "sendcmd" not in llamadas[-1]
    assert any("detector de caras" in e.get("warning", "") for e in eventos)


def test_solo_subtitulos_sin_bloques_no_mueve_el_original(entorno_vertical, tmp_path,
                                                          monkeypatch):
    # Sin ningún paso aplicado, publicar el "resultado" sería mover el original.
    _, video, _, _ = entorno_vertical
    monkeypatch.setattr(pipeline, "agrupar", lambda palabras, preset_id: [])
    with pytest.raises(PasoFallido):
        pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                    paso_audio=False, paso_silencios=False,
                                    subtitulos=True), None)
    assert video.read_bytes() == b"VID"
    assert not (tmp_path / "f.mp4").exists()


@pytest.mark.parametrize("pasos", [
    {"paso_vertical": True, "subtitulos": True},  # vertical + subtítulos
    {"subtitulos": True},                         # solo subtítulos
])
def test_subtitulos_sin_base_transcriben_audio_rellenado(entorno_vertical, tmp_path,
                                                         monkeypatch, pasos):
    # Whisper ignora los huecos del audio del iPhone: sin pasos de audio ni
    # silencios hay que transcribir una pista continua o los subtítulos se adelantan.
    llamadas, video, _, _ = entorno_vertical
    fuentes: list[Path] = []

    def falso_transcribir(video_, idioma, modelo, prompt=None):
        fuentes.append(Path(video_))
        from videopipeline.subtitles import Palabra
        return [Palabra(texto="hola", inicio=0.0, fin=0.5)]

    monkeypatch.setattr(pipeline, "transcribir", falso_transcribir)
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_audio=False, paso_silencios=False, **pasos), None)
    assert "extraer:16000" in llamadas
    assert fuentes and fuentes[0].suffix == ".wav" and fuentes[0] != video
    assert not fuentes[0].exists()


def test_vertical_falla_borra_vertical_anterior(entorno_vertical, tmp_path, monkeypatch):
    _, video, _, _ = entorno_vertical
    anterior = tmp_path / "f_vertical.mp4"
    anterior.write_bytes(b"VIEJO")

    def revienta(*args, **kwargs):
        raise PasoFallido("boom")

    monkeypatch.setattr(pipeline, "convertir_vertical", revienta)
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_vertical=True), None)
    assert (tmp_path / "f.mp4").exists() and not anterior.exists()


def test_vertical_nunca_sobrescribe_la_entrada(entorno_vertical, tmp_path):
    llamadas, _, _, _ = entorno_vertical
    entrada = tmp_path / "X_vertical.mp4"
    entrada.write_bytes(b"ORIGINAL")
    with pytest.raises(ValueError, match="salida"):
        pipeline.run(PipelineConfig(video=entrada, salida=tmp_path / "X.mp4",
                                    paso_vertical=True), None)
    assert entrada.read_bytes() == b"ORIGINAL" and llamadas == []


# --- título de inicio --------------------------------------------------------------

def test_titulo_sin_subtitulos_transcribe_y_quema_solo_el_titulo(entorno_titulo, tmp_path):
    llamadas, video, _, _ = entorno_titulo
    salida = tmp_path / "f.mp4"
    pipeline.run(PipelineConfig(video=video, salida=salida, paso_audio=False,
                                titulo=True), None)
    orden = ["cortar", "transcribir:es:turbo", "ollama:asegurar",
             "titulo:qwen3.5:9b:es", "ollama:cerrar", "ass:titulo", "quemar"]
    posiciones = [next(i for i, l in enumerate(llamadas) if l.startswith(o))
                  for o in orden]
    assert posiciones == sorted(posiciones)
    assert not any(l.startswith("agrupar") for l in llamadas)
    assert not salida.with_suffix(".srt").exists()
    assert salida.read_bytes() == b"MP4SUBS"


def test_titulo_y_subtitulos_en_el_mismo_ass(entorno_titulo, tmp_path):
    llamadas, video, _, _ = entorno_titulo
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                subtitulos=True, titulo=True), None)
    assert llamadas.count("transcribir:es:turbo") == 1
    assert llamadas.count("quemar") == 1
    assert "ass:titulo" in llamadas
    assert (tmp_path / "f.srt").is_file()


def test_titulo_fallido_avisa_y_guarda_el_video(entorno_titulo, tmp_path):
    llamadas, video, _, estado = entorno_titulo
    estado["falla"] = True
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(PipelineConfig(video=video, salida=salida, paso_audio=False,
                                titulo=True), eventos.append)
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert len(avisos) == 1 and "título" in avisos[0]
    assert "Ollama no responde" in avisos[0] and "sin título" in avisos[0]
    assert "quemar" not in llamadas and "ass:titulo" not in llamadas
    assert "ollama:cerrar" in llamadas  # el servidor se cierra aunque falle
    assert salida.read_bytes() == b"MP4FINAL"


def test_titulo_sin_transcripcion_avisa_y_guarda_el_video(entorno_titulo, tmp_path,
                                                          monkeypatch):
    llamadas, video, _, _ = entorno_titulo

    def revienta(video_, idioma, modelo, prompt=None):
        raise RuntimeError("whisper caído")

    monkeypatch.setattr(pipeline, "transcribir", revienta)
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(PipelineConfig(video=video, salida=salida, paso_audio=False,
                                titulo=True), eventos.append)
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert len(avisos) == 1
    assert avisos[0].startswith("No se pudo transcribir para el título: whisper caído")
    assert not any(l.startswith("titulo:") or l == "quemar" for l in llamadas)
    assert salida.read_bytes() == b"MP4FINAL"


def test_titulo_en_el_vertical(entorno_titulo, entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_audio=False, paso_vertical=True,
                                titulo=True), None)
    vertical = next(l for l in llamadas if l.startswith("vertical"))
    assert vertical.startswith("vertical:.f_tmp.mp4:True:False:")
    assert filtro_ass("subs_vertical.ass") in vertical
    assert llamadas.count("ass:titulo") == 2  # horizontal y vertical
    assert _sin_temporales(tmp_path)


def test_caption_reutiliza_la_transcripcion_del_titulo(entorno_titulo, tmp_path):
    llamadas, video, _, _ = entorno_titulo
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_audio=False, titulo=True,
                                caption_seo=True), None)
    assert llamadas.count("transcribir:es:turbo") == 1
    assert (tmp_path / "f.md").is_file()


@pytest.mark.parametrize("pasos, total", [
    ({"paso_audio": False, "titulo": True}, 4),
    ({"paso_audio": False, "paso_silencios": False, "subtitulos": True,
      "titulo": True}, 3),
    ({"paso_audio": False, "titulo": True, "caption_seo": True}, 5),
    ({"paso_audio": False, "paso_silencios": False, "paso_vertical": True,
      "encuadre": "cara", "titulo": True}, 4),
    ({"paso_audio": False, "paso_silencios": False, "paso_vertical": True,
      "titulo": True}, 3),
])
def test_total_pasos_con_titulo(entorno_titulo, entorno_vertical, tmp_path, pasos,
                                total):
    _, video, _, _ = entorno_vertical
    config = PipelineConfig(video=video, salida=tmp_path / "f.mp4", **pasos)
    assert pipeline.total_pasos(config) == total
    eventos: list[dict] = []
    pipeline.run(config, eventos.append)
    assert {e["total"] for e in eventos if "step" in e} == {total}
    assert max(e["step"] for e in eventos if "step" in e) == total
