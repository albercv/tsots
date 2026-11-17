"""Rótulos (overlays con alfa) para la edición de shorts.

Port de chatcut/tools/gen_overlays.py sin la capa CLI/JSON: plantillas PIL de
etiqueta, contador lateral y 7 transiciones, más render a ProRes 4444.
"""
import math
import random
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from videopipeline.edicion.estilos import Paleta

W, H = 1080, 1920
FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
_FUENTES_RESPALDO = [
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/System/Library/Fonts/Menlo.ttc", 1),
]
_CHECK = "✓"
_ARROW = "→"
_PUNTUACION = set(" .,:;¿?¡!«»\"'·-%&()/")


def glifos_validos(texto: str, check: bool) -> bool:
    """Solo letras latinas (con acentos y Ñ), dígitos ASCII y puntuación básica; '✓' solo con check."""
    return all((c.isalpha() and ord(c) < 0x250 and c not in "ªº") or c in "0123456789" or c in _PUNTUACION
               or (check and c == _CHECK) for c in texto)


def _fuente(paleta: Paleta, size: int) -> ImageFont.FreeTypeFont:
    for path, idx in [tuple(paleta.fuente)] + _FUENTES_RESPALDO:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except OSError:
            continue
    raise RuntimeError("No se encontró ninguna fuente en negrita utilizable")


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _vacio() -> Image.Image:
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def _tam_texto(fnt, texto):
    bb = fnt.getbbox(texto)
    return bb[2] - bb[0], bb[3] - bb[1]


def _n_frames(dur: float, fps: int) -> int:
    return int(round(dur * fps))


def _destello(d, t):
    if 0.25 < t < 0.55:
        flash = int(46 * (1 - abs(t - 0.4) / 0.15))
        d.rectangle([0, 0, W, H], fill=(255, 255, 255, max(0, flash)))


# ---------- transiciones (0.5 s, acento/blanco) ----------

def _barrido_abajo(dur, paleta, fps):
    n = _n_frames(dur, fps)
    for i in range(n):
        t = i / max(n - 1, 1)
        img = _vacio()
        d = ImageDraw.Draw(img)
        y = int(_ease_out_cubic(t) * (H + 200)) - 100
        for trail in range(6):
            ty = y - trail * 26
            if -20 < ty < H:
                d.rectangle([0, ty, W, ty + 14], fill=(*paleta.acento, max(0, 200 - trail * 38)))
        _destello(d, t)
        yield img


def _barrido_derecha(dur, paleta, fps):
    n = _n_frames(dur, fps)
    for i in range(n):
        t = i / max(n - 1, 1)
        img = _vacio()
        d = ImageDraw.Draw(img)
        x = int(_ease_out_cubic(t) * (W + 200)) - 100
        for trail in range(6):
            tx = x - trail * 26
            if -20 < tx < W:
                d.rectangle([tx, 0, tx + 14, H], fill=(*paleta.acento, max(0, 200 - trail * 38)))
        _destello(d, t)
        yield img


def _iris(dur, paleta, fps):
    n = _n_frames(dur, fps)
    cx, cy = W // 2, H // 2
    max_r, grosor = 1250, 12
    for i in range(n):
        t = i / max(n - 1, 1)
        img = _vacio()
        d = ImageDraw.Draw(img)
        r = _ease_out_cubic(t) * max_r
        if r > grosor / 2:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*paleta.acento, 255), width=grosor)
        _destello(d, t)
        yield img


def _glitch(dur, paleta, fps):
    n = _n_frames(dur, fps)
    n_glitch = int(round(0.3 * fps))
    alto = H // 4
    offsets, parpadeos = [], []
    for s in range(4):
        rng = random.Random(s)  # semilla fija por franja
        mag = rng.randint(40, 60)
        offsets.append((1 if s % 2 == 0 else -1) * mag)
        pool = list(range(n_glitch))
        parpadeos.append(set(rng.sample(pool, min(rng.randint(2, 3), len(pool)))))
    for i in range(n):
        img = _vacio()
        if i < n_glitch:
            d = ImageDraw.Draw(img)
            for s in range(4):
                if i in parpadeos[s]:
                    continue
                d.rectangle([offsets[s], s * alto, offsets[s] + W, (s + 1) * alto],
                            fill=(*paleta.acento, 90))
        yield img


def _diagonal(dur, paleta, fps):
    n = _n_frames(dur, fps)
    k = 1 / math.sqrt(2)
    u, v = (k, -k), (k, k)
    proj_full = (W + H) * k
    bar_len = math.hypot(W, H) * 1.3
    half = 7
    for i in range(n):
        t = i / max(n - 1, 1)
        img = _vacio()
        d = ImageDraw.Draw(img)
        travel = _ease_out_cubic(t) * (proj_full + 200) - 100
        for trail in range(6):
            td = travel - trail * 26
            alpha = max(0, 200 - trail * 38)
            if alpha <= 0 or not (-bar_len < td < proj_full + bar_len):
                continue
            cx, cy = td * v[0], td * v[1]
            L = bar_len / 2
            pts = [(cx + u[0] * L + v[0] * half, cy + u[1] * L + v[1] * half),
                   (cx + u[0] * L - v[0] * half, cy + u[1] * L - v[1] * half),
                   (cx - u[0] * L - v[0] * half, cy - u[1] * L - v[1] * half),
                   (cx - u[0] * L + v[0] * half, cy - u[1] * L + v[1] * half)]
            d.polygon(pts, fill=(*paleta.acento, alpha))
        _destello(d, t)
        yield img


def _puertas(dur, paleta, fps):
    n = _n_frames(dur, fps)
    entra, sale = 0.2, 0.3
    mitad = W / 2
    for i in range(n):
        t_abs = i / max(n - 1, 1) * dur
        if t_abs <= entra:
            gap = (1 - _ease_out_cubic(min(1.0, t_abs / entra))) * mitad
        else:
            gap = _ease_out_cubic(min(1.0, (t_abs - entra) / sale)) * mitad
        img = _vacio()
        d = ImageDraw.Draw(img)
        d.rectangle([-gap, 0, mitad - gap, H], fill=(*paleta.acento, 120))
        d.rectangle([mitad + gap, 0, W + gap, H], fill=(*paleta.acento, 120))
        if gap < 4:
            d.rectangle([W / 2 - 3, 0, W / 2 + 3, H], fill=(255, 255, 255, 255))
        yield img


def _persianas(dur, paleta, fps):
    n = _n_frames(dur, fps)
    alto_banda = H / 5
    retardo, crece = 0.03, 0.15
    for i in range(n):
        t = i / max(n - 1, 1)
        t_abs = t * dur
        img = _vacio()
        d = ImageDraw.Draw(img)
        fade = max(0.0, (1 - t) / (0.2 / dur)) if t > 1 - 0.2 / dur else 1.0
        alpha = int(100 * fade)
        if alpha > 0:
            for idx in range(5):
                g = max(0.0, min(1.0, (t_abs - idx * retardo) / crece))
                if g <= 0:
                    continue
                medio = _ease_out_cubic(g) * alto_banda / 2
                cy = idx * alto_banda + alto_banda / 2
                d.rectangle([0, cy - medio, W, cy + medio], fill=(*paleta.acento, alpha))
        yield img


_TRANSICIONES = {"A": _barrido_abajo, "B": _barrido_derecha, "C": _iris, "D": _glitch,
                 "E": _diagonal, "F": _puertas, "G": _persianas}


def frames_transicion(tipo: str, dur: float, paleta: Paleta, fps: int):
    if tipo not in _TRANSICIONES:
        raise ValueError(f"Transición desconocida: {tipo!r}")
    return _TRANSICIONES[tipo](dur, paleta, fps)


# ---------- contador lateral (nunca centrado) ----------

def _max_ancho_texto(cx: int, lado: str, pad: int) -> float:
    """Ancho máximo del texto para que la pill no salga del borde ni cruce x=540 en más de 80 px."""
    margen = 24
    fuera = cx - margen if lado == "L" else (W - margen) - cx
    dentro = (540 + 80) - cx if lado == "L" else cx - (540 - 80)
    return 2 * min(fuera, dentro) - 2 * pad


def frames_contador(num: int, texto: str, dur: float, lado: str, paleta: Paleta, fps: int):
    """Caja de acento (170 px) con número y pill de texto debajo; en cx 280/800, cy 360."""
    n = _n_frames(dur, fps)
    f_num = _fuente(paleta, 100)
    caja, pad = 170, 34
    cx = 280 if lado == "L" else 800
    cy = 360
    max_w = _max_ancho_texto(cx, lado, pad)
    tam = 38 if _tam_texto(_fuente(paleta, 46), texto)[0] > 460 else 46
    f_lab = _fuente(paleta, tam)
    tw_lab, th_lab = _tam_texto(f_lab, texto)
    while tw_lab > max_w and tam > 20:
        tam -= 2
        f_lab = _fuente(paleta, tam)
        tw_lab, th_lab = _tam_texto(f_lab, texto)
    fondo = paleta.fondo
    for i in range(n):
        t = i / max(n - 1, 1)
        img = _vacio()
        d = ImageDraw.Draw(img)
        fade = max(0.0, (1 - t) / (0.25 / dur)) if t > 1 - 0.25 / dur else 1.0
        st = min(1.0, t * dur / 0.3)
        s = 0.3 + 0.7 * _ease_out_cubic(st)
        half = int(caja * s / 2)
        a = int(255 * min(1.0, st * 1.5) * fade)
        d.rounded_rectangle([cx - half, cy - half, cx + half, cy + half],
                            radius=int(34 * s), fill=(*paleta.acento, a))
        if st > 0.4:
            na = int(255 * min(1.0, (st - 0.4) / 0.4) * fade)
            tw, th = _tam_texto(f_num, str(num))
            d.text((cx - tw / 2, cy - th / 2 - f_num.getbbox(str(num))[1]),
                   str(num), font=f_num, fill=(*paleta.texto, na))
        lt = min(1.0, max(0.0, (t * dur - 0.15) / 0.3))
        if lt > 0:
            la = int(255 * lt * fade)
            py = cy + caja // 2 + 60 + int((1 - _ease_out_cubic(lt)) * 30)
            pill = [cx - tw_lab / 2 - pad, py, cx + tw_lab / 2 + pad, py + th_lab + pad]
            d.rounded_rectangle(pill, radius=(th_lab + pad) // 2,
                                fill=(*fondo[:3], int(fondo[3] * lt * fade)),
                                outline=(*paleta.acento, la), width=4)
            d.text((cx - tw_lab / 2, py + pad / 2 - f_lab.getbbox(texto)[1]),
                   texto, font=f_lab, fill=(*paleta.texto, la))
        yield img


# ---------- etiqueta (pill centrada, N líneas apiladas) ----------

def _tokenizar(linea: str, check: bool):
    """Parte una línea en ('text', s) / ('arrow', None) / ('check', None): la fuente
    no tiene glifo para → ni ✓, así que se dibujan vectorialmente."""
    delims = [_ARROW] + ([_CHECK] if check else [])
    patron = "(" + "|".join(re.escape(x) for x in delims) + ")"
    tokens = []
    for parte in re.split(patron, linea):
        if parte == _ARROW:
            tokens.append(("arrow", None))
        elif check and parte == _CHECK:
            tokens.append(("check", None))
        else:
            tokens.append(("text", parte.strip()))
    return tokens


def _metricas_linea(tokens, f_txt, icon_w, gap):
    seg, ancho, alto = [], 0.0, 0
    for kind, val in tokens:
        if kind == "text":
            w, h = _tam_texto(f_txt, val) if val else (0, 0)
            seg.append((kind, val, w))
            ancho += w
            alto = max(alto, h)
        else:
            seg.append((kind, None, icon_w))
            ancho += icon_w + 2 * gap
    return seg, ancho, alto


def _dibuja_icono(d, kind, x, ay, icon_w, shaft_w, color, alpha):
    if kind == "arrow":
        d.line([(x, ay), (x + icon_w - 12, ay)], fill=(*color, alpha), width=shaft_w)
        d.polygon([(x + icon_w - 18, ay - 14), (x + icon_w - 18, ay + 14), (x + icon_w, ay)],
                  fill=(*color, alpha))
    elif kind == "check":
        p0 = (x, ay)
        p1 = (x + icon_w * 0.35, ay + icon_w * 0.35)
        p2 = (x + icon_w, ay - icon_w * 0.45)
        d.line([p0, p1], fill=(*color, alpha), width=shaft_w)
        d.line([p1, p2], fill=(*color, alpha), width=shaft_w)


def _geometria_etiqueta(lineas, grande, check, paleta):
    tam = 60 if grande else 52
    f_txt = _fuente(paleta, tam)
    icon_w, gap = int(tam * 0.9), int(tam * 0.3)
    metricas = [_metricas_linea(_tokenizar(l, check), f_txt, icon_w, gap) for l in lineas]
    ancho = max((cw for _, cw, _ in metricas), default=0)
    return tam, f_txt, icon_w, gap, metricas, ancho


_PAD_X, _PAD_Y = 40, 26


def cabe(lineas: list[str], grande: bool, paleta: Paleta, ancho_max: int = 1000) -> bool:
    """True si la pill (línea más ancha + relleno) cabe en ancho_max."""
    ancho = _geometria_etiqueta(lineas, grande, True, paleta)[5]
    return ancho + 2 * _PAD_X <= ancho_max


def frames_etiqueta(lineas: list[str], dur: float, paleta: Paleta, fps: int,
                    grande: bool = False, check: bool = False, cx: int = 540, y0: int = 330):
    """Pill oscura con borde de acento y texto; entra deslizando hacia arriba con fundido."""
    n = _n_frames(dur, fps)
    tam, f_txt, icon_w, gap, metricas, ancho = _geometria_etiqueta(lineas, grande, check, paleta)
    borde = 6 if grande else 4
    shaft_w = max(4, tam // 10)
    line_gap = int(tam * 0.35)
    alto_texto = sum(th for _, _, th in metricas) + line_gap * max(0, len(lineas) - 1)
    alto = alto_texto + _PAD_Y * 2
    fondo = paleta.fondo
    for i in range(n):
        t = i / max(n - 1, 1)
        img = _vacio()
        d = ImageDraw.Draw(img)
        fade = max(0.0, (1 - t) / (0.2 / dur)) if t > 1 - 0.2 / dur else 1.0
        a = _ease_out_cubic(min(1.0, max(0.0, t * dur / 0.25)))
        cy = y0 + int((1 - a) * 40)
        alpha = int(255 * a * fade)
        d.rounded_rectangle([cx - ancho / 2 - _PAD_X, cy, cx + ancho / 2 + _PAD_X, cy + alto],
                            radius=alto // 2, fill=(*fondo[:3], int(fondo[3] * a * fade)),
                            outline=(*paleta.acento, alpha), width=borde)
        y = cy + _PAD_Y
        for seg, lw, th in metricas:
            x = cx - lw / 2
            ay = y + th / 2
            for kind, val, w in seg:
                if kind == "text":
                    if val:
                        d.text((x, y - f_txt.getbbox(val)[1]), val, font=f_txt, fill=(*paleta.texto, alpha))
                    x += w
                else:
                    x += gap
                    _dibuja_icono(d, kind, x, ay, icon_w, shaft_w, paleta.texto, alpha)
                    x += w + gap
            y += th + line_gap
        yield img


# ---------- render ----------

def render_slot(frames: Iterable[Image.Image], destino: Path, fps: int) -> Path:
    """Escribe los frames como PNG y los codifica a ProRes 4444 con alfa."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for idx, frame in enumerate(frames):
            frame.save(f"{tmp}/f_{idx:04d}.png")
        subprocess.run([
            FFMPEG, "-y", "-framerate", str(fps), "-i", f"{tmp}/f_%04d.png",
            "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(destino),
        ], check=True, capture_output=True)
    return destino
