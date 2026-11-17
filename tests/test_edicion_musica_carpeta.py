"""Música de fondo: pistas propias en ~/TSOTS/musica/<estilo>/ y, sin ellas,
la sintetizada con variantes."""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import pytest

from videopipeline.edicion import musica, renderizar
from videopipeline.edicion.componer import FFMPEG


def _tono(destino: Path, segundos: float, hz: int = 440) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency={hz}:duration={segundos}", str(destino)], check=True)
    return destino


def _segundos(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        assert (w.getnchannels(), w.getframerate()) == (2, 44100)
        return w.getnframes() / w.getframerate()


def test_sin_carpeta_ni_pistas_no_hay_pista(tmp_path):
    assert musica.elegir_pista("divertido", tmp_path / "no-existe") is None
    (tmp_path / "divertido").mkdir()
    (tmp_path / "divertido" / "LICENCIA.txt").write_text("x")
    assert musica.elegir_pista("divertido", tmp_path) is None


def test_rota_las_pistas_sin_repetir_seguidas(tmp_path):
    for nombre in ("a.mp3", "b.mp3", "c.wav"):
        _tono(tmp_path / "divertido" / nombre, 1)
    elegidas = [musica.elegir_pista("divertido", tmp_path).name for _ in range(6)]
    assert set(elegidas[:3]) == {"a.mp3", "b.mp3", "c.wav"}  # se usan todas
    assert all(x != y for x, y in zip(elegidas, elegidas[1:]))
    assert json.loads((tmp_path / ".rotacion.json").read_text())["divertido"] == 5


def test_cada_estilo_usa_su_carpeta(tmp_path):
    _tono(tmp_path / "divertido" / "a.mp3", 1)
    assert musica.elegir_pista("formal", tmp_path) is None
    assert musica.elegir_pista("divertido", tmp_path).name == "a.mp3"


def test_una_pista_corta_se_repite_hasta_el_final(tmp_path):
    corta = _tono(tmp_path / "corta.mp3", 2)
    salida = musica.preparar_pista(corta, 5.0, 1.0, tmp_path / "m.wav")
    assert _segundos(salida) == pytest.approx(5.0, abs=0.05)


def test_una_pista_larga_se_recorta(tmp_path):
    larga = _tono(tmp_path / "larga.mp3", 8)
    assert _segundos(musica.preparar_pista(larga, 3.0, 1.0, tmp_path / "m.wav")) == \
        pytest.approx(3.0, abs=0.05)


def test_variantes_sintetizadas(tmp_path):
    def bytes_de(variante, nombre):
        return musica.pista(6, 96, "lofi", 1.0, tmp_path / nombre, variante=variante).read_bytes()
    assert bytes_de(0, "a.wav") == bytes_de(0, "b.wav")  # determinista
    distintas = {bytes_de(v, f"v{v}.wav") for v in range(5)}
    assert len(distintas) == 5


def test_render_usa_la_carpeta_y_si_no_la_sintetizada(tmp_path, monkeypatch):
    from videopipeline import edicion
    monkeypatch.setattr(edicion, "DIR_MUSICA", tmp_path / "musica")
    datos = {"bpm": 96, "db": -14, "progresion": "lofi", "fade_out": 1.0}
    sintetizada = renderizar._pista_musica(datos, "divertido", 4.0, tmp_path / "t1", "trabajo")
    assert sintetizada.exists() and _segundos(sintetizada) == pytest.approx(4.0, abs=0.05)
    _tono(tmp_path / "musica" / "divertido" / "propia.mp3", 10, hz=660)
    propia = renderizar._pista_musica(datos, "divertido", 4.0, tmp_path / "t2", "trabajo")
    assert propia.read_bytes() != sintetizada.read_bytes()
    assert json.loads((tmp_path / "musica" / ".rotacion.json").read_text()) == {"divertido": 0}
    assert renderizar._pista_musica(None, "divertido", 4.0, tmp_path / "t3", "x") is None


def test_si_la_pista_propia_falla_se_usa_la_sintetizada(tmp_path, monkeypatch):
    from videopipeline import edicion
    monkeypatch.setattr(edicion, "DIR_MUSICA", tmp_path / "musica")
    rota = tmp_path / "musica" / "divertido" / "rota.mp3"
    rota.parent.mkdir(parents=True)
    rota.write_bytes(b"no es audio")
    datos = {"bpm": 96, "db": -14, "progresion": "lofi", "fade_out": 1.0}
    pista = renderizar._pista_musica(datos, "divertido", 3.0, tmp_path / "t", "trabajo")
    assert _segundos(pista) == pytest.approx(3.0, abs=0.05)
