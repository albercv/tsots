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

from . import i18n, shorts
from .config import PipelineConfig
from .errores import explicar
from .ficha import Ficha, cargar
from .i18n import _
from .pipeline import Progreso, run
from .reproceso import ejecutar
from .reproceso_plan import Decisiones, planificar
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


def _cargar_ficha(id_: str) -> Ficha:
    ficha = cargar(id_)
    if ficha is None:
        raise PasoFallido(
            _("No se encuentra la ficha de este vídeo ({id}). Arrastra el "
              "original para procesarlo de nuevo.").format(id=id_))
    return ficha


def _reprocesar(config: PipelineConfig, reproceso: dict, on_progress: Progreso
                ) -> tuple[Path, Path | None]:
    """Una pasada sobre la ficha. Devuelve la salida principal y el vertical que
    acompaña a un horizontal (si lo hay)."""
    # «Solo caption» no marca ningún paso de vídeo.
    config.validar(exigir_paso_de_video=False)
    ficha = _cargar_ficha(reproceso["ficha"])
    plan = planificar(ficha, config, Decisiones(
        rehacer=frozenset(reproceso.get("rehacer", ())),
        regenerar_vertical=bool(reproceso.get("regenerar_vertical", False))))
    if plan.error:
        raise PasoFallido(plan.error)
    if plan.vacio:  # nada que hacer: se muestra lo que ya hay
        if ficha.final is None:
            raise PasoFallido(
                _('"{nombre}" no tiene ninguna salida que mostrar. Arrastra el '
                  'original para procesarlo de nuevo.').format(nombre=ficha.nombre))
        salida = ficha.final.ruta
    else:
        salida = ejecutar(ficha, plan, on_progress)  # deja la ficha al día
    return salida, ficha.vertical.ruta if ficha.vertical else None


def _crear_shorts(config: PipelineConfig, pedido: dict, on_progress: Progreso
                  ) -> shorts.Resultado:
    """Los shorts de la ficha, ya procesada (la carga de nuevo: `ejecutar` actualiza
    la suya, no la que tenga quien llama)."""
    opciones = shorts.OpcionesShorts.de_datos(pedido)
    return shorts.crear(_cargar_ficha(pedido["ficha"]), config, opciones, on_progress)


def _shorts_desde_boton(config: PipelineConfig, pedido: dict, on_progress: Progreso
                        ) -> tuple[shorts.Resultado, Path | None]:
    """Solo shorts: si el vídeo aún no está procesado, lo procesa antes con los
    ajustes del panel. Devuelve también el vertical que haya salido de ahí."""
    config.validar(exigir_paso_de_video=False)
    vertical = None
    if _cargar_ficha(pedido["ficha"]).final is None:
        _, vertical = _reprocesar(config, {"ficha": pedido["ficha"]}, on_progress)
    return _crear_shorts(config, pedido, on_progress), vertical


def _escrito_ahora(ruta: Path | None, inicio: float) -> Path | None:
    """La ruta resuelta si es un archivo escrito en esta ejecución: si falló, el
    de una ejecución anterior sigue en disco y no debe parecer nuevo."""
    if ruta is None:
        return None
    ruta = ruta.expanduser().resolve()
    return ruta if ruta.is_file() and ruta.stat().st_mtime >= inicio else None


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

    inicio = time.time() - 1  # margen para relojes de sistemas de archivos gruesos
    try:
        datos = json.loads(config_path.read_text(encoding="utf-8"))
        reproceso = datos.pop("reproceso", None)  # no es un campo de PipelineConfig
        pedido_shorts = datos.pop("shorts", None)  # ni este
        config = PipelineConfig.from_datos(datos)
        i18n.instalar(config.idioma_ui)
        log.escribir("config: " + json.dumps(asdict(config), ensure_ascii=False,
                                             default=str))
        resultado_shorts = None
        if pedido_shorts is not None:
            log.escribir("shorts: " + json.dumps(pedido_shorts, ensure_ascii=False))
        if reproceso is None and pedido_shorts is not None:  # el botón de shorts
            resultado_shorts, vertical = _shorts_desde_boton(
                config, pedido_shorts, on_progress)
            salida = resultado_shorts.carpeta
        else:
            if reproceso is None:
                salida = run(config, on_progress)
                vertical = config.ruta_salida_vertical()
            else:
                log.escribir("reproceso: " + json.dumps(reproceso, ensure_ascii=False))
                salida, vertical = _reprocesar(config, reproceso, on_progress)
            if pedido_shorts is not None:
                # Con «crear shorts al procesar» un fallo de los shorts no hace
                # fallar el procesado: es un aviso.
                try:
                    resultado_shorts = _crear_shorts(config, pedido_shorts, on_progress)
                except Exception as error:  # noqa: BLE001
                    log.escribir("".join(traceback.format_exception(error)))
                    motivo = (str(error) if isinstance(error, PasoFallido)
                              else f"{type(error).__name__}: {error}")
                    on_progress({"warning": _(
                        "Los shorts fallaron: {error}. El vídeo se ha procesado "
                        "igual.").format(error=motivo.rstrip("."))})
    except PasoFallido as error:
        return fallar(str(error), error.detalle)
    except Exception as error:  # noqa: BLE001 — el subproceso reporta todo por JSON
        return fallar(
            f"{type(error).__name__}: {error}",
            "".join(traceback.format_exception(error)),
        )

    vertical = _escrito_ahora(vertical, inicio)
    log.escribir(
        f"OK · salida={salida}" + (f" · vertical={vertical}" if vertical else ""))
    log.cerrar()
    evento = {
        "done": True,
        "salida": str(salida),
        "salida_vertical": str(vertical) if vertical else None,
    }
    if reproceso is not None:
        evento["ficha"] = reproceso["ficha"]
    if resultado_shorts is not None and resultado_shorts.n > 0:
        evento["shorts"] = {
            "carpeta": str(resultado_shorts.carpeta), "n": resultado_shorts.n}
    _imprimir(evento)
    return 0


if __name__ == "__main__":
    sys.exit(main())
