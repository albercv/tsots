"""B-roll de Pexels: búsqueda, caché, llavero y dibujo (sin red real)."""
import json
import logging
import subprocess

import httpx
import pytest

from videopipeline.edicion import broll
from videopipeline.edicion.componer import FFMPEG
from videopipeline.edicion.estilos import Paleta

PALETA = Paleta((255, 200, 0), (0, 0, 0, 200), (255, 255, 255), ("x", 40))


def _video(id, dur, alturas=(1280,), autor="Ana"):
    return {"id": id, "duration": dur, "user": {"name": autor}, "url": f"https://pexels.com/v/{id}",
            "video_files": [{"link": f"https://cdn/{id}-{h}.mp4", "width": 720, "height": h,
                             "file_type": "video/mp4"} for h in alturas]}


@pytest.fixture
def clip_mp4(tmp_path):
    ruta = tmp_path / "clip.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x568:rate=10:duration=1", "-pix_fmt", "yuv420p", str(ruta)],
                   check=True)
    return ruta


def _cliente(videos=None, estado=200, peticiones=None, mp4=b"MP4"):
    def handler(req):
        if peticiones is not None:
            peticiones.append(str(req.url))
        if req.url.host == "api.pexels.com":
            if estado != 200:
                return httpx.Response(estado)
            return httpx.Response(200, json={"videos": videos or []})
        return httpx.Response(200, content=mp4)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_obtener_elige_vertical_largo_no_usado(tmp_path):
    videos = [_video(1, 1.5), _video(2, 10), _video(3, 8, (720, 1920, 2560))]
    pet = []
    clip = broll.obtener("gatos", {2}, tmp_path, "K", cliente=_cliente(videos, peticiones=pet))
    assert clip.id == 3 and clip.autor == "Ana" and clip.url == "https://pexels.com/v/3"
    assert clip.archivo == tmp_path / "3.mp4" and clip.archivo.read_bytes() == b"MP4"
    assert any("3-1920.mp4" in p for p in pet)
    assert any("orientation=portrait" in p for p in pet)


def test_obtener_usa_cache(tmp_path):
    pet = []
    a = broll.obtener("Gatos Azules", set(), tmp_path, "K", cliente=_cliente([_video(2, 10)], peticiones=pet))
    n = len(pet)
    b = broll.obtener("Gatos Azules", set(), tmp_path, "K", cliente=_cliente(peticiones=pet))
    assert a == b and len(pet) == n


@pytest.mark.parametrize("caso", ["vacio", "cortos", "401", "429", "timeout"])
def test_obtener_falla_suave(tmp_path, caso):
    if caso == "timeout":
        def h(req):
            raise httpx.ReadTimeout("t")
        c = httpx.Client(transport=httpx.MockTransport(h))
    else:
        c = _cliente([_video(1, 1.0)] if caso == "cortos" else [],
                     estado=int(caso) if caso.isdigit() else 200)
    assert broll.obtener("x", set(), tmp_path, "K", cliente=c) is None


def test_clave_no_sale_en_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    assert broll.obtener("x", set(), tmp_path, "SECRETA123", cliente=_cliente(estado=401)) is None
    assert "SECRETA123" not in caplog.text and "401" in caplog.text
    assert all("SECRETA123" not in p.read_text(errors="ignore") for p in tmp_path.iterdir())


def test_leer_clave_usa_security(llavero_falso):
    assert broll.leer_clave() is None and not broll.hay_clave()
    llavero_falso.elementos[("tsots-pexels", "api-key")] = "abc"
    assert broll.leer_clave() == "abc" and broll.hay_clave()
    assert llavero_falso.llamadas[-2][0][1:] == [
        "find-generic-password", "-s", "tsots-pexels", "-a", "api-key", "-w"]
    assert "-w" not in llavero_falso.llamadas[-1][0]


def test_servicio_coincide_con_app():
    from app import credenciales
    assert broll.SERVICIO == credenciales.servicio("pexels") and broll.CUENTA == credenciales.CUENTA


def test_probar_clave():
    assert broll.probar_clave("K", cliente=_cliente([])) is True
    assert broll.probar_clave("K", cliente=_cliente(estado=401)) is False


def test_frames_tapa_respeta_subtitulos(clip_mp4):
    z = {"subtitulos": [1269, 1440], "graficos_hasta": 700}
    f = list(broll.frames_broll(clip_mp4, "tapa", 1.0, z, PALETA, 10))
    assert len(f) == 10 and f[0].size == (1080, 1920)
    m = f[5]
    assert m.getpixel((540, 600))[3] == 255 and m.getpixel((540, 1269))[3] == 0
    assert m.getpixel((540, 1268))[3] == 255
    assert f[0].getpixel((540, 600))[3] < 255  # fundido de entrada
    entera = list(broll.frames_broll(clip_mp4, "tapa", 1.0, {"subtitulos": None}, PALETA, 10))
    assert entera[5].getpixel((540, 1900))[3] == 255


def test_frames_ventana_en_zona_superior(clip_mp4):
    z = {"subtitulos": [1269, 1440], "graficos_hasta": 900}
    m = list(broll.frames_broll(clip_mp4, "ventana", 1.0, z, PALETA, 10))[5]
    assert m.getpixel((540, 400))[3] == 255
    assert m.getpixel((5, 400))[3] == 0 and m.getpixel((540, 1000))[3] == 0
    assert m.getpixel((540, 100))[3] == 0
    assert m.getpixel((540, 869))[3] == 255 and m.getpixel((540, 905))[3] < 60  # tarjeta acaba en 870
