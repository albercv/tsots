"""Lectura de la pantalla: OCR de Apple (Vision) sobre el vídeo final.

Muestrea `video.mp4` a FPS_MUESTREO, tapa de negro los subtítulos y el título
quemados (si no, saldrían como «texto en pantalla») y guarda lo que lee en
`pantalla.json`:

    {"version": 1,
     "muestras": [{"t": 41.5,
                   "detecciones": [{"texto": "Revisión",
                                    "caja": [x, y, w, h],      # píxeles en 1080x1920, origen arriba-izquierda
                                    "confianza": 0.98,
                                    "inclinacion": 0.06}]}]}  # px que baja la línea base por px

Las consultas (`hay_texto`, `modo_broll`, `buscar`, `coincidencias`) trabajan sobre
la lista de `Muestra`. Si el OCR no está disponible, nada de aquí debe romper `preparar`.
"""
import io
import json
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageDraw

from videopipeline.edicion import componer
from videopipeline.edicion.texto import normalizar
from videopipeline.subtitles import Palabra

ANCHO, ALTO = 1080, 1920
FPS_MUESTREO = 2
# Fracción del fotograma que debe cubrir el texto detectado para contar como «hay texto»
# (1 %: ~20 000 px², una línea de unos 60 px de alto). Se mide sobre el fotograma entero:
# las bandas tapadas no tienen detecciones, así que no suman.
UMBRAL_AREA = 0.01
MIN_LETRAS = 4  # palabras más cortas darían coincidencias por azar
CERCA_DICHO = 0.45  # s entre la palabra y la muestra que la respalda (< el margen de 0.5 de `buscar`)


@dataclass(frozen=True)
class Deteccion:
    texto: str
    caja: tuple[int, int, int, int]  # x, y, w, h
    confianza: float
    inclinacion: float = 0.0  # px que baja la línea base por px de ancho (móvil torcido ante el monitor)


@dataclass(frozen=True)
class Muestra:
    t: float
    detecciones: tuple[Deteccion, ...]


@dataclass(frozen=True)
class Coincidencia:
    t0: float
    t1: float
    visible: str
    palabra: str
    t_palabra: float


def ocr_disponible() -> bool:
    try:
        import Vision  # noqa: F401
        return True
    except Exception:
        return False


def leer_fotograma(imagen: Image.Image) -> list[Deteccion]:
    """Una Deteccion por línea reconocida (mejor candidato), cajas en píxeles arriba-izquierda."""
    import objc
    import Vision
    from Foundation import NSData

    buf = io.BytesIO()
    imagen.convert("RGB").save(buf, "PNG")
    ancho, alto = imagen.size
    salida = []
    with objc.autorelease_pool():  # sin él, cada fotograma deja ~1 MB de objetos de Vision vivos
        datos = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
        peticion = Vision.VNRecognizeTextRequest.alloc().init()
        peticion.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        peticion.setRecognitionLanguages_(["es-ES", "en-US"])
        peticion.setUsesLanguageCorrection_(True)
        manejador = Vision.VNImageRequestHandler.alloc().initWithData_options_(datos, None)
        ok, _ = manejador.performRequests_error_([peticion], None)
        for obs in (peticion.results() or []) if ok else []:
            cand = obs.topCandidates_(1)
            if not cand:
                continue
            caja = obs.boundingBox()  # normalizada, origen abajo-izquierda
            x, w = caja.origin.x * ancho, caja.size.width * ancho
            h = caja.size.height * alto
            y = (1 - caja.origin.y - caja.size.height) * alto
            bi, bd = obs.bottomLeft(), obs.bottomRight()  # la caja va recta; estas esquinas, no
            dx = (bd.x - bi.x) * ancho
            incl = (bi.y - bd.y) * alto / dx if dx > 0 else 0.0
            salida.append(Deteccion(str(cand[0].string()), (round(x), round(y), round(w), round(h)),
                                    float(cand[0].confidence()), round(incl, 4)))
    return salida


def enmascarar(imagen: Image.Image, zonas: dict, t: float) -> Image.Image:
    """Copia con los subtítulos y el título (mientras dura) tapados de negro."""
    img = imagen.copy()
    dib = ImageDraw.Draw(img)
    if zonas.get("subtitulos"):
        y0, y1 = zonas["subtitulos"]
        dib.rectangle([0, y0, img.width, y1], fill="black")
    tit = zonas.get("titulo")
    if tit and t < tit["hasta"]:
        y0, y1 = tit["y"]
        dib.rectangle([0, y0, img.width, y1], fill="black")
    return img


def _fotogramas(video: Path):
    """Genera (t, imagen 1080x1920) a FPS_MUESTREO con ffmpeg.

    RuntimeError si ffmpeg falla o no da ningún fotograma: así no parece un vídeo sin texto."""
    cmd = [componer.FFMPEG, "-v", "error", "-i", str(video),
           "-vf", f"fps={FPS_MUESTREO},scale={ANCHO}:{ALTO}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    tam = ANCHO * ALTO * 3
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as p:
        i = 0
        while len(datos := p.stdout.read(tam)) == tam:
            yield i / FPS_MUESTREO, Image.frombytes("RGB", (ANCHO, ALTO), datos)
            i += 1
        if p.wait() != 0 or i == 0:
            raise RuntimeError(f"ffmpeg no pudo leer {Path(video).name} (código {p.returncode}, {i} fotogramas)")


def analizar(video: Path, zonas: dict, destino: Path) -> list[Muestra]:
    muestras = [Muestra(t, tuple(leer_fotograma(enmascarar(img, zonas, t))))
                for t, img in _fotogramas(video)]
    datos = {"version": 1, "muestras": [
        {"t": m.t, "detecciones": [{"texto": d.texto, "caja": list(d.caja), "confianza": d.confianza,
                                    "inclinacion": d.inclinacion} for d in m.detecciones]} for m in muestras]}
    destino = Path(destino)
    tmp = destino.with_name(destino.name + ".tmp")  # atómico: nunca queda un json a medias
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(destino)
    return muestras


def cargar(ruta: Path) -> list[Muestra]:
    try:
        datos = json.loads(Path(ruta).read_text("utf-8"))
        return [Muestra(float(m["t"]), tuple(Deteccion(d["texto"], tuple(int(v) for v in d["caja"]),
                                                       float(d["confianza"]), float(d.get("inclinacion", 0.0)))
                                             for d in m["detecciones"]))
                for m in datos["muestras"]]
    except Exception:
        return []


def _area(m: Muestra) -> int:
    return sum(d.caja[2] * d.caja[3] for d in m.detecciones)


def hay_texto(muestras: list[Muestra], t0: float, t1: float) -> bool:
    return any(t0 <= m.t <= t1 and _area(m) >= UMBRAL_AREA * ANCHO * ALTO for m in muestras)


def modo_broll(muestras: list[Muestra], t: float, dur: float = 2.5) -> str:
    return "ventana" if hay_texto(muestras, t, t + dur) else "tapa"


def franja_texto(muestras: list[Muestra], t: float, dur: float) -> tuple[int, int] | None:
    """(y0, y1) que ocupa todo el texto detectado entre t y t+dur, o None si no hay."""
    ys = [(d.caja[1], d.caja[1] + d.caja[3]) for s in muestras if t <= s.t <= t + dur for d in s.detecciones]
    return (min(a for a, _ in ys), max(b for _, b in ys)) if ys else None


def recortar(d: Deteccion, texto: str) -> Deteccion:
    """La detección con la caja reducida al fragmento `texto` de su línea.

    Vision da una caja por línea: la del fragmento se estima por su posición en el texto
    normalizado y, si la línea está inclinada, por la altura de la línea base en ese tramo."""
    linea, frag = normalizar(d.texto), normalizar(texto)
    i = linea.find(frag)
    if i < 0 or not frag or len(frag) == len(linea):
        return d
    x, y, w, h = d.caja
    k = d.inclinacion
    x1, x2 = x + w * i / len(linea), x + w * (i + len(frag)) / len(linea)
    letra = max(h - abs(k) * w, 0.3 * h)  # alto de la letra, sin lo que baja la línea
    y1 = y + max(0.0, k) * (x1 - x) + max(0.0, -k) * (x + w - x2)
    return replace(d, caja=(round(x1), round(y1), round(x2 - x1), round(letra + abs(k) * (x2 - x1))))


def buscar(muestras: list[Muestra], texto: str, t: float, margen: float = 0.5) -> Deteccion | None:
    """La detección más fiable que contiene `texto` (normalizado) en t ± margen, con la caja
    recortada a ese fragmento."""
    n = normalizar(texto)
    if not n:
        return None
    cands = [d for m in muestras if abs(m.t - t) <= margen for d in m.detecciones if n in normalizar(d.texto)]
    mejor = max(cands, key=lambda d: d.confianza, default=None)
    return recortar(mejor, texto) if mejor else None


def coincidencias(muestras: list[Muestra], palabras: list[Palabra]) -> list[Coincidencia]:
    """Palabras dichas mientras ese texto se ve, con la línea que se ve al decirlas.

    Solo las que `buscar` acepta en el instante de la palabra: la muestra del tramo más
    cercana está a CERCA_DICHO s como mucho, y no se lista una dicha tras la última muestra
    con el texto (el render ya no lo encontraría). Sin repetir seguidas (misma línea y palabra)."""
    huecos = 1.5 / FPS_MUESTREO  # más separación entre muestras = tramo distinto
    # palabras normalizadas de cada línea, una sola vez
    lineas = {id(m): [(d.texto, {normalizar(w) for w in re.split(r"\W+", d.texto)})
                      for d in m.detecciones] for m in muestras}
    res = []
    for p in palabras:
        n = normalizar(p.texto)
        if len(n) < MIN_LETRAS:
            continue
        tramo: list[tuple[float, str]] = []
        for m in muestras + [None]:
            vis = next((t for t, ws in lineas[id(m)] if n in ws), None) if m else None
            if vis and (not tramo or m.t - tramo[-1][0] <= huecos):
                tramo.append((m.t, vis))
                continue
            if tramo:
                t_vis, linea = min(tramo, key=lambda x: abs(x[0] - p.inicio))
                if abs(t_vis - p.inicio) <= CERCA_DICHO and p.inicio <= tramo[-1][0]:
                    res.append(Coincidencia(tramo[0][0], tramo[-1][0], linea, n, p.inicio))
            tramo = [(m.t, vis)] if vis else []
    res.sort(key=lambda c: c.t_palabra)
    return [c for a, c in zip([None] + res, res) if not a or (a.visible, a.palabra) != (c.visible, c.palabra)]
