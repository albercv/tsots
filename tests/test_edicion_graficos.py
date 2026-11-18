import numpy as np
from PIL import Image, ImageDraw

from videopipeline.edicion import estilos, graficos, numeros
from videopipeline.subtitles import Palabra

P = estilos.cargar("divertido").paleta


def _opacos_acento(img):
    a = np.array(img)
    return int(((a[..., 3] > 200) & (np.abs(a[..., :3].astype(int) - P.acento).sum(-1) < 12)).sum())


def test_catalogo_iconos_se_dibuja():
    assert len(graficos.ICONOS) >= 40
    for nombre in graficos.ICONOS:
        im = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(im).text((0, 0), graficos._glifo(nombre), font=graficos._fuente_iconos(100), fill=255)
        assert im.getbbox() is not None, nombre


def test_frames_icono_alfa_y_duracion():
    fr = list(graficos.frames_icono("documento", 2.0, 540, 330, 220, P, 10))
    assert len(fr) == 20
    assert np.array(fr[0])[..., 3].max() < 40
    assert _opacos_acento(fr[10]) > 1000
    assert all(np.array(f)[900:, :, 3].max() == 0 for f in fr)


def test_frames_dato_cuenta_y_barra():
    fr = list(graficos.frames_dato(10, "usuarios", None, 2.0, P, 10))
    assert len(fr) == 20
    assert np.array(fr[1]).tobytes() != np.array(fr[10]).tobytes()
    assert graficos._formato(10) == "10" and graficos._formato(3.5) == "3,5"
    sin = _opacos_acento(fr[12])
    con = list(graficos.frames_dato(50, "usuarios", "%", 2.0, P, 10))
    assert _opacos_acento(con[12]) > sin
    assert all(np.array(f)[900:, :, 3].max() == 0 for f in con)


def test_valor_de_formas():
    v = numeros.valor_de
    assert (v("10"), v("1.000"), v("3,5"), v("20%")) == (10, 1000, 3.5, 20)
    assert (v("diez"), v("cien"), v("mil"), v("veintiuno"), v("treinta"), v("Diez,")) == (10, 100, 1000, 21, 30, 10)
    assert v("hola") is None


def test_numeros_dichos_porcentaje():
    ps = [Palabra("veinte", 1.0, 1.3), Palabra("por", 1.3, 1.4), Palabra("ciento", 1.4, 1.8),
          Palabra("casas", 2.0, 2.3), Palabra("5%", 3.0, 3.2)]
    assert numeros.numeros_dichos(ps) == [(1.0, 20, "veinte", True), (3.0, 5, "5%", True)]


def test_parecidos():
    assert "documento" in graficos.parecidos("documentos")
    assert graficos.icono_disponible("casa") and not graficos.icono_disponible("zzz")


def _dichos(frase, t0=1.0):
    ps = [Palabra(w, t0 + i * 0.3, t0 + i * 0.3 + 0.2) for i, w in enumerate(frase.split())]
    return numeros.numeros_dichos(ps)


def test_numeros_dichos_articulos_y_compuestos():
    assert _dichos("una vez") == [] and _dichos("una empresa") == []
    assert _dichos("uno %") == [(1.0, 1, "uno", True)]
    for frase, v in [("treinta y cinco", 35), ("ciento veinte", 120), ("doscientos", 200), ("tres mil", 3000),
                     ("dos mil euros", 2000), ("mil doscientos", 1200), ("tres mil quinientos", 3500),
                     ("veintiún", 21), ("1.000", 1000)]:
        assert _dichos(frase) == [(1.0, v, frase.split()[0], False)], frase
    assert _dichos("veinte por ciento") == [(1.0, 20, "veinte", True)]
    assert _dichos("treinta y cinco por ciento") == [(1.0, 35, "treinta", True)]
