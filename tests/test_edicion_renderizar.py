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


def test_sfx_academico_solo_en_contadores():
    A = estilos.cargar("academico")
    s = der([M("etiqueta", 1, texto=["A"]), M("transicion", 5), M("titulo", 8, texto=["T"]),
             M("contador", 10, lista=1, num=1, texto="X"),
             M("contador", 12, lista=2, num=2, texto="Y")], estilo=A)
    assert {e.tipo for e in s.sfx} == {"pop", "pluck"}


def test_sfx_formal_tics_alternos_audibles():
    F = estilos.cargar("formal")
    s = der([M("etiqueta", 1, texto=["A"]), M("etiqueta", 4, texto=["B"])], estilo=F)
    assert [e.tipo for e in s.sfx] == ["tick", "tick2"]


# ---- tipos nuevos: señalar, lupa, B-roll, icono, dato ----
import pytest  # noqa: E402

from videopipeline.edicion import broll, callouts, graficos, pantalla  # noqa: E402
from videopipeline.edicion import renderizar as rmod  # noqa: E402

DET = pantalla.Deteccion("Factura", (100, 700, 300, 60), 0.9)
LECTURA = [pantalla.Muestra(t, (DET,)) for t in (1.0, 5.0)]


def der2(momentos, estilo=D, pant=LECTURA, dur=20.0):
    return derivar(Plan(momentos, None), ZONAS, estilo, dur, pant)


def test_derivar_tipos_nuevos():
    s = der2([M("senalar", 1.0, pantalla="Factura", forma="flecha"), M("lupa", 5.0, pantalla="Factura"),
              M("broll", 9.0, buscar="person typing"), M("icono", 13.0, icono="casa"),
              M("dato", 16.0, valor=40, texto=["DE LOS CASOS"], unidad="%")])
    p = {x.clase: x for x in s.piezas}
    assert p["senalar"].params == {"pantalla": "Factura", "forma": "flecha", "caja": DET}
    assert p["lupa"].params == {"pantalla": "Factura", "caja": DET}
    assert p["senalar"].dur == DURACION["senalar"] and p["lupa"].t == 5.0
    assert p["broll"].params == {"buscar": "person typing", "modo": "tapa"}  # sin texto en pantalla
    assert p["icono"].params == {"icono": "casa", "cx": 540, "cy": 330, "tam": 220}
    assert p["dato"].params == {"valor": 40, "texto": "DE LOS CASOS", "unidad": "%"}


def test_derivar_omite_senalar_sin_lectura():
    for pant in (None, []):
        assert der2([M("senalar", 1.0, pantalla="Factura", forma="circulo")], pant=pant).piezas == []


def test_broll_modo_ventana_si_hay_texto(monkeypatch):
    monkeypatch.setattr(rmod.ocr, "modo_broll", lambda m, t, d: "ventana")
    assert der2([M("broll", 2.0, buscar="a b")]).piezas[0].params["modo"] == "ventana"


def test_broll_ventana_evita_el_texto():
    pant = [pantalla.Muestra(2.0, (pantalla.Deteccion("Grupo", (100, 300, 300, 60), 0.9),)),
            pantalla.Muestra(3.0, (pantalla.Deteccion("Empresas", (100, 500, 300, 80), 0.9),)),
            pantalla.Muestra(9.0, (pantalla.Deteccion("Fuera", (100, 900, 300, 80), 0.9),))]
    p = der2([M("broll", 2.0, buscar="a b")], pant=pant).piezas[0]
    assert p.params["modo"] == "ventana" and p.params["evitar"] == (300, 580)


def test_icono_lateral_con_etiqueta():
    s = der2([M("etiqueta", 2, texto=["A"]), M("icono", 3, icono="casa")])
    i = [x for x in s.piezas if x.clase == "icono"][0]
    assert (i.params["cx"], i.params["tam"]) == (950, 170)


def test_icono_lateral_con_dato_o_lupa():
    for otro in (M("dato", 10.0, valor=2, texto=["EMPRESAS"]), M("lupa", 10.0, pantalla="Factura")):
        pant = [pantalla.Muestra(10.0, (DET,))]
        s = der2([otro, M("icono", 10.5, icono="casa")], pant=pant)
        i = [x for x in s.piezas if x.clase == "icono"][0]
        assert (i.params["cx"], i.params["tam"]) == (950, 170), otro.tipo


def test_sfx_nuevos_segun_estilo():
    F = estilos.cargar("formal")
    ms = [M("senalar", 1.0, pantalla="Factura", forma="circulo")]
    assert [e.tipo for e in der2(ms, estilo=F).sfx] == ["tick"]
    assert sfx(der2(ms), "tap")[0].t == 1.08
    from dataclasses import replace
    assert der2(ms, estilo=replace(F, sfx={"ding": -9})).sfx == []


def _slot_falso(frames, destino, fps):
    destino.write_bytes(b"x")
    return destino


def test_render_pieza_omite_y_limpia_si_falla(tmp_path, monkeypatch):
    def rota(*a, **k):
        raise RuntimeError("ocr")
    monkeypatch.setattr(callouts, "seguir", rota)
    d = tmp_path / "s.mov"
    d.write_bytes(b"parcial")
    p = rmod.Pieza("senalar", 1.0, 2.0, {"pantalla": "x", "forma": "circulo", "caja": DET})
    ctx = rmod.RenderCtx(tmp_path / "v.mp4", ZONAS, tmp_path / "b", set(), [], None)
    assert rmod._render_pieza(p, D, 10, d, ctx) is None and not d.exists()


def test_render_pieza_omite_callout_casi_invisible(tmp_path, monkeypatch):
    caja = (100, 700, 300, 60)
    monkeypatch.setattr(rmod.rotulos, "render_slot", _slot_falso)
    ctx = rmod.RenderCtx(tmp_path / "v.mp4", ZONAS, tmp_path / "b", set(), [], None)
    for visibles, sale in ((5, False), (7, True)):  # a 10 fps: 0.5 s se omite, 0.7 s se pinta
        monkeypatch.setattr(callouts, "seguir", lambda *a, **k: [caja] * visibles + [None] * (20 - visibles))
        for clase, q in (("senalar", {"forma": "circulo"}), ("lupa", {})):
            p = rmod.Pieza(clase, 1.0, 2.0, {"pantalla": "Factura", "caja": DET, **q})
            monkeypatch.setattr(callouts, "frames_lupa", lambda *a, **k: iter(()))
            assert (rmod._render_pieza(p, D, 10, tmp_path / "s.mov", ctx) is not None) is sale, (clase, visibles)


def test_render_senalar_pasa_la_inclinacion(tmp_path, monkeypatch):
    det = pantalla.Deteccion("Factura", (100, 700, 300, 60), 0.9, 0.07)
    vistas = []
    monkeypatch.setattr(rmod.rotulos, "render_slot", _slot_falso)
    monkeypatch.setattr(callouts, "seguir", lambda *a, **k: [det.caja] * 20)
    monkeypatch.setattr(callouts, "frames_senalar", lambda *a, **k: vistas.append(a) or iter(()))
    p = rmod.Pieza("senalar", 1.0, 2.0, {"pantalla": "Factura", "caja": det, "forma": "subrayado"})
    rmod._render_pieza(p, D, 10, tmp_path / "s.mov", rmod.RenderCtx(tmp_path / "v.mp4", ZONAS, tmp_path, set(), []))
    assert vistas and vistas[0][-1] == 0.07


@pytest.fixture
def clip_mp4(tmp_path):
    ruta = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x568:rate=10:duration=1", "-pix_fmt", "yuv420p", str(ruta)],
                   check=True)
    return ruta


def test_renderizar_con_broll_y_creditos(tmp_path, video_vertical, clip_mp4, monkeypatch):
    monkeypatch.setattr(broll, "obtener",
                        lambda buscar, usados, carpeta, clave=None, **k: broll.Clip(clip_mp4, "Ana", "https://p/1", 1))
    t = _trabajo(tmp_path, video_vertical, [{"tipo": "broll", "t": 0.5, "buscar": "person typing"}])
    assert renderizar(t, borrador=True).exists()
    assert json.loads((t / "broll.json").read_text("utf-8")) == [
        {"autor": "Ana", "url": "https://p/1", "buscar": "person typing", "t": 0.5}]


def test_renderizar_omite_broll_si_pixabay_falla(tmp_path, video_vertical, monkeypatch):
    monkeypatch.setattr(broll, "obtener", lambda *a, **k: None)
    t = _trabajo(tmp_path, video_vertical, [{"tipo": "broll", "t": 0.5, "buscar": "person typing"}])
    (t / "broll.json").write_text("[]")  # resto de un render anterior
    assert renderizar(t, borrador=True).exists() and not (t / "broll.json").exists()


def test_renderizar_omite_pieza_si_falla(tmp_path, video_vertical, clip_mp4, monkeypatch):
    intentos = []

    def rota(*a, **k):
        intentos.append(1)
        raise RuntimeError("vision")
    monkeypatch.setattr(callouts, "seguir", rota)
    monkeypatch.setattr(broll, "obtener",
                        lambda buscar, usados, carpeta, clave=None, **k: broll.Clip(clip_mp4, "Ana", "u", 1))
    monkeypatch.setattr(broll, "frames_broll", lambda *a, **k: iter(()))  # cero fotogramas
    capturados = []
    pista = rmod.sonidos.pista
    monkeypatch.setattr(rmod.sonidos, "pista", lambda ev, *a, **k: (capturados.extend(ev), pista(ev, *a, **k))[1])
    t = _trabajo(tmp_path, video_vertical, [
        {"tipo": "senalar", "t": 1.0, "pantalla": "Factura", "forma": "circulo"},
        {"tipo": "broll", "t": 0.5, "buscar": "person typing"}])
    (t / "pantalla.json").write_text(json.dumps({"version": 1, "muestras": [
        {"t": 1.0, "detecciones": [{"texto": "Factura", "caja": [100, 700, 300, 60], "confianza": 0.9}]}]}))
    assert renderizar(t, borrador=True).exists()
    assert intentos  # el seguimiento se intentó de verdad
    assert not list((t / "tmp").glob("slot_*.mov")) and not (t / "broll.json").exists()
    # sin imagen, sin sonido: solo queda el boom de inicio
    assert [e.tipo for e in capturados] == ["boom"]


def _crop(salida, seg, tmp_path, nombre):
    png = tmp_path / nombre
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(seg), "-i", str(salida), "-frames:v", "1",
                    "-vf", "crop=720:300:0:100", str(png)], check=True)
    from PIL import Image, ImageChops
    return Image.open(png).convert("RGB"), ImageChops


def test_renderizar_icono_y_dato(tmp_path, video_vertical):
    base = renderizar(_trabajo(tmp_path, video_vertical, []), borrador=True)
    ref, ch = _crop(base, 1.5, tmp_path, "ref.png")
    t2 = tmp_path / "t2"
    t2.mkdir()
    (t2 / "video.mp4").symlink_to(video_vertical)
    (t2 / "trabajo.json").write_text(json.dumps({"estilo": "divertido", "zonas": ZONAS}))
    (t2 / "plan.validado.json").write_text(json.dumps({"momentos": [
        {"tipo": "icono", "t": 1.0, "icono": "casa"},
        {"tipo": "dato", "t": 2.2, "valor": 40, "texto": ["DE LOS CASOS"], "unidad": "%"}]}))
    sal = renderizar(t2, borrador=True)
    for seg, n in ((1.5, "i.png"), (3.2, "d.png")):
        img, _ = _crop(sal, seg, tmp_path, n)
        r0, _ = _crop(base, seg, tmp_path, "r" + n)
        assert ch.difference(img, r0).getbbox() is not None


def test_zoom_lento_no_empieza_antes_del_titulo_si_solapa_la_franja():
    z = {**ZONAS, "titulo": {"y": [442, 695], "hasta": 5.0}}
    s = der([], zonas=z)
    assert all(zoom.t0 >= 5.0 for zoom in s.zooms)
    assert Zoom(17, 20, 1, D.zoom_lento) in s.zooms  # el de cierre se mantiene
    # Con el título encima de la franja (o sin título) el zoom lento sigue igual.
    for libre in ({**ZONAS, "titulo": {"y": [442, 600], "hasta": 5.0}}, ZONAS):
        assert Zoom(0, 2.5, 1, D.zoom_lento) in der([], zonas=libre).zooms


def test_transiciones_empiezan_segun_la_semilla():
    ms = [M("transicion", 2 * i + 1) for i in range(3)]
    primeras = {[p.params["tipo"] for p in derivar(Plan(ms, None), ZONAS, D, 30.0, semilla=s).piezas][0]
                for s in range(len(D.transiciones))}
    assert primeras == set(D.transiciones)  # no siempre A, B, C
