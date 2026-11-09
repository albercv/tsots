"""Portada estilo 3: tamaños, posición de la cara, degradado, título y logo."""
import numpy as np
import pytest
from PIL import Image

from videopipeline.portada import (TAM_BLOG, TAM_LINKEDIN, componer_portada,
                                   palabra_destacada)

FONDO = (5, 10, 15)


def _sintetica(cara=None, tam=(1920, 1080)):
    """Fotograma gris con un rectángulo claro en la caja de la cara."""
    img = Image.new("RGB", tam, (90, 90, 90))
    if cara:
        img.paste((250, 200, 40), cara)  # amarillo: no se confunde con el título
    return img


def _blanca():
    return Image.new("RGB", (1920, 1080), (255, 255, 255))


def _negra():
    return Image.new("RGB", (1920, 1080), (0, 0, 0))


def _centro_x_de_lo_claro(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    cols = np.where(((a[..., 0] - a[..., 2]) > 100).any(axis=0))[0]
    return (cols.min() + cols.max()) / 2


def _caja_de_pixeles_blancos_o_turquesa(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    blanco = a.min(axis=2) > 200
    turq = (abs(a[..., 0] - 5) < 40) & (abs(a[..., 1] - 180) < 40) & (abs(a[..., 2] - 186) < 40)
    ys, xs = np.where(blanco | turq)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_tamanos_exactos():
    img = componer_portada(_sintetica(), "Agentes de IA rentables", TAM_BLOG)
    assert img.size == (1672, 941)
    assert componer_portada(_sintetica(), "Agentes de IA rentables", TAM_LINKEDIN).size == (1080, 1350)


def test_palabra_destacada_es_la_mas_larga():
    assert palabra_destacada("Agentes de IA rentables") == 3
    assert palabra_destacada("uno dos") == 0  # empate: la primera


def test_cara_queda_en_el_tercio_derecho():
    cara = (1650, 200, 1950, 600)  # fotograma ancho: hay holgura para colocar la cara
    img = componer_portada(_sintetica(cara=cara, tam=(3000, 1080)), "Uno dos tres", TAM_BLOG, cara=cara)
    assert _centro_x_de_lo_claro(img) / img.width == pytest.approx(0.70, abs=0.05)


def test_lado_izquierdo_oscurecido():
    img = componer_portada(_blanca(), "Uno dos tres", TAM_BLOG)
    assert img.getpixel((5, 470))[0] < 40 and img.getpixel((1660, 470))[0] > 200


def test_titulo_largo_cabe():
    img = componer_portada(_negra(), "Automatizaciones inteligentes para pequeñas empresas", TAM_BLOG)
    x0, _, x1, _ = _caja_de_pixeles_blancos_o_turquesa(img)
    assert x0 >= int(0.08 * 1672) - 2 and x1 <= int(0.58 * 1672) + 2


def test_portada_sin_cara():
    assert componer_portada(_sintetica(), "Uno dos tres", TAM_LINKEDIN, cara=None).size == TAM_LINKEDIN


def test_logo_solo_si_se_pide():
    sin = componer_portada(_negra(), "Uno dos tres", TAM_LINKEDIN)
    con = componer_portada(_negra(), "Uno dos tres", TAM_LINKEDIN, con_logo=True)
    zona = (int(1080 * 0.85), 5, 1075, int(1080 * 0.2))  # esquina superior derecha
    assert sin.crop(zona).getextrema() != con.crop(zona).getextrema()


@pytest.mark.parametrize("tam", [TAM_BLOG, TAM_LINKEDIN])
def test_vertical_con_cara_grande_no_se_corta(tam):
    cara = (28, 630, 776, 1378)
    img = componer_portada(_sintetica(cara=cara, tam=(1080, 1920)), "Agentes de IA rentables", tam, cara=cara)
    assert img.size == tam
    a = np.asarray(img.convert("RGB")).astype(int)
    ys, xs = np.where((a[..., 0] - a[..., 2]) > 60)  # el rectángulo amarillo es la cara
    assert ys.min() > 0 and ys.max() < tam[1] - 1 and xs.max() < tam[0] - 1
    assert (ys.max() - ys.min()) < 0.65 * tam[1]  # tope de tamaño de cara
    if tam == TAM_BLOG:
        assert (np.abs(a[:, -1] - FONDO).sum(axis=1) > 10).any()  # sin banda de fondo a la derecha
