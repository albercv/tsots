"""Escribe contexto.md: lo que Haiku lee para decidir los momentos del short."""
import json
import math
import sys
from pathlib import Path

from videopipeline import subtitles
from videopipeline.config import PipelineConfig
from videopipeline.edicion import estilos
from videopipeline.edicion.componer import _duracion
from videopipeline.subtitles import Palabra

SILENCIO_FRASE = 0.5


def _frases(palabras: list[Palabra]) -> list[str]:
    grupos: list[list[Palabra]] = []
    for p in palabras:
        if grupos and p.inicio - grupos[-1][-1].fin < SILENCIO_FRASE:
            grupos[-1].append(p)
        else:
            grupos.append([p])
    return [f"[{g[0].inicio:.2f}-{g[-1].fin:.2f}] {' '.join(p.texto for p in g)}" for g in grupos]


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
    lineas = [
        "# Contexto del vídeo", "",
        "## Estilo",
        f"- id: {estilo.id}",
        f"- tipos permitidos: {', '.join(sorted(estilo.tipos))}",
        f"- máximo: como mucho {maximo} momentos en este vídeo (sin contar zoom); duración {dur:.2f} s",
        f"- emojis: {'sí' if 'emoji' in estilo.tipos else 'no'}",
        "", "## Zonas",
        f"- zoom: {'posible' if zoom else 'no disponible'}",
        f"- gráficos permitidos desde el segundo {desde:g}",
        "",
    ]
    caption = trabajo / "caption.md"
    if caption.exists():
        lineas += ["## Caption", caption.read_text("utf-8").strip(), ""]
    lineas += ["## Frases", *_frases(palabras), "",
               "## Palabras", *(f"{p.inicio:.2f} {p.texto}" for p in palabras), ""]
    destino = trabajo / "contexto.md"
    destino.write_text("\n".join(lineas), "utf-8")
    return destino


def main(args: list[str]) -> int:
    try:
        print(preparar(Path(args[0])))
        return 0
    except Exception as e:  # noqa: BLE001 - mensaje de una línea para el agente
        print(f"No se pudo preparar el contexto: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
