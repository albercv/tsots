"""B-roll gratuito de Pixabay: clave en el Llavero, búsqueda con caché y dibujo.

Modos: «tapa» cubre todo lo que hay sobre los subtítulos; «ventana» es una
tarjeta redondeada en el hueco sin texto de la zona de gráficos. La clave nunca
se escribe en caché ni en logs.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from videopipeline.edicion.componer import FFMPEG

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx registra la URL completa, que lleva la clave: no subir su nivel

SERVICIO = "tsots-pixabay"
CUENTA = "api-key"
DURACION = 2.5  # s mínimos de un clip útil
SECURITY = "/usr/bin/security"
URL_BUSQUEDA = "https://pixabay.com/api/videos/"
W, H = 1080, 1920
VENTANA_ANCHO, VENTANA_ALTO = 860, 540  # tarjeta apaisada: deja ver la demo
VENTANA_MIN, MARGEN_VENTANA = 240, 24   # px: más baja no se distingue; separación del texto


@dataclass(frozen=True)
class Clip:
    archivo: Path
    autor: str
    url: str
    id: int


def _security(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([SECURITY, "find-generic-password", "-s", SERVICIO, "-a", CUENTA, *extra],
                          capture_output=True, text=True, timeout=30)


def leer_clave() -> str | None:
    try:
        r = _security("-w")
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Llavero no disponible (%s)", type(e).__name__)
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None  # 44 = no existe


def hay_clave() -> bool:
    try:
        return _security().returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def probar_clave(clave: str, cliente: httpx.Client | None = None) -> bool:
    try:
        c = cliente or httpx.Client()
        r = c.get(URL_BUSQUEDA, params={"key": clave, "q": "nature", "per_page": 3}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _slug(buscar: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", buscar.lower()).strip("-")[:60] or "q"


def _version(v: dict) -> dict | None:
    """La versión más grande con ambos lados ≤ 1920 (si ninguna, la más pequeña)."""
    vs = [x for x in (v.get("videos") or {}).values() if x.get("url") and (x.get("width") or 0) > 0
          and (x.get("height") or 0) > 0]
    ok = [x for x in vs if x["width"] <= 1920 and x["height"] <= 1920]
    if ok:
        return max(ok, key=lambda x: x["width"] * x["height"])
    return min(vs, key=lambda x: x["width"] * x["height"]) if vs else None


def _candidatos(hits: list) -> list[dict]:
    """Vídeos de ≥ DURACION s con su versión elegida; los verticales primero, luego el orden de la API."""
    sal = []
    for v in hits:
        ver = _version(v)
        if v.get("duration", 0) >= DURACION and ver:
            sal.append({"id": v["id"], "autor": v.get("user", ""), "url": v.get("pageURL", ""),
                        "link": ver["url"], "vertical": ver["height"] > ver["width"]})
    return sorted(sal, key=lambda x: not x["vertical"])  # sort estable


def obtener(buscar: str, usados: set[int], carpeta: Path, clave: str | None = None,
            cliente: httpx.Client | None = None) -> Clip | None:
    """Primer clip largo no usado para `buscar` (verticales antes); `None` ante cualquier fallo.

    La clave va en la URL de la petición: no se registran URLs ni mensajes de httpx."""
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        indice = carpeta / f"{_slug(buscar)}.json"
        c = cliente or httpx.Client()
        if indice.exists():
            cands = json.loads(indice.read_text())
        else:
            clave = clave or leer_clave()
            if not clave:
                log.warning("B-roll: sin clave de Pixabay")
                return None
            r = c.get(URL_BUSQUEDA, timeout=10,
                      params={"key": clave, "q": buscar, "per_page": 20, "safesearch": "true",
                              "video_type": "film"})
            if r.status_code != 200:
                log.warning("B-roll: Pixabay respondió %s", r.status_code)
                return None
            cands = _candidatos(r.json().get("hits", []))
            if cands:
                indice.write_text(json.dumps(cands))
        cand = next((x for x in cands if x["id"] not in usados), None)
        if cand is None:
            log.warning("B-roll: sin clips válidos para %r", buscar)
            return None
        archivo = carpeta / f"{cand['id']}.mp4"
        if not archivo.exists():
            d = c.get(cand["link"], timeout=30, follow_redirects=True)
            d.raise_for_status()
            tmp = archivo.with_suffix(".part")
            tmp.write_bytes(d.content)
            tmp.rename(archivo)
        return Clip(archivo, cand["autor"], cand["url"], cand["id"])
    except Exception as e:  # red, JSON, disco: el B-roll es opcional
        log.warning("B-roll: fallo %s", type(e).__name__)
        return None


def _decodificar(clip: Path, ancho: int, alto: int, dur: float, fps: int, inicio: float = 0.0):
    """Frames RGB del clip (desde `inicio` s) llenando `ancho`×`alto`; en bucle si es más corto que `dur`."""
    cmd = [FFMPEG, "-v", "error", "-stream_loop", "-1", "-ss", f"{inicio:.3f}", "-i", str(clip), "-t", f"{dur:.3f}",
           "-r", str(fps), "-vf",
           f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,crop={ancho}:{alto}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = ancho * alto * 3
    try:
        while len(buf := p.stdout.read(n)) == n:
            yield Image.frombytes("RGB", (ancho, alto), buf)
    finally:
        p.kill()
        p.wait()


def _fundido(ts: float, dur: float) -> float:
    return max(0.0, min(1.0, ts / 0.2, (dur - ts) / 0.2))


def hueco_ventana(zonas: dict, t: float, evitar: tuple[int, int] | None) -> tuple[int, int, int]:
    """(y0, y1, alto) del mayor hueco libre para la ventana y el alto que le cabe.

    Entre el título (si se ve en `t`) y `graficos_hasta`, sin la franja `evitar`.
    Sin hueco para VENTANA_MIN px, ValueError."""
    tit = zonas.get("titulo")
    arriba, abajo = (tit["y"][1] if tit and t < tit["hasta"] else 120), zonas["graficos_hasta"]
    huecos = [(arriba, abajo)] if not evitar else [(arriba, min(abajo, evitar[0])),
                                                   (max(arriba, evitar[1]), abajo)]
    h0, h1 = max(huecos, key=lambda h: h[1] - h[0])
    alto = min(VENTANA_ALTO, h1 - h0 - 2 * MARGEN_VENTANA)
    if alto < VENTANA_MIN:
        raise ValueError("no hay hueco libre de texto para la ventana del B-roll")
    return h0, h1, alto


def frames_broll(clip: Path, modo: str, dur: float, zonas: dict, paleta, fps: int,
                 evitar: tuple[int, int] | None = None, t: float = 0.0):
    """Fotogramas RGBA 1080×1920 del B-roll («tapa» o «ventana»), con fundido de 0.2 s.

    La ventana va en el hueco libre más grande entre el título (si se ve en `t`) y
    `graficos_hasta`, sin pisar la franja vertical `evitar` (el texto en pantalla).
    Sin hueco para VENTANA_MIN px, ValueError: la pieza se omite."""
    sub = zonas.get("subtitulos")
    if modo == "tapa":
        ancho, alto, x0, y0 = W, (sub[0] if sub else H), 0, 0
    else:
        h0, h1, alto = hueco_ventana(zonas, t, evitar)
        ancho = round(alto * VENTANA_ANCHO / VENTANA_ALTO)  # apaisada, también si se encoge
        x0, y0 = (W - ancho) // 2, (h0 + h1 - alto) // 2
        mascara = Image.new("L", (ancho, alto), 0)
        ImageDraw.Draw(mascara).rounded_rectangle([0, 0, ancho - 1, alto - 1], radius=36, fill=255)
        sombra = Image.new("L", (W, H), 0)
        sombra.paste(mascara.point(lambda v: v * 110 // 255), (x0, y0 + 12))
        sombra = sombra.filter(ImageFilter.GaussianBlur(18))
    for i, rgb in enumerate(_decodificar(clip, ancho, alto, dur, fps)):
        ts = i / fps
        if modo == "tapa":  # zoom lento 1.00 → 1.06
            z = 1 + 0.06 * ts / max(dur, 1e-6)
            cw, ch = round(ancho / z), round(alto / z)
            l, t = (ancho - cw) // 2, (alto - ch) // 2
            rgb = rgb.crop((l, t, l + cw, t + ch)).resize((ancho, alto), Image.BILINEAR)
            alfa = Image.new("L", (ancho, alto), 255)
            base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        else:
            alfa = mascara
            base = Image.merge("RGBA", (*Image.new("RGB", (W, H)).split(), sombra))
        f = _fundido(ts, dur)
        base.paste(Image.merge("RGBA", (*rgb.split(), alfa)), (x0, y0))
        base.putalpha(base.getchannel("A").point(lambda v: int(v * f)))
        yield base
