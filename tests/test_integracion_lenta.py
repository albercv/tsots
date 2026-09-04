from __future__ import annotations

import pytest

from videopipeline.config import PipelineConfig
from videopipeline.pipeline import run
from videopipeline.steps import BASE_DIR, comprobar_dependencias


@pytest.mark.slow
def test_pipeline_completo_real(video_sintetico, tmp_path, monkeypatch):
    if comprobar_dependencias():
        pytest.skip("faltan ffmpeg/auto-editor")
    if not (BASE_DIR / "checkpoints" / "MossFormer2_SE_48K").is_dir():
        pytest.skip("checkpoint MossFormer2_SE_48K no descargado")
    monkeypatch.chdir(BASE_DIR)
    salida = tmp_path / "final.mp4"
    eventos: list[dict] = []
    resultado = run(
        PipelineConfig(video=video_sintetico, salida=salida, umbral="1%"), eventos.append
    )
    assert resultado == salida
    assert salida.is_file() and salida.stat().st_size > 0
    assert eventos[0]["step"] == 1 and eventos[-1]["step"] == 4


@pytest.mark.slow
def test_pipeline_con_subtitulos_real(video_con_voz, tmp_path, monkeypatch):
    if comprobar_dependencias():
        pytest.skip("faltan ffmpeg/auto-editor")
    if not (BASE_DIR / "checkpoints" / "MossFormer2_SE_48K").is_dir():
        pytest.skip("checkpoint MossFormer2_SE_48K no descargado")
    monkeypatch.chdir(BASE_DIR)
    salida = tmp_path / "final.mp4"
    eventos: list[dict] = []
    resultado = run(
        PipelineConfig(
            video=video_con_voz, salida=salida, umbral="1%",
            subtitulos=True, diseno="reels_bold", modelo_whisper="small",
        ),
        eventos.append,
    )
    assert resultado == salida
    assert salida.is_file() and salida.stat().st_size > 0
    # Sin warnings: la fase de subtítulos completó de verdad.
    assert not [e for e in eventos if "warning" in e]
    srt = salida.with_suffix(".srt")
    assert srt.is_file()
    contenido = srt.read_text(encoding="utf-8").lower()
    assert "hola" in contenido or "mundo" in contenido or "prueba" in contenido
    assert any(e.get("label") == "Quemando subtítulos" for e in eventos
               if "label" in e)
