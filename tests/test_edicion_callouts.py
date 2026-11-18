"""Señalar y lupa: seguimiento del texto por OCR (simulado) y dibujo de los callouts."""
import subprocess

import pytest
from PIL import Image

from videopipeline.edicion import callouts, pantalla
from videopipeline.edicion.componer import FFMPEG
from videopipeline.edicion.estilos import Paleta
from videopipeline.edicion.pantalla import Deteccion

PALETA = Paleta((255, 200, 0), (0, 0, 0, 200), (255, 255, 255), ("x", 40))
ZONAS = {"subtitulos": [1500, 1700], "titulo": None, "graficos_hasta": 1400}
FPS = 10
Y = 300


@pytest.fixture
def video(tmp_path):
    """1.5 s, fondo negro, «Revisión» blanca que avanza 3 px por fotograma."""
    ruta = tmp_path / "video.mp4"
    vf = ("drawtext=fontfile=/System/Library/Fonts/Helvetica.ttc:text='Revisión':fontsize=80:"
          f"fontcolor=white:x=50+3*n:y={Y}")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c=black:s=1080x1920:r={FPS}:d=1.5", "-vf", vf, "-pix_fmt", "yuv420p", str(ruta)],
                   check=True)
    return ruta


def _leer_real(imagen):
    """OCR falso: la caja del texto blanco que haya en la imagen."""
    caja = imagen.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
    return [Deteccion("Revisión", (caja[0], caja[1], caja[2] - caja[0], caja[3] - caja[1]), 0.9)] if caja else []


def _inicial(video):
    return _leer_real(next(callouts._decodificar(video, 1080, 1920, 0.2, FPS)))[0]


def test_seguir_texto_que_se_mueve(video, monkeypatch):
    monkeypatch.setattr(pantalla, "leer_fotograma", _leer_real)
    ini = _inicial(video)
    cajas = callouts.seguir(video, "revision", 0.0, 1.5, FPS, ini, ZONAS)
    assert len(cajas) == 15 and None not in cajas
    for i, c in enumerate(cajas):
        assert abs(c[0] - (ini.caja[0] + 3 * i)) < 10


@pytest.mark.parametrize("fallo", ["salto", "perdida"])
def test_seguir_salto_o_perdida_da_none(video, monkeypatch, fallo):
    llamadas = []

    def leer(imagen):
        llamadas.append(1)
        if len(llamadas) < 3:
            return _leer_real(imagen)
        if fallo == "perdida":
            return []
        d = _leer_real(imagen)[0]
        return [Deteccion(d.texto, (d.caja[0] + 600, *d.caja[1:]), 0.9)]

    monkeypatch.setattr(pantalla, "leer_fotograma", leer)
    cajas = callouts.seguir(video, "Revisión", 0.0, 1.5, FPS, _inicial(video), ZONAS)
    k = cajas.index(None)
    assert 0 < k <= 6 and all(c is None for c in cajas[k:])  # nunca vuelve
    assert all(c is not None and c[0] < 300 for c in cajas[:k])  # y no salta antes de perderse


def test_frames_senalar_formas_y_fundido():
    caja = (300, 400, 300, 80)
    cajas = [caja] * 8 + [None] * 7
    for forma in ("circulo", "flecha", "subrayado"):
        frames = list(callouts.frames_senalar(cajas, forma, PALETA, FPS, ZONAS, 0.0))
        assert len(frames) == 15 and frames[0].size == (1080, 1920)
        pintado = frames[6].crop((200, 200, 700, 600)).getchannel("A").getbbox()
        assert pintado, forma
        assert any(frames[6].getpixel((x, y))[:3] == (255, 200, 0) and frames[6].getpixel((x, y))[3] > 200
                   for x in range(200, 700) for y in range(200, 600)), forma
        alfas = [f.getchannel("A").getextrema()[1] for f in frames]
        assert alfas[7] == max(alfas)  # hasta el primer None, opacidad plena
        assert alfas[9] < alfas[7] and alfas[-1] == 0  # luego baja hasta 0


def test_frames_lupa_no_tapa_subtitulos(video):
    caja = (60, Y + 10, 300, 70)
    cajas = [caja] * 12
    frames = list(callouts.frames_lupa(video, cajas, 0.0, 1.2, ZONAS, PALETA, FPS))
    assert len(frames) == 12
    f = frames[6]
    assert f.getchannel("A").crop((0, 1500, 1080, 1700)).getextrema() == (0, 0)  # banda de subtítulos limpia
    assert f.getchannel("A").crop((0, 960, 1080, 1400)).getbbox()  # tarjeta en la mitad opuesta (inferior)
    assert f.getchannel("A").crop((0, 0, 1080, 200)).getextrema() == (0, 0)
    inferior = f.crop((0, 960, 1080, 1400))
    # el recorte ampliado es texto blanco sobre negro dentro de la tarjeta
    assert any(p[:3] == (255, 255, 255) and p[3] == 255 for p in inferior.getdata())
    assert any(p[:3] == (0, 0, 0) and p[3] == 255 for p in inferior.getdata())


def test_lupa_trazo_no_cruza_la_caja(video):
    caja = (60, Y + 10, 300, 70)
    f = list(callouts.frames_lupa(video, [caja] * 12, 0.0, 1.2, ZONAS, PALETA, FPS))[6]
    interior = f.getchannel("A").crop((caja[0] + 5, caja[1] + 5, caja[0] + caja[2] - 5, caja[1] + caja[3] - 5))
    assert interior.getextrema() == (0, 0)


def test_flecha_viaja_hacia_la_caja():
    caja = (300, 400, 300, 80)
    fr = list(callouts.frames_senalar([caja] * 8, "flecha", PALETA, FPS, ZONAS, 0.0))
    bajos = [f.getchannel("A").getbbox()[3] for f in fr[:4]]
    assert bajos == sorted(bajos) and bajos[0] < bajos[3] <= caja[1]


def test_senalar_respeta_banda_de_subtitulos():
    caja = (300, 1420, 300, 80)
    for forma in ("circulo", "flecha", "subrayado"):
        for f in callouts.frames_senalar([caja] * 8, forma, PALETA, FPS, ZONAS, 0.0):
            assert f.getchannel("A").crop((0, 1500, 1080, 1700)).getextrema() == (0, 0)


def test_seguir_caja_inicial_desplazada(video, monkeypatch):
    # la muestra de pantalla.json es de otro instante: la cámara movió el texto ~300 px
    monkeypatch.setattr(pantalla, "leer_fotograma", _leer_real)
    ini = _inicial(video)
    cacheada = Deteccion(ini.texto, (ini.caja[0] + 300, ini.caja[1] + 40, *ini.caja[2:]), 0.9)
    cajas = callouts.seguir(video, "Revisión", 0.0, 1.5, FPS, cacheada, ZONAS)
    assert None not in cajas
    assert all(abs(c[0] - (ini.caja[0] + 3 * i)) < 10 for i, c in enumerate(cajas))


def test_seguir_prefiere_la_linea_exacta(video, monkeypatch):
    otra = Deteccion("Empresas de la revisión", (600, 1000, 400, 80), 0.95)
    monkeypatch.setattr(pantalla, "leer_fotograma", lambda img: [*_leer_real(img), otra])
    ini = _inicial(video)
    cerca_de_otra = Deteccion("Revisión", (560, 980, 300, 80), 0.9)
    cajas = callouts.seguir(video, "Revisión", 0.0, 1.5, FPS, cerca_de_otra, ZONAS)
    assert None not in cajas
    assert all(abs(c[0] - (ini.caja[0] + 3 * i)) < 10 for i, c in enumerate(cajas))


def test_seguir_un_candidato_lejano_no_corta(video, monkeypatch):
    llamadas = []

    def leer(imagen):
        llamadas.append(1)
        d = _leer_real(imagen)[0]
        return [Deteccion(d.texto, (d.caja[0] + 600, *d.caja[1:]), 0.9)] if len(llamadas) == 4 else [d]

    monkeypatch.setattr(pantalla, "leer_fotograma", leer)
    cajas = callouts.seguir(video, "Revisión", 0.0, 1.5, FPS, _inicial(video), ZONAS)
    assert None not in cajas and all(c[0] < 300 for c in cajas)


def test_seguir_tras_un_barrido_no_salta_a_otra_igual(video, monkeypatch):
    # la cámara barre: un fotograma sin lectura, el texto aparece 400 px más allá y en el
    # sitio de antes queda la misma palabra en pequeño (otro elemento de la interfaz)
    llamadas = []

    def leer(imagen):
        llamadas.append(1)
        d = _leer_real(imagen)[0]
        if len(llamadas) <= 3:
            return [d]
        if len(llamadas) == 4:
            return []
        x, y, w, h = d.caja
        return [Deteccion(d.texto, (x + 400, y, w, h), 0.9), Deteccion(d.texto, (x, y, w // 2, h // 2), 0.9)]

    monkeypatch.setattr(pantalla, "leer_fotograma", leer)
    ini = _inicial(video)
    cajas = callouts.seguir(video, "Revisión", 0.0, 1.5, FPS, ini, ZONAS)
    assert None not in cajas
    assert all(c[0] > ini.caja[0] + 300 and c[2] > ini.caja[2] * 0.8 for c in cajas[11:])


def test_subrayado_sigue_la_inclinacion():
    caja = (100, 400, 800, 120)  # línea base de (100, 456) a (900, 520): baja 0.08 px por px
    f = list(callouts.frames_senalar([caja] * 15, "subrayado", PALETA, FPS, ZONAS, 0.0, inclinacion=0.08))[6]
    filas = lambda x: [y for y in range(300, 700) if f.getpixel((x, y))[3] > 200]
    assert filas(120) and 454 <= min(filas(120)) and max(filas(120)) <= 470  # pegado a la base, no más abajo
    assert filas(880) and 512 <= min(filas(880)) and max(filas(880)) <= 532
    plano = list(callouts.frames_senalar([caja] * 15, "subrayado", PALETA, FPS, ZONAS, 0.0))[6]
    assert plano.getpixel((120, 524))[3] > 200 and plano.getpixel((880, 524))[3] > 200


def test_lupa_no_encoge_el_texto(video):
    with pytest.raises(ValueError):
        list(callouts.frames_lupa(video, [(60, Y + 10, 700, 70)] * 12, 0.0, 1.2, ZONAS, PALETA, FPS))
    assert callouts.cabe_en_lupa((0, 0, 400, 60)) and not callouts.cabe_en_lupa((0, 0, 700, 60))
