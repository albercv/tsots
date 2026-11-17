"""Música de fondo sintetizada: progresión lofi con piano eléctrico, bajo y batería."""
from pathlib import Path

import numpy as np

from videopipeline.edicion.sonidos import SR, _hp, _lp, escribir_wav

PROGRESIONES = ("lofi", "tranquila")
_NOTAS = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def _hz(nombre):  # "A3" -> Hz
    return 440 * 2 ** ((_NOTAS[nombre[:-1]] + 12 * (int(nombre[-1]) + 1) - 69) / 12)


def _piano(f, dur):
    t = np.arange(int(dur * SR)) / SR
    tono = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.08 * np.sin(6 * np.pi * f * t)
    return tono * np.exp(-t / 1.2) * np.minimum(1, t / 0.005) * (1 + 0.15 * np.sin(2 * np.pi * 5 * t))


def pista(total: float, bpm: int, progresion: str, fade_out: float, destino: Path) -> Path:
    if progresion not in PROGRESIONES:
        raise ValueError(f"progresión desconocida: {progresion!r}")
    lofi = progresion == "lofi"
    beat = 60 / bpm
    bar = 4 * beat
    prog = [("A2", ["C4", "E4", "G4", "B4"]), ("F2", ["A3", "C4", "E4", "G4"]),
            ("C3", ["E4", "G4", "B4", "D5"]), ("G2", ["B3", "D4", "E4", "A4"])]
    n = int(round(total * SR))
    teclas, bajo, bateria = np.zeros(n), np.zeros(n), np.zeros(n)
    rng = np.random.default_rng(7)

    def sumar(buf, x, t, g):
        i = int(t * SR)
        if i < n:
            j = min(n, i + len(x))
            buf[i:j] += g * x[:j - i]

    tk = np.arange(int(0.3 * SR)) / SR
    bombo = np.sin(2 * np.pi * np.cumsum(45 + 80 * np.exp(-tk * 30)) / SR) * np.exp(-tk / 0.12)
    ts = np.arange(int(0.2 * SR)) / SR
    caja = (_hp(rng.standard_normal(len(ts)), 1200) * 0.6 + np.sin(2 * np.pi * 185 * ts)) * np.exp(-ts / 0.06)
    th = np.arange(int(0.05 * SR)) / SR
    hat = _hp(rng.standard_normal(len(th)), 7000) * np.exp(-th / 0.012)

    g_bombo = 0.9 if lofi else 0.45
    larga = 1.2 if lofi else 2.0  # en "tranquila" las teclas suenan más tiempo
    b = 0
    while b * bar < total:
        raiz, acorde = prog[b % 4]
        t0 = b * bar
        for nota in acorde:
            sumar(teclas, _piano(_hz(nota), bar * larga), t0, 0.22)
            sumar(teclas, _piano(_hz(nota), beat), t0 + 2.5 * beat, 0.10)  # acento a contratiempo
        tb = np.arange(int(beat * 1.5 * SR)) / SR
        nota_bajo = np.sin(2 * np.pi * _hz(raiz) * tb) * np.exp(-tb / 0.5)
        sumar(bajo, nota_bajo, t0, 0.8)
        sumar(bajo, nota_bajo, t0 + 2 * beat, 0.6)
        for k in (0, 2):
            sumar(bateria, bombo, t0 + k * beat, g_bombo)
        if lofi:
            for k in (1, 3):
                sumar(bateria, caja, t0 + k * beat, 0.35)
            for k in range(4):
                for e in range(2):
                    swing = 0.06 * beat if e else 0.0
                    sumar(bateria, hat, t0 + k * beat + e * beat / 2 + swing, 0.12 + 0.05 * e)
        b += 1

    mezcla = _lp(teclas, 5000) + bajo + bateria
    env = np.ones(n)
    fi = min(n, int(0.3 * SR))
    env[:fi] = np.linspace(0, 1, fi)
    fo = min(n, int(fade_out * SR))
    if fo:
        env[-fo:] = np.minimum(env[-fo:], np.linspace(1, 0, fo))
    mezcla *= env
    mezcla = mezcla / (np.max(np.abs(mezcla)) + 1e-9) * 10 ** (-1 / 20)
    return escribir_wav(destino, mezcla)
