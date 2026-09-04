from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline.preview import extraer_frame, renderizar_preview
from videopipeline.steps import PasoFallido


def test_extraer_frame(video_sintetico, tmp_path):
    destino = tmp_path / "frame.png"
    extraer_frame(video_sintetico, destino)
    assert destino.is_file() and destino.stat().st_size > 0


def test_extraer_frame_video_corto_reintenta(video_sintetico, tmp_path):
    # El vídeo dura 2s; pedir el segundo 10 fuerza el reintento sin -ss.
    destino = tmp_path / "frame.png"
    extraer_frame(video_sintetico, destino, segundo=10.0)
    assert destino.is_file() and destino.stat().st_size > 0


def test_extraer_frame_video_inexistente(tmp_path):
    with pytest.raises(PasoFallido):
        extraer_frame(tmp_path / "no.mp4", tmp_path / "f.png")


def test_renderizar_preview(video_sintetico, tmp_path):
    frame = tmp_path / "frame.png"
    extraer_frame(video_sintetico, frame)
    destino = tmp_path / "preview.png"
    renderizar_preview(frame, "reels_bold", 75, 100, destino)
    assert destino.is_file() and destino.stat().st_size > 0
    # El quemado cambió píxeles: no es el mismo archivo.
    assert destino.read_bytes() != frame.read_bytes()
    # El .ass temporal no queda atrás.
    assert not list(tmp_path.glob("*.ass"))


def test_renderizar_preview_karaoke(video_sintetico, tmp_path):
    frame = tmp_path / "frame.png"
    extraer_frame(video_sintetico, frame)
    destino = tmp_path / "preview.png"
    renderizar_preview(frame, "reels_karaoke", 60, 150, destino)
    assert destino.is_file() and destino.stat().st_size > 0


def test_renderizar_preview_preset_desconocido(video_sintetico, tmp_path):
    frame = tmp_path / "frame.png"
    extraer_frame(video_sintetico, frame)
    with pytest.raises(KeyError):
        renderizar_preview(frame, "neon", 75, 100, tmp_path / "p.png")
