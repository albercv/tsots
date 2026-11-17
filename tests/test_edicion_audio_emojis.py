import wave

import numpy as np
import pytest

from videopipeline.edicion import emojis, musica, sonidos
from videopipeline.edicion.sonidos import EventoSfx


def _leer(ruta):
    with wave.open(str(ruta)) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 44100
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768
    return x.reshape(-1, 2)


def test_emoji_disponible():
    assert emojis.disponible("🍉")
    assert not emojis.disponible("\U000E0001")


def test_frames_emoji_pop():
    frames = list(emojis.frames_emoji("🍉", 1.0, 540, 960, 200, 30))
    assert len(frames) == 30
    assert frames[0].size == (1080, 1920)
    b0 = frames[0].getbbox()
    assert b0 is None or max(b0[2] - b0[0], b0[3] - b0[1]) < 40
    b = frames[9].getbbox()
    assert b[2] - b[0] >= 200 * 0.9


def test_vineta_bordes():
    f = list(emojis.frames_vineta(1.0, 30))[3]
    a = np.asarray(f)[..., 3]
    assert a[0, 0] > a[960, 540] == 0


def test_pista_sfx(tmp_path):
    ev = [EventoSfx(0.5, "tick", -6), EventoSfx(1.0, "golpe", -6)]
    x = _leer(sonidos.pista(ev, 3.0, tmp_path / "s.wav"))
    assert len(x) == 3 * 44100
    assert np.abs(x[: int(0.49 * 44100)]).max() == 0
    assert np.abs(x[44100:]).max() > 0.01
    assert np.abs(x).max() <= 10 ** (-10 / 20) + 1e-3
    with pytest.raises(ValueError):
        sonidos.pista([EventoSfx(0, "nada", 0)], 1, tmp_path / "x.wav")
    with pytest.raises(ValueError):
        sonidos.pista([EventoSfx(0, "pop", 0)], 1, tmp_path / "x.wav")  # falta num
    with pytest.raises(ValueError):
        sonidos.pista([EventoSfx(-1, "tick", 0)], 1, tmp_path / "x.wav")


def test_todos_los_tipos(tmp_path):
    ev = [EventoSfx(0, t, -10, num=2, freq=700) for t in sonidos.TIPOS]
    sonidos.pista(ev, 2.0, tmp_path / "t.wav")


def test_musica(tmp_path):
    for prog in ("lofi", "tranquila"):
        x = _leer(musica.pista(10, 96, prog, 1.5, tmp_path / f"{prog}.wav"))
        assert abs(len(x) / 44100 - 10) <= 0.01
        assert np.abs(x[-4410:]).max() < 0.05
        assert np.abs(x).max() > 0.8
    with pytest.raises(ValueError):
        musica.pista(10, 96, "x", 1.5, tmp_path / "m.wav")
