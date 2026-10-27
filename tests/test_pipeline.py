from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline import pipeline
from videopipeline.config import PipelineConfig
from videopipeline.steps import PasoFallido


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

    monkeypatch.setattr(pipeline, "extraer_audio", falso_extraer)
    monkeypatch.setattr(pipeline, "limpiar_audio", falso_limpiar)
    monkeypatch.setattr(pipeline, "remux", falso_remux)
    monkeypatch.setattr(pipeline, "rellenar_huecos_audio", falso_rellenar)
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

    monkeypatch.setattr(pipeline, "asegurar_servidor", falso_asegurar)
    monkeypatch.setattr(pipeline, "generar_caption", falso_generar)
    return llamadas, video, base


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


@pytest.fixture()
def entorno_vertical(entorno_subs, monkeypatch):
    """Extiende `entorno_subs` mockeando la conversión y el seguimiento."""
    llamadas, video, base = entorno_subs
    resolucion = {"valor": (1920, 1080)}
    monkeypatch.setattr(pipeline, "resolucion_video", lambda v: resolucion["valor"])

    def falso_convertir(video_, salida, filtro, cwd, usa_ass, desde_original=False,
                        on_percent=None):
        llamadas.append(
            f"vertical:{Path(video_).name}:{usa_ass}:{desde_original}:{filtro}")
        salida.write_bytes(b"VERTICAL")

    def falso_seguimiento(video_, ancho, alto, ruta_cmd, on_percent=None,
                          detector=None):
        llamadas.append("caras")
        ruta_cmd.write_text("0.000 crop@v x 10;")
        return 10

    monkeypatch.setattr(pipeline, "convertir_vertical", falso_convertir)
    monkeypatch.setattr(pipeline, "preparar_seguimiento", falso_seguimiento)
    return llamadas, video, base, resolucion


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
    assert vertical.endswith("ass=subs_vertical.ass,format=yuv420p[v]")
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
    assert "caras" in llamadas and "crop@v=606:1080:10:0" in llamadas[-1]
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


def test_cara_sin_caras_cae_a_central(entorno_vertical, tmp_path, monkeypatch):
    llamadas, video, _, _ = entorno_vertical
    monkeypatch.setattr(pipeline, "preparar_seguimiento", lambda *a, **k: None)
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True,
                       encuadre="cara"),
        eventos.append,
    )
    assert "crop=606:1080" in llamadas[-1] and "sendcmd" not in llamadas[-1]
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


def test_cara_sin_detector_cae_a_central(entorno_vertical, tmp_path, monkeypatch):
    llamadas, video, _, _ = entorno_vertical

    def revienta(*args, **kwargs):
        raise PasoFallido("sin pesos")

    monkeypatch.setattr(pipeline, "preparar_seguimiento", revienta)
    eventos: list[dict] = []
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_vertical=True, encuadre="cara"), eventos.append)
    assert "crop=606:1080" in llamadas[-1]
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
