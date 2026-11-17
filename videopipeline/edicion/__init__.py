"""Edición automática de shorts con Claude Haiku: el agente en segundo plano."""
import logging
import shutil
import subprocess
from pathlib import Path

from videopipeline.steps import BASE_DIR

log = logging.getLogger(__name__)

DIR_EDICION = Path.home() / "TSOTS" / "edicion"
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
