"""Compositor de una sola pasada para shorts editados: zoom solo en la
franja del vídeo -> rótulos (PTS desplazado) -> SFX + música con ducking ->
loudnorm. Port de VideoEditor/tools/compose.py con API tipada."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
ANCHO = 1080


@dataclass(frozen=True)
class Overlay:
    archivo: Path
    t: float
    dur: float


@dataclass(frozen=True)
class Zoom:
    t0: float
    t1: float
    z0: float
    z1: float


def _z_por_tramos(zooms: list[Zoom]) -> str:
    """Expresión de zoompan: rampa lineal z0->z1 en [t0,t1], 1 fuera."""
    expr = "1"
    for z in reversed(zooms):
        rampa = f"({z.z0}+({z.z1}-{z.z0})*(it-{z.t0})/({z.t1}-{z.t0}))"
        expr = f"if(between(it,{z.t0},{z.t1}),{rampa},{expr})"
    return expr


def _fps(fuente: Path) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate", "-of", "csv=p=0", str(fuente)],
        capture_output=True, text=True, check=True).stdout.strip()


def _ejecutar(cmd: list[str]) -> str:
    """Ejecuta ffmpeg; si falla, el error lleva su stderr. Devuelve el stderr."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stderr
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg falló al componer: {e.stderr}") from e


def _duracion(fuente: Path) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(fuente)],
        capture_output=True, text=True, check=True).stdout.strip()


def _tiene_audio(fuente: Path) -> bool:
    return bool(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(fuente)],
        capture_output=True, text=True, check=True).stdout.strip())


def componer(fuente: Path, destino: Path, overlays: list[Overlay],
             franja: tuple[int, int] | None, zooms: list[Zoom],
             sfx: list[Path], musica: Path | None, musica_db: float,
             borrador: bool = False) -> None:
    if not _tiene_audio(fuente):
        raise ValueError(f"La fuente no tiene pista de audio: {fuente}")
    entradas = ["-i", str(fuente)]
    fc: list[str] = []
    fa: list[str] = []
    actual = "[0:v]"

    if franja is not None and zooms:
        y0, y1 = franja
        alto = (y1 - y0) // 2 * 2  # el recorte debe tener alto par
        zp = (f"zoompan=z='{_z_por_tramos(zooms)}':x='iw/2-iw/zoom/2':"
              f"y='ih/2-ih/zoom/2':d=1:s={ANCHO}x{alto}:fps={_fps(fuente)}")
        fc.append(f"{actual}split=2[full][b];[b]crop={ANCHO}:{alto}:0:{y0},{zp}[bz];"
                  f"[full][bz]overlay=0:{y0}[v0]")
        actual = "[v0]"

    for i, ov in enumerate(sorted(overlays, key=lambda o: o.t), start=1):
        entradas += ["-i", str(ov.archivo)]
        fc.append(f"[{i}:v]setpts=PTS-STARTPTS+{ov.t}/TB[o{i}]")
        fc.append(f"{actual}[o{i}]overlay=enable='between(t,{ov.t},{ov.t + ov.dur})'"
                  f":eof_action=pass[v{i}]")
        actual = f"[v{i}]"
    fc.append(f"{actual}{'scale=720:-2' if borrador else 'null'}[vout]")

    n = len(overlays) + 1
    pistas = []
    for wav in sfx:
        entradas += ["-i", str(wav)]
        pistas.append(f"[{n}:a]")
        n += 1
    if musica is not None:
        entradas += ["-i", str(musica)]
        fa.append("[0:a]loudnorm=I=-16:TP=-1.5,asplit=2[voz][sc]")
        fa.append(f"[{n}:a]volume={musica_db}dB[mus]")
        fa.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=8:attack=15:"
                  "release=400[duck]")
        mezcla = ["[voz]"] + pistas + ["[duck]"]
    else:
        fa.append("[0:a]loudnorm=I=-16:TP=-1.5[voz]")
        mezcla = ["[voz]"] + pistas
    fa.append(f"{''.join(mezcla)}amix=inputs={len(mezcla)}:duration=first:normalize=0[mix]")
    # loudnorm de una pasada se pasa de largo en clips cortos: dos pasadas
    ln = "loudnorm=I=-14:TP=-1.5:LRA=11"
    medida = _ejecutar([FFMPEG, "-y", "-v", "info", *entradas, "-filter_complex",
                        ";".join(fa) + f";[mix]{ln}:print_format=json[x]",
                        "-map", "[x]", "-f", "null", "-"])
    m = json.loads(re.findall(r"\{[^{}]*\}", medida)[-1])
    ln += (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
           f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
           f":offset={m['target_offset']}:linear=true")
    fa.append(f"[mix]{ln},aresample=48000[aout]")

    cod = ["-c:v", "libx264", "-preset", "veryfast" if borrador else "slow",
           "-crf", "26" if borrador else "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k" if borrador else "256k",
           "-ar", "48000", "-movflags", "+faststart"]
    cmd = [FFMPEG, "-y", "-v", "error", *entradas, "-filter_complex", ";".join(fc + fa),
           "-map", "[vout]", "-map", "[aout]", "-t", _duracion(fuente), *cod,
           str(destino)]
    _ejecutar(cmd)
