import json
import subprocess

import pytest
from PIL import Image

from videopipeline.edicion import estilos, rotulos

P = estilos.cargar("divertido").paleta
FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"


def test_etiqueta_render_prores_alpha(tmp_path):
    mov = rotulos.render_slot(rotulos.frames_etiqueta(["HOLA"], 0.5, P, 30), tmp_path / "a.mov", 30)
    out = subprocess.run([FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=pix_fmt,codec_tag_string,nb_read_frames", "-of", "json", str(mov)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    # el decodificador ProRes de ffmpeg 8 informa 12 bits; ap4h = 4444 con alfa
    assert s["codec_tag_string"] == "ap4h"
    assert s["pix_fmt"] in ("yuva444p10le", "yuva444p12le")
    assert s["nb_read_frames"] == "15"
    png = tmp_path / "f.png"
    subprocess.run([rotulos.FFMPEG, "-y", "-i", str(mov), "-vf", "select=eq(n\\,8)", "-frames:v", "1",
                    "-pix_fmt", "rgba", str(png)], check=True, capture_output=True)
    im = Image.open(png).convert("RGBA")
    assert im.getpixel((540, 360))[3] > 0
    assert im.getpixel((540, 1800))[3] == 0


def test_cabe():
    assert rotulos.cabe(["CORTO"], False, P)
    assert not rotulos.cabe(["X" * 60], False, P)


def test_glifos():
    assert rotulos.glifos_validos("¿QUÉ PUEDE FALLAR? «SÍ» · 1", False)
    assert not rotulos.glifos_validos("HOLA 🍉", False)
    assert not rotulos.glifos_validos("A → B", False)
    assert not rotulos.glifos_validos("LISTO ✓", False)
    assert rotulos.glifos_validos("LISTO ✓", True)


@pytest.mark.parametrize("letra", "ABCDEFG")
def test_transiciones_todas(letra):
    assert len(list(rotulos.frames_transicion(letra, 0.5, P, 30))) == 15


def test_transicion_desconocida():
    with pytest.raises(ValueError):
        list(rotulos.frames_transicion("Z", 0.5, P, 30))


def _x_min_opaco(img):
    return img.getchannel("A").point(lambda v: 255 if v else 0).getbbox()[0]


def test_contador_lados():
    l = list(rotulos.frames_contador(1, "TIENDA", 1.0, "L", P, 30))[-6]
    r = list(rotulos.frames_contador(1, "TIENDA", 1.0, "R", P, 30))[-6]
    assert _x_min_opaco(l) < 540
    assert _x_min_opaco(r) > 540
