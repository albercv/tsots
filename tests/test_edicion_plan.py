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
