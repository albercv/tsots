"""Fotograma de portada: elección del más nítido y hilo de publicación."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.widgets import dialogo_publicar
from tests.redes_falsos import ProveedorFalso
from videopipeline.redes import portada_video
from videopipeline.redes.modelo import Opciones, Plataforma, Publicacion


def _con_nitidez(segundo_nitido: float):
    def leer(video, segundo):
        rng = np.random.default_rng(0)
        if segundo == segundo_nitido:
            return rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
        return np.zeros((40, 40, 3), np.uint8)
    return leer


def test_elige_el_mas_nitido():
    leer = lambda v, s: np.indices((40, 40)).sum(0).astype(np.uint8)[..., None].repeat(3, 2) \
        if s < 4.5 else np.random.default_rng(1).integers(0, 255, (40, 40, 3), dtype=np.uint8)
    assert portada_video.elegir(Path("x.mp4"), 10.0, leer)[0] == 4.5


def test_duracion_corta_limita_instantes():
    vistos = []
    leer = lambda v, s: vistos.append(s) or np.zeros((8, 8, 3), np.uint8)
    portada_video.elegir(Path("x.mp4"), 2.0, leer)
    assert vistos == [0.5, 1.0, 1.5]


def test_duracion_menor_que_el_primer_instante():
    assert portada_video.elegir(Path("x.mp4"), 0.3, _con_nitidez(0.5)) is None


def test_sin_fotogramas_o_con_error_devuelve_none():
    assert portada_video.elegir(Path("x.mp4"), 5.0, lambda v, s: None) is None

    def falla(v, s):
        raise RuntimeError("boom")
    assert portada_video.elegir(Path("x.mp4"), 5.0, falla) is None


def test_con_portada_video_real(video_vertical, tmp_path):
    pub = Publicacion(video=video_vertical, titulo="t", caption="c")
    nueva = portada_video.con_portada(pub, tmp_path)
    assert nueva.portada is not None and 0.5 <= nueva.portada <= 3.5
    assert nueva.miniatura == tmp_path / "miniatura.jpg"
    assert cv2.imread(str(nueva.miniatura)) is not None


def test_con_portada_video_inexistente(tmp_path):
    pub = Publicacion(video=tmp_path / "no.mp4", titulo="t", caption="c")
    assert portada_video.con_portada(pub, tmp_path) == pub


def test_hilo_pasa_portada_al_publicador(video_vertical, qtbot, monkeypatch):
    capturado = {}

    def falso(proveedor, publicacion, *a, **k):
        capturado["pub"] = publicacion
        capturado["existe"] = publicacion.miniatura.exists()
        return {}
    monkeypatch.setattr(dialogo_publicar.publicador, "publicar", falso)
    pub = Publicacion(video=video_vertical, titulo="t", caption="c")
    hilo = dialogo_publicar.HiloPublicacion(
        ProveedorFalso(), pub, Opciones(), [Plataforma.YOUTUBE], "falso")
    with qtbot.waitSignal(hilo.terminado, timeout=20000):
        hilo.start()
    hilo.wait()
    assert capturado["pub"].portada is not None and capturado["existe"]


def test_hilo_no_calcula_portada_si_ninguna_red_la_usa(video_vertical, qtbot, monkeypatch):
    llamadas = []
    monkeypatch.setattr(dialogo_publicar.portada_video, "con_portada",
                        lambda pub, tmp: llamadas.append(1) or pub)
    monkeypatch.setattr(dialogo_publicar.publicador, "publicar", lambda *a, **k: {})
    pub = Publicacion(video=video_vertical, titulo="t", caption="c")
    hilo = dialogo_publicar.HiloPublicacion(
        ProveedorFalso(), pub, Opciones(), [Plataforma.X, Plataforma.LINKEDIN], "falso")
    with qtbot.waitSignal(hilo.terminado, timeout=20000):
        hilo.start()
    hilo.wait()
    assert llamadas == []
