"""Efectos de sonido sintetizados (numpy/scipy, sin muestras con licencia).

Port de chatcut/tools/gen_sfx.py y de sting/buzzer de VideoEditor/tools/extras.py.
`t` de cada evento es el instante literal en la pista: el desfase perceptivo
(p. ej. whoosh 0.12 s antes del corte) lo aplica quien llama.
"""
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
TECHO_DB = -10  # techo de seguridad de la pista


@dataclass(frozen=True)
class EventoSfx:
    t: float
    tipo: str
    db: float
    num: int | None = None
    freq: float | None = None


def _lp(x, fc):
    return sosfilt(butter(4, fc, "low", fs=SR, output="sos"), x)


def _hp(x, fc):
    return sosfilt(butter(4, fc, "high", fs=SR, output="sos"), x)


def _bp(x, lo, hi):
    return sosfilt(butter(4, [lo, hi], "band", fs=SR, output="sos"), x)


def _env_ad(n, ataque, caida):
    e = np.ones(n)
    a, d = max(1, int(ataque)), max(1, int(caida))
    e[:a] = np.linspace(0, 1, a)
    e[-d:] *= np.linspace(1, 0, d)
    return e


def _norm(x):
    p = np.max(np.abs(x))
    return x / p if p > 0 else x


def _ruido(n, semilla=7):
    return np.random.default_rng(semilla).standard_normal(n)


def _barrido(n, f0, f1):
    """ruido filtrado paso banda en 5 tramos entre f0 y f1"""
    ruido = _ruido(n)
    bordes = np.linspace(f0, f1, 6)
    trozos = []
    for i in range(5):
        lo, hi = sorted((bordes[i], bordes[i + 1]))
        trozos.append(_bp(ruido[i * n // 5:(i + 1) * n // 5], lo, hi))
    return np.concatenate(trozos)


def _env_whoosh(x):
    return _norm(x * _env_ad(len(x), 0.12 * SR, 0.18 * SR))


def _whoosh_a(dur=0.45):
    return _env_whoosh(_barrido(int(dur * SR), 2500, 500))


def _whoosh_b():
    return _env_whoosh(_barrido(int(0.45 * SR), 500, 2500))


def _whoosh_c():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    return _env_whoosh(_barrido(n, 2000, 800) + 0.30 * np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 6))


def _pulsos(n, on, off):
    m = np.zeros(n)
    for p in range(0, n, on + off):
        m[p:p + on] = 1
    return m


def _whoosh_d():
    n = int(0.45 * SR)
    return _env_whoosh(_hp(_ruido(n) * _pulsos(n, int(0.04 * SR), int(0.03 * SR)), 1000))


def _whoosh_e():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    return _env_whoosh(_barrido(n, 1800, 600) + 0.20 * np.sin(2 * np.pi * 300 * t))


def _whoosh_f():
    n = int(0.51 * SR)
    x = np.zeros(n)
    w = _whoosh_a(0.45)
    x[:len(w)] += w
    d = int(0.06 * SR)
    fin = min(d + len(w), n)
    x[d:fin] += 0.70 * w[:fin - d]
    return _env_whoosh(x)


def _whoosh_g():
    n = int(0.41 * SR)
    paso = int(0.05 * SR) + int(0.04 * SR)
    m = np.zeros(n)
    for i in range(5):
        m[i * paso:min(i * paso + int(0.05 * SR), n)] = 1
    return _env_whoosh(_bp(_ruido(n) * m, 1000, 3000))


def _boom():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    ruido = _lp(_ruido(n, 42), 200) * np.exp(-t * 10)
    return _norm(np.sin(2 * np.pi * 60 * t) * np.exp(-t * 10) + 0.2 * ruido)


def _impact():
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    mascara = np.zeros(n)
    mascara[:int(0.03 * SR)] = 1
    return _norm(np.sin(2 * np.pi * 90 * t) * np.exp(-t * 14) + _hp(_ruido(n, 43), 2000) * mascara)


def _tap(freq):
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2.5 * t)) * np.exp(-t * 45)
    x[:8] += np.linspace(0.6, 0, 8)
    return _norm(x)


def _pop(num):
    f = 520 * (1 + 0.12 * (num - 1))
    t = np.arange(int(0.14 * SR)) / SR
    x = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2 * t)) * np.exp(-t * 28)
    x[:12] += np.linspace(0.6, 0, 12)
    return _norm(x)


def _pluck(num):
    f = 440 * (1 + 0.15 * (num - 1))
    t = np.arange(int(0.18 * SR)) / SR
    x = sum(a * np.sin(2 * np.pi * k * f * t) for k, a in ((1, 1), (2, 0.5), (3, 0.33), (4, 0.25)))
    return _norm(x * np.exp(-t * 22))


def _tick():
    n = int(0.04 * SR)
    return _norm(_hp(_ruido(n, 3), 3000) * _env_ad(n, 0.002 * SR, 0.03 * SR))


def _tick2():
    n = int(0.04 * SR)
    return _norm(_bp(_ruido(n, 3), 1500, 4000) * _env_ad(n, 0.002 * SR, 0.03 * SR))


def _ding():
    t = np.arange(int(0.8 * SR)) / SR
    return _norm((np.sin(2 * np.pi * 880 * t) + 0.5 * np.sin(2 * np.pi * 1760 * t)) * np.exp(-t * 5))


def _riser():
    n = int(1.2 * SR)
    return _norm(_lp(_ruido(n, 8), 400) * np.linspace(0, 1, n))


def _saw(f, t):
    return 2 * ((f * t) % 1.0) - 1


def _golpe(largo=1.4):
    """golpe de suspense: sub descendente + racimo disonante + transitorio metálico"""
    t = np.arange(int(largo * SR)) / SR
    dec = np.exp(-t / (largo * 0.45))
    sub = np.sin(2 * np.pi * np.cumsum(70 * np.exp(-t * 1.5) + 38) / SR) * dec
    racimo = _lp(sum(_saw(f, t) for f in (110, 116.5, 155.6, 233)) / 4, 1800) * np.minimum(1, t / 0.04) * dec
    ruido = _hp(_ruido(len(t), 1), 3000) * np.exp(-t / 0.05)
    return _norm(0.9 * sub + 0.7 * racimo + 0.25 * ruido)


def _error():
    """doble zumbido de respuesta incorrecta"""
    out = []
    for d in (0.16, 0.24):
        t = np.arange(int(d * SR)) / SR
        sq = np.sign(np.sin(2 * np.pi * 140 * t)) + np.sign(np.sin(2 * np.pi * 147 * t))
        env = np.minimum(1, t / 0.01) * np.minimum(1, (d - t) / 0.02)
        out += [_lp(sq * env * 0.5, 2500), np.zeros(int(0.05 * SR))]
    return _norm(np.concatenate(out))


_SINTE = {
    "whoosh_a": lambda ev: _whoosh_a(), "whoosh_b": lambda ev: _whoosh_b(),
    "whoosh_c": lambda ev: _whoosh_c(), "whoosh_d": lambda ev: _whoosh_d(),
    "whoosh_e": lambda ev: _whoosh_e(), "whoosh_f": lambda ev: _whoosh_f(),
    "whoosh_g": lambda ev: _whoosh_g(),
    "pop": lambda ev: _pop(ev.num), "pluck": lambda ev: _pluck(ev.num),
    "tick": lambda ev: _tick(), "tick2": lambda ev: _tick2(),
    "tap": lambda ev: _tap(ev.freq), "boom": lambda ev: _boom(),
    "impact": lambda ev: _impact(), "riser": lambda ev: _riser(),
    "ding": lambda ev: _ding(), "golpe": lambda ev: _golpe(), "error": lambda ev: _error(),
}
TIPOS = tuple(_SINTE)


def escribir_wav(destino: Path, mono: np.ndarray) -> Path:
    datos = (np.clip(np.column_stack([mono, mono]), -1, 1) * 32767).astype(np.int16)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(datos.tobytes())
    return destino


def pista(eventos: list[EventoSfx], total: float, destino: Path) -> Path:
    pista_ = np.zeros(int(round(total * SR)))
    for ev in eventos:
        if ev.tipo not in _SINTE:
            raise ValueError(f"tipo de sfx desconocido: {ev.tipo!r}")
        if ev.tipo in ("pop", "pluck") and ev.num is None:
            raise ValueError(f"{ev.tipo} requiere num")
        if ev.tipo == "tap" and ev.freq is None:
            raise ValueError("tap requiere freq")
        if ev.t < 0:
            raise ValueError(f"t negativo: {ev.t}")
        x = _SINTE[ev.tipo](ev) * 10 ** (ev.db / 20)
        i = int(ev.t * SR)
        j = min(len(pista_), i + len(x))
        if i < j:
            pista_[i:j] += x[:j - i]
    techo = 10 ** (TECHO_DB / 20)
    pico = np.max(np.abs(pista_)) if len(pista_) else 0
    if pico > techo:  # solo baja, nunca sube
        pista_ *= techo / pico
    return escribir_wav(destino, pista_)
