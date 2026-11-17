"""Deriva overlays, sonidos y zooms del plan validado y renderiza el short editado.

`derivar` es pura (sin ffmpeg ni PIL); `renderizar` ejecuta el resultado.
"""
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from videopipeline.edicion import componer, emojis, estilos, musica, rotulos, sonidos
from videopipeline.edicion.componer import Overlay, Zoom
from videopipeline.edicion.estilos import Estilo
from videopipeline.edicion.plan import DURACION, DURACION_FINAL, Momento, Plan, leer
from videopipeline.edicion.sonidos import EventoSfx

DUR_MIN = 0.2
FREQS_TAP = (650, 700, 750, 800, 850, 900)


@dataclass
class Pieza:
    clase: str  # etiqueta | contador | emoji | transicion | vineta
    t: float
    dur: float
    params: dict


@dataclass
class Specs:
    piezas: list[Pieza]
    sfx: list[EventoSfx]
    zooms: list[Zoom]
    musica: dict | None


def _lineas(texto) -> list[str]:
    return [texto] if isinstance(texto, str) else list(texto or [])


def derivar(plan: Plan, zonas: dict, estilo: Estilo, duracion: float) -> Specs:
    piezas: list[Pieza] = []
    sfx: list[EventoSfx] = []

    def pieza(clase, t, dur, **params) -> bool:
        dur = min(dur, duracion - t)  # el plan no valida el fin: se recorta
        if dur < DUR_MIN:
            return False
        piezas.append(Pieza(clase, t, dur, params))
        return True

    def sonido(tipo, t, **kw):
        if tipo in estilo.sfx:
            sfx.append(EventoSfx(max(0.0, t), tipo, estilo.sfx[tipo], **kw))

    sonido("boom", 0.05)
    visuales = sorted((m for m in plan.momentos if m.tipo != "zoom"), key=lambda m: m.t)
    ticks = lado = letra = 0
    for m in (m for m in visuales if m.tipo != "emoji"):
        t = m.t
        if m.tipo == "etiqueta":
            if pieza("etiqueta", t, DURACION["etiqueta"], lineas=_lineas(m.texto)):
                sonido("tick" if ticks % 2 == 0 else "tick2", t + 0.08)
                ticks += 1
        elif m.tipo == "titulo":
            if pieza("etiqueta", t, DURACION["titulo"], lineas=_lineas(m.texto), grande=True):
                sonido("riser", t - 1.07)
                sonido("impact", t)
        elif m.tipo == "contador":
            if pieza("contador", t, DURACION["contador"], num=m.num, texto=_lineas(m.texto)[0],
                     lado="LR"[lado % 2]):
                lado += 1
                sonido("pop" if m.lista == 1 else "pluck", t + 0.08, num=m.num)
        elif m.tipo == "transicion":
            nueva = estilo.transiciones[letra % len(estilo.transiciones)]  # letras distintas: no repite
            if pieza("transicion", t, DURACION["transicion"], tipo=nueva):
                letra += 1
                sonido("whoosh_" + nueva.lower(), t - 0.12)
        elif m.tipo == "golpe":
            if pieza("vineta", t, DURACION["golpe"]):
                sonido("golpe", t)
        elif m.tipo == "error":
            if pieza("emoji", t, DURACION["error"], emoji="❌", cx=540, cy=385, tam=200):
                sonido("error", t)
    if plan.final:
        t = max(0.0, duracion - DURACION_FINAL)
        if pieza("etiqueta", t, DURACION_FINAL, lineas=_lineas(plan.final["texto"]), grande=True,
                 check=bool(plan.final.get("check"))):
            sonido("ding", t)
    ocupado = [(p.t, p.t + p.dur) for p in piezas if p.clase in ("etiqueta", "contador")]
    taps = 0
    for m in (m for m in visuales if m.tipo == "emoji"):
        fin = min(m.t + DURACION["emoji"], duracion)
        lateral = any(a < fin and m.t < b for a, b in ocupado)
        if pieza("emoji", m.t, DURACION["emoji"], emoji=m.emoji, cy=330,
                 cx=950 if lateral else 540, tam=170 if lateral else 220):
            sonido("tap", m.t, freq=FREQS_TAP[taps % len(FREQS_TAP)])
            taps += 1
    sfx.sort(key=lambda e: e.t)
    return Specs(piezas, sfx, _zooms(plan, zonas, estilo, duracion), estilo.musica)


def _zooms(plan: Plan, zonas: dict, estilo: Estilo, duracion: float) -> list[Zoom]:
    if not zonas.get("franja_zoom"):
        return []
    zooms = []
    alto = estilo.zoom_max
    for m in sorted((m for m in plan.momentos if m.tipo == "zoom"), key=lambda m: m.t0):
        t1 = min(m.t1, duracion)
        if t1 - m.t0 > 0:
            zooms.append(Zoom(m.t0, t1, alto, alto))
            alto = 1 + (estilo.zoom_max - 1) / 2 if alto == estilo.zoom_max else estilo.zoom_max
    punch = list(zooms)
    zl = estilo.zoom_lento
    if zl > 0 and duracion > 2.5:
        tiempos = [m.t0 if m.tipo == "zoom" else m.t for m in plan.momentos]
        h = min([5.0, duracion] + [t for t in tiempos if t >= 2.5])
        # un zoom de golpe dentro de la entrada+mantenido: se omiten (zooms solapados son ambiguos)
        if not any(z.t0 < max(2.5, h) for z in punch):
            zooms.append(Zoom(0, 2.5, 1, zl))
            if h > 2.5:
                zooms.append(Zoom(2.5, h, zl, zl))
        ini = duracion - 3
        if ini >= max(2.5, h) and not any(z.t1 > ini for z in punch):
            zooms.append(Zoom(ini, duracion, 1, zl))
    return zooms


def _fps_overlay(fuente: Path) -> int:
    n, _, d = componer._fps(fuente).partition("/")
    return min(30, round(float(n) / float(d or 1)))


def _render_pieza(p: Pieza, estilo: Estilo, fps: int, destino: Path) -> Path:
    q = p.params
    if p.clase == "etiqueta":
        fr = rotulos.frames_etiqueta(q["lineas"], p.dur, estilo.paleta, fps,
                                     grande=q.get("grande", False), check=q.get("check", False))
    elif p.clase == "contador":
        fr = rotulos.frames_contador(q["num"], q["texto"], p.dur, q["lado"], estilo.paleta, fps)
    elif p.clase == "transicion":
        fr = rotulos.frames_transicion(q["tipo"], p.dur, estilo.paleta, fps)
    elif p.clase == "emoji":
        fr = emojis.frames_emoji(q["emoji"], p.dur, q["cx"], q["cy"], q["tam"], fps)
    else:
        fr = emojis.frames_vineta(p.dur, fps)
    return rotulos.render_slot(fr, destino, fps)


def renderizar(trabajo: Path, borrador: bool = False) -> Path:
    trabajo = Path(trabajo)
    datos = json.loads((trabajo / "trabajo.json").read_text("utf-8"))
    estilo = estilos.cargar(datos["estilo"])
    zonas = datos["zonas"]
    plan = leer(trabajo / "plan.validado.json")
    video = trabajo / "video.mp4"
    duracion = float(componer._duracion(video))
    specs = derivar(plan, zonas, estilo, duracion)
    tmp = trabajo / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    fps = _fps_overlay(video)
    overlays = [Overlay(_render_pieza(p, estilo, fps, tmp / f"slot_{i:02d}.mov"), p.t, p.dur)
                for i, p in enumerate(specs.piezas)]
    pista_sfx = sonidos.pista(specs.sfx, duracion, tmp / "sfx.wav")
    pista_musica = None
    if specs.musica:
        m = specs.musica
        pista_musica = musica.pista(duracion, m["bpm"], m["progresion"], m["fade_out"], tmp / "musica.wav")
    franja = tuple(zonas["franja_zoom"]) if zonas.get("franja_zoom") else None
    salida = trabajo / "salida.mp4"
    componer.componer(video, salida, overlays, franja, specs.zooms, [pista_sfx], pista_musica,
                      specs.musica["db"] if specs.musica else 0.0, borrador=borrador)
    return salida


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--borrador"]
    if len(args) != 1:
        print("Uso: python -m videopipeline.edicion.renderizar <trabajo> [--borrador]", file=sys.stderr)
        return 1
    try:
        print(renderizar(Path(args[0]), "--borrador" in argv))
    except Exception as e:
        print(f"Error al renderizar: {e}"[:300].replace("\n", " "), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
