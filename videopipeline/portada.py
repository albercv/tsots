"""Portada «estilo 3» de E2D: foto con la cara a la derecha, degradado de
fondo desde la izquierda y título en mayúsculas con una palabra en turquesa."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

TAM_BLOG = (1672, 941)
TAM_LINKEDIN = (1080, 1350)
TURQUESA, FONDO = "#05b4ba", "#050a0f"

_DIR = Path(__file__).resolve().parent
_FUENTE = _DIR / "fuentes" / "Inter-Black.ttf"
_LOGO = _DIR / "recursos" / "e2d_logo.png"
_RGB_FONDO = (5, 10, 15)


def palabra_destacada(titulo: str) -> int:
    """Índice de la palabra más larga; a igualdad, la primera."""
    palabras = titulo.split()
    return max(range(len(palabras)), key=lambda i: (len(palabras[i]), -i))


def _colocar_foto(fotograma, tam, cara, vertical):
    """Escala y coloca el fotograma en un lienzo de `FONDO`; devuelve (lienzo, x0, ancho)."""
    W, H = tam
    fw, fh = fotograma.size
    esc = max(W / fw, H / fh)
    if cara:
        esc = min(esc, (0.60 if vertical else 0.45) * H / (cara[3] - cara[1]))
    foto = fotograma.convert("RGB").resize((round(fw * esc), round(fh * esc)), Image.LANCZOS)
    fw, fh = foto.size
    cx, cy = ((cara[0] + cara[2]) / 2 * esc, (cara[1] + cara[3]) / 2 * esc) if cara else (fw / 2, fh / 2)
    # Sin cara: recorte centrado.
    cx_dest, cy_dest = ((0.50 if vertical else 0.70) * W, (0.40 if vertical else 0.48) * H) if cara else (W / 2, H / 2)
    x0 = min(max(round(cx_dest - cx), W - fw), 0) if fw >= W else W - fw
    y0 = min(max(round(cy_dest - cy), H - fh), 0) if fh >= H else (H - fh) // 2
    lienzo = Image.new("RGB", tam, _RGB_FONDO)
    lienzo.paste(foto, (x0, y0))
    return lienzo, x0, fw


def _degradar(lienzo, x0, fw, vertical):
    """Mezcla `FONDO` con opacidad 0,92 en x=0 → 0 en el 65 % del ancho (y desde abajo en 4:5)."""
    W, H = lienzo.size
    a = np.broadcast_to(np.clip(1 - np.arange(W) / (0.65 * W), 0, 1) * 0.92, (H, W))
    if vertical:
        a = np.maximum(a, np.clip((np.arange(H) - 0.45 * H) / (0.55 * H), 0, 1)[:, None] * 0.92)
    if fw < W:  # el borde izquierdo de la foto se funde con el fondo
        a = np.maximum(a, (1 - np.clip((np.arange(W) - x0) / (0.12 * W), 0, 1))[None, :])
    arr = np.asarray(lienzo).astype(np.float32)
    arr = arr * (1 - a[..., None]) + np.array(_RGB_FONDO, np.float32) * a[..., None]
    return Image.fromarray(arr.astype(np.uint8))


def _ajustar(d, palabras, ancho, tam, max_lineas):
    """(fuente, tamaño, líneas) con la letra más grande, desde `tam`, con la
    que `palabras` caben en `max_lineas` de `ancho`."""
    while True:
        f = ImageFont.truetype(str(_FUENTE), tam)
        lineas, act = [], []
        for i in range(len(palabras)):
            if act and d.textlength(" ".join(palabras[j] for j in act + [i]), font=f) > ancho:
                lineas.append(act)
                act = [i]
            else:
                act.append(i)
        lineas.append(act)
        if len(lineas) <= max_lineas and all(d.textlength(p, font=f) <= ancho for p in palabras):
            return f, tam, lineas
        tam -= 2


def _escribir(d, texto, lineas, f, tam, x_ini, y):
    palabras, dest = texto.upper().split(), palabra_destacada(texto)
    for k, linea in enumerate(lineas):
        x = x_ini
        for i in linea:
            d.text((x, y + k * tam * 0.95), palabras[i], font=f, fill=TURQUESA if i == dest else "#ffffff")
            x += d.textlength(palabras[i] + " ", font=f)


def _titulo(lienzo, titulo, vertical):
    W, H = lienzo.size
    d = ImageDraw.Draw(lienzo)
    x_ini, x_fin = (0.07 * W, 0.93 * W) if vertical else (0.08 * W, 0.58 * W)
    f, tam, lineas = _ajustar(d, titulo.upper().split(), x_fin - x_ini, int(0.13 * H), 3)
    alto = len(lineas) * tam * 0.95
    y = H * 0.94 - alto if vertical else (H - alto) / 2
    _escribir(d, titulo, lineas, f, tam, x_ini, y)


def _poner_logo(lienzo):
    """Arriba a la derecha: el texto ocupa la parte baja o el centro."""
    W = lienzo.width
    logo = Image.open(_LOGO).convert("RGBA")
    s = int(0.09 * W)
    logo = logo.resize((s, round(logo.height * s / logo.width)), Image.LANCZOS)
    lienzo.paste(logo, (int(W - 0.04 * W - s), int(0.04 * W)), logo)


def componer_portada(fotograma: Image.Image, titulo: str, tamano: tuple[int, int], *,
                     cara: tuple[int, int, int, int] | None = None,
                     con_logo: bool = False) -> Image.Image:
    """Compone la portada de `tamano` a partir de un fotograma.

    `cara` es (x1, y1, x2, y2) en píxeles del `fotograma`. El logo (solo
    LinkedIn) va arriba a la derecha porque el título ocupa la parte baja.
    """
    vertical = tamano[1] > tamano[0]
    lienzo, x0, fw = _colocar_foto(fotograma, tamano, cara, vertical)
    lienzo = _degradar(lienzo, x0, fw, vertical)
    _titulo(lienzo, titulo, vertical)
    if con_logo:
        _poner_logo(lienzo)
    return lienzo


def componer_tarjeta(idea: str, tamano: tuple[int, int], *,
                     fondo: Image.Image | None = None) -> Image.Image:
    """Tarjeta de LinkedIn con una idea clave y sin la cara de quien habla.

    `fondo` es una captura del vídeo sin la cara (pantalla, demo): va
    desenfocada y oscurecida para que el texto se lea. Sin ella, el fondo de
    la marca con un brillo turquesa abajo a la derecha.
    """
    W, H = tamano
    if fondo is None:
        yy, xx = np.mgrid[0:H, 0:W]
        a = np.clip(1 - np.hypot(xx - W, yy - H) / (1.1 * H), 0, 1)[..., None] * 0.22
        arr = (np.array(_RGB_FONDO, np.float32) * (1 - a)
               + np.array(ImageColor.getrgb(TURQUESA), np.float32) * a)
    else:
        esc = max(W / fondo.width, H / fondo.height)
        foto = fondo.convert("RGB").resize(
            (round(fondo.width * esc), round(fondo.height * esc)), Image.LANCZOS)
        x, y = (foto.width - W) // 2, (foto.height - H) // 2
        foto = foto.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(0.013 * W))
        arr = np.asarray(foto, np.float32) * 0.22 + np.array(_RGB_FONDO, np.float32) * 0.78
    lienzo = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(lienzo)
    x_ini = 0.09 * W
    f, tam, lineas = _ajustar(d, idea.upper().split(), 0.82 * W, int(0.11 * H), 5)
    y = (H - len(lineas) * tam * 0.95) / 2 + 0.03 * H  # centrado con la barra de encima
    d.rectangle([x_ini, y - 0.06 * H, x_ini + 0.12 * W, y - 0.051 * H], fill=TURQUESA)
    _escribir(d, idea, lineas, f, tam, x_ini, y)
    _poner_logo(lienzo)
    return lienzo
