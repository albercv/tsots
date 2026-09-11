from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import i18n
from .config import PipelineConfig
from .errores import explicar
from .i18n import _
from .pipeline import run
from .steps import BASE_DIR, PasoFallido

# Un log por trabajo: logs/<vídeo>_<YYYYmmdd-HHMMSS>.log. Guarda config,
# eventos con marca de tiempo, y en caso de error el diagnóstico completo.
DIR_LOGS = BASE_DIR / "logs"


def _imprimir(evento: dict) -> None:
    print(json.dumps(evento, ensure_ascii=False), flush=True)


class _Log:
    def __init__(self, ruta: Path | None):
        self.ruta = ruta
        self._inicio = time.monotonic()
        self._fh = None
        if ruta is not None:
            try:
                ruta.parent.mkdir(parents=True, exist_ok=True)
                self._fh = ruta.open("a", encoding="utf-8")
            except OSError:
                self.ruta = None  # sin log no se aborta el trabajo

    def escribir(self, texto: str) -> None:
        if self._fh is None:
            return
        marca = f"[{time.monotonic() - self._inicio:8.1f}s] "
        sangria = "\n" + " " * len(marca)
        self._fh.write(marca + texto.rstrip("\n").replace("\n", sangria) + "\n")
        self._fh.flush()

    def cerrar(self) -> None:
        if self._fh is not None:
            self._fh.close()


def _ruta_log(config_path: Path) -> Path:
    try:
        nombre = json.loads(config_path.read_text(encoding="utf-8")).get("video", "")
        stem = Path(nombre).stem or "trabajo"
    except (OSError, ValueError, AttributeError):
        stem = "trabajo"
    return DIR_LOGS / f"{stem}_{datetime.now():%Y%m%d-%H%M%S}.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ejecuta el pipeline de limpieza y emite progreso JSON."
    )
    parser.add_argument("--config", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        if error.code in (None, 0):
            # --help u otra salida "limpia" de argparse: ya se imprimió lo debido.
            return 0
        _imprimir({
            "error": _("argumentos inválidos: se requiere --config"), "step": 0
        })
        return 1

    # Resolver la ruta de config contra el cwd del llamador ANTES del chdir.
    config_path = args.config.expanduser().resolve()
    log = _Log(_ruta_log(config_path))

    # Los checkpoints de ClearVoice se resuelven relativos a clearvoice/.
    os.chdir(BASE_DIR)

    log.escribir(
        f"TheSilenceOfTheShorts runner · {platform.platform()} · Python "
        f"{platform.python_version()} · cwd={BASE_DIR}"
    )

    ultimo_paso = 0
    ultima_etiqueta = ""

    def on_progress(evento: dict) -> None:
        nonlocal ultimo_paso, ultima_etiqueta
        ultimo_paso = evento.get("step", ultimo_paso)
        if evento.get("label"):
            ultima_etiqueta = evento["label"]
        # El progreso porcentual es ruido en el log; los cambios de paso no.
        if evento.get("percent") is None or "warning" in evento:
            log.escribir(json.dumps(evento, ensure_ascii=False))
        _imprimir(evento)

    def fallar(mensaje: str, detalle: str) -> int:
        diagnostico = explicar(mensaje, detalle)
        log.escribir(
            _("ERROR en paso {paso} ({etiqueta})").format(
                paso=ultimo_paso, etiqueta=ultima_etiqueta or '?')
        )
        log.escribir(diagnostico.texto())
        log.cerrar()
        _imprimir({
            "error": mensaje if not detalle else f"{mensaje}\n{detalle}",
            "step": ultimo_paso,
            "paso": ultima_etiqueta,
            "diagnostico": asdict(diagnostico),
            "log": str(log.ruta) if log.ruta else "",
        })
        return 1

    try:
        config = PipelineConfig.from_json(
            config_path.read_text(encoding="utf-8")
        )
        i18n.instalar(config.idioma_ui)
        log.escribir("config: " + json.dumps(asdict(config), ensure_ascii=False,
                                             default=str))
        salida = run(config, on_progress)
    except PasoFallido as error:
        return fallar(str(error), error.detalle)
    except Exception as error:  # noqa: BLE001 — el subproceso reporta todo por JSON
        return fallar(
            f"{type(error).__name__}: {error}",
            "".join(traceback.format_exception(error)),
        )

    log.escribir(f"OK · salida={salida}")
    log.cerrar()
    _imprimir({"done": True, "salida": str(salida)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
