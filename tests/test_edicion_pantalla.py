"""Lectura de la pantalla: máscara, análisis, consultas y OCR real."""
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from videopipeline.edicion import pantalla
from videopipeline.edicion.pantalla import Deteccion, Muestra
from videopipeline.subtitles import Palabra

ZONAS = {"subtitulos": [1269, 1440], "titulo": {"y": [100, 300], "hasta": 5.0}}


def _det(texto, caja=(100, 500, 600, 80)):
    return Deteccion(texto, caja, 0.9)


def _muestras(t0, t1, dets):
    n = round((t1 - t0) * 2)
    return [Muestra(t0 + i / 2, tuple(dets)) for i in range(n + 1)]


def test_enmascara_subtitulos_y_titulo():
    img = Image.new("RGB", (1080, 1920), "white")
    a = pantalla.enmascarar(img, ZONAS, 1.0)
    assert a.getpixel((500, 1300)) == (0, 0, 0) and a.getpixel((500, 200)) == (0, 0, 0)
    assert a.getpixel((500, 800)) == (255, 255, 255)
    b = pantalla.enmascarar(img, ZONAS, 6.0)
    assert b.getpixel((500, 1300)) == (0, 0, 0) and b.getpixel((500, 200)) == (255, 255, 255)
    c = pantalla.enmascarar(img, {"subtitulos": None, "titulo": None}, 1.0)
    assert c.getpixel((500, 1300)) == (255, 255, 255)
    assert img.getpixel((500, 1300)) == (255, 255, 255)  # no toca el original


def test_analizar_escribe_pantalla_json(tmp_path, monkeypatch):
    monkeypatch.setattr(pantalla, "_fotogramas", lambda v: ((i / 2, Image.new("RGB", (1080, 1920))) for i in range(4)))
    monkeypatch.setattr(pantalla, "leer_fotograma", lambda img: [_det("Hola")])
    destino = tmp_path / "pantalla.json"
    m = pantalla.analizar(tmp_path / "v.mp4", ZONAS, destino)
    assert [x.t for x in m] == [0.0, 0.5, 1.0, 1.5]
    assert pantalla.cargar(destino) == m
    assert not destino.with_name("pantalla.json.tmp").exists()


def test_cargar_sin_fichero_es_lista_vacia(tmp_path):
    assert pantalla.cargar(tmp_path / "no.json") == []
    (tmp_path / "mal.json").write_text("{no", "utf-8")
    assert pantalla.cargar(tmp_path / "mal.json") == []


def test_hay_texto_y_modo_broll():
    m = _muestras(0, 30, []) 
    m = [Muestra(x.t, (_det("Revisión"),) if 10 <= x.t <= 12 else ()) for x in m]
    assert pantalla.hay_texto(m, 9.0, 11.0)
    assert not pantalla.hay_texto(m, 20.0, 22.0)
    assert pantalla.modo_broll(m, 9.0) == "ventana"
    assert pantalla.modo_broll(m, 20.0) == "tapa"


def test_texto_diminuto_no_cuenta():
    m = [Muestra(t / 2, (Deteccion("x", (0, 0, 20, 10), 0.9),)) for t in range(10)]
    assert not pantalla.hay_texto(m, 0, 5)


def test_buscar_normaliza():
    m = _muestras(10, 12, [_det("Revisión")])
    assert pantalla.buscar(m, "revision", 10.5).texto == "Revisión"
    assert pantalla.buscar(m, "revision", 14.0) is None


def test_coincidencias_dicho_y_visto():
    m = _muestras(41.5, 45.0, [_det("Documentos de la empresa")])
    c = pantalla.coincidencias(m, [Palabra("documentos", 41.9, 42.3), Palabra("otra", 43.0, 43.2)])
    assert len(c) == 1
    assert (c[0].t0, c[0].t1, c[0].palabra, c[0].t_palabra) == (41.5, 45.0, "documentos", 41.9)
    assert c[0].visible == "Documentos de la empresa"


def test_coincidencias_palabra_entera_no_subcadena():
    m = _muestras(10.0, 12.0, [_det("Conectar el servidor")])
    assert pantalla.coincidencias(m, [Palabra("con", 10.5, 10.7), Palabra("tar", 10.8, 10.9)]) == []
    assert len(pantalla.coincidencias(m, [Palabra("Servidor.", 10.5, 10.9)])) == 1


def test_video_sin_texto_no_da_coincidencias():
    m = [Muestra(i / 2, ()) for i in range(20)]
    assert pantalla.coincidencias(m, [Palabra("documentos", 1.0, 1.5)]) == []


def test_sin_pyobjc_ocr_no_disponible(monkeypatch):
    from tests.conftest import OCR_REAL
    monkeypatch.setitem(sys.modules, "Vision", None)  # import → ImportError
    assert OCR_REAL() is False


def test_ocr_real_lee_texto():
    pytest.importorskip("Vision")
    img = Image.new("RGB", (1080, 1920), "white")
    fuente = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 120)
    ImageDraw.Draw(img).text((100, 800), "Documentos", fill="black", font=fuente)
    dets = pantalla.leer_fotograma(img)
    assert any("documentos" in d.texto.lower() for d in dets)
    d = next(d for d in dets if "documentos" in d.texto.lower())
    assert 700 < d.caja[1] < 900 and d.caja[0] < 200  # caja en píxeles, origen arriba-izquierda
