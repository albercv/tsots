"""Edición automática de shorts con Claude Haiku: el agente en segundo plano."""
import json
import logging
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from videopipeline.steps import BASE_DIR
from videopipeline.subtitles import Palabra

log = logging.getLogger(__name__)

DIR_EDICION = Path.home() / "TSOTS" / "edicion"
# Música de fondo propia, una carpeta por estilo (divertido/, formal/, academico/).
DIR_MUSICA = Path.home() / "TSOTS" / "musica"
AGENTE = BASE_DIR / "lanzador" / "edicion" / "procesar_pendientes.sh"


def claude_disponible() -> bool:
    return bool(shutil.which("claude")
                or (Path.home() / ".local" / "bin" / "claude").exists()
                or Path("/opt/homebrew/bin/claude").exists())


def lanzar_agente_edicion(dir_edicion: Path = DIR_EDICION) -> bool:
    """Arranca el agente suelto, sin esperarlo, si hay trabajos en `pendientes/`
    (como `difusion.lanzar_agente`). Su bloqueo evita dos a la vez. Nunca lanza."""
    try:
        if not AGENTE.is_file() or not any(
                p.is_dir() and not p.name.startswith(".")
                for p in (dir_edicion / "pendientes").iterdir()):
            return False
        with open(dir_edicion / "agente.log", "ab") as registro:
            subprocess.Popen([str(AGENTE), str(dir_edicion)], stdin=subprocess.DEVNULL,
                             stdout=registro, stderr=registro,
                             start_new_session=True, close_fds=True)
    except FileNotFoundError:
        return False
    except OSError as error:
        log.warning("No se pudo lanzar el agente de edición (%s): %s", AGENTE, error)
        return False
    return True


def encolar(carpeta: Path, episodio: str, stems: list[str],
            tramos: dict[str, list[Palabra]], estilo: str, zonas: dict[str, dict],
            idioma: str, encuadre: str, dir_edicion: Path = DIR_EDICION) -> list[Path]:
    """Deja un trabajo en `pendientes/` por cada short `<stem>.mp4` de `carpeta`.

    Cada uno se escribe en `.<nombre>.tmp` y se renombra al acabar. Nunca lanza:
    un trabajo que falla se registra y se salta."""
    from videopipeline.difusion import _carpeta_libre, _enlazar_o_copiar
    creados = []
    for stem in stems:
        origen = carpeta / f"{stem}.mp4"
        if not origen.is_file():
            continue
        nombre = f"{episodio} - {stem}"
        tmp = dir_edicion / "pendientes" / f".{nombre}.tmp"
        try:
            destino = _carpeta_libre(dir_edicion, nombre)
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            _enlazar_o_copiar(origen, tmp / "video.mp4")
            for sufijo, copia in ((".srt", "subs.srt"), (".md", "caption.md")):
                if (carpeta / f"{stem}{sufijo}").is_file():
                    shutil.copy2(carpeta / f"{stem}{sufijo}", tmp / copia)
            (tmp / "palabras.json").write_text(
                json.dumps([asdict(p) for p in tramos.get(stem, [])],
                           ensure_ascii=False), encoding="utf-8")
            info = origen.stat()
            (tmp / "trabajo.json").write_text(json.dumps({
                "version": 1, "origen": str(origen),
                "destino": str(carpeta / f"{stem}.editado.mp4"),
                "origen_tam": info.st_size, "origen_mtime": info.st_mtime,
                "estilo": estilo, "idioma": idioma, "resolucion": [1080, 1920],
                "encuadre": encuadre, "zonas": zonas.get(stem, {}),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(destino)
            creados.append(destino)
        except Exception as error:  # noqa: BLE001 — encolar nunca rompe a quien llama
            log.warning("No se pudo encolar %s para edición: %s", nombre, error)
            shutil.rmtree(tmp, ignore_errors=True)
    return creados
