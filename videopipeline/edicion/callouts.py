"""Señalar y lupa: llamadas de atención ancladas a texto que se ve en pantalla.

`seguir` localiza el texto fotograma a fotograma (OCR cada 2 fotogramas, interpolación
y media móvil); `frames_senalar` dibuja un círculo, flecha o subrayado sobre él y
`frames_lupa` una tarjeta con el recorte ampliado unida a él por un trazo. Ambas son
generadores perezosos de fotogramas RGBA 1080×1920 que nunca pintan sobre la banda de
subtítulos ni sobre el título mientras se ve.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from videopipeline.edicion import pantalla
from videopipeline.edicion.broll import _decodificar
from videopipeline.edicion.rotulos import _ease_out_cubic
from videopipeline.edicion.texto import normalizar

W, H = 1080, 1920
SALTO_MAX = 0.25 * W      # px entre lecturas: más es «otro texto»
HUECO_MAX = 0.3           # s sin lectura antes de darlo por perdido
GROSOR = 8
FUNDIDO = 0.2             # s
ENTRADA = 0.3             # s que tarda en trazarse la forma
MARGEN_LUPA, ZOOM, ANCHO_LUPA_MAX = 0.3, 2, 900
BORDE, RADIO = 6, 28
Caja = tuple[int, int, int, int]


def _centro(c: Caja) -> tuple[float, float]:
    return c[0] + c[2] / 2, c[1] + c[3] / 2


def seguir(video: Path, texto: str, t: float, dur: float, fps: int, inicial, zonas: dict) -> list[Caja | None]:
    """Una caja por fotograma del tramo; `None` desde que el texto salta o deja de verse."""
    n = round(dur * fps)
    obj = normalizar(texto)
    lecturas = {0: inicial.caja}  # índice de fotograma -> caja leída
    perdido = n
    for i, img in enumerate(_decodificar(video, W, H, dur, fps, t)):
        if i >= n or i == 0 or i % 2:
            continue
        previa_i = max(lecturas)
        previa = lecturas[previa_i]
        cands = [d.caja for d in pantalla.leer_fotograma(pantalla.enmascarar(img, zonas, t + i / fps))
                 if obj and obj in normalizar(d.texto)]
        if cands:
            caja = min(cands, key=lambda c: abs(_centro(c)[0] - _centro(previa)[0]) + abs(_centro(c)[1] - _centro(previa)[1]))
            if abs(_centro(caja)[0] - _centro(previa)[0]) <= SALTO_MAX and abs(_centro(caja)[1] - _centro(previa)[1]) <= SALTO_MAX:
                lecturas[i] = caja
                continue
            perdido = previa_i + 1  # salta a otra parte: no es el mismo texto
            break
        if (i - previa_i) / fps > HUECO_MAX:
            perdido = previa_i + 1
            break
    claves = sorted(lecturas)
    interp = []
    for i in range(min(n, perdido)):
        a = max(k for k in claves if k <= i)
        b = min((k for k in claves if k >= i), default=a)
        f = 0 if a == b else (i - a) / (b - a)
        interp.append(tuple(lecturas[a][j] + f * (lecturas[b][j] - lecturas[a][j]) for j in range(4)))
    suave = []
    for i in range(len(interp)):  # media móvil de ~5 fotogramas, centrada
        ventana = interp[max(0, i - 2):i + 3]
        suave.append(tuple(round(sum(c[j] for c in ventana) / len(ventana)) for j in range(4)))
    return suave + [None] * (n - len(suave))


def _alfa(i: int, cajas: list, fps: int) -> float:
    """Opacidad: plena hasta el primer None; baja a 0 en 0.2 s (y también al acabar el tramo)."""
    m = max(1, round(FUNDIDO * fps))
    k = next((j for j, c in enumerate(cajas) if c is None), len(cajas))
    return max(0.0, min(1.0, 1 - (i - k) / m, (len(cajas) - 1 - i) / m))


def _terminar(img: Image.Image, zonas: dict | None, ts: float, alfa: float) -> Image.Image:
    """Aplica el fundido y borra las bandas prohibidas (subtítulos; título mientras dura)."""
    zonas = zonas or {}
    img.putalpha(img.getchannel("A").point(lambda v: int(v * alfa)))
    borrar = []
    if zonas.get("subtitulos"):
        borrar.append(zonas["subtitulos"])
    if zonas.get("titulo") and ts < zonas["titulo"]["hasta"]:
        borrar.append(zonas["titulo"]["y"])
    for y0, y1 in borrar:
        img.paste((0, 0, 0, 0), (0, y0, W, y1))
    return img


def _ultima(cajas: list, i: int) -> Caja | None:
    return next((c for c in reversed(cajas[:i + 1]) if c is not None), None)


def frames_senalar(cajas, forma: str, paleta, fps: int, zonas: dict | None = None, t: float = 0.0):
    """Fotogramas RGBA con círculo, flecha o subrayado sobre la caja."""
    color = (*paleta.acento, 255)
    for i in range(len(cajas)):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        caja = _ultima(cajas, i)
        if caja:
            x, y, w, h = caja
            p = _ease_out_cubic(min(1.0, i / fps / ENTRADA))
            dib = ImageDraw.Draw(img)
            if forma == "circulo":
                m = 18
                dib.arc([x - m, y - m, x + w + m, y + h + m], -90, -90 + 360 * p, fill=color, width=GROSOR)
            elif forma == "subrayado":
                dib.line([x, y + h + 12, x + w * p, y + h + 12], fill=color, width=GROSOR)
            else:  # flecha: llega en diagonal desde arriba-izquierda hasta el borde superior de la caja
                px, py = x + w * 0.35, y - 10
                tx, ty = px - 140 * (2 - p), py - 190 * (2 - p) * 0.9
                dib.line([tx, ty, px - 14, py - 20], fill=color, width=GROSOR)
                dib.polygon([(px, py), (px - 34, py - 12), (px - 12, py - 36)], fill=color)
        yield _terminar(img, zonas, t + i / fps, _alfa(i, cajas, fps))


def _tarjeta(recorte: Image.Image, color) -> Image.Image:
    """Recorte con borde de acento, esquinas redondeadas y sombra suave (RGBA, con holgura)."""
    w, h = recorte.size[0] + 2 * BORDE, recorte.size[1] + 2 * BORDE
    pad = 40
    tarjeta = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(tarjeta).rounded_rectangle([0, 0, w - 1, h - 1], RADIO, fill=color)
    mascara = Image.new("L", recorte.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, recorte.width - 1, recorte.height - 1], RADIO - BORDE, fill=255)
    tarjeta.paste(recorte.convert("RGBA"), (BORDE, BORDE), mascara)
    sombra = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    sombra.paste(tarjeta.getchannel("A").point(lambda v: v * 110 // 255), (pad, pad + 12))
    base = Image.new("RGBA", sombra.size, (0, 0, 0, 0))
    base.putalpha(sombra.filter(ImageFilter.GaussianBlur(14)))
    base.alpha_composite(tarjeta, (pad, pad))
    return base


def frames_lupa(video: Path, cajas, t: float, dur: float, zonas: dict, paleta, fps: int):
    """Fotogramas RGBA con una tarjeta del texto ampliado, unida a su caja por un trazo."""
    color = (*paleta.acento, 255)
    tit = zonas.get("titulo")
    # arriba: bajo el título si se ve en algún momento del tramo (fijo, para que la tarjeta no salte)
    y_min = tit["y"][1] if tit and t < tit["hasta"] else 120
    y_max = zonas["graficos_hasta"]
    frames = _decodificar(video, W, H, dur, fps, t)
    rgb = None
    for i in range(len(cajas)):
        rgb = next(frames, rgb)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        caja = _ultima(cajas, i)
        if caja and rgb:
            x, y, w, h = caja
            mx, my = w * MARGEN_LUPA, h * MARGEN_LUPA
            izq, arr = max(0, round(x - mx)), max(0, round(y - my))
            der, aba = min(W, round(x + w + mx)), min(H, round(y + h + my))
            k = min(ZOOM, ANCHO_LUPA_MAX / max(1, der - izq))
            hueco_ini, hueco_fin = (max(y_min, H // 2), y_max) if y + h / 2 < H // 2 else (y_min, min(y_max, H // 2))
            if hueco_fin - hueco_ini < 150:  # mitad opuesta sin sitio: todo el rango permitido
                hueco_ini, hueco_fin = y_min, y_max
            k = min(k, (hueco_fin - hueco_ini - 2 * BORDE - 40) / max(1, aba - arr))
            recorte = rgb.crop((izq, arr, der, aba)).resize(
                (max(1, round((der - izq) * k)), max(1, round((aba - arr) * k))), Image.LANCZOS)
            tarjeta = _tarjeta(recorte, color)
            tw, th = tarjeta.size
            cx, cy = (W - tw) // 2, (hueco_ini + hueco_fin - th) // 2
            # trazo: del borde de la tarjeta que mira a la caja hasta el borde de la caja
            bx, by = _centro(caja)
            arriba = cy + th / 2 < by
            ex = min(max(bx, cx + 60), cx + tw - 60)
            ey = cy + th - 40 - BORDE if arriba else cy + 40 + BORDE
            dib = ImageDraw.Draw(img)
            dib.line([ex, ey, bx, y if not arriba else y + h], fill=color, width=GROSOR)
            img.alpha_composite(tarjeta, (cx, cy))
        yield _terminar(img, zonas, t + i / fps, _alfa(i, cajas, fps))
