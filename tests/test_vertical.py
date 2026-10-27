from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from videopipeline.steps import (
    FILTRO_HUECOS_AUDIO,
    PasoFallido,
    cmd_quemar_subtitulos,
    resolucion_video,
)
from videopipeline.vertical import (
    ancho_recorte,
    audio_cabe_en_mp4,
    cmd_convertir_vertical,
    convertir_vertical,
    es_ya_vertical,
    filtro_vertical,
)


def _probe(ruta: Path) -> tuple[int, int, str, str | None]:
    """Ancho, alto y pix_fmt del vídeo, y códec de audio (o None)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,pix_fmt",
         "-of", "json", str(ruta)],
        capture_output=True, text=True, check=True,
    ).stdout
    streams = json.loads(out)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next((s["codec_name"] for s in streams if s["codec_type"] == "audio"), None)
    return v["width"], v["height"], v["pix_fmt"], a


def _lavfi(destino: Path, video: str, audio: list[str]) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg no disponible")
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", video,
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", *audio, "-shortest",
         str(destino)],
        check=True,
    )
    return destino


def test_ancho_recorte():
    assert (ancho_recorte(1080), ancho_recorte(720), ancho_recorte(480)) == (
        606, 404, 270)


def test_es_ya_vertical():
    assert not es_ya_vertical(1920, 1080)
    assert not es_ya_vertical(1080, 1080)  # cuadrado: se recorta
    assert not es_ya_vertical(1080, 1350)  # 4:5: se recorta
    assert es_ya_vertical(1080, 1920) and es_ya_vertical(1080, 2400)


def test_filtro_central():
    f = filtro_vertical("central", 1920, 1080)
    assert f.startswith("[0:v]") and f.endswith("format=yuv420p[v]")
    assert "crop=606:1080" in f and "scale=1080:1920" in f


def test_filtro_barras():
    f = filtro_vertical("barras", 1920, 1080)
    assert "pad=1080:1920" in f and "crop" not in f


def test_filtro_difuminado():
    f = filtro_vertical("difuminado", 1920, 1080)
    assert all(p in f for p in ("split", "boxblur", "overlay"))


def test_filtro_cara():
    f = filtro_vertical("cara", 1920, 1080, x_cara=300)
    assert "sendcmd=f=cara.cmd" in f and "crop@v=606:1080:300:0" in f


def test_filtro_cara_sin_x_falla():
    with pytest.raises(ValueError):
        filtro_vertical("cara", 1920, 1080)


def test_filtro_encuadre_desconocido_falla():
    with pytest.raises(ValueError):
        filtro_vertical("zoom", 1920, 1080)


def test_filtro_ass_al_final():
    f = filtro_vertical("difuminado", 1920, 1080, ass_nombre="subs_vertical.ass")
    assert f.endswith("ass=subs_vertical.ass,format=yuv420p[v]")


def test_cmd_convertir_copia_audio():
    cmd = cmd_convertir_vertical(
        "ffmpeg", Path("in.mp4"), "[0:v]null[v]", Path("out.mp4"), "30", "copiar")
    assert cmd[cmd.index("-filter_complex") + 1] == "[0:v]null[v]"
    assert cmd[cmd.index("-r") + 1] == "30"
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert cmd[cmd.index("-crf") + 1] == "18" and "libx264" in cmd
    assert "[v]" in cmd and "0:a:0?" in cmd and cmd[-1] == "out.mp4"


def test_cmd_convertir_recodifica_audio():
    cmd = cmd_convertir_vertical(
        "ffmpeg", Path("in.mov"), "[0:v]null[v]", Path("o.mp4"), "30", "aac")
    i = cmd.index("-c:a")
    assert cmd[i + 1:i + 4] == ["aac", "-b:a", "192k"]
    assert "-af" not in cmd


def test_cmd_convertir_rellena_audio():
    cmd = cmd_convertir_vertical(
        "ffmpeg", Path("in.mov"), "[0:v]null[v]", Path("o.mp4"), "30000/1001",
        "rellenar")
    assert cmd[cmd.index("-af") + 1] == FILTRO_HUECOS_AUDIO
    i = cmd.index("-c:a")
    assert cmd[i + 1:i + 4] == ["aac", "-b:a", "192k"]
    assert cmd[cmd.index("-r") + 1] == "30000/1001"


def test_convertir_desde_original_fuerza_fps_y_rellena_audio(tmp_path):
    # Fuente de tasa variable (como el iPhone): la salida debe tener tasa entera.
    vfr = tmp_path / "vfr.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=1280x720:d=2:r=30", "-f", "lavfi", "-i", "sine=d=2",
                    "-vf", "setpts='PTS+0.02*sin(N)/TB'", "-fps_mode", "vfr",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(vfr)],
                   check=True)
    salida = tmp_path / "o.mp4"
    convertir_vertical(vfr, salida, filtro_vertical("central", 1280, 720), tmp_path,
                       usa_ass=False, desde_original=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=r_frame_rate,avg_frame_rate",
                        "-of", "csv=p=0", str(salida)],
                       capture_output=True, text=True, check=True
                       ).stdout.strip().split(",")
    assert r[0] == r[1] and r[0] in ("30/1", "30000/1001")
    assert _probe(salida)[3] == "aac"


def test_quemar_desde_original_fuerza_fps():
    cmd = cmd_quemar_subtitulos("ffmpeg", Path("v.mov"), "s.ass", Path("o.mp4"),
                                desde_original=True, fps="30")
    assert cmd[cmd.index("-r") + 1] == "30" and FILTRO_HUECOS_AUDIO in cmd


def test_quemar_por_defecto_sin_cambios():
    cmd = cmd_quemar_subtitulos("ffmpeg", Path("v.mp4"), "s.ass", Path("o.mp4"))
    assert "-r" not in cmd and cmd[cmd.index("-c:a") + 1] == "copy"


@pytest.mark.parametrize("encuadre", ["central", "difuminado", "barras"])
def test_convertir_real_1080x1920(video_720p, tmp_path, encuadre):
    salida = tmp_path / f"{encuadre}.mp4"
    porcentajes: list[float] = []
    convertir_vertical(video_720p, salida, filtro_vertical(encuadre, 1280, 720),
                       cwd=tmp_path, usa_ass=False, on_percent=porcentajes.append)
    assert _probe(salida) == (1080, 1920, "yuv420p", "aac")
    assert porcentajes and all(0 <= p <= 100 for p in porcentajes)


def test_convertir_real_resolucion_rara(tmp_path):
    raro = _lavfi(tmp_path / "raro.mp4", "testsrc2=s=854x480:d=1:r=10",
                  ["-c:a", "aac"])
    salida = tmp_path / "o.mp4"
    convertir_vertical(raro, salida, filtro_vertical("central", 854, 480),
                       tmp_path, False)
    assert _probe(salida)[:3] == (1080, 1920, "yuv420p")


def test_convertir_real_con_rotacion(video_720p, tmp_path):
    rotado = tmp_path / "rot.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90",
                        "-i", str(video_720p), "-c", "copy", str(rotado)])
    if r.returncode != 0:
        pytest.skip("ffmpeg sin -display_rotation")
    ancho, alto = resolucion_video(rotado)
    assert (ancho, alto) == (720, 1280) and es_ya_vertical(ancho, alto)
    salida = tmp_path / "o.mp4"
    convertir_vertical(rotado, salida, filtro_vertical("barras", ancho, alto),
                       tmp_path, False)
    assert _probe(salida)[:2] == (1080, 1920)


def test_audio_pcm_mov_recodifica(tmp_path):
    mov = _lavfi(tmp_path / "camara.mov", "testsrc2=s=1280x720:d=1:r=10",
                 ["-c:a", "pcm_s16le"])
    assert audio_cabe_en_mp4(mov) is False
    salida = tmp_path / "o.mp4"
    convertir_vertical(mov, salida, filtro_vertical("central", 1280, 720),
                       tmp_path, False)
    assert _probe(salida)[3] == "aac"


def test_audio_aac_cabe(video_720p):
    assert audio_cabe_en_mp4(video_720p) is True


def test_convertir_fallo(tmp_path):
    falso = tmp_path / "no_video.mp4"
    falso.write_bytes(b"basura")
    with pytest.raises(PasoFallido):
        convertir_vertical(falso, tmp_path / "o.mp4",
                           filtro_vertical("central", 1280, 720), tmp_path, False)


def test_filtro_difuminado_desenfoca_a_baja_resolucion():
    # boxblur a 1080x1920 multiplica por ~5 el tiempo; se desenfoca pequeño.
    f = filtro_vertical("difuminado", 1920, 1080)
    fondo = f.split(";")[1]
    assert fondo.index("scale=270:480") < fondo.index("boxblur")
    assert fondo.endswith("scale=1080:1920[bg]")
