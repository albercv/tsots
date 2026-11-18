from videopipeline.config import PipelineConfig
from videopipeline.edicion.zonas import calcular

FUENTE = (1920, 1080)


def _cfg(**kw):
    kw = {"diseno": "karaoke_verde", **kw}
    return PipelineConfig(video="x.mp4", posicion_subs=75, tamano_subs=150,
                          subtitulos=True, **kw)


def test_difuminado():
    z = calcular(_cfg(), "difuminado", FUENTE, True)
    assert z["contenido"] == [0, 656, 1080, 608]
    assert z["subtitulos"] == [1269, 1440]
    assert z["franja_zoom"] == [656, 1264]


def test_cara():
    z = calcular(_cfg(), "cara", FUENTE, True)
    assert z["contenido"][1] == 555 and z["contenido"][3] == 810
    assert z["franja_zoom"][1] == min(1365, z["subtitulos"][0])


def test_central_sin_franja():
    z = calcular(_cfg(), "central", FUENTE, True)
    assert z["contenido"] == [0, 0, 1080, 1920]
    assert z["franja_zoom"] is None


def test_titulo_al_23_por_ciento():
    assert calcular(_cfg(), "difuminado", FUENTE, True)["titulo"]["y"][0] == 442


def test_sin_titulo():
    assert calcular(_cfg(), "difuminado", FUENTE, False)["titulo"] is None


def test_sin_subtitulos():
    z = calcular(PipelineConfig(video="x.mp4"), "difuminado", FUENTE, True)
    assert z["subtitulos"] is None and z["franja_zoom"] == [656, 1264]


def test_graficos_por_encima():
    assert calcular(_cfg(), "difuminado", FUENTE, True)["graficos_hasta"] == 656
    z = calcular(_cfg(), "central", FUENTE, True)
    assert z["graficos_hasta"] == z["subtitulos"][0] - 201


def test_frases_parten_en_dos_lineas():
    dos = calcular(_cfg(diseno="caja"), "difuminado", FUENTE, True)  # fuente 129 px
    assert dos["subtitulos"] == [1175, 1440]  # 0.85 + 1.2 líneas de fuente (1 línea: 1330)
    assert dos["franja_zoom"][1] == dos["subtitulos"][0]
