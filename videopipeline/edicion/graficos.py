"""Iconos vectoriales animados y tarjetas de dato (fotogramas RGBA 1080x1920)."""
import difflib
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from videopipeline.edicion.emojis import _ease_out_back
from videopipeline.edicion.estilos import Paleta
from videopipeline.edicion.rotulos import _ease_out_cubic, _fuente, _tam_texto
from videopipeline.steps import BASE_DIR

W, H = 1080, 1920
_RECURSOS = BASE_DIR / "lanzador" / "edicion" / "recursos"

# nombre en español -> nombre en Material Icons
ICONOS: dict[str, str] = {
    "documento": "description", "carpeta": "folder", "busqueda": "search", "candado": "lock",
    "seguridad": "security", "euro": "euro", "grafica": "bar_chart", "reloj": "schedule",
    "calendario": "calendar_month", "usuario": "person", "equipo": "groups", "idea": "lightbulb",
    "check": "check_circle", "alerta": "warning", "mensaje": "chat", "correo": "mail",
    "nube": "cloud", "ia": "smart_toy", "codigo": "code", "casa": "home", "edificio": "apartment",
    "contrato": "gavel", "firma": "draw", "dinero": "payments", "tiempo": "hourglass_empty",
    "objetivo": "flag", "cohete": "rocket_launch", "ajustes": "settings", "crecimiento": "trending_up",
    "escudo": "shield", "estrella": "star", "corazon": "favorite", "telefono": "call",
    "mundo": "language", "movil": "phone_iphone", "ojo": "visibility", "herramienta": "build",
    "educacion": "school", "tienda": "store", "carrito": "shopping_cart",
}


@lru_cache(maxsize=1)
def _codepoints() -> dict[str, str]:
    lineas = (_RECURSOS / "MaterialIcons-Regular.codepoints").read_text().splitlines()
    return dict(l.split() for l in lineas if l.strip())


def _glifo(nombre: str) -> str:
    return chr(int(_codepoints()[ICONOS[nombre]], 16))


def _fuente_iconos(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_RECURSOS / "MaterialIcons-Regular.ttf"), size)


def icono_disponible(nombre: str) -> bool:
    return nombre in ICONOS


def parecidos(nombre: str, n: int = 5) -> list[str]:
    return difflib.get_close_matches(nombre, list(ICONOS), n=n, cutoff=0.5)


def _fade(ts: float, dur: float) -> float:
    return min(1.0, max(0.0, (dur - ts) / 0.2))  # desvanece los últimos 0.2 s


def frames_icono(nombre: str, dur: float, cx: int, cy: int, tam: int, paleta: Paleta, fps: int):
    """Insignia redonda de acento con el glifo; entrada con rebote como frames_emoji."""
    glifo, fnt = _glifo(nombre), _fuente_iconos(int(tam * 0.6))
    for i in range(int(round(dur * fps))):
        ts = i / fps
        s = _ease_out_back(min(1.0, ts / 0.3))
        a = int(255 * _fade(ts, dur) * min(1.0, 4 * s))  # nace transparente
        r = max(1, int(tam * s / 2))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*paleta.acento, a))
        f = _fuente_iconos(max(1, int(tam * 0.6 * s)))
        d.text((cx, cy), glifo, font=f, fill=(*paleta.texto, a), anchor="mm")
        yield img


def _formato(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}".replace(".", ",")


def frames_dato(valor: float, texto: str, unidad: str | None, dur: float, paleta: Paleta, fps: int):
    """Número grande que cuenta de 0 a valor, píldora con el texto y, con '%', barra de progreso."""
    cx, cy, pad = 540, 330, 34
    f_num, f_lab = _fuente(paleta, 190), _fuente(paleta, 46)
    texto = texto.upper()
    tw_lab, th_lab = _tam_texto(f_lab, texto)
    for i in range(int(round(dur * fps))):
        ts = i / fps
        k = _ease_out_cubic(min(1.0, ts / 0.8))
        fade = _fade(ts, dur)
        a = int(255 * fade)
        v = valor * k
        s = _formato(round(v, 1) if not float(valor).is_integer() else round(v)) + (unidad or "")
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((cx, cy - 60), s, font=f_num, fill=(*paleta.texto, a), anchor="mm",
               stroke_width=8, stroke_fill=(*paleta.fondo[:3], a))
        py = cy + 60
        d.rounded_rectangle([cx - tw_lab / 2 - pad, py, cx + tw_lab / 2 + pad, py + th_lab + pad],
                            radius=(th_lab + pad) // 2, fill=(*paleta.fondo[:3], int(paleta.fondo[3] * fade)),
                            outline=(*paleta.acento, a), width=4)
        d.text((cx - tw_lab / 2, py + pad / 2 - f_lab.getbbox(texto)[1]), texto, font=f_lab,
               fill=(*paleta.texto, a))
        if unidad == "%":
            by, bw = py + th_lab + pad + 40, 700
            d.rounded_rectangle([cx - bw / 2, by, cx + bw / 2, by + 36], radius=18,
                                fill=(*paleta.fondo[:3], int(paleta.fondo[3] * fade)))
            if v > 0:
                d.rounded_rectangle([cx - bw / 2, by, cx - bw / 2 + max(36, bw * min(v, 100) / 100), by + 36],
                                    radius=18, fill=(*paleta.acento, a))
        yield img
