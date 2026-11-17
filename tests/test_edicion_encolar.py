from videopipeline.edicion import encolar
from videopipeline.subtitles import Palabra


def _llamar(carpeta, dir_edicion, stems=("s",)):
    return encolar(carpeta, "ep", list(stems), {"s": [Palabra("hola", 0.0, 0.5)]},
                   "formal", {"s": {"x": 1}}, "es", "cara", dir_edicion=dir_edicion)


def test_encolar_nombre_ocupado(tmp_path):
    carpeta = tmp_path / "c"
    carpeta.mkdir()
    (carpeta / "s.mp4").write_bytes(b"V")
    (carpeta / "s.srt").write_text("1")
    d = tmp_path / "ed"
    a, b = _llamar(carpeta, d)[0], _llamar(carpeta, d)[0]
    assert a.name == "ep - s" and b.name == "ep - s-2"
    assert (a / "subs.srt").is_file() and not (a / "caption.md").exists()
    assert not [p for p in (d / "pendientes").iterdir() if p.name.startswith(".")]


def test_encolar_salta_lo_que_no_existe(tmp_path):
    assert _llamar(tmp_path, tmp_path / "ed", ("falta",)) == []
