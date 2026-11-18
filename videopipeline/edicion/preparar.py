"""Escribe contexto.md: lo que Haiku lee para decidir los momentos del short."""
import argparse
import json
import math
import shutil
import sys
from pathlib import Path

from videopipeline import subtitles
from videopipeline.config import ENCUADRES, PipelineConfig
from videopipeline.edicion import broll, graficos, numeros, pantalla, estilos, zonas as zonas_edicion
from videopipeline.edicion.componer import _duracion
from videopipeline.subtitles import Palabra

SILENCIO_FRASE = 0.5


def _frases(palabras: list[Palabra]) -> list[str]:
    """Corta en silencios >= 0.5 s, tras . ? ! , si la frase ya dura >= 3 s, y siempre a los 8 s."""
    grupos: list[list[Palabra]] = []
    abierta = False
    for p in palabras:
        if abierta and p.inicio - grupos[-1][-1].fin < SILENCIO_FRASE:
            grupos[-1].append(p)
        else:
            grupos.append([p])
        g = grupos[-1]
        dur = p.fin - g[0].inicio
        abierta = not (dur >= 8 or (dur >= 3 and p.texto.rstrip().endswith((".", "?", "!", ","))))
    return [f"[{g[0].inicio:.2f}-{g[-1].fin:.2f}] {' '.join(p.texto for p in g)}" for g in grupos]


def _leer_pantalla(trabajo: Path, zonas: dict):
    """Muestras del OCR, o None si no hay lectura. pantalla.json existe solo si el análisis terminó."""
    ruta = trabajo / "pantalla.json"
    if not ruta.exists() and pantalla.ocr_disponible():
        try:
            pantalla.analizar(trabajo / "video.mp4", zonas, ruta)
        except Exception as e:  # noqa: BLE001 - el OCR nunca debe romper preparar
            ruta.unlink(missing_ok=True)
            print(f"Lectura de pantalla no disponible: {e}")
    return pantalla.cargar(ruta) if ruta.exists() else None


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def crear_trabajo(video: Path, estilo: str, encuadre: str, srt: Path | None = None,
                  trabajo: Path | None = None) -> Path:
    """Modo interactivo: la carpeta de trabajo de un vídeo suelto (con su trabajo.json)."""
    from videopipeline.difusion import _enlazar_o_copiar
    from videopipeline.steps import resolucion_video
    video = Path(video).resolve()
    estilos.cargar(estilo)  # valida el id
    if encuadre not in ENCUADRES:
        raise ValueError(f"Encuadre desconocido: {encuadre!r}")
    trabajo = Path(trabajo) if trabajo else video.with_name(f"{video.stem}.edicion")
    trabajo.mkdir(parents=True, exist_ok=True)
    if not (trabajo / "video.mp4").exists():
        _enlazar_o_copiar(video, trabajo / "video.mp4")
    if srt:
        shutil.copy2(srt, trabajo / "subs.srt")
    info = video.stat()
    zonas = zonas_edicion.calcular(PipelineConfig(video=video, subtitulos=True), encuadre,
                                   resolucion_video(video), con_titulo=True)
    (trabajo / "trabajo.json").write_text(json.dumps({
        "version": 1, "origen": str(video),
        "destino": str(video.with_name(f"{video.stem}.editado.mp4")),
        "origen_tam": info.st_size, "origen_mtime": info.st_mtime,
        "estilo": estilo, "idioma": "es", "resolucion": [1080, 1920],
        "encuadre": encuadre, "zonas": zonas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return trabajo


def preparar(trabajo: Path) -> Path:
    trabajo = Path(trabajo)
    datos = json.loads((trabajo / "trabajo.json").read_text("utf-8"))
    ruta_pal = trabajo / "palabras.json"
    if not ruta_pal.exists():
        pals = subtitles.transcribir(trabajo / "video.mp4", datos.get("idioma", "es"),
                                     PipelineConfig(video=trabajo / "video.mp4").modelo_whisper)
        ruta_pal.write_text(json.dumps(
            [{"texto": p.texto, "inicio": p.inicio, "fin": p.fin} for p in pals],
            ensure_ascii=False), "utf-8")
    palabras = [Palabra(d["texto"], d["inicio"], d["fin"])
                for d in json.loads(ruta_pal.read_text("utf-8"))]
    estilo = estilos.cargar(datos["estilo"])
    zonas = datos["zonas"]
    dur = float(_duracion(trabajo / "video.mp4"))
    maximo = math.ceil(estilo.densidad_max * dur)
    zoom = zonas.get("franja_zoom") is not None and "zoom" in estilo.tipos
    desde = (zonas.get("titulo") or {}).get("hasta", 0) if zonas.get("titulo") else 0
    muestras = _leer_pantalla(trabajo, datos["zonas"])
    en_pantalla = ("- no disponible",) if muestras is None else tuple(
        f"{c.t0:.2f}-{c.t1:.2f} «{c.visible}» (dicha «{c.palabra}» en {c.t_palabra:.2f})"
        for c in pantalla.coincidencias(muestras, palabras)) or ("- ninguna",)
    dichos = [f"{t:.2f} {_num(v)} «{pal}»{' %' if pct else ''}"
              for t, v, pal, pct in numeros.numeros_dichos(palabras)] or ["- ninguno"]
    lineas = [
        "# Contexto del vídeo", "",
        "## Estilo",
        f"- id: {estilo.id}",
        f"- tipos permitidos: {', '.join(sorted(estilo.tipos))}",
        f"- máximo: como mucho {maximo} momentos en este vídeo (sin contar zoom); duración {dur:.2f} s",
        f"- emojis: {'sí' if 'emoji' in estilo.tipos else 'no'}",
        f"- lectura de pantalla: {'no' if muestras is None else 'sí'}",
        "- B-roll: " + ("disponible" if broll.hay_clave() else "no disponible (falta la clave de Pexels)"),
        "", "## Zonas",
        f"- zoom: {'posible' if zoom else 'no disponible'}",
        f"- gráficos permitidos desde el segundo {desde:g}",
        "",
    ]
    caption = trabajo / "caption.md"
    if caption.exists():
        lineas += ["## Caption", caption.read_text("utf-8").strip(), ""]
    lineas += ["## En pantalla", *en_pantalla, "", "## Números dichos", *dichos, "",
               "## Iconos", ", ".join(graficos.ICONOS), ""]
    lineas += ["## Frases", *_frases(palabras), "",
               "## Palabras", *(f"{p.inicio:.2f} {p.texto}" for p in palabras), ""]
    destino = trabajo / "contexto.md"
    destino.write_text("\n".join(lineas), "utf-8")
    return destino


def main(args: list[str]) -> int:
    try:
        ap = argparse.ArgumentParser(prog="preparar")
        ap.add_argument("trabajo", nargs="?")
        ap.add_argument("--video")
        ap.add_argument("--estilo", default="divertido")
        ap.add_argument("--encuadre", default="cara")
        ap.add_argument("--srt")
        ap.add_argument("--trabajo", dest="carpeta")
        a = ap.parse_args(args)
        if a.video:
            trabajo = crear_trabajo(Path(a.video), a.estilo, a.encuadre,
                                    Path(a.srt) if a.srt else None,
                                    Path(a.carpeta) if a.carpeta else None)
            preparar(trabajo)
            print(trabajo)
        elif a.trabajo:
            print(preparar(Path(a.trabajo)))
        else:
            raise ValueError("falta la carpeta del trabajo o --video")
        return 0
    except Exception as e:  # noqa: BLE001 - mensaje de una línea para el agente
        print(f"No se pudo preparar el contexto: {e}")
        return 1
    except SystemExit:  # argparse ya imprimió su error
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
