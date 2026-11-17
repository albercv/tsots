import json
import subprocess

from videopipeline.edicion import estilos
from videopipeline.edicion.componer import Zoom
from videopipeline.edicion.plan import DURACION, DURACION_FINAL, Momento, Plan
from videopipeline.edicion.renderizar import derivar, renderizar

ZONAS = {"contenido": [0, 656, 1080, 608], "subtitulos": [1269, 1440], "titulo": None,
         "franja_zoom": [656, 1264], "graficos_hasta": 656}
D = estilos.cargar("divertido")


def M(tipo, t=0.0, **kw):
    return Momento(tipo, t, **kw)


def der(momentos, final=None, zonas=ZONAS, estilo=D, dur=20.0):
    return derivar(Plan(momentos, final), zonas, estilo, dur)


def sfx(s, tipo):
    return [e for e in s.sfx if e.tipo == tipo]


def test_sonido_emparejado():
    s = der([M("etiqueta", 1, texto=["A"]), M("etiqueta", 4, texto=["B"]),
             M("contador", 6, lista=1, num=2, texto="X"), M("contador", 9, lista=2, num=1, texto="Y"),
             M("transicion", 12), M("titulo", 14, texto=["T"]), M("golpe", 3.2), M("error", 16),
             M("emoji", 17, emoji="🍉"), M("emoji", 18.5, emoji="🍌")],
            final={"texto": ["F"], "check": True})
    assert [e.tipo for e in s.sfx if e.tipo.startswith("tick")] == ["tick", "tick2"]
    assert sfx(s, "tick")[0].t == 1.08
    assert (sfx(s, "pop")[0].num, sfx(s, "pluck")[0].num) == (2, 1)
    assert sfx(s, "pop")[0].t == 6.08
    w = [e for e in s.sfx if e.tipo.startswith("whoosh")][0]
    assert abs(w.t - 11.88) < 1e-9
    assert abs(sfx(s, "riser")[0].t - 12.93) < 1e-9 and sfx(s, "impact")[0].t == 14
    assert sfx(s, "golpe") and any(p.clase == "vineta" for p in s.piezas)
    assert sfx(s, "error") and any(p.clase == "emoji" and p.params["emoji"] == "❌" for p in s.piezas)
    f1, f2 = [e.freq for e in sfx(s, "tap")]
    assert f1 != f2
    assert sfx(s, "ding")[0].t == 20 - DURACION_FINAL
    assert sfx(s, "boom")[0].t == 0.05
    assert all(e.db == D.sfx[e.tipo] for e in s.sfx)


def test_tipo_ausente_sin_evento():
    s = der([M("etiqueta", 1, texto=["A"])], estilo=estilos.cargar("formal"))
    assert [e.tipo for e in s.sfx] == ["tick"]  # formal no tiene boom


def test_transiciones_rotan():
    s = der([M("transicion", 2 * i + 1) for i in range(5)])
    letras = [p.params["tipo"] for p in s.piezas if p.clase == "transicion"]
    assert len(letras) == 5 and all(a != b for a, b in zip(letras, letras[1:]))
    assert set(letras) <= set(D.transiciones)
    assert [e.tipo for e in s.sfx if e.tipo.startswith("whoosh")][0] == "whoosh_" + letras[0].lower()


def test_contadores_alternan_lado():
    s = der([M("contador", 2 + 3 * i, lista=1, num=i + 1, texto="X") for i in range(4)])
    c = [p for p in s.piezas if p.clase == "contador"]
    assert [p.params["lado"] for p in c] == ["L", "R", "L", "R"]
    assert len({p.dur for p in c}) == 1


def test_contadores_lado_por_lista():
    ms = [M("contador", 1 + 2 * i, lista=1, num=i + 1, texto="X") for i in range(3)]
    ms += [M("contador", 8 + 2 * i, lista=2, num=i + 1, texto="Y") for i in range(2)]
    c = [p for p in der(ms).piezas if p.clase == "contador"]
    assert [p.params["lado"] for p in c] == ["L", "R", "L", "L", "R"]


def test_emoji_lateral_con_etiqueta():
    s = der([M("etiqueta", 2, texto=["A"]), M("emoji", 3, emoji="🍉"), M("emoji", 10, emoji="🍌")])
    e = [p for p in s.piezas if p.clase == "emoji"]
    assert (e[0].params["cx"], e[0].params["tam"]) == (950, 170)
    assert (e[1].params["cx"], e[1].params["tam"]) == (540, 220)


def test_zoom_y_entrada_lenta():
    s = der([M("zoom", t0=6, t1=9), M("zoom", t0=10, t1=12)])
    a, b = D.zoom_max, 1 + (D.zoom_max - 1) / 2
    assert s.zooms[:2] == [Zoom(6, 9, a, a), Zoom(10, 12, b, b)] or \
        Zoom(6, 9, a, a) in s.zooms and Zoom(10, 12, b, b) in s.zooms
    if D.zoom_lento > 0:
        assert Zoom(0, 2.5, 1, D.zoom_lento) in s.zooms
        assert Zoom(2.5, 5.0, D.zoom_lento, D.zoom_lento) in s.zooms
        assert Zoom(17, 20, 1, D.zoom_lento) in s.zooms
    z = dict(ZONAS, franja_zoom=None)
    assert der([M("zoom", t0=6, t1=9)], zonas=z).zooms == []


def test_cierre_omitido_si_zoom_solapa():
    s = der([M("zoom", t0=18, t1=19.5)])
    assert Zoom(17, 20, 1, D.zoom_lento) not in s.zooms


def test_golpe_temprano_omite_entrada_lenta():
    s = der([M("zoom", t0=1.0, t1=3.0)])
    assert not any(z.t0 == 0 for z in s.zooms) and Zoom(1.0, 3.0, D.zoom_max, D.zoom_max) in s.zooms
    assert not any(z.t0 == 2.5 for z in s.zooms)


def test_final_ocupa_hasta_el_fin():
    s = der([], final={"texto": ["FIN"], "check": True})
    p = s.piezas[-1]
    assert p.clase == "etiqueta" and p.params["grande"] and p.params["check"]
    assert abs(p.t - (20 - DURACION_FINAL)) < 1e-9 and abs(p.t + p.dur - 20) < 1e-9


def test_recorte_y_descarte():
    s = der([M("etiqueta", 19.0, texto=["A"]), M("etiqueta", 19.9, texto=["B"])])
    p = [p for p in s.piezas if p.clase == "etiqueta"]
    assert len(p) == 1 and abs(p[0].t + p[0].dur - 20) < 1e-9
    assert len(sfx(s, "tick")) + len(sfx(s, "tick2")) == 1


def test_plan_vacio():
    s = der([])
    assert s.piezas == [] and [e.tipo for e in s.sfx] == ["boom"] and s.musica == D.musica


def _trabajo(tmp_path, video, momentos, final=None):
    t = tmp_path / "t"
    t.mkdir()
    (t / "video.mp4").symlink_to(video)
    (t / "trabajo.json").write_text(json.dumps({"estilo": "divertido", "zonas": ZONAS}))
    (t / "plan.validado.json").write_text(json.dumps({"momentos": momentos, **({"final": final} if final else {})}))
    return t


def _sonda(ruta, extra):
    return subprocess.run(["ffprobe", "-v", "error", *extra, "-of", "csv=p=0", str(ruta)],
                          capture_output=True, text=True, check=True).stdout.split()


def test_renderizar_clip(tmp_path, video_vertical):
    t = _trabajo(tmp_path, video_vertical, [
        {"tipo": "etiqueta", "t": 0.5, "texto": ["HOLA"]}, {"tipo": "emoji", "t": 1.0, "emoji": "🍉"},
        {"tipo": "transicion", "t": 2.0}, {"tipo": "zoom", "t0": 1.0, "t1": 3.0}])
    salida = renderizar(t, borrador=True)
    assert salida == t / "salida.mp4"
    assert _sonda(salida, ["-select_streams", "v:0", "-show_entries", "stream=width,height"]) == ["720,1280"]
    assert abs(float(_sonda(salida, ["-show_entries", "format=duration"])[0]) - 4) <= 0.1
    assert _sonda(salida, ["-select_streams", "a:0", "-show_entries", "stream=codec_type"]) == ["audio"]


def test_renderizar_plan_vacio(tmp_path, video_vertical):
    assert renderizar(_trabajo(tmp_path, video_vertical, []), borrador=True).exists()
