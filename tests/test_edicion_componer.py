from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from videopipeline.edicion.componer import Overlay, Zoom, componer

FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
W, H = 1080, 1920


def _sonda(ruta: Path, flujo: str, campos: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", flujo, "-show_entries",
         f"stream={campos}", "-of", "csv=p=0", str(ruta)],
        capture_output=True, text=True, check=True).stdout.strip()


def _fotograma(ruta: Path, t: float) -> np.ndarray:
    crudo = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", str(t), "-i", str(ruta), "-frames:v", "1",
         "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(crudo, np.uint8).reshape(H, W, 3).astype(int)


def _wav(destino: Path, dur: float = 4) -> Path:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=220:duration={dur}", "-ar", "48000", str(destino)],
        check=True)
    return destino


def _comp(fuente, destino, **kw):
    args = dict(overlays=[], franja=None, zooms=[], sfx=[], musica=None,
                musica_db=-14.0)
    args.update(kw)
    componer(fuente, destino, **args)
    return destino


def test_salida_mismas_dimensiones_y_duracion(video_vertical, tmp_path):
    sal = _comp(video_vertical, tmp_path / "s.mp4")
    assert _sonda(sal, "v:0", "width,height") == f"{W},{H}"
    assert _sonda(sal, "v:0", "r_frame_rate") == _sonda(video_vertical, "v:0", "r_frame_rate")
    assert abs(float(_sonda(sal, "v:0", "duration")) - 4) < 0.1
    assert _sonda(sal, "a:0", "codec_name") == "aac"


def test_zoom_no_toca_fuera_de_franja(video_vertical, tmp_path):
    sal = _comp(video_vertical, tmp_path / "s.mp4", franja=(600, 1200),
                zooms=[Zoom(0, 4, 1.3, 1.3)])
    a, b = _fotograma(video_vertical, 2), _fotograma(sal, 2)
    for y in (300, 1500):
        assert np.abs(a[y] - b[y]).mean() < 3
    assert np.abs(a[900] - b[900]).mean() > 3


def test_overlay_en_su_ventana(video_vertical, tmp_path):
    rojo = tmp_path / "rojo.mov"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=c=red:s={W}x{H}:d=1:r=30", "-c:v", "libx264", "-pix_fmt",
         "yuv420p", str(rojo)], check=True)
    sal = _comp(video_vertical, tmp_path / "s.mp4",
                overlays=[Overlay(rojo, 1.0, 1.0)])

    def es_rojo(t):
        p = _fotograma(sal, t)[900:1000, 400:600].mean(axis=(0, 1))
        return p[0] > 200 and p[1] < 60 and p[2] < 60

    assert es_rojo(1.5)
    assert not es_rojo(0.5)
    assert not es_rojo(2.5)


def test_loudness_final(video_vertical, tmp_path):
    musica = _wav(tmp_path / "m.wav")
    sal = _comp(video_vertical, tmp_path / "s.mp4", musica=musica)
    err = subprocess.run(
        [FFMPEG, "-nostats", "-i", str(sal), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True).stderr
    lufs = float(re.findall(r"I:\s+(-?\d+\.\d+) LUFS", err)[-1])
    assert -15.5 < lufs < -13.5


def test_sin_musica_sin_sfx(video_vertical, tmp_path):
    sal = _comp(video_vertical, tmp_path / "s.mp4", sfx=[], musica=None)
    assert sal.stat().st_size > 0


def test_borrador_720(video_vertical, tmp_path):
    sal = _comp(video_vertical, tmp_path / "s.mp4", borrador=True,
                sfx=[_wav(tmp_path / "x.wav")])
    assert _sonda(sal, "v:0", "width,height") == "720,1280"
