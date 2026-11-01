"""Ejecuta el plan de una pasada sobre la ficha de un vídeo.

Cada acción del plan es un paso. Se trabaja en `ficha.carpeta / "tmp"`, que se
vacía al empezar y se borra al terminar, haya ido bien o mal. Cada salida se
escribe en un temporal y sustituye a la anterior solo cuando está completa, y la
ficha se guarda tras cada acción con lo que terminó, con las claves que espera
`reproceso_plan`. Nunca se sustituye ni se borra un archivo que la ficha no
registra o que ha cambiado fuera de la app.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .config import SAMPLE_RATE_POR_MODELO
from .ficha import (
    AUDIO, BASE, CAPTION, HORIZONTAL, SEGUIMIENTO, TRANSCRIPCION, VERTICAL,
    Artefacto, Ficha, Huella, _escribir_json, guardar, limpiar_temporales,
)
from .i18n import _
from .pipeline import (
    Progreso, _avisar, _emitir, _fase_caption, _fase_vertical, _quemar_subs,
    _transcribir_subs,
)
from .reproceso_plan import (
    Accion, Plan, ajustes_audio, ajustes_caption, ajustes_silencios,
    ajustes_subtitulos, ajustes_transcripcion, ajustes_vertical, clave,
)
from .seguimiento import RUTA_PESOS, preparar_seguimiento
from .steps import (
    BASE_DIR, PasoFallido, a_flac, cortar_silencios, extraer_audio,
    limpiar_audio, rellenar_huecos_audio, remux, resolucion_video,
)
from .subtitles import Palabra, agrupar, generar_srt
from .vertical import es_ya_vertical

FLAC = "audio_limpio.flac"


def ejecutar(ficha: Ficha, plan: Plan, on_progress: Progreso | None = None) -> Path:
    """Ejecuta `plan.acciones` sobre `ficha` y devuelve la salida principal.

    Lanza PasoFallido si falla un paso que no se degrada. Emite
    {"step", "total", "label", "percent"}: un paso por acción.
    """
    if plan.error:
        raise PasoFallido(plan.error)
    pasada = _Pasada(ficha, plan, on_progress)
    ficha.carpeta_salida.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(pasada.tmp, ignore_errors=True)
    pasada.tmp.mkdir(parents=True)
    try:
        for paso, accion in enumerate(plan.acciones, 1):
            getattr(pasada, accion.value)(paso)  # un método por acción
    finally:
        limpiar_temporales(ficha)
    return ficha.final.ruta


def _ajeno(ruta: Path) -> str:
    return _('No se toca "{ruta}": ha cambiado fuera de la app o no lo creó '
             'ella. Muévelo o bórralo y vuelve a procesar.').format(ruta=ruta)


def _oculto(destino: Path) -> Path:
    return destino.with_name(f".{destino.stem}_tmp{destino.suffix}")


def _publicar(origen: Path, destino: Path) -> None:
    """Mueve el temporal `origen` a `destino` por otro oculto a su lado:
    `destino` nunca queda a medias, aunque esté en otro disco."""
    oculto = _oculto(destino)
    try:
        shutil.move(origen, oculto)
        oculto.replace(destino)
    except BaseException:
        oculto.unlink(missing_ok=True)
        raise


def _mover_acompanantes(viejo: Path, nuevo: Path) -> None:
    """R10: el .md y el .srt van junto al nuevo final. Si allí ya hay uno, es
    el que ha escrito esta pasada y el viejo sobra."""
    for sufijo in (".md", ".srt"):
        origen, destino = viejo.with_suffix(sufijo), nuevo.with_suffix(sufijo)
        if not origen.is_file():
            continue
        if destino.exists():
            origen.unlink()
        else:
            shutil.move(origen, destino)


class _Pasada:
    """La base actual y lo que esta pasada aún no ha registrado en la ficha."""

    def __init__(self, ficha: Ficha, plan: Plan, on_progress: Progreso | None):
        self.ficha, self.c, self.on_progress = ficha, plan.config, on_progress
        self.acciones = plan.acciones
        self.marcar_desactualizado = plan.marcar_desactualizado
        self.total = len(plan.acciones)
        self.tmp = ficha.carpeta / "tmp"
        base = ficha.artefactos.get(BASE)
        if base is None:  # sin audio ni silencios, la base es el original
            self.base, self.linea = self.fuente, "original"
        else:
            self.base = ficha.ruta(base.archivo) if base.archivo else ficha.final.ruta
            self.linea = base.linea_tiempo
        if ficha.final is not None and self.base == ficha.final.ruta:
            self._comprobar_propio(self.base)  # nada sale de un final ajeno
        self.base_nueva: Artefacto | None = None  # se registra con su final
        cambia_base = {Accion.CORTAR, Accion.PONER_AUDIO} & set(plan.acciones)
        # Como hoy: si los subtítulos son lo único que cambia, su fallo es el
        # fallo del trabajo.
        self.degradar_subs = bool(cambia_base) or Accion.QUEMAR not in plan.acciones
        self.palabras: list[Palabra] | None = None
        self.transcrito = False
        seguimiento = ficha.artefactos.get(SEGUIMIENTO)
        self.x_cara = seguimiento.ajustes.get("x_inicial") if seguimiento else None
        # El vertical único, por si esta pasada crea el horizontal (R10).
        self.vertical_unico = None if ficha.hay_horizontal() else ficha.final

    @property
    def fuente(self) -> Path:
        """El original o, en una salida antigua sin él, el propio final."""
        return (self.ficha.original or self.ficha.final).ruta

    def _paso(self, paso: int, etiqueta: str, porcentaje: float | None = None) -> None:
        _emitir(self.on_progress, paso, self.total, etiqueta, porcentaje)

    def _comprobar_propio(self, ruta: Path) -> None:
        """Solo se sustituye un archivo que la ficha registra y que no ha
        cambiado desde entonces."""
        if not ruta.exists():
            return
        huellas = [h for h in (self.ficha.final, self.ficha.vertical)
                   if h is not None and h.ruta == ruta.resolve()]
        if not any(h.coincide(ruta) for h in huellas):
            raise PasoFallido(_ajeno(ruta))

    def _palabras(self) -> list[Palabra] | None:
        """Las de esta pasada o, si no se ha transcrito, las de la ficha (el
        planificador ya ha comprobado que valen)."""
        if not self.transcrito:
            self.transcrito = True
            if TRANSCRIPCION in self.ficha.artefactos:
                datos = json.loads(self.ficha.ruta("transcripcion.json")
                                   .read_text(encoding="utf-8"))
                self.palabras = [Palabra(**palabra) for palabra in datos]
        return self.palabras

    # --- La base ------------------------------------------------------------

    def _limpiar_audio(self, paso: int, video: Path, linea: str) -> None:
        c = self.c
        wav, limpio, flac = (self.tmp / nombre for nombre in
                             ("audio_original.wav", "audio_limpio.wav", FLAC))
        self._paso(paso, _("Extrayendo audio"))
        extraer_audio(video, wav, SAMPLE_RATE_POR_MODELO[c.modelo])
        self._paso(paso, _("Limpiando audio")
                   if (BASE_DIR / "checkpoints" / c.modelo).is_dir()
                   else _("Descargando modelo y limpiando audio"))
        limpiar_audio(wav, limpio, c.tarea, c.modelo)
        a_flac(limpio, flac)
        flac.replace(self.ficha.ruta(FLAC))
        ajustes = ajustes_audio(c)
        self.ficha.artefactos[AUDIO] = Artefacto(clave(ajustes), FLAC, ajustes, linea)
        guardar(self.ficha)

    def limpiar_audio_original(self, paso: int) -> None:
        self._limpiar_audio(paso, self.fuente, "original")

    def limpiar_audio_base(self, paso: int) -> None:
        # La base ya recortada conserva sus cortes: su línea de tiempo no cambia.
        self._limpiar_audio(paso, self.base, self.linea)

    def _nueva_base(self, video: Path, linea: str) -> None:
        ajustes = {}
        if self.c.paso_audio:
            ajustes["audio"] = ajustes_audio(self.c)
        if self.c.paso_silencios:
            ajustes["silencios"] = ajustes_silencios(self.c)
        self.base, self.linea = video, linea
        self.base_nueva = Artefacto(clave(ajustes, linea), None, ajustes, linea)

    def poner_audio(self, paso: int) -> None:
        self._paso(paso, _("Sustituyendo pista de audio"))
        audio = self.ficha.artefactos[AUDIO]
        # Sobre el vídeo del que salió ese audio: el original o la base recortada.
        video = self.fuente if audio.linea_tiempo == "original" else self.base
        salida = self.tmp / "base.mp4"
        remux(video, self.ficha.ruta(FLAC), salida)
        self._nueva_base(salida, audio.linea_tiempo)

    def cortar(self, paso: int) -> None:
        c, etiqueta = self.c, _("Recortando silencios")
        self._paso(paso, etiqueta)
        entrada = self.tmp / "entrada.mov"
        if c.paso_audio:
            # PCM intermedio: auto-editor no hereda el retardo de arranque del AAC.
            remux(self.fuente, self.ficha.ruta(FLAC), entrada, intermedio=True)
        else:
            # auto-editor colapsa los huecos del audio del iPhone: se le pasa
            # una copia con los huecos rellenos.
            rellenar_huecos_audio(self.fuente, entrada)
        salida = self.tmp / "base.mp4"
        cortar_silencios(
            entrada, salida, c.margen, c.umbral, c.silencios,
            c.velocidad_silencios,
            on_percent=lambda p: self._paso(paso, etiqueta, p),
            on_aviso=lambda texto: _avisar(self.on_progress, texto),
        )
        entrada.unlink()
        self._nueva_base(salida, clave(ajustes_audio(c) if c.paso_audio else None,
                                       ajustes_silencios(c)))

    # --- Transcripción y horizontal ----------------------------------------

    def transcribir(self, paso: int) -> None:
        c = self.c
        para_subs = (Accion.QUEMAR in self.acciones
                     or (Accion.VERTICAL in self.acciones and c.subtitulos))
        self.transcrito = True
        try:
            # El .srt de la salida lo escribe quien la publica: este va a tmp.
            self.palabras = _transcribir_subs(
                c, self.base, self.tmp / "transcripcion.mp4", self.on_progress,
                paso, self.total, degradar=para_subs and self.degradar_subs,
                wav_continuo=(self.tmp / "subs.wav"
                              if self.base == self.fuente else None),
            )[0]
        except Exception:  # noqa: BLE001 — solo era para el caption: lo reintenta y avisa él
            if para_subs:
                raise
        if self.palabras is None:
            return
        ajustes = ajustes_transcripcion(c)
        _escribir_json(self.ficha.ruta("transcripcion.json"),
                       [asdict(palabra) for palabra in self.palabras])
        self.ficha.artefactos[TRANSCRIPCION] = Artefacto(
            clave(ajustes), "transcripcion.json", ajustes, self.linea)
        guardar(self.ficha)

    def quemar(self, paso: int) -> None:
        c, destino = self.c, self.ficha.ruta_final(True)
        palabras = self._palabras()
        bloques = agrupar(palabras, c.diseno) if palabras else None
        quemado = None
        if bloques:
            quemado = _quemar_subs(
                c, bloques, self.base, destino, self.tmp, self.on_progress, paso,
                self.total, desde_original=self.base == self.fuente,
                degradar=self.degradar_subs)
        if quemado is None:
            if self.base.parent != self.tmp:  # sin base nueva no hay nada que guardar
                raise PasoFallido(
                    _("No se pudieron añadir los subtítulos: la transcripción "
                      "no dio texto que mostrar."))
            # Como hoy: la base nueva se guarda sin subtítulos y con el .srt.
            self.escribir_final(paso)
            if bloques:
                self._escribir_srt(bloques, destino)
            return
        self._sustituir_final(quemado, destino)
        if self.base.parent == self.tmp:  # la base nueva se guarda aparte (R3)
            self.base.replace(self.ficha.ruta("base.mp4"))
            self.base = self.ficha.ruta("base.mp4")
        self._registrar_final(destino, {"subtitulos": ajustes_subtitulos(c)})
        self._escribir_srt(bloques, destino)

    def escribir_final(self, paso: int) -> None:
        self._paso(paso, _("Guardando el vídeo"))
        assert self.base.parent == self.tmp, "solo se mueve una base de esta pasada"
        destino = self.ficha.ruta_final(True)
        self._sustituir_final(self.base, destino)
        self.base = destino
        self._registrar_final(destino, {})
        # Sin subtítulos el final es la base y no se duplica (R3).
        self.ficha.ruta("base.mp4").unlink(missing_ok=True)

    def _sustituir_final(self, nuevo: Path, destino: Path) -> None:
        """`nuevo` pasa a ser el final. Si lo que había en `destino` es lo único
        que queda de algo que la ficha necesita, antes se guarda en ella."""
        ficha = self.ficha
        self._comprobar_propio(destino)
        # Lo que puede fallar (copiar a otro disco) antes de apartar el final:
        # si falla, el final sigue en su sitio y el oculto lo borra la limpieza.
        oculto = _oculto(destino)
        shutil.move(nuevo, oculto)
        if destino.exists() and ficha.original is None:
            # Salida antigua: es su propio original. `legado` sigue en True
            # porque lleva lo que llevara (p. ej. subtítulos quemados).
            guardado = ficha.ruta("original" + destino.suffix)
            shutil.move(destino, guardado)
            ficha.original = Huella.de(guardado)
            if self.base == destino:
                self.base = ficha.original.ruta
            guardar(ficha)
        elif destino.exists() and self.base == destino:
            # El final es la base (R3): se guarda aparte antes de sustituirlo.
            shutil.move(destino, ficha.ruta("base.mp4"))
            self.base = ficha.ruta("base.mp4")
            ficha.artefactos[BASE].archivo = "base.mp4"
            guardar(ficha)
        oculto.replace(destino)

    def _registrar_final(self, destino: Path, ajustes: dict) -> None:
        """El final nuevo y su base en un solo guardado: la ficha nunca describe
        una base que no es la del final que hay en disco."""
        ficha = self.ficha
        base = self.base_nueva or ficha.artefactos.get(BASE)
        if base is not None:
            base.archivo = "base.mp4" if self.base == ficha.ruta("base.mp4") else None
            ficha.artefactos[BASE] = base
        if not ficha.hay_horizontal():
            ficha.vertical = ficha.final  # el vertical único lo acompaña hasta R10
        ficha.final = Huella.de(destino)
        ficha.artefactos[HORIZONTAL] = Artefacto(clave(self.linea, ajustes), None,
                                                 ajustes)
        if self.marcar_desactualizado:
            ficha.desactualizado.add("vertical")
        guardar(ficha)
        self.base_nueva = None

    def _escribir_srt(self, bloques, final: Path) -> None:
        srt = self.tmp / "subs.srt"
        generar_srt(bloques, srt)
        _publicar(srt, final.with_suffix(".srt"))

    # --- Caption y vertical -------------------------------------------------

    def caption(self, paso: int) -> None:
        # Se escribe en tmp: si falla, el caption que había se queda (R1).
        md = self.tmp / "caption.md"
        _fase_caption(self.c, self.base, md.with_suffix(".mp4"), self._palabras(),
                      self.on_progress, paso, self.total)
        if not md.is_file():
            return
        final = self.ficha.ruta_final(self.ficha.hay_horizontal())
        copia = self.tmp / "salida.md"
        shutil.copyfile(md, copia)
        _publicar(copia, final.with_suffix(".md"))
        md.replace(self.ficha.ruta("caption.md"))
        ajustes = ajustes_caption(self.c)
        self.ficha.artefactos[CAPTION] = Artefacto(clave(ajustes), "caption.md",
                                                   {"caption": ajustes})
        guardar(self.ficha)

    def seguimiento(self, paso: int) -> None:
        self._paso(paso, _("Detectando caras") if RUTA_PESOS.is_file()
                   else _("Descargando detector de caras"))
        ancho, alto = resolucion_video(self.base)
        if es_ya_vertical(ancho, alto):
            return  # se reescala con barras: no hay cara que seguir
        comandos = self.tmp / "seguimiento.cmd"
        try:
            self.x_cara = preparar_seguimiento(
                self.base, ancho, alto, comandos,
                on_percent=lambda p: self._paso(paso, _("Detectando caras"), p))
        except Exception as error:  # noqa: BLE001 — degradación deliberada
            self.x_cara = None
            _avisar(self.on_progress,
                    _("No se pudo preparar el detector de caras: {error}. Se usa "
                      "recorte central.").format(error=error))
            return
        if self.x_cara is None:
            _avisar(self.on_progress, _("No se detectó ninguna cara: se usa "
                                        "recorte central."))
            comandos.touch()  # «sin caras» también es un resultado: no se repite
        comandos.replace(self.ficha.ruta("cara.cmd"))
        self.ficha.artefactos[SEGUIMIENTO] = Artefacto(
            self.linea, "cara.cmd", {"x_inicial": self.x_cara})
        guardar(self.ficha)

    def vertical(self, paso: int) -> None:
        ficha, c = self.ficha, self.c
        horizontal = ficha.hay_horizontal()
        destino = ficha.ruta_vertical() if horizontal else ficha.ruta_final(False)
        palabras = self._palabras() if c.subtitulos else None
        bloques = agrupar(palabras, c.diseno) if palabras else None
        # Se convierte en tmp: si falla, el vertical que había se queda.
        salida = self.tmp / "vertical.mp4"
        _fase_vertical(c, self.base, salida, bloques, self.tmp, self.on_progress,
                       paso, self.total, degradar=horizontal,
                       desde_original=self.base == self.fuente,
                       seguimiento=(self.x_cara, ficha.ruta("cara.cmd")))
        if not salida.is_file():
            return
        self._comprobar_propio(destino)
        _publicar(salida, destino)
        if horizontal:
            ficha.vertical = Huella.de(destino)
        else:
            ficha.final = Huella.de(destino)
            if bloques:
                self._escribir_srt(bloques, destino)
        ajustes = {"vertical": ajustes_vertical(c)}
        if bloques:
            ajustes["subtitulos"] = ajustes_subtitulos(c)
        ficha.artefactos[VERTICAL] = Artefacto(clave(self.linea, ajustes), None,
                                               ajustes)
        ficha.desactualizado.discard("vertical")
        guardar(ficha)

    # --- R10 ----------------------------------------------------------------

    def renombrar_vertical(self, paso: int) -> None:
        self._paso(paso, _("Ordenando las salidas"))
        viejo, destino = self.vertical_unico.ruta, self.ficha.ruta_vertical()
        self._comprobar_propio(viejo)
        self._comprobar_propio(destino)
        shutil.move(viejo, destino)  # misma carpeta: se renombra de una vez
        _mover_acompanantes(viejo, self.ficha.final.ruta)
        self.ficha.vertical = Huella.de(destino)
        guardar(self.ficha)

    def retirar_vertical_unico(self, paso: int) -> None:
        if self.ficha.vertical == self.vertical_unico:
            # El vertical nuevo falló: el viejo se queda, con el nombre nuevo (R7).
            self.ficha.desactualizado.add("vertical")
            return self.renombrar_vertical(paso)
        self._paso(paso, _("Ordenando las salidas"))
        viejo = self.vertical_unico
        if viejo.coincide(viejo.ruta):  # solo se borra lo que la ficha registró
            viejo.ruta.unlink()
        elif viejo.ruta.exists():
            _avisar(self.on_progress, _ajeno(viejo.ruta))
        _mover_acompanantes(viejo.ruta, self.ficha.final.ruta)
