"""Orquesta la publicación: orden fijo, fallos aislados, sondeo y registro.

Solo trabaja contra el protocolo `Proveedor`: no conoce ningún servicio.
Deja constancia de cada paso con `logging` (ver `diario`).
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable, Iterable

from ..i18n import _
from . import registro
from .modelo import ORDEN, Opciones, Plataforma, Publicacion, Resultado
from .proveedor import Proveedor


class Estado(str, Enum):
    SUBIENDO = "subiendo"
    PROCESANDO = "procesando"
    HECHO = "hecho"
    ERROR = "error"


log = logging.getLogger(__name__)

Progreso = Callable[[Plataforma, Estado, "Resultado | None"], None]

INTERVALO_SONDEO = 10.0
ESPERA_MAXIMA = 15 * 60.0


def modo_de(plataforma: Plataforma, opciones: Opciones) -> str:
    if plataforma == Plataforma.TIKTOK:
        return opciones.tiktok_modo.value
    if plataforma == Plataforma.INSTAGRAM:
        return opciones.instagram_modo.value
    return "publico"


def _fallo(plataforma: Plataforma, excepcion: BaseException) -> Resultado:
    # Solo el tipo: el mensaje de una excepción ajena podría llevar datos sensibles.
    return Resultado(plataforma, ok=False, error=_(
        "Error inesperado ({tipo}). Detalles en el registro de la publicación.").format(
        tipo=type(excepcion).__name__))


def _describir(resultado: Resultado) -> str:
    if resultado.ok:
        return f"OK {resultado.url or '(sin enlace)'}"
    if resultado.pendiente:
        return f"pendiente (referencia {resultado.referencia or '-'}) {resultado.error}".rstrip()
    return f"ERROR {resultado.error}"


def publicar(
    proveedor: Proveedor,
    publicacion: Publicacion,
    opciones: Opciones,
    plataformas: Iterable[Plataforma],
    *,
    progreso: Progreso | None = None,
    nombre_proveedor: str = "",
    registrar: bool = True,
    cancelado: Callable[[], bool] = lambda: False,
    espera: Callable[[float], None] = time.sleep,
    reloj: Callable[[], float] = time.monotonic,
    intervalo: float | None = None,
    espera_maxima: float | None = None,
) -> dict[Plataforma, Resultado]:
    """Publica en las plataformas elegidas, en el orden TikTok → YouTube →
    Instagram. Un fallo en una no detiene las siguientes. Las que quedan
    pendientes en el proveedor se consultan hasta `espera_maxima` segundos.
    Cada éxito se anota en el registro en cuanto se conoce."""
    # Se leen al llamar (no al definir la función) para poder ajustarlas.
    intervalo = INTERVALO_SONDEO if intervalo is None else intervalo
    espera_maxima = ESPERA_MAXIMA if espera_maxima is None else espera_maxima
    elegidas = [p for p in ORDEN if p in set(plataformas)]
    avisar = progreso or (lambda *a: None)
    resultados: dict[Plataforma, Resultado] = {}
    pendientes: dict[Plataforma, Resultado] = {}

    def terminar(plataforma: Plataforma, resultado: Resultado) -> None:
        resultados[plataforma] = resultado
        log.info("%s: resultado final: %s", plataforma.nombre, _describir(resultado))
        # Lo que quedó sin confirmar puede estar publicado: también se anota,
        # para avisar antes de repetirlo.
        if (resultado.ok or resultado.pendiente) and registrar:
            try:
                registro.anotar(publicacion.video, plataforma, resultado.url,
                                nombre_proveedor, modo_de(plataforma, opciones),
                                sin_confirmar=not resultado.ok)
            except OSError:
                # El vídeo ya está publicado; perder la nota no es grave.
                log.warning("%s: no se pudo anotar en el registro local", plataforma.nombre,
                            exc_info=True)
        avisar(plataforma, Estado.HECHO if resultado.ok else Estado.ERROR, resultado)

    log.info("Orden: %s", ", ".join(p.nombre for p in elegidas) or "(ninguna)")
    for plataforma in elegidas:
        if cancelado():
            log.info("Cancelado antes de %s", plataforma.nombre)
            break
        avisar(plataforma, Estado.SUBIENDO, None)
        log.info("%s: enviando (modo %s)", plataforma.nombre, modo_de(plataforma, opciones))
        inicio = reloj()
        try:
            resultado = proveedor.publicar(plataforma, publicacion, opciones)
        except Exception as e:  # un proveedor no debería lanzar; si lo hace, se aísla
            log.exception("%s: excepción inesperada del proveedor", plataforma.nombre)
            resultado = _fallo(plataforma, e)
        log.info("%s: envío terminado en %.1f s: %s", plataforma.nombre, reloj() - inicio,
                 _describir(resultado))
        if resultado.pendiente and resultado.referencia:
            pendientes[plataforma] = resultado
            avisar(plataforma, Estado.PROCESANDO, resultado)
        else:  # también un pendiente sin referencia: no hay nada que consultar
            terminar(plataforma, resultado)

    inicio = reloj()
    vuelta = 0
    while pendientes and not cancelado() and reloj() - inicio < espera_maxima:
        espera(intervalo)
        vuelta += 1
        for plataforma, anterior in list(pendientes.items()):
            try:
                nuevo = proveedor.estado(plataforma, anterior.referencia)
            except Exception:
                log.warning("%s: la consulta %d falló; se reintenta", plataforma.nombre,
                            vuelta, exc_info=True)
                continue  # se reintenta en la siguiente vuelta
            log.info("%s: consulta %d (referencia %s): %s", plataforma.nombre, vuelta,
                     anterior.referencia, _describir(nuevo))
            if not nuevo.pendiente or not nuevo.referencia:
                del pendientes[plataforma]
                terminar(plataforma, nuevo)

    for plataforma, anterior in pendientes.items():
        log.warning("%s: sin respuesta final tras %.0f s de espera", plataforma.nombre,
                    reloj() - inicio)
        terminar(plataforma, Resultado(
            plataforma, ok=False, pendiente=True, referencia=anterior.referencia,
            error=_("Sigue procesándose en el servicio. Revisa {plataforma} en unos minutos.").format(
                plataforma=plataforma.nombre),
        ))

    return {p: resultados[p] for p in elegidas if p in resultados}
