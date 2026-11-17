"""Emojis animados y viñeta roja para los cortos (fotogramas RGBA 1080x1920)."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FUENTE = "/System/Library/Fonts/Apple Color Emoji.ttc"  # fuente bitmap: solo renderiza a 160


def _ease_out_back(t, s=1.7):
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def _render(emoji: str) -> Image.Image:
    f = ImageFont.truetype(FUENTE, 160)
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((0, 0), emoji, font=f, embedded_color=True)
    return im


def disponible(emoji: str) -> bool:
    try:
        return _render(emoji).getbbox() is not None
    except Exception:
        return False


def _imagen(emoji: str, tam: int) -> Image.Image:
    im = _render(emoji)
    return im.crop(im.getbbox()).resize((tam, tam), Image.LANCZOS)


def frames_emoji(emoji: str, dur: float, cx: int, cy: int, tam: int, fps: int):
    base = _imagen(emoji, tam)
    for i in range(int(round(dur * fps))):
        ts = i / fps
        s = _ease_out_back(min(1.0, ts / 0.3))          # entrada con rebote
        fade = min(1.0, max(0.0, (dur - ts) / 0.2))      # desvanece los últimos 0.2 s
        ang = 6 * math.sin(ts * 7)                       # balanceo suave
        sz = max(1, int(tam * s))
        em = base.resize((sz, sz), Image.LANCZOS).rotate(ang, resample=Image.BICUBIC, expand=True)
        if fade < 1:
            em.putalpha(em.getchannel("A").point(lambda a: int(a * fade)))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(em, (int(cx - em.width / 2), int(cy - em.height / 2 + 8 * math.sin(ts * 5))))
        yield img


def frames_vineta(dur: float, fps: int, pico: float = 0.6):
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
    mascara = np.clip((r - 0.55) / 0.6, 0, 1) ** 1.4
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[..., 0] = 190
    for i in range(int(round(dur * fps))):
        ts = i / fps
        env = min(1.0, ts / 0.08) * max(0.0, 1 - max(0.0, ts - 0.08) / (dur - 0.08))
        a = (mascara * pico * env * 255).astype(np.uint8)
        yield Image.fromarray(np.dstack([rgb, a]), "RGBA")
