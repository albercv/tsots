"""Qué hay que hacer en una pasada, a partir de lo que la ficha ya tiene.

Lógica pura: no ejecuta nada ni escribe; solo comprueba si existen los
archivos de los que depende cada artefacto (R0). Compara lo que el ejecutor
guarda en cada uno:

- AUDIO: `clave(ajustes_audio)`, ajustes_audio y la línea de tiempo del vídeo
  del que sale.
- BASE: ajustes `{"audio": ..., "silencios": ...}` con los pasos aplicados y
  su línea de tiempo; `archivo` None si el final es la base (R3).
- TRANSCRIPCION: ajustes_transcripcion y la línea de tiempo de la base. Vale
  con la misma línea, idioma y modelo: el glosario solo cuenta si se pide
  rehacer los subtítulos (R6 lo pregunta).
- HORIZONTAL y VERTICAL: `{"subtitulos": ajustes_subtitulos}` si los llevan;
  VERTICAL, además, `{"vertical": ajustes_vertical}`.
- CAPTION: `{"caption": ajustes_caption}`.
- SEGUIMIENTO: clave = línea de tiempo de la base; la imagen solo depende de
  los cortes, no del audio.

Línea de tiempo de la base: "original" sin recorte, y
`clave(ajustes_audio o None, ajustes_silencios)` al recortar (sobre el audio
limpio o sobre el del original). Sin BASE, la base es el original o, en una
salida antigua sin él, el propio final.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import Enum

from .config import PipelineConfig
from .ficha import (
    AUDIO, BASE, CAPTION, HORIZONTAL, PASOS, SEGUIMIENTO, TRANSCRIPCION,
    VERTICAL, Artefacto, Ficha, Huella,
)
from .i18n import N_, _


def clave(*partes) -> str:
    texto = json.dumps(partes, sort_keys=True, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


# Ajustes de los que depende cada paso: nombre en la ficha → campo del panel.
_CAMPOS = {
    "audio": {"tarea": "tarea", "modelo": "modelo"},
    "silencios": {"margen": "margen", "umbral": "umbral",
                  "silencios": "silencios", "velocidad": "velocidad_silencios"},
    "subtitulos": {"diseno": "diseno", "posicion": "posicion_subs",
                   "tamano": "tamano_subs", "idioma": "idioma_subs",
                   "modelo_whisper": "modelo_whisper"},
    "caption": {"modelo_caption": "modelo_caption"},
    "vertical": {"encuadre": "encuadre"},
}
# Casilla del panel que marca cada paso.
_MARCA = {"audio": "paso_audio", "silencios": "paso_silencios",
          "subtitulos": "subtitulos", "caption": "caption_seo",
          "vertical": "paso_vertical"}
_DE_BASE = ("audio", "silencios")


def _ajustes(paso: str, c: PipelineConfig) -> dict:
    return {nombre: getattr(c, campo) for nombre, campo in _CAMPOS[paso].items()}


def ajustes_audio(c: PipelineConfig) -> dict:
    return _ajustes("audio", c)


def ajustes_silencios(c: PipelineConfig) -> dict:
    return _ajustes("silencios", c)


def ajustes_subtitulos(c: PipelineConfig) -> dict:
    return _ajustes("subtitulos", c)


def ajustes_transcripcion(c: PipelineConfig) -> dict:
    return {"idioma": c.idioma_subs, "modelo_whisper": c.modelo_whisper,
            "glosario": clave(c.glosario)}


def ajustes_vertical(c: PipelineConfig) -> dict:
    return _ajustes("vertical", c)


def ajustes_caption(c: PipelineConfig) -> dict:
    return _ajustes("caption", c)


class Accion(str, Enum):
    # En orden de ejecución: el plan las devuelve siempre así.
    LIMPIAR_AUDIO_ORIGINAL = "limpiar_audio_original"   # audio del original entero → AUDIO(linea "original")
    LIMPIAR_AUDIO_BASE = "limpiar_audio_base"           # audio de la base recortada → AUDIO(linea de la base)
    PONER_AUDIO = "poner_audio"                         # remux sin recodificar → BASE
    CORTAR = "cortar"                                   # auto-editor → BASE
    TRANSCRIBIR = "transcribir"                         # → TRANSCRIPCION(linea de la base nueva)
    QUEMAR = "quemar"                                   # base + subs → final (guarda la base aparte, R3)
    ESCRIBIR_FINAL = "escribir_final"                   # base sin subs → final
    CAPTION = "caption"
    SEGUIMIENTO = "seguimiento"
    VERTICAL = "vertical"
    RENOMBRAR_VERTICAL = "renombrar_vertical"           # R10 sin recodificar
    RETIRAR_VERTICAL_UNICO = "retirar_vertical_unico"   # R10 tras regenerar


@dataclass(frozen=True)
class Consulta:
    paso: str          # uno de PASOS
    tipo: str          # "hecho" | "otros_ajustes" | "cambia_base" | "bloqueado"
    texto: str         # traducido, listo para el diálogo
    cambios: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decisiones:
    rehacer: frozenset[str] = frozenset()
    regenerar_vertical: bool = False


@dataclass
class Plan:
    acciones: list[Accion]
    # Efectiva: ajustes del panel para lo pedido; R8 para lo implícito. Sus
    # casillas de audio, silencios y subtítulos dicen cómo queda el vídeo.
    config: PipelineConfig
    avisos: list[str]  # bloqueos aplicados (legado)
    error: str = ""  # no se puede ejecutar (falta el original, caption sin vídeo)
    marcar_desactualizado: bool = False

    @property
    def vacio(self) -> bool:
        return not self.acciones and not self.error


# --- Textos -----------------------------------------------------------------

_NOMBRE_PASO = {
    "audio": N_("la limpieza de audio"),
    "silencios": N_("el recorte de silencios"),
    "subtitulos": N_("subtítulos"),
    "caption": N_("caption"),
    "vertical": N_("vertical"),
}
_BLOQUEADO = {
    "subtitulos": N_('"{nombre}" ya lleva los subtítulos quemados y no hay una '
                     'versión sin ellos. Arrastra el original para rehacerlos.'),
    "vertical": N_('El vertical de "{nombre}" no puede llevar subtítulos: ya '
                   'están quemados en el vídeo. Arrastra el original para '
                   'rehacerlos.'),
}
_CAMBIA_BASE = {  # (paso, la ficha tiene subtítulos)
    ("silencios", True): N_('Recortar silencios cambia los tiempos de '
                            '"{nombre}": se volverán a transcribir y quemar los '
                            'subtítulos. El caption se mantiene.'),
    ("silencios", False): N_('Recortar silencios cambia los tiempos de '
                             '"{nombre}".'),
    ("audio", True): N_('Limpiar el audio cambia la base de "{nombre}": se '
                        'volverán a quemar los subtítulos. El caption se '
                        'mantiene.'),
    ("audio", False): N_('Limpiar el audio cambia la base de "{nombre}".'),
}
_VERTICAL_DESACTUALIZADO = N_("El vertical quedará desactualizado si no lo "
                              "regeneras.")


def _texto_bloqueado(ficha: Ficha, paso: str) -> str:
    return _(_BLOQUEADO[paso]).format(nombre=ficha.nombre)


# --- Lo que tiene la ficha --------------------------------------------------

def _existe(huella: Huella | None) -> bool:
    return huella is not None and huella.ruta.is_file()


def _vale(ficha: Ficha, tipo: str) -> Artefacto | None:
    """El artefacto, si está y su archivo existe (R0). Sin archivo vive fuera de
    la ficha: es la base que coincide con el final."""
    artefacto = ficha.artefactos.get(tipo)
    if artefacto is None:
        return None
    if artefacto.archivo is not None:
        existe = ficha.ruta(artefacto.archivo).is_file()
    else:
        existe = _existe(ficha.final)
    return artefacto if existe else None


def _hecho(ficha: Ficha, paso: str) -> dict | None:
    """Con qué ajustes se hizo `paso` ({} si no se saben); None si no se hizo."""
    if paso not in ficha.pasos_hechos():
        return None
    salida = HORIZONTAL if ficha.hay_horizontal() else VERTICAL
    tipo = {"audio": BASE, "silencios": BASE, "subtitulos": salida,
            "caption": CAPTION, "vertical": VERTICAL}[paso]
    return ficha.artefactos[tipo].ajustes.get(paso) or {}


def _fuente(ficha: Ficha) -> Huella | None:
    """De dónde sale la base nueva: el original o, en una salida antigua sin él,
    el propio final (el ejecutor lo guarda en la ficha antes de pisarlo)."""
    if ficha.original is not None:
        return ficha.original
    return ficha.final if ficha.hay_horizontal() else None


def _fuente_vale(ficha: Ficha) -> bool:
    fuente = _fuente(ficha)
    return fuente is not None and fuente.coincide(fuente.ruta)


def _base_vale(ficha: Ficha) -> bool:
    if BASE in ficha.artefactos:
        return _vale(ficha, BASE) is not None
    return _fuente_vale(ficha)


def _subs_bloqueados(ficha: Ficha) -> bool:
    """Subtítulos quemados sin base limpia ni original del que rehacerla. Con
    `legado` y original, el original sería el propio final antiguo."""
    return ficha.subs_quemados_sin_base and (ficha.original is None or ficha.legado)


# --- Revisar ----------------------------------------------------------------

def _comparables(ficha: Ficha, paso: str, config: PipelineConfig
                 ) -> tuple[dict, dict]:
    antes, ahora = _hecho(ficha, paso), _ajustes(paso, config)
    transcripcion = _vale(ficha, TRANSCRIPCION)
    if (paso == "subtitulos" and transcripcion is not None
            and "glosario" in transcripcion.ajustes):
        antes = {**antes, "glosario": transcripcion.ajustes["glosario"]}
        ahora = {**ahora, "glosario": clave(config.glosario)}
    return antes, ahora


def _cambios(antes: dict, ahora: dict) -> tuple[str, ...]:
    # Del glosario solo se guarda su clave: se dice que cambió, no cómo.
    return tuple(
        campo if campo == "glosario" else f"{campo}: {antes[campo]} → {valor}"
        for campo, valor in ahora.items()
        if campo in antes and antes[campo] != valor)


def revisar(ficha: Ficha, config: PipelineConfig) -> list[Consulta]:
    """Qué preguntar antes de procesar, por cada paso que marca el panel."""
    hechos = ficha.pasos_hechos()
    con_subs, con_vertical = "subtitulos" in hechos, "vertical" in hechos
    # Un vertical único no se queda desactualizado: R10 lo regenera.
    avisa_vertical = con_vertical and ficha.hay_horizontal()
    bloqueado = config.subtitulos and _subs_bloqueados(ficha)
    consultas = []
    for paso in PASOS:
        if not getattr(config, _MARCA[paso]):
            continue
        extra = []
        if bloqueado and paso in ("subtitulos", "vertical"):
            tipo, cambios = "bloqueado", ()
            texto = _texto_bloqueado(ficha, paso)
        elif paso in hechos:
            cambios = _cambios(*_comparables(ficha, paso, config))
            tipo = "otros_ajustes" if cambios else "hecho"
            texto = (_('"{nombre}" ya tiene {paso} con otros ajustes ({cambios}). '
                       '¿Rehacerlo?') if cambios
                     else _('"{nombre}" ya tiene {paso}. ¿Rehacerlo?')).format(
                nombre=ficha.nombre, paso=_(_NOMBRE_PASO[paso]),
                cambios=", ".join(cambios))
            if paso in _DE_BASE and con_subs:
                extra.append(_("Rehacerlo volverá a transcribir y quemar los "
                               "subtítulos; el caption se mantiene."))
        elif paso in _DE_BASE and (con_subs or con_vertical):
            tipo, cambios = "cambia_base", ()
            texto = _(_CAMBIA_BASE[paso, con_subs]).format(nombre=ficha.nombre)
        else:
            continue
        if paso in _DE_BASE and avisa_vertical:
            extra.append(_(_VERTICAL_DESACTUALIZADO))
        consultas.append(Consulta(paso, tipo, " ".join([texto, *extra]), cambios))
    return consultas


# --- Planificar -------------------------------------------------------------

def planificar(ficha: Ficha, config: PipelineConfig,
               decisiones: Decisiones) -> Plan:
    marcados = {paso for paso in PASOS if getattr(config, _MARCA[paso])}
    rehacer = decisiones.rehacer & marcados
    bloqueado = "subtitulos" in marcados and _subs_bloqueados(ficha)
    avisos = [_texto_bloqueado(ficha, paso) for paso in ("subtitulos", "vertical")
              if bloqueado and paso in marcados]

    # 1. Estado objetivo: lo del panel si se pide y falta o se rehace; si no,
    #    lo de la ficha (R1, R6).
    def objetivo(paso: str) -> dict | None:
        hecho = _hecho(ficha, paso)
        pedido = paso in marcados and (hecho is None or paso in rehacer)
        if pedido and not (bloqueado and paso == "subtitulos"):
            return _ajustes(paso, config)
        return hecho

    audio, silencios, subs, encuadre = (
        objetivo(paso) for paso in ("audio", "silencios", "subtitulos", "vertical"))
    efectiva = config
    for paso, ajustes in (("audio", audio), ("silencios", silencios),
                          ("subtitulos", subs), ("vertical", encuadre)):
        if ajustes:  # R8: lo implícito, con los ajustes de la ficha
            efectiva = replace(efectiva, **{
                campo: ajustes[nombre] for nombre, campo in _CAMPOS[paso].items()
                if nombre in ajustes})
    efectiva = replace(efectiva, paso_audio=audio is not None,
                       paso_silencios=silencios is not None,
                       subtitulos=subs is not None)

    # 2. ¿Cambia la base? Rehacer un paso de base invalida lo que depende de ella.
    audio_antes, silencios_antes = _hecho(ficha, "audio"), _hecho(ficha, "silencios")
    base = ficha.artefactos.get(BASE)
    linea_antes = base.linea_tiempo if base is not None else "original"
    base_rehecha = bool(rehacer & set(_DE_BASE))
    cambia_base = (audio != audio_antes or silencios != silencios_antes
                   or base_rehecha)

    subs_antes = _hecho(ficha, "subtitulos")
    transcripcion = _vale(ficha, TRANSCRIPCION)
    # Rehacer los subtítulos solo para cambiar su estilo no vuelve a transcribir.
    solo_estilo = (transcripcion is not None
                   and transcripcion.linea_tiempo == linea_antes
                   and transcripcion.ajustes == ajustes_transcripcion(config)
                   and subs_antes != ajustes_subtitulos(config))
    retranscribir = "subtitulos" in rehacer and not bloqueado and not solo_estilo

    crea_horizontal = not ficha.hay_horizontal() and (
        config.paso_audio or config.paso_silencios
        or (config.subtitulos and not bloqueado and not config.paso_vertical))
    horizontal = ficha.hay_horizontal() or crea_horizontal
    quemar_sin_base_nueva = horizontal and subs is not None and (
        crea_horizontal or subs != subs_antes or retranscribir)

    hay_vertical = _existe(ficha.vertical if ficha.hay_horizontal() else ficha.final)
    r10 = crea_horizontal and hay_vertical  # solo tenía vertical
    vertical = ficha.artefactos.get(VERTICAL)
    subs_vertical = vertical.ajustes.get("subtitulos") if vertical else None

    def genera_vertical(cambia: bool) -> tuple[bool, bool]:
        """(se genera, quedaría desactualizado) — R7, R10."""
        desactualizado = hay_vertical and (
            cambia or subs != subs_vertical
            or (subs is not None and retranscribir))
        pedido = config.paso_vertical and (not hay_vertical or "vertical" in rehacer)
        regenera = desactualizado and (
            decisiones.regenerar_vertical or not horizontal or r10)
        genera = (pedido or regenera) and not (bloqueado and "vertical" in marcados)
        return genera, desactualizado

    genera, desactualizado = genera_vertical(cambia_base)
    # Si falta la base que se va a usar, se rehace desde el original (R0).
    rehace_base = cambia_base or (
        (quemar_sin_base_nueva or genera) and not _base_vale(ficha))

    elegidas: set[Accion] = set()
    usa_fuente = False
    linea = linea_antes
    if rehace_base:
        audio_limpio = _vale(ficha, AUDIO)

        def audio_vale(linea_audio: str) -> bool:
            return (audio_limpio is not None and "audio" not in rehacer
                    and audio_limpio.linea_tiempo == linea_audio
                    and audio_limpio.clave == clave(audio))

        if (audio_antes is None and audio is not None and silencios is not None
                and silencios == silencios_antes and "silencios" not in rehacer
                and _base_vale(ficha)):
            # Caso 8: se limpia el audio de la base ya recortada y se conservan
            # sus cortes, así que la línea de tiempo no cambia.
            if not audio_vale(linea_antes):
                elegidas.add(Accion.LIMPIAR_AUDIO_BASE)
            elegidas.add(Accion.PONER_AUDIO)
        else:
            usa_fuente = True
            if audio is not None and not audio_vale("original"):  # R9
                elegidas.add(Accion.LIMPIAR_AUDIO_ORIGINAL)
            if silencios is None:
                linea = "original"  # y, sin audio, la base es el propio original
                if audio is not None:
                    elegidas.add(Accion.PONER_AUDIO)
            else:
                linea = clave(audio, silencios)
                elegidas.add(Accion.CORTAR)
        if linea != linea_antes:  # una base rehecha por falta de archivo
            genera, desactualizado = genera_vertical(True)

    # 3-5. Transcripción y horizontal.
    transcripcion_vale = (
        transcripcion is not None and transcripcion.linea_tiempo == linea
        and not base_rehecha and not retranscribir
        and transcripcion.ajustes.get("idioma") == efectiva.idioma_subs
        and transcripcion.ajustes.get("modelo_whisper") == efectiva.modelo_whisper)
    quemar = horizontal and subs is not None and (rehace_base or quemar_sin_base_nueva)
    if quemar:
        elegidas.add(Accion.QUEMAR)
    elif horizontal and subs is None and (rehace_base or crea_horizontal):
        elegidas.add(Accion.ESCRIBIR_FINAL)
    if subs is not None and not transcripcion_vale and (quemar or genera):
        elegidas.add(Accion.TRANSCRIBIR)

    # 6. Caption (R4): para él vale cualquier transcripción (R5).
    if config.caption_seo and (_vale(ficha, CAPTION) is None
                               or "caption" in rehacer):
        elegidas.add(Accion.CAPTION)
        if transcripcion is None:
            elegidas.add(Accion.TRANSCRIBIR)

    # 7-8. Vertical y R10.
    if genera:
        elegidas.add(Accion.VERTICAL)
        seguimiento = _vale(ficha, SEGUIMIENTO)
        if efectiva.encuadre == "cara" and (seguimiento is None
                                            or seguimiento.clave != linea):
            elegidas.add(Accion.SEGUIMIENTO)
    if r10:
        elegidas.add(Accion.RETIRAR_VERTICAL_UNICO if genera
                     else Accion.RENOMBRAR_VERTICAL)

    error = ""
    if usa_fuente and not _fuente_vale(ficha):
        fuente = _fuente(ficha)
        error = (_('No encuentro el original de "{nombre}": {ruta}')
                 if fuente is not None
                 else _('No encuentro el original de "{nombre}": arrástralo '
                        'para rehacer el vídeo')).format(
            nombre=ficha.nombre, ruta=fuente.ruta if fuente else "")
    elif (Accion.CAPTION in elegidas and ficha.final is None
          and not elegidas & {Accion.QUEMAR, Accion.ESCRIBIR_FINAL, Accion.VERTICAL}):
        error = _('"{nombre}" aún no tiene vídeo procesado: el caption solo se '
                  'puede pedir sobre un vídeo ya procesado').format(
            nombre=ficha.nombre)

    # 9. Orden: el de la enumeración.
    acciones = [] if error else [accion for accion in Accion if accion in elegidas]
    return Plan(acciones, efectiva, avisos, error,
                marcar_desactualizado=(desactualizado and not genera
                                       and not error))
