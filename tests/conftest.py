from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def video_sintetico(tmp_path_factory) -> Path:
    """Vídeo de 2 s (1 s tono + 1 s silencio) con pista de audio."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg no disponible")
    destino = tmp_path_factory.mktemp("media") / "sintetico.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2:r=10",
            "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1",
            "-af", "apad=whole_dur=2",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(destino),
        ],
        check=True,
    )
    return destino


@pytest.fixture(scope="session")
def video_sin_audio(tmp_path_factory) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg no disponible")
    destino = tmp_path_factory.mktemp("media") / "mudo.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1:r=10",
            "-c:v", "libx264", "-an", str(destino),
        ],
        check=True,
    )
    return destino


@pytest.fixture(scope="session")
def video_con_voz(tmp_path_factory) -> Path:
    """Vídeo de ~3 s con voz real sintetizada (say de macOS)."""
    ffmpeg = shutil.which("ffmpeg")
    say = shutil.which("say")
    if ffmpeg is None or say is None:
        pytest.skip("ffmpeg o say no disponibles")
    carpeta = tmp_path_factory.mktemp("media_voz")
    aiff = carpeta / "voz.aiff"
    subprocess.run(
        [say, "-v", "Monica", "-o", str(aiff),
         "hola mundo esto es una prueba de subtítulos"],
        check=True,
    )
    destino = carpeta / "voz.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=4:r=10",
            "-i", str(aiff),
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(destino),
        ],
        check=True,
    )
    return destino


@pytest.fixture(autouse=True)
def logs_en_tmp(tmp_path, monkeypatch):
    """El runner escribe un log por trabajo; en tests nunca en el proyecto."""
    from videopipeline import runner

    monkeypatch.setattr(runner, "DIR_LOGS", tmp_path / "logs")
