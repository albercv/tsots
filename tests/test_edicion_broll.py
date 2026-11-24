"""B-roll de Pixabay: búsqueda, caché, llavero y dibujo (sin red real)."""
import json
import logging
import subprocess

import httpx
import pytest

from videopipeline.edicion import broll
from videopipeline.edicion.componer import FFMPEG
from videopipeline.edicion.estilos import Paleta

PALETA = Paleta((255, 200, 0), (0, 0, 0, 200), (255, 255, 255), ("x", 40))


def _rend(w, h, n):
    return {"url": f"https://cdn.pixabay.com/v/{n}.mp4", "width": w, "height": h, "size": 1000}


def _video(id, dur, vers=None, autor="Ana"):
    """`vers`: {nombre: (ancho, alto)}; por defecto apaisado 1920 y 3840."""
    vers = vers or {"large": (1920, 1080), "medium": (1280, 720), "small": (640, 360)}
    return {"id": id, "duration": dur, "user": autor, "pageURL": f"https://pixabay.com/videos/{id}/",
            "videos": {k: _rend(w, h, f"{id}-{k}") for k, (w, h) in vers.items()}}


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
        if req.url.host == "pixabay.com":
            if estado != 200:
                return httpx.Response(estado)
            return httpx.Response(200, json={"totalHits": len(videos or []), "hits": videos or []})
        return httpx.Response(200, content=mp4)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_obtener_elige_largo_no_usado_y_credita(tmp_path):
    videos = [_video(1, 1.5), _video(2, 10), _video(3, 8)]
    pet = []
    clip = broll.obtener("gatos", {2}, tmp_path, "K", cliente=_cliente(videos, peticiones=pet))
    assert clip.id == 3 and clip.autor == "Ana" and clip.url == "https://pixabay.com/videos/3/"
    assert clip.archivo == tmp_path / "3.mp4" and clip.archivo.read_bytes() == b"MP4"
    assert any("3-large.mp4" in p for p in pet)
    q = httpx.URL(pet[0]).params
    assert (q["q"], q["per_page"], q["safesearch"], q["video_type"]) == ("gatos", "20", "true", "film")


def test_obtener_pixabay_prefiere_vertical_y_version_1920(tmp_path):
    horiz = _video(1, 10, {"large": (3840, 2160), "medium": (1920, 1080)})
    vert = _video(2, 10, {"large": (2160, 3840), "medium": (1080, 1920), "small": (540, 960)})
    pet = []
    clip = broll.obtener("x", set(), tmp_path, "K", cliente=_cliente([horiz, vert], peticiones=pet))
    assert clip.id == 2 and any("2-medium.mp4" in p for p in pet)  # vertical y la mayor ≤ 1920
    pet.clear()
    clip = broll.obtener("y", set(), tmp_path, "K", cliente=_cliente([horiz], peticiones=pet))
    assert clip.id == 1 and any("1-medium.mp4" in p for p in pet)  # 3840 no, 1920 sí
    solo_grande = _video(5, 10, {"large": (3840, 2160), "medium": (2560, 1440)})
    pet.clear()
    broll.obtener("z", set(), tmp_path, "K", cliente=_cliente([solo_grande], peticiones=pet))
    assert any("5-medium.mp4" in p for p in pet)  # ninguna cabe: la más pequeña


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


@pytest.mark.parametrize("caso", ["401", "429", "timeout", "ok"])
def test_clave_no_sale_en_logs_ni_cache(tmp_path, caplog, caso):
    caplog.set_level(logging.DEBUG)

    def h(req):
        if req.url.host == "pixabay.com":
            assert req.url.params["key"] == "SECRETA123"  # va en la URL
        else:
            assert "key" not in req.url.params  # la descarga del CDN no lleva la clave
        if caso == "timeout":
            raise httpx.ReadTimeout("fallo en " + str(req.url))  # la excepción lleva la URL
        if caso != "ok":
            return httpx.Response(int(caso))
        if req.url.host == "pixabay.com":
            return httpx.Response(200, json={"hits": [_video(1, 10)]})
        return httpx.Response(200, content=b"MP4")
    c = httpx.Client(transport=httpx.MockTransport(h))
    r = broll.obtener("x", set(), tmp_path, "SECRETA123", cliente=c)
    assert (r is not None) == (caso == "ok")
    assert "SECRETA123" not in caplog.text and "pixabay.com" not in caplog.text
    if caso.isdigit():
        assert caso in caplog.text
    assert all("SECRETA123" not in p.read_text(errors="ignore") for p in tmp_path.iterdir()
               if p.suffix == ".json")
    assert all("key=" not in p.read_text(errors="ignore") for p in tmp_path.iterdir() if p.suffix == ".json")


def test_leer_clave_usa_security(llavero_falso):
    assert broll.leer_clave() is None and not broll.hay_clave()
    llavero_falso.elementos[("tsots-pixabay", "api-key")] = "abc"
    assert broll.leer_clave() == "abc" and broll.hay_clave()
    assert llavero_falso.llamadas[-2][0][1:] == [
        "find-generic-password", "-s", "tsots-pixabay", "-a", "api-key", "-w"]
    assert "-w" not in llavero_falso.llamadas[-1][0]


def test_servicio_coincide_con_app():
    from app import credenciales
    assert broll.SERVICIO == credenciales.servicio("pixabay") and broll.CUENTA == credenciales.CUENTA


def test_probar_clave():
    pet = []
    assert broll.probar_clave("K", cliente=_cliente([], peticiones=pet)) is True
    q = httpx.URL(pet[0]).params
    assert (q["q"], q["per_page"]) == ("nature", "3")
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
    banner = list(broll.frames_broll(clip_mp4, "tapa", 1.0,
                                     {"subtitulos": None, "banner": [1480, 1571]}, PALETA, 10))
    assert banner[5].getpixel((540, 1479))[3] == 255 and banner[5].getpixel((540, 1480))[3] == 0


def _tarjeta(frame):
    """(y0, y1, alto) de la parte opaca de la ventana (sin la sombra)."""
    caja = frame.getchannel("A").point(lambda v: 255 if v > 200 else 0).getbbox()
    return caja[1], caja[3], caja[3] - caja[1]


Z_CENTRAL = {"subtitulos": [1269, 1440], "titulo": None, "graficos_hasta": 1068}


def test_frames_ventana_en_zona_superior(clip_mp4):
    m = list(broll.frames_broll(clip_mp4, "ventana", 1.0, Z_CENTRAL, PALETA, 10))[5]
    y0, y1, alto = _tarjeta(m)
    assert 120 <= y0 and y1 <= 1068 and alto <= broll.VENTANA_ALTO
    assert m.getpixel((5, 400))[3] == 0 and m.getpixel((540, 100))[3] == 0


@pytest.mark.parametrize("evitar", [(184, 700), (700, 1000), (300, 400), (1100, 1200)])
def test_frames_ventana_no_tapa_el_texto(clip_mp4, evitar):
    m = list(broll.frames_broll(clip_mp4, "ventana", 1.0, Z_CENTRAL, PALETA, 10, evitar=evitar))[5]
    y0, y1, alto = _tarjeta(m)
    assert y1 <= evitar[0] or y0 >= evitar[1], (y0, y1)  # nunca sobre el texto
    assert 120 <= y0 and y1 <= 1068 and 0 < alto <= broll.VENTANA_ALTO


def test_frames_ventana_bajo_el_titulo(clip_mp4):
    z = {**Z_CENTRAL, "titulo": {"y": [154, 407], "hasta": 5.0}}
    y0, _, _ = _tarjeta(list(broll.frames_broll(clip_mp4, "ventana", 1.0, z, PALETA, 10, t=4.0))[5])
    assert y0 >= 407
    y0, _, _ = _tarjeta(list(broll.frames_broll(clip_mp4, "ventana", 1.0, z, PALETA, 10, t=6.0))[5])
    assert y0 < 407


def test_frames_ventana_sin_sitio_falla(clip_mp4):
    with pytest.raises(ValueError):
        list(broll.frames_broll(clip_mp4, "ventana", 1.0, Z_CENTRAL, PALETA, 10, evitar=(184, 850)))


def test_hueco_ventana_comparte_calculo():
    assert broll.hueco_ventana(Z_CENTRAL, 0.0, None)[2] == broll.VENTANA_ALTO
    with pytest.raises(ValueError):
        broll.hueco_ventana(Z_CENTRAL, 0.0, (184, 850))
