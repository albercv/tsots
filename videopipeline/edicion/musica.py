"""Música de fondo: una pista propia de ~/TSOTS/musica/<estilo>/ en rotación o,
sin ellas, una sintetizada (piano eléctrico, bajo y batería) con variantes de
progresión, tono y tempo para que no suene igual en todos los shorts."""
import json
import subprocess
from pathlib import Path

import numpy as np

from videopipeline.edicion.componer import FFMPEG

from videopipeline.edicion.sonidos import SR, _hp, _lp, escribir_wav

PROGRESIONES = ("lofi", "tranquila")
EXTENSIONES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
# Variantes de la sintetizada: (raíz, acorde) por compás. La primera es la original.
_ACORDES = (
    (("A2", ["C4", "E4", "G4", "B4"]), ("F2", ["A3", "C4", "E4", "G4"]),
     ("C3", ["E4", "G4", "B4", "D5"]), ("G2", ["B3", "D4", "E4", "A4"])),
    (("C3", ["E4", "G4", "B4", "D5"]), ("G2", ["B3", "D4", "E4", "G4"]),
     ("A2", ["C4", "E4", "G4", "A4"]), ("F2", ["A3", "C4", "E4", "G4"])),
    (("D3", ["F4", "A4", "C5", "E5"]), ("G2", ["F4", "B4", "E5"]),
     ("C3", ["E4", "G4", "B4", "D5"]), ("A2", ["C4", "E4", "G4", "B4"])),
    (("D3", ["F#4", "A4", "D5"]), ("B2", ["D4", "F#4", "A4"]),
     ("G2", ["B3", "D4", "F#4"]), ("A2", ["C#4", "E4", "A4"])),
    (("E3", ["G4", "B4", "D5", "F#5"]), ("C3", ["E4", "G4", "B4"]),
     ("G2", ["B3", "D4", "G4"]), ("D3", ["F#4", "A4", "B4"])),
)
_TRANSPORTE = (0, 2, -3, 5, -2)  # semitonos
_TEMPO = (0, 4, -4, 8, -6)  # bpm


def elegir_pista(estilo: str, dir_musica: Path) -> Path | None:
    """La siguiente pista de `dir_musica/estilo/` en rotación (así no se repite
    en dos shorts seguidos si hay más de una y se usan todas), o None si no hay
    ninguna. La rotación se guarda en `dir_musica/.rotacion.json`."""
    carpeta = dir_musica / estilo
    try:
        pistas = sorted(p for p in carpeta.iterdir()
                        if p.is_file() and p.suffix.lower() in EXTENSIONES
                        and not p.name.startswith("."))
    except OSError:
        return None
    if not pistas:
        return None
    estado = dir_musica / ".rotacion.json"
    try:
        rotacion = json.loads(estado.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rotacion = {}
    n = int(rotacion.get(estilo, -1)) + 1
    rotacion[estilo] = n
    try:
        estado.write_text(json.dumps(rotacion), encoding="utf-8")
    except OSError:
        pass  # sin rotación guardada se repite la primera: no impide editar
    return pistas[n % len(pistas)]


def preparar_pista(origen: Path, total: float, fade_out: float, destino: Path) -> Path:
    """`origen` al largo del short: repetida si es más corta, recortada si es
    más larga, a un volumen igual para todas (el del estilo se aplica al
    mezclar), con entrada y salida suaves. WAV estéreo 44,1 kHz."""
    fo = min(fade_out, total / 2)
    # El largo se corta en el filtro (atrim) y no con -t: al repetir un mp3 los
    # huecos entre vueltas harían que -t se quedara corto; apad cubre el resto.
    filtro = (f"loudnorm=I=-16:TP=-2:LRA=11,atrim=end={total:.3f},afade=t=in:d=0.3,"
              f"afade=t=out:st={max(0.0, total - fo):.3f}:d={fo:.3f},"
              f"apad=whole_dur={total:.3f}")
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-stream_loop", "-1", "-i", str(origen),
                        "-af", filtro, "-ac", "2", "-ar", "44100",
                        "-c:a", "pcm_s16le", str(destino)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"No se pudo preparar la música {origen.name}: {r.stderr.strip()[-300:]}")
    return destino
_NOTAS = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def _hz(nombre, transporte=0):  # "A3" -> Hz
    return 440 * 2 ** ((_NOTAS[nombre[:-1]] + 12 * (int(nombre[-1]) + 1) - 69 + transporte) / 12)


def _piano(f, dur):
    t = np.arange(int(dur * SR)) / SR
    tono = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.08 * np.sin(6 * np.pi * f * t)
    return tono * np.exp(-t / 1.2) * np.minimum(1, t / 0.005) * (1 + 0.15 * np.sin(2 * np.pi * 5 * t))


def pista(total: float, bpm: int, progresion: str, fade_out: float, destino: Path,
          variante: int = 0) -> Path:
    """Música sintetizada. `variante` elige progresión, tono y tempo (0 es la
    original); la misma variante da siempre el mismo audio."""
    if progresion not in PROGRESIONES:
        raise ValueError(f"progresión desconocida: {progresion!r}")
    lofi = progresion == "lofi"
    variante = abs(int(variante))
    prog = _ACORDES[variante % len(_ACORDES)]
    transporte = _TRANSPORTE[(variante // len(_ACORDES)) % len(_TRANSPORTE)]
    bpm = bpm + _TEMPO[(variante // (len(_ACORDES) * len(_TRANSPORTE))) % len(_TEMPO)]
    beat = 60 / bpm
    bar = 4 * beat
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
            sumar(teclas, _piano(_hz(nota, transporte), bar * larga), t0, 0.22)
            sumar(teclas, _piano(_hz(nota, transporte), beat), t0 + 2.5 * beat, 0.10)  # acento a contratiempo
        tb = np.arange(int(beat * 1.5 * SR)) / SR
        nota_bajo = np.sin(2 * np.pi * _hz(raiz, transporte) * tb) * np.exp(-tb / 0.5)
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
