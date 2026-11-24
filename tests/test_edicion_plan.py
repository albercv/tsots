import json
import subprocess

import pytest

from videopipeline.edicion import estilos, plan as P, validar_plan
from videopipeline.edicion.plan import Momento, Plan
from videopipeline.subtitles import Palabra

PAL = [Palabra("Hola", 1.0, 1.4), Palabra("melón,", 31.76, 32.1), Palabra("llama", 53.36, 53.7), Palabra("fin", 58.0, 58.3)]
ZONAS = {"contenido": [0, 1920], "subtitulos": [1400, 1700], "titulo": None,
         "franja_zoom": [660, 1260], "graficos_hasta": 600}
DIV = estilos.cargar("divertido")
FOR = estilos.cargar("formal")


def val(momentos, final=None, estilo=DIV, zonas=ZONAS, dur=60.0):
    return P.validar(Plan(momentos, final), PAL, zonas, estilo, dur)


def et(t, texto=("HOLA",), palabra="hola"):
    return Momento("etiqueta", t=t, palabra=palabra, texto=list(texto))


def test_ajusta_t_a_la_palabra():
    plan, errs = val([Momento("golpe", t=31.5, palabra="melón")])
    assert errs == [] and plan.momentos[0].t == 31.76


def test_palabra_inexistente():
    _, errs = val([Momento("golpe", t=31.5, palabra="sandía")])
    assert len(errs) == 1 and "sandía" in errs[0]


def test_palabra_lejos():
    _, errs = val([Momento("golpe", t=20, palabra="melón")])
    assert errs and "31.76" in errs[0]


def test_fuera_de_duracion():
    assert val([Momento("transicion", t=61)])[1]


def test_emoji_no_permitido_en_formal():
    assert val([Momento("emoji", t=31.76, palabra="melón", emoji="🍉")], estilo=FOR)[1]


def test_emoji_sin_glifo():
    assert val([Momento("emoji", t=31.76, palabra="melón", emoji="\U000E0001")])[1]


def test_emoji_valido():
    assert val([Momento("emoji", t=31.76, palabra="melón", emoji="🍉")])[1] == []


def test_texto_con_glifo_raro():
    _, errs = val([et(1.0, ["HOLA 🍉"])])
    assert errs and "🍉" in errs[0]


def test_texto_no_cabe():
    assert val([et(1.0, ["W" * 60])])[1]


def test_solape_misma_zona():
    a = Momento("etiqueta", t=31.76, palabra="melón", texto=["A"])
    assert val([et(31.8, palabra="melón"), a])[1]
    e = Momento("emoji", t=31.76, palabra="melón", emoji="🍉")
    assert val([a, e])[1] == []
    assert val([e, Momento("emoji", t=31.76, palabra="melón", emoji="🍉")])[1]


def test_nada_antes_del_titulo():
    z = {**ZONAS, "titulo": {"y": [0, 300], "hasta": 5.0}}
    _, errs = val([et(1.0)], zonas=z)
    assert errs and "5" in errs[0]
    assert val([Momento("golpe", t=1.0, palabra="hola")], zonas=z)[1] == []
    assert val([et(1.0)])[1] == []


def test_presupuesto():
    ms = [Momento("transicion", t=float(2 * i)) for i in range(30)]
    _, errs = val(ms, estilo=FOR)
    assert any("máximo" in e for e in errs)


def test_contadores_consecutivos():
    def c(t, n, w):
        return Momento("contador", t=t, palabra=w, lista=1, num=n, texto="X")
    assert val([c(1.0, 1, "hola"), c(53.36, 3, "llama")])[1]
    assert val([c(1.0, 1, "hola"), c(53.36, 2, "llama")])[1] == []


def test_contador_largo():
    assert val([Momento("contador", t=1.0, palabra="hola", lista=1, num=1, texto="A" * 23)])[1]


def test_zoom():
    z = lambda a, b: Momento("zoom", t0=a, t1=b)
    assert val([z(10, 14)])[1] == []
    assert val([z(10, 14), z(12, 16)])[1]
    assert val([z(10, 14)], zonas={**ZONAS, "franja_zoom": None})[1]
    assert val([z(14, 10)])[1]
    assert val([z(10, 10.5)])[1]
    assert val([z(10, 17)])[1]
    assert val([z(10, 14)], estilo=FOR)[1]


def test_final():
    assert val([], {"texto": ["REVISA · PLANIFICA"], "check": True})[1] == []
    assert val([], {"texto": ["✓ NO"], "check": False})[1]
    assert val([Momento("emoji", t=58.0, palabra="fin", emoji="🍉")], {"texto": ["FIN"], "check": False})[1]


def test_plan_vacio_valido():
    assert val([])[1] == []


def test_leer_errores(tmp_path):
    f = tmp_path / "p.json"
    for txt in ("no json", '{"x": 1}', '{"momentos": [{"tipo": "raro"}]}',
                '{"momentos": [{"tipo": "golpe", "t": "a"}]}',
                '{"momentos": [{"tipo": "golpe", "zzz": 1}]}'):
        f.write_text(txt)
        with pytest.raises(ValueError):
            P.leer(f)


def test_guardar_leer(tmp_path):
    p = Plan([Momento("golpe", t=1.0, palabra="hola"), Momento("zoom", t0=1.0, t1=3.0)], {"texto": ["A"], "check": False})
    P.guardar(p, tmp_path / "p.json")
    assert P.leer(tmp_path / "p.json") == p


def _trabajo(tmp_path, momentos):
    subprocess.run(["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=60:r=1",
                    str(tmp_path / "video.mp4")], check=True, capture_output=True)
    (tmp_path / "palabras.json").write_text(json.dumps([{"texto": "melón", "inicio": 31.76, "fin": 32.1}]))
    (tmp_path / "trabajo.json").write_text(json.dumps({"estilo": "divertido", "zonas": ZONAS}))
    (tmp_path / "plan.json").write_text(json.dumps({"momentos": momentos}))


def test_cli(tmp_path, capsys):
    _trabajo(tmp_path, [{"tipo": "golpe", "t": 31.5, "palabra": "melón"}])
    assert validar_plan.main([str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert json.loads((tmp_path / "plan.validado.json").read_text())["momentos"][0]["t"] == 31.76
    (tmp_path / "plan.json").write_text(json.dumps({"momentos": [{"tipo": "golpe", "t": 5, "palabra": "nada"}]}))
    assert validar_plan.main([str(tmp_path)]) == 1
    assert not (tmp_path / "plan.validado.json").exists()
    assert "nada" in capsys.readouterr().out
    (tmp_path / "plan.json").write_text("{")
    assert validar_plan.main([str(tmp_path)]) == 1


def test_texto_str_o_lista_incorrecta():
    for tipo in ("etiqueta", "titulo"):
        _, errs = val([Momento(tipo, t=1.0, palabra="hola", texto="HOLA")])
        assert errs and '["HOLA"]' in errs[0]
        assert val([Momento(tipo, t=1.0, palabra="hola", texto=["A", "B", "C"])])[1]
    assert val([Momento("contador", t=1.0, palabra="hola", lista=1, num=1, texto=["X"])])[1]
    assert val([], {"texto": "FIN", "check": False})[1]


# ---- tipos nuevos: señalar, lupa, B-roll, icono, dato ----
from videopipeline.edicion.pantalla import Deteccion, Muestra

PAL2 = PAL + [Palabra("diez", 20.0, 20.3), Palabra("por", 40.0, 40.1), Palabra("ciento", 40.1, 40.4),
              Palabra("cuarenta", 39.8, 40.0)]
PAL2.sort(key=lambda p: p.inicio)
PANT = [Muestra(t / 2, (Deteccion("Revisión", (100, 800, 400, 80), 0.98),)) for t in range(0, 130)]


def val2(momentos, pantalla=PANT, broll=True, estilo=DIV, zonas=ZONAS, dur=60.0, final=None):
    return P.validar(Plan(momentos, final), PAL2, zonas, estilo, dur, pantalla, broll)


def sen(t=31.76, tipo="senalar", **kw):
    return Momento(tipo, t=t, palabra="melón", pantalla="revision", **kw)


def test_senalar_y_lupa_validos():
    plan, errs = val2([sen()])
    assert errs == [] and plan.momentos[0].forma == "circulo"
    plan, errs = val2([sen(tipo="lupa")])
    assert errs == [] and plan.momentos[0].forma == "circulo"


def test_senalar_texto_no_visible():
    _, errs = val2([Momento("senalar", t=31.76, palabra="melón", pantalla="otra cosa")], pantalla=[])
    assert errs and "no está visible" in errs[0] and "coincidencia" in errs[0]


def test_senalar_sin_ocr():
    _, errs = val2([sen()], pantalla=None)
    assert errs == ["Momento 0 (senalar): este vídeo no tiene lectura de pantalla; quita el momento"]


def test_forma_invalida():
    assert "forma" in val2([sen(forma="cuadro")])[1][0]
    assert val2([sen(forma="flecha")])[1] == []


def test_broll_requiere_clave_y_busqueda():
    b = lambda s: Momento("broll", t=31.76, palabra="melón", buscar=s)
    assert val2([b("person typing")], broll=False)[1]
    assert val2([b("person typing")])[1] == []
    for malo in ("laptop", "a b c d e f g", "persona ñandú", "日本 語"):
        assert val2([b(malo)])[1], malo


def test_broll_ventana_sin_hueco_es_error():
    b = Momento("broll", t=31.76, palabra="melón", buscar="person typing")
    llena = [Muestra(t / 2, (Deteccion("Pantalla llena", (100, 130, 800, 460), 0.98),)) for t in range(0, 130)]
    errs = val2([b], pantalla=llena)[1]
    assert len(errs) == 1 and "casi toda la pantalla" in errs[0] and "t=31.76" in errs[0]
    assert val2([b])[1] == []  # texto con hueco: ventana
    assert val2([b], pantalla=[])[1] == []  # sin texto: tapa
    assert val2([b], pantalla=None)[1] == []


def test_broll_maximo_por_duracion():
    ms = [Momento("broll", t=t, palabra=p, buscar="person typing") for t, p in ((1.0, "hola"), (20.0, "diez"), (31.76, "melón"))]
    assert any("B-roll" in e for e in val2(ms, dur=30.0)[1])
    assert not any("B-roll" in e for e in val2(ms[:2], dur=30.0)[1])


def test_broll_no_coincide_con_nada_visual():
    b = Momento("broll", t=31.76, palabra="melón", buscar="person typing")
    otros = [et(31.76, palabra="melón"), Momento("icono", t=31.76, palabra="melón", icono="check"),
             sen(), sen(tipo="lupa"), Momento("emoji", t=31.76, palabra="melón", emoji="🔥")]
    for o in otros:
        assert val2([b, o])[1], o.tipo
    assert val2([b], final={"texto": ["FIN"], "check": False}, dur=33.0)[1]
    assert val2([b, Momento("transicion", t=32.5)])[1] == []


def test_icono_desconocido_sugiere_parecidos():
    _, errs = val2([Momento("icono", t=31.76, palabra="melón", icono="chek")])
    assert errs and "parecidos" in errs[0] and "check" in errs[0]


def test_dato_valor_dicho():
    d = lambda v, **kw: Momento("dato", t=20.0, palabra="diez", valor=v, texto="USUARIOS", **kw)
    assert val2([d(10)])[1] == []
    assert val2([d(12)])[1]
    assert val2([Momento("dato", t=20.0, palabra="diez", valor=10, texto="X" * 23)])[1]


def test_dato_porcentaje():
    d = lambda **kw: Momento("dato", t=40.0, palabra="cuarenta", valor=40, texto="TASA", **kw)
    assert val2([d(unidad="%")])[1] == []
    _, errs = val2([Momento("dato", t=20.0, palabra="diez", valor=10, texto="X", unidad="%")])
    assert errs


def test_lupa_y_dato_ocupan_zona_superior():
    d = Momento("dato", t=20.0, palabra="diez", valor=10, texto="X")
    assert val2([Momento("lupa", t=20.0, palabra="diez", pantalla="revision"), d])[1]
    assert val2([d, et(20.0, palabra="diez")])[1]


def test_icono_lateral_como_emoji():
    ic = Momento("icono", t=31.76, palabra="melón", icono="check")
    assert val2([ic, et(31.76, palabra="melón")])[1] == []


def test_senalar_no_coincide_con_zoom():
    z = Momento("zoom", t0=30.0, t1=34.0)
    assert val2([sen(), z])[1]
    assert val2([sen()])[1] == []
    assert val2([sen()], zonas={**ZONAS, "franja_zoom": None})[1] == []
    ultimo = Momento("senalar", t=58.0, palabra="fin", pantalla="revision")  # zoom lento automático
    assert val2([ultimo])[1]
    assert val2([ultimo], zonas={**ZONAS, "franja_zoom": None})[1] == []


def test_senalar_inicio_con_zoom_lento():
    assert val2([Momento("senalar", t=1.0, palabra="hola", pantalla="revision")])[1]


def test_sugerencia_etiqueta_en_pantalla():
    plan = Plan([et(31.76, texto=("REVISIÓN",), palabra="melón")])
    s = P.sugerencias(plan, PANT)
    assert len(s) == 1 and s[0].startswith("Sugerencia: ") and "senalar" in s[0] and "momento 0" in s[0]
    assert P.sugerencias(plan, None) == []


def test_sugerencia_variedad():
    plan = Plan([Momento("golpe", t=1.0), Momento("golpe", t=2.0), Momento("zoom", t0=1, t1=3), Momento("golpe", t=3.0)])
    assert len(P.sugerencias(plan, None)) == 1


def test_cli_sugerencia(tmp_path, capsys):
    _trabajo(tmp_path, [{"tipo": "etiqueta", "t": 31.76, "palabra": "melón", "texto": ["REVISIÓN"]}])
    (tmp_path / "pantalla.json").write_text(json.dumps({"version": 1, "muestras": [
        {"t": 31.5, "detecciones": [{"texto": "Revisión", "caja": [0, 0, 10, 10], "confianza": 0.9}]}]}))
    assert validar_plan.main([str(tmp_path)]) == 0
    sal = capsys.readouterr().out.splitlines()
    assert sal[0] == "OK" and sal[1].startswith("Sugerencia: ")


def test_densidad_cuenta_nuevos():
    ms = [Momento("icono", t=1.0 + i, palabra="hola", icono="check") for i in range(30)]
    assert any("momentos" in e for e in val2(ms)[1])


def test_error_pantalla_lista_coincidencias_cercanas():
    # una línea con cada palabra dicha, visible justo cuando se dice
    pant = [Muestra(i / 2, tuple(Deteccion(f"Texto {p.texto.strip(',')}", (100, 800, 400, 80), 0.9)
                                 for p in PAL2 if -0.25 <= i / 2 - p.inicio <= 1.0)) for i in range(0, 121)]
    _, errs = val2([Momento("senalar", t=53.36, palabra="llama", pantalla="otra cosa")], pantalla=pant)
    assert errs and "'llama'" in errs[0] and "'hola'" not in errs[0]


ANCHA = [Muestra(t / 2, (Deteccion("Revisión de las fichas de la empresa", (100, 800, 800, 80), 0.98),))
         for t in range(0, 130)]


def test_lupa_texto_demasiado_ancho():
    lupa = lambda p: Momento("lupa", t=31.76, palabra="melón", pantalla=p)
    _, errs = val2([lupa("Revisión de las fichas de la empresa")], pantalla=ANCHA)
    assert errs and "demasiado ancho para la lupa" in errs[0]
    assert val2([lupa("Revisión")], pantalla=ANCHA)[1] == []  # un fragmento corto sí cabe
    assert val2([Momento("senalar", t=31.76, palabra="melón", pantalla="Revisión de las fichas de la empresa")],
                pantalla=ANCHA)[1] == []


def test_sugerencia_no_con_texto_diminuto_ni_ya_senalado():
    x = [Muestra(t / 2, (Deteccion("X", (100, 800, 20, 20), 0.9),)) for t in range(0, 130)]
    assert P.sugerencias(Plan([et(31.76, texto=("EXTRA",), palabra="melón")]), x) == []
    assert P.sugerencias(Plan([et(31.76, texto=("REVISIÓN",), palabra="melón"), sen()]), PANT) == []
    assert P.sugerencias(Plan([et(31.76, texto=("REVISIÓN",), palabra="melón"), sen(t=50.0)]), PANT)


def test_zoom_no_empieza_antes_del_titulo_si_solapa_la_franja():
    z = {**ZONAS, "titulo": {"y": [442, 695], "hasta": 5.0}}
    _, errs = val([Momento("zoom", t0=2.0, t1=4.0)], zonas=z)
    assert errs and "5" in errs[0] and "zoom" in errs[0]
    assert val([Momento("zoom", t0=5.0, t1=7.0)], zonas=z)[1] == []
    # Sin solape (encuadre central, titulo por encima de la franja) no hay restricción.
    z = {**ZONAS, "titulo": {"y": [442, 600], "hasta": 5.0}}
    assert val([Momento("zoom", t0=2.0, t1=4.0)], zonas=z)[1] == []


def test_error_solo_si_se_habla_de_un_error():
    pal = [Palabra("La", 9.6, 9.7), Palabra("novedad", 9.7, 10.0), Palabra("no", 10.0, 10.1),
           Palabra("es", 10.1, 10.2), Palabra("simplemente", 10.2, 10.7),
           Palabra("ahora", 20.0, 20.2), Palabra("no", 20.3, 20.4), Palabra("se", 20.4, 20.5),
           Palabra("puede.", 20.5, 20.8)]

    def v(t):
        return P.validar(Plan([Momento("error", t=t, palabra="no")]), pal, ZONAS, DIV, 60.0)[1]
    errs = v(10.0)  # una negación sin más no lleva cruz
    assert len(errs) == 1 and "error" in errs[0] and "novedad" in errs[0]
    assert v(20.3) == []
