from __future__ import annotations

import json
from dataclasses import asdict

from videopipeline import ficha as modulo_ficha
from videopipeline import shorts, shorts_prueba
from videopipeline.ficha import (
    BASE, TRANSCRIPCION, Artefacto, Ficha, Huella, _escribir_json, guardar,
)
from videopipeline.subtitles import Palabra


def _ficha(tmp_path, monkeypatch, transcrita=True):
    monkeypatch.setattr(modulo_ficha, "DIR_FICHAS", tmp_path / "fichas")
    original = tmp_path / "charla.mov"
    original.write_bytes(b"VID")
    ficha = Ficha(id="f1", nombre="charla", carpeta_salida=tmp_path,
                  original=Huella.de(original), final=Huella.de(original),
                  artefactos={BASE: Artefacto("b", "base.mp4", {}, "l")})
    if transcrita:
        ficha.artefactos[TRANSCRIPCION] = Artefacto("t", "transcripcion.json", {}, "l")
    ficha.carpeta.mkdir(parents=True)
    if transcrita:
        # 20 frases de 10 s, con punto al final de cada una.
        palabras = [Palabra(f"f{k}" + ("." if i == 9 else ""), (k - 1) * 10.0 + i,
                            (k - 1) * 10.0 + i + 1)
                    for k in range(1, 21) for i in range(10)]
        _escribir_json(ficha.ruta("transcripcion.json"), [asdict(p) for p in palabras])
    guardar(ficha)
    return ficha


def _listado(carpeta):
    return sorted((p.relative_to(carpeta), p.stat().st_mtime_ns, p.read_bytes())
                  for p in carpeta.rglob("*") if p.is_file())


def test_shorts_prueba_no_escribe_en_la_ficha(tmp_path, monkeypatch, capsys):
    ficha = _ficha(tmp_path, monkeypatch)
    monkeypatch.setattr(shorts_prueba, "duracion_video", lambda v: 200.0)
    monkeypatch.setattr(shorts_prueba, "asegurar_servidor",
                        lambda: type("S", (), {"cerrar": lambda self: None})())
    monkeypatch.setattr(shorts, "descargar", lambda m: None)
    monkeypatch.setattr(shorts, "systemone", lambda *a, **k: {
        "independiente": {"probabilities": {"si": 0.9}},
        **{parte: {"score": 3.0} for parte in shorts.PARTES_INTERES}})
    monkeypatch.setattr(shorts, "chat_json", lambda m, ms, esquema, **k: {
        "temas": [{"frase_inicio": 1, "titulo": "Todo", "sigue_al_anterior": False},
                  {"frase_inicio": 18, "titulo": "Cola", "sigue_al_anterior": False}]})
    antes = _listado(ficha.carpeta)
    salida = tmp_path / "fuera" / "salida.json"

    assert shorts_prueba.main(["f1", str(salida)]) == 0

    assert _listado(ficha.carpeta) == antes
    assert not (ficha.carpeta / "tmp").exists()
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["version"] == 2 and "segundos" in datos
    assert [t["titulo"] for t in datos["temas"]] == ["Todo", "Cola"]
    assert [(c["origen"], c["descarte"]) for c in datos["candidatos"]] == [
        ("tema", ""), ("tema", "tema_corto")]
    assert "tema" in capsys.readouterr().out


def test_shorts_prueba_ficha_inexistente_devuelve_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(modulo_ficha, "DIR_FICHAS", tmp_path / "fichas")
    assert shorts_prueba.main(["nada", str(tmp_path / "s.json")]) == 1
    assert "No existe" in capsys.readouterr().err


def test_shorts_prueba_sin_transcripcion_devuelve_1(tmp_path, monkeypatch, capsys):
    _ficha(tmp_path, monkeypatch, transcrita=False)
    assert shorts_prueba.main(["f1", str(tmp_path / "s.json")]) == 1
    assert "no está transcrita" in capsys.readouterr().err
    assert not (tmp_path / "s.json").exists()
