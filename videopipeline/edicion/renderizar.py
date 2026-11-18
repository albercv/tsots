"""Deriva overlays, sonidos y zooms del plan validado y renderiza el short editado.

`derivar` es pura (sin ffmpeg ni PIL); `renderizar` ejecuta el resultado.
"""
import json
import logging
import shutil
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from videopipeline import edicion
from videopipeline.edicion import (broll, callouts, componer, emojis, estilos, graficos, musica,
                                   rotulos, sonidos)
from videopipeline.edicion import pantalla as ocr
from videopipeline.edicion.componer import Overlay, Zoom
from videopipeline.edicion.estilos import Estilo
from videopipeline.edicion.plan import DURACION, DURACION_FINAL, Momento, Plan, leer
from videopipeline.edicion.sonidos import EventoSfx

log = logging.getLogger(__name__)

DUR_MIN = 0.2
# Primer sonido de la lista que tenga el estilo; ninguno si no tiene ninguno.
SFX_NUEVOS = {"senalar": ("tap", "tick", "pop"), "lupa": ("whoosh_b", "tick", "pop"),
              "broll": ("whoosh_g", "whoosh_b", "pluck"), "icono": ("pop", "tick", "tap"),
              "dato": ("tick2", "tick", "pluck")}
FREQS_TAP = (650, 700, 750, 800, 850, 900)


@dataclass
class Pieza:
    clase: str  # etiqueta | contador | emoji | transicion | vineta | senalar | lupa | broll | icono | dato
    t: float
    dur: float
    params: dict
    sfx: EventoSfx | None = None  # sonido propio: se descarta si la pieza se omite


@dataclass
class Specs:
    piezas: list[Pieza]
    sfx: list[EventoSfx]
    zooms: list[Zoom]
    musica: dict | None


def _lineas(texto) -> list[str]:
    return [texto] if isinstance(texto, str) else list(texto or [])


def derivar(plan: Plan, zonas: dict, estilo: Estilo, duracion: float,
            pantalla: list | None = None) -> Specs:
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

    def sonido_nuevo(tipo, t):
        primero = next((s for s in SFX_NUEVOS[tipo] if s in estilo.sfx), None)
        if primero:
            # pop/pluck piden num y tap pide freq (los sintetizadores los exigen)
            sonido(primero, t + 0.08, **{"pop": {"num": 1}, "pluck": {"num": 1},
                                          "tap": {"freq": FREQS_TAP[0]}}.get(primero, {}))
            piezas[-1].sfx = sfx[-1]  # la pieza recién añadida

    sonido("boom", 0.05)
    visuales = sorted((m for m in plan.momentos if m.tipo != "zoom"), key=lambda m: m.t)
    ticks = letra = 0
    lado: dict = {}  # contador de lado por lista: cada lista empieza en L
    for m in (m for m in visuales if m.tipo not in ("emoji", "icono")):
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
                     lado="LR"[lado.get(m.lista, 0) % 2]):
                lado[m.lista] = lado.get(m.lista, 0) + 1
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
        elif m.tipo in ("senalar", "lupa"):
            caja = ocr.buscar(pantalla, m.pantalla, t) if pantalla else None
            if caja is not None:  # un plan validado la encuentra; si no, se omite
                extra = {"forma": m.forma or "circulo"} if m.tipo == "senalar" else {}
                if pieza(m.tipo, t, DURACION[m.tipo], pantalla=m.pantalla, caja=caja, **extra):
                    sonido_nuevo(m.tipo, t)
        elif m.tipo == "broll":
            if pieza("broll", t, DURACION["broll"], buscar=m.buscar,
                     modo=ocr.modo_broll(pantalla or [], t, broll.DURACION)):
                sonido_nuevo("broll", t)
        elif m.tipo == "dato":
            if pieza("dato", t, DURACION["dato"], valor=m.valor, texto=_lineas(m.texto)[0],
                     unidad=m.unidad):
                sonido_nuevo("dato", t)
    if plan.final:
        t = max(0.0, duracion - DURACION_FINAL)
        if pieza("etiqueta", t, DURACION_FINAL, lineas=_lineas(plan.final["texto"]), grande=True,
                 check=bool(plan.final.get("check"))):
            sonido("ding", t)
    ocupado = [(p.t, p.t + p.dur) for p in piezas if p.clase in ("etiqueta", "contador")]
    taps = 0
    for m in (m for m in visuales if m.tipo in ("emoji", "icono")):
        fin = min(m.t + DURACION[m.tipo], duracion)
        lateral = any(a < fin and m.t < b for a, b in ocupado)
        pos = dict(cy=330, cx=950 if lateral else 540, tam=170 if lateral else 220)
        if m.tipo == "icono":
            if pieza("icono", m.t, DURACION["icono"], icono=m.icono, **pos):
                sonido_nuevo("icono", m.t)
        elif pieza("emoji", m.t, DURACION["emoji"], emoji=m.emoji, **pos):
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


@dataclass
class RenderCtx:
    video: Path
    zonas: dict
    carpeta_broll: Path
    usados: set[int]
    creditos: list[dict]
    clave: str | None = None


def _render_nueva(p: Pieza, estilo: Estilo, fps: int, destino: Path, ctx: RenderCtx) -> Path | None:
    q = p.params
    if p.clase == "senalar":
        cajas = callouts.seguir(ctx.video, q["pantalla"], p.t, p.dur, fps, q["caja"], ctx.zonas)
        fr = callouts.frames_senalar(cajas, q["forma"], estilo.paleta, fps, ctx.zonas, p.t)
    elif p.clase == "lupa":
        cajas = callouts.seguir(ctx.video, q["pantalla"], p.t, p.dur, fps, q["caja"], ctx.zonas)
        fr = callouts.frames_lupa(ctx.video, cajas, p.t, p.dur, ctx.zonas, estilo.paleta, fps)
    elif p.clase == "broll":
        clip = broll.obtener(q["buscar"], ctx.usados, ctx.carpeta_broll, ctx.clave)
        if clip is None:
            return None
        fr = broll.frames_broll(clip.archivo, q["modo"], p.dur, ctx.zonas, estilo.paleta, fps)
        ruta = rotulos.render_slot(fr, destino, fps)  # el crédito solo cuenta si se renderizó
        ctx.usados.add(clip.id)
        ctx.creditos.append({"autor": clip.autor, "url": clip.url, "buscar": q["buscar"], "t": p.t})
        return ruta
    elif p.clase == "icono":
        fr = graficos.frames_icono(q["icono"], p.dur, q["cx"], q["cy"], q["tam"], estilo.paleta, fps)
    else:
        fr = graficos.frames_dato(q["valor"], q["texto"], q["unidad"], p.dur, estilo.paleta, fps)
    return rotulos.render_slot(fr, destino, fps)


def _render_pieza(p: Pieza, estilo: Estilo, fps: int, destino: Path, ctx: RenderCtx) -> Path | None:
    """`None` si la pieza se omite: los recursos nuevos nunca tumban el render."""
    if p.clase in ("senalar", "lupa", "broll", "icono", "dato"):
        try:
            return _render_nueva(p, estilo, fps, destino, ctx)
        except Exception as e:  # noqa: BLE001 — OCR, red, ffmpeg o clip malo: se omite
            log.warning("Pieza %s en t=%.1f omitida: %s", p.clase, p.t, type(e).__name__)
            destino.unlink(missing_ok=True)
            return None
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


def _pista_musica(m: dict | None, estilo_id: str, duracion: float, tmp: Path,
                  semilla: str) -> Path | None:
    """La música del short: una pista propia del estilo (en rotación) o, si no
    hay o falla, la sintetizada con una variante que depende del trabajo."""
    if not m:
        return None
    tmp.mkdir(parents=True, exist_ok=True)
    destino = tmp / "musica.wav"
    propia = musica.elegir_pista(estilo_id, edicion.DIR_MUSICA)
    if propia is not None:
        try:
            return musica.preparar_pista(propia, duracion, m["fade_out"], destino)
        except Exception as error:  # noqa: BLE001 — la sintetizada siempre vale
            log.warning("Música propia descartada: %s", error)
    return musica.pista(duracion, m["bpm"], m["progresion"], m["fade_out"], destino,
                        variante=zlib.crc32(semilla.encode("utf-8")))


def renderizar(trabajo: Path, borrador: bool = False) -> Path:
    trabajo = Path(trabajo)
    datos = json.loads((trabajo / "trabajo.json").read_text("utf-8"))
    estilo = estilos.cargar(datos["estilo"])
    zonas = datos["zonas"]
    plan = leer(trabajo / "plan.validado.json")
    video = trabajo / "video.mp4"
    duracion = float(componer._duracion(video))
    ruta_pantalla = trabajo / "pantalla.json"
    muestras = ocr.cargar(ruta_pantalla) if ruta_pantalla.exists() else None
    specs = derivar(plan, zonas, estilo, duracion, muestras)
    tmp = trabajo / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    fps = _fps_overlay(video)
    ctx = RenderCtx(video, zonas, trabajo / "broll", set(), [], broll.leer_clave())
    overlays, omitidos = [], []
    for i, p in enumerate(specs.piezas):
        ruta = _render_pieza(p, estilo, fps, tmp / f"slot_{i:02d}.mov", ctx)
        if ruta is not None:
            overlays.append(Overlay(ruta, p.t, p.dur))
        elif p.sfx is not None:
            omitidos.append(p.sfx)
    specs.sfx = [e for e in specs.sfx if not any(e is o for o in omitidos)]  # sin imagen, sin sonido
    creditos = trabajo / "broll.json"
    if ctx.creditos:
        creditos.write_text(json.dumps(ctx.creditos, ensure_ascii=False, indent=2), "utf-8")
    else:
        creditos.unlink(missing_ok=True)
    pista_sfx = sonidos.pista(specs.sfx, duracion, tmp / "sfx.wav")
    pista_musica = _pista_musica(specs.musica, estilo.id, duracion, tmp, trabajo.name)
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
