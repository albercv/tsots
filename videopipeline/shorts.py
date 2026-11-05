"""Shorts (1:00-2:59) cortados de un vídeo largo a partir de su transcripción.

Flujo: la transcripción por palabras se trocea en frases numeradas; el LLM
propone trozos como rangos de frases; el código valida esos rangos (existen,
duran entre 60 y 179 s, no se repiten), `tev1` (o el modelo del caption) los
puntúa y se eligen los mejores sin solapes. `crear` corta cada uno de la base
de la ficha y publica la carpeta.
"""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .config import ENCUADRES, PipelineConfig
from .ficha import TRANSCRIPCION, Ficha, _escribir_json
from .i18n import _
from .ollama import asegurar_servidor, chat_json, systemone
from .pipeline import Progreso, _avisar, _emitir, _fase_caption, _fase_vertical
from .reproceso import _Pasada, ejecutar
from .reproceso_plan import (
    Accion, Plan, _base_vale, _subs_bloqueados, _vale, seguimiento_vale,
)
from .seguimiento import recortar_comandos
from .steps import PasoFallido, duracion_video
from .subtitles import Palabra, agrupar, generar_srt

DURACION_MIN = 60.0
DURACION_MAX = 179.0
UMBRAL_INTERES = 2.0
UMBRAL_INDEPENDIENTE = 0.5
PAUSA_FRASE = 1.0  # s de silencio que cierran una frase sin puntuación
MAX_PALABRAS_FRASE = 60
MARGEN_CORTE = 0.25  # s de aire antes y después del trozo
MINUTOS_PARTE = 20
MINUTOS_SOLAPE = 2
MAX_NOMBRE = 60
JUEZ = "tev1:0.8b"

_PUNTUACION_FINAL = (".", "!", "?", "…")
_CIERRES = "\"'”’»)]}›"  # pueden ir pegados detrás del punto: `."`, `?»`, `!)`
_NO_VALIDOS_EN_NOMBRE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f-\x9f]')

# Por qué se descarta un candidato (`Candidato.descarte`; "" = sigue en pie).
DESCARTES = (
    "fuera_de_rango", "duracion", "repetido", "flojo", "no_se_entiende_solo",
    "solapa", "sobra",
)


@dataclass
class Frase:
    palabras: list[Palabra]

    @property
    def inicio(self) -> float:
        return self.palabras[0].inicio

    @property
    def fin(self) -> float:
        return self.palabras[-1].fin

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


@dataclass
class Candidato:
    frase_inicio: int  # de 1 a n, globales
    frase_fin: int
    titulo: str
    motivo: str
    inicio: float = 0.0  # segundos de corte, con margen
    fin: float = 0.0
    independiente: float | None = None  # probabilidad de «se entiende solo»
    interes: float | None = None  # de 0 a 4
    descarte: str = ""
    archivo: str = ""  # nombre del .mp4 si salió


def trocear_frases(palabras: list[Palabra]) -> list[Frase]:
    """Frases por puntuación, por pausa larga o al llegar al tope de palabras.

    Whisper a veces no pone puntos: sin las dos últimas reglas saldría una sola
    frase enorme y no habría dónde cortar.
    """
    frases: list[Frase] = []
    actual: list[Palabra] = []
    for p in palabras:
        if actual and p.inicio - actual[-1].fin > PAUSA_FRASE:
            frases.append(Frase(actual))
            actual = []
        actual.append(p)
        cierra = p.texto.rstrip(_CIERRES).endswith(_PUNTUACION_FINAL)
        if cierra or len(actual) >= MAX_PALABRAS_FRASE:
            frases.append(Frase(actual))
            actual = []
    if actual:
        frases.append(Frase(actual))
    return frases


def maximo_shorts(duracion: float) -> int:
    return int(duracion // 180)


def partes(frases: list[Frase]) -> list[tuple[int, int]]:
    """Rangos `[desde, hasta)` de frases de como mucho `MINUTOS_PARTE` minutos.

    Cada parte empieza `MINUTOS_PARTE - MINUTOS_SOLAPE` minutos después de la
    anterior, para que un trozo cortado por el límite quepa entero en la
    siguiente.
    """
    paso = (MINUTOS_PARTE - MINUTOS_SOLAPE) * 60
    resultado: list[tuple[int, int]] = []
    desde = 0
    while desde < len(frases):
        limite = frases[desde].inicio + MINUTOS_PARTE * 60
        hasta = desde + 1  # una parte nunca está vacía
        while hasta < len(frases) and frases[hasta].fin <= limite:
            hasta += 1
        resultado.append((desde, hasta))
        if hasta == len(frases):
            break
        siguiente = frases[desde].inicio + paso
        desde += 1
        while desde < len(frases) and frases[desde].inicio < siguiente:
            desde += 1
    return resultado


def _entero(valor) -> int | None:
    """Un entero, o el texto de uno ("12"); `None` si no lo es (bool no cuenta)."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str):
        try:
            return int(valor)
        except ValueError:
            return None
    return None


def validar(datos: dict, frases: list[Frase], duracion: float) -> list[Candidato]:
    """Un `Candidato` por entrada válida de `datos["candidatos"]`.

    Los que no valen quedan con su código en `descarte`; a los que valen se
    les calcula el corte (`inicio`/`fin`), con margen pero sin pisar las
    frases vecinas.
    """
    entradas = datos.get("candidatos") if isinstance(datos, dict) else None
    if not isinstance(entradas, list):
        raise PasoFallido(
            _("La respuesta del modelo no es válida: faltan los candidatos"),
            detalle=json.dumps(datos, ensure_ascii=False, default=str)[:2000],
        )
    candidatos: list[Candidato] = []
    vistos: set[tuple[int, int]] = set()
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        ini = _entero(entrada.get("frase_inicio"))
        fin = _entero(entrada.get("frase_fin"))
        if ini is None or fin is None:
            continue
        c = Candidato(
            ini, fin,
            titulo=" ".join(str(entrada.get("titulo") or "").split()),
            motivo=str(entrada.get("motivo") or "").strip(),
        )
        candidatos.append(c)
        if not 1 <= ini <= fin <= len(frases):
            c.descarte = "fuera_de_rango"
            continue
        largo = frases[fin - 1].fin - frases[ini - 1].inicio
        if not DURACION_MIN <= largo <= DURACION_MAX:
            c.descarte = "duracion"
        elif (ini, fin) in vistos:
            c.descarte = "repetido"
        else:
            vistos.add((ini, fin))
            anterior = frases[ini - 2].fin if ini > 1 else 0.0
            siguiente = frases[fin].inicio if fin < len(frases) else duracion
            c.inicio = max(frases[ini - 1].inicio - MARGEN_CORTE, anterior)
            c.fin = min(frases[fin - 1].fin + MARGEN_CORTE, siguiente)
    return candidatos


def elegir(candidatos: list[Candidato], maximo: int) -> list[Candidato]:
    """Los mejores candidatos puntuados, sin solapes y como mucho `maximo`.

    Marca en `descarte` el motivo de los que no entran y devuelve los elegidos
    de mejor a peor. Un candidato sin nota no pasa. Se solapan los que
    comparten alguna frase, no los que solo se tocan por el margen del corte.
    """
    vivos = [c for c in candidatos if not c.descarte]
    for c in vivos:
        if (c.interes or 0.0) < UMBRAL_INTERES:
            c.descarte = "flojo"
        elif (c.independiente or 0.0) < UMBRAL_INDEPENDIENTE:
            c.descarte = "no_se_entiende_solo"
    pasan = [c for c in vivos if not c.descarte]
    pasan.sort(key=lambda c: (-c.interes, -c.independiente, c.inicio))
    elegidos: list[Candidato] = []
    for c in pasan:
        if any(c.frase_inicio <= e.frase_fin and e.frase_inicio <= c.frase_fin
               for e in elegidos):
            c.descarte = "solapa"
        elif len(elegidos) >= maximo:
            c.descarte = "sobra"
        else:
            elegidos.append(c)
    return elegidos


def nombre_archivo(numero: int, titulo: str) -> str:
    """`"03 - Título limpio"`, sin extensión y válido como nombre de archivo."""
    limpio = " ".join(_NO_VALIDOS_EN_NOMBRE.sub(" ", titulo).split())
    limpio = limpio.strip(". ")[:MAX_NOMBRE].rstrip(". ")
    return f"{numero:02d} - {limpio or 'Short'}"


def tramo_palabras(palabras: list[Palabra], inicio: float, fin: float) -> list[Palabra]:
    """Copias de las palabras de `[inicio, fin]`, con los tiempos desde 0."""
    return [
        Palabra(p.texto, p.inicio - inicio, p.fin - inicio)
        for p in palabras if inicio <= p.inicio and p.fin <= fin
    ]


_SYSTEM_CANDIDATOS = (
    "Eres editor de vídeo para redes. Te doy la transcripción de un vídeo largo "
    "en frases numeradas con su segundo de inicio y fin. Elige hasta {n} "
    "fragmentos que funcionen como short independiente: que se entiendan sin el "
    "resto del vídeo, con gancho al empezar y un cierre claro. Cada fragmento "
    "empieza al inicio de una frase y acaba al final de otra, y dura entre 60 y "
    "179 segundos (fin de la última menos inicio de la primera). Para cada uno "
    "da: frase_inicio y frase_fin (números de frase), un título de 3 a 5 "
    "palabras y una línea con el motivo, en el idioma de la transcripción. Si no "
    "hay ninguno bueno, devuelve la lista vacía. Responde solo JSON."
)

ESQUEMA_CANDIDATOS = {
    "type": "object",
    "properties": {
        "candidatos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase_inicio": {"type": "integer"},
                    "frase_fin": {"type": "integer"},
                    "titulo": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["frase_inicio", "frase_fin", "titulo", "motivo"],
            },
        },
    },
    "required": ["candidatos"],
}

# Preguntas de `tev1` (probadas con Ollama 0.40.14: unos 0,15 s por trozo).
PREGUNTAS = {
    "independiente": {
        "type": "choice",
        "instructions": "¿Este fragmento de vídeo se entiende solo, sin haber visto el resto del vídeo?",
        "criteria": {"si": "Se entiende solo: tiene contexto, desarrollo y cierre.",
                     "no": "Depende de lo anterior o se corta a medias."},
    },
    "interes": {
        "type": "score",
        "instructions": "¿Cuánto engancharía este fragmento como short en redes sociales?",
        "criteria": ["Aburrido o sin valor", "Flojo", "Correcto", "Interesante",
                     "Muy enganchante"],
    },
}

# Juez de respaldo: con gemma4 a temperatura 0 da lo mismo en dos pasadas
# (unos 9 s por trozo).
_SYSTEM_JUEZ = (
    "Juzgas fragmentos de vídeo para publicarlos como short en redes. Responde "
    "solo JSON con: independiente: \"si\" si se entiende solo, sin haber visto "
    "el resto del vídeo (tiene contexto, desarrollo y cierre), o \"no\" si "
    "depende de lo anterior o se corta a medias; interes: de 0 a 4, cuánto "
    "engancharía como short (0 aburrido o sin valor, 1 flojo, 2 correcto, "
    "3 interesante, 4 muy enganchante)."
)

ESQUEMA_JUEZ = {
    "type": "object",
    "properties": {
        "independiente": {"type": "string", "enum": ["si", "no"]},
        "interes": {"type": "integer", "minimum": 0, "maximum": 4},
    },
    "required": ["independiente", "interes"],
}


def construir_mensajes(frases: list[Frase], desde: int, hasta: int, n: int
                       ) -> list[dict]:
    """Mensajes para pedir hasta `n` candidatos entre `frases[desde:hasta]`.

    Las frases se numeran con su número global, el que luego se valida.
    """
    lineas = [
        f"[{i}] {f.inicio:.0f}s-{f.fin:.0f}s: {f.texto}"
        for i, f in enumerate(frases[desde:hasta], desde + 1)
    ]
    return [
        {"role": "system", "content": _SYSTEM_CANDIDATOS.format(n=n)},
        {"role": "user", "content": "Transcripción:\n" + "\n".join(lineas)},
    ]


def buscar_candidatos(
    frases: list[Frase],
    duracion: float,
    maximo: int,
    modelo: str,
    on_percent: Callable[[float], None] | None = None,
) -> list[Candidato]:
    """Candidatos validados de todas las partes; sin frases, ninguno.

    Una llamada por parte, pidiendo `2 × maximo` repartidos según lo que dura
    la parte. Un trozo que dos partes proponen igual queda una vez y la otra
    como `"repetido"`.
    """
    por_partes = partes(frases)
    candidatos: list[Candidato] = []
    vistos: set[tuple[int, int]] = set()
    for k, (desde, hasta) in enumerate(por_partes, 1):
        dura = frases[hasta - 1].fin - frases[desde].inicio
        n = max(2, round(2 * maximo * dura / duracion))
        datos = chat_json(modelo, construir_mensajes(frases, desde, hasta, n),
                          ESQUEMA_CANDIDATOS)
        for c in validar(datos, frases, duracion):
            if not c.descarte:
                if (c.frase_inicio, c.frase_fin) in vistos:
                    c.descarte = "repetido"
                vistos.add((c.frase_inicio, c.frase_fin))
            candidatos.append(c)
        if on_percent is not None:
            on_percent(100.0 * k / len(por_partes))
    return candidatos


def _respuesta_invalida(juez: str, datos) -> PasoFallido:
    return PasoFallido(
        _("La respuesta de {juez} no es válida").format(juez=juez),
        detalle=json.dumps(datos, ensure_ascii=False, default=str)[:2000],
    )


def nota_tev1(texto: str) -> tuple[float, float]:
    """`(probabilidad de que se entienda solo, interés de 0 a 4)` según `tev1`."""
    respuestas = systemone(JUEZ, texto, PREGUNTAS)
    try:
        return (float(respuestas["independiente"]["probabilities"]["si"]),
                float(respuestas["interes"]["score"]))
    except (KeyError, TypeError, ValueError):
        raise _respuesta_invalida(JUEZ, respuestas) from None


def nota_chat(texto: str, modelo: str) -> tuple[float, float]:
    """Lo mismo que `nota_tev1` con el modelo del caption: `(1.0 o 0.0, interés)`."""
    datos = chat_json(
        modelo,
        [{"role": "system", "content": _SYSTEM_JUEZ},
         {"role": "user", "content": "Fragmento:\n" + texto}],
        ESQUEMA_JUEZ,
        temperatura=0,
    )
    try:
        return (1.0 if datos["independiente"] == "si" else 0.0,
                min(4.0, max(0.0, float(datos["interes"]))))
    except (KeyError, TypeError, ValueError):
        raise _respuesta_invalida(modelo, datos) from None


def puntuar(
    candidatos: list[Candidato],
    frases: list[Frase],
    modelo: str,
    on_aviso: Callable[[str], None],
    on_percent: Callable[[float], None] | None = None,
) -> str:
    """Rellena `independiente` e `interes` de los candidatos en pie.

    Usa `tev1`; si falla, puntúa todos de nuevo con `modelo` (así no se mezclan
    dos escalas) y avisa. Devuelve el nombre del juez que puntuó.
    """
    vivos = [c for c in candidatos if not c.descarte]
    textos = [" ".join(f.texto for f in frases[c.frase_inicio - 1:c.frase_fin])
              for c in vivos]

    def puntuar_con(nota: Callable[[str], tuple[float, float]]) -> None:
        for k, (c, texto) in enumerate(zip(vivos, textos), 1):
            c.independiente, c.interes = nota(texto)
            if on_percent is not None:
                on_percent(100.0 * k / len(vivos))

    try:
        puntuar_con(nota_tev1)
        return JUEZ
    except PasoFallido as error:
        on_aviso(_("No se pudo usar {juez} para puntuar ({error}): puntúa {modelo}, más despacio.")
                 .format(juez=JUEZ, error=error, modelo=modelo))
    try:
        puntuar_con(lambda texto: nota_chat(texto, modelo))
    except PasoFallido as error:
        raise PasoFallido(
            _("No se pudieron puntuar los trozos: ni {juez} ni {modelo} responden.")
            .format(juez=JUEZ, modelo=modelo),
            detalle=str(error),
        ) from error
    return modelo


# --- Generar y publicar la carpeta ------------------------------------------

TMP = ".shorts_tmp"
_SUFIJOS = (".mp4", ".srt", ".md")


@dataclass(frozen=True)
class OpcionesShorts:
    subtitulos: bool = True
    encuadre: str = "cara"

    @classmethod
    def de_datos(cls, datos: dict) -> OpcionesShorts:
        """Las del JSON del runner. ValueError si el encuadre no existe."""
        opciones = cls(bool(datos.get("subtitulos", True)),
                       datos.get("encuadre", "cara"))
        if opciones.encuadre not in ENCUADRES:
            raise ValueError(f"encuadre inválido: {opciones.encuadre!r} "
                             f"(esperado uno de {ENCUADRES})")
        return opciones


@dataclass(frozen=True)
class Resultado:
    carpeta: Path
    n: int  # shorts creados


def carpeta_shorts(ficha: Ficha) -> Path:
    return ficha.carpeta_salida / ficha.nombre


def hay_shorts(ficha: Ficha) -> bool:
    return (carpeta_shorts(ficha) / "shorts.json").is_file()


def limpiar_temporal(ficha: Ficha) -> None:
    carpeta = carpeta_shorts(ficha)
    shutil.rmtree(carpeta / TMP, ignore_errors=True)
    # Cancelar mata al runner antes de su `finally`: una primera pasada
    # cancelada dejaría la carpeta vacía. `rmdir` nunca quita una con algo.
    with suppress(OSError):
        carpeta.rmdir()


def _transcrita(ficha: Ficha, linea: str) -> bool:
    transcripcion = _vale(ficha, TRANSCRIPCION)
    return transcripcion is not None and transcripcion.linea_tiempo == linea


def _anteriores(carpeta: Path) -> list[str]:
    """Lo que la app escribió la vez anterior, según su `shorts.json`. Solo
    nombres sueltos: nunca se borra fuera de la carpeta. Dañado, nada."""
    try:
        archivos = json.loads(
            (carpeta / "shorts.json").read_text(encoding="utf-8"))["archivos"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if not isinstance(archivos, list):
        return []
    return [n for n in archivos if isinstance(n, str)
            and n not in ("", ".", "..") and Path(n).name == n]


def _con_etiqueta(on_progress: Progreso | None, etiqueta: str) -> Progreso | None:
    """`on_progress` con `etiqueta` en los eventos de paso; los avisos, tal cual."""
    if on_progress is None:
        return None
    return lambda evento: on_progress(
        {**evento, "label": etiqueta} if "step" in evento else evento)


def crear(ficha: Ficha, config: PipelineConfig, opciones: OpcionesShorts,
          on_progress: Progreso | None = None) -> Resultado:
    """Saca los shorts de `ficha` a `carpeta_shorts(ficha)`; PasoFallido si no.

    Antes transcribe la base o sigue la cara si hace falta, y lo registra en la
    ficha. Los shorts se generan en `TMP` y solo si salen todos sustituyen a los
    anteriores: de la carpeta solo se borra lo que lista su `shorts.json`, y no
    se pisa nada más.
    """
    nombre = ficha.nombre
    if ficha.final is None:
        raise PasoFallido(_('"{nombre}" aún no tiene vídeo procesado del que '
                            'sacar shorts.').format(nombre=nombre))
    if _subs_bloqueados(ficha):
        raise PasoFallido(_(
            '"{nombre}" lleva los subtítulos quemados y no hay una versión sin '
            'ellos de la que cortar los shorts. Arrastra el original y vuelve a '
            'procesarlo.').format(nombre=nombre))
    if not _base_vale(ficha):
        raise PasoFallido(_('La versión sin subtítulos de "{nombre}" ya no está. '
                            'Vuelve a procesarlo para sacar shorts.'
                            ).format(nombre=nombre))
    pasada = _Pasada(ficha, Plan([], config, []), on_progress)
    # Antes de transcribir o seguir la cara, que no cambian la base.
    duracion = duracion_video(pasada.base)
    maximo = maximo_shorts(duracion)
    if maximo == 0:
        raise PasoFallido(_('"{nombre}" dura menos de 3 minutos: es demasiado '
                            'corto para sacar shorts.').format(nombre=nombre))
    sin_transcripcion = _('No se pudo transcribir "{nombre}": sin transcripción '
                          'no se pueden buscar shorts.').format(nombre=nombre)
    acciones = []
    if not _transcrita(ficha, pasada.linea):
        acciones.append(Accion.TRANSCRIBIR)
    if opciones.encuadre == "cara" and not seguimiento_vale(ficha, pasada.linea):
        acciones.append(Accion.SEGUIMIENTO)
    if acciones:
        try:
            ejecutar(ficha, Plan(acciones, config, []), on_progress)
        except Exception as error:
            if _transcrita(ficha, pasada.linea):
                raise  # falló el seguimiento, no la transcripción
            detalle = f"{error}\n{getattr(error, 'detalle', '')}".strip()
            raise PasoFallido(sin_transcripcion, detalle=detalle) from error
        pasada = _Pasada(ficha, Plan([], config, []), on_progress)
    # Por si `_Pasada.transcribir` acaba sin palabras y sin lanzar nada.
    if not _transcrita(ficha, pasada.linea):
        raise PasoFallido(sin_transcripcion)
    palabras = pasada._palabras()
    frases = trocear_frases(palabras)
    total = 2 + maximo

    def avance(paso: int, etiqueta: str) -> Callable[[float], None]:
        _emitir(on_progress, paso, total, etiqueta)
        return lambda p: _emitir(on_progress, paso, total, etiqueta, p)

    servidor = asegurar_servidor()
    try:
        candidatos = buscar_candidatos(
            frases, duracion, maximo, config.modelo_caption,
            avance(1, _("Buscando trozos para shorts")))
        juez = puntuar(candidatos, frases, config.modelo_caption,
                       on_aviso=lambda texto: _avisar(on_progress, texto),
                       on_percent=avance(2, _("Puntuando los trozos")))
    finally:
        servidor.cerrar()

    elegidos = elegir(candidatos, maximo)
    carpeta = carpeta_shorts(ficha)
    if not elegidos:
        _avisar(on_progress, _('Ningún trozo de "{nombre}" es lo bastante bueno '
                               'para un short: no se ha creado ninguno.'
                               ).format(nombre=nombre))
        return Resultado(carpeta, 0)

    anteriores = _anteriores(carpeta)
    nombres = [nombre_archivo(i, c.titulo) for i, c in enumerate(elegidos, 1)]
    for c, stem in zip(elegidos, nombres):
        c.archivo = stem + ".mp4"
        for sufijo in _SUFIJOS:
            ruta = carpeta / (stem + sufijo)
            if ruta.exists() and ruta.name not in anteriores:
                raise PasoFallido(_(
                    'No se toca "{ruta}": no lo creó la app. Muévelo o bórralo y '
                    'vuelve a crear los shorts.').format(ruta=ruta))

    cara = (ficha.ruta("cara.cmd").read_text(encoding="utf-8")
            if opciones.encuadre == "cara" and seguimiento_vale(ficha, pasada.linea)
            else None)
    config_vertical = replace(config, encuadre=opciones.encuadre)
    total = 2 + len(elegidos)
    tmp = carpeta / TMP
    comandos = tmp / "tramo.cmd"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for i, (c, stem) in enumerate(zip(elegidos, nombres), 1):
            progreso = _con_etiqueta(on_progress, _("Creando short {n} de {total}")
                                     .format(n=i, total=len(elegidos)))
            tramo = tramo_palabras(palabras, c.inicio, c.fin)
            bloques = (agrupar(tramo, config.diseno)
                       if opciones.subtitulos and tramo else None)
            seguimiento = None
            if opciones.encuadre == "cara":
                # Siempre con seguimiento: sin él, `_fase_vertical` buscaría la
                # cara en toda la base. Sin uno válido, x None: recorte central.
                x0 = None
                if cara is not None:
                    texto, x0 = recortar_comandos(cara, c.inicio, c.fin)
                    comandos.write_text(texto, encoding="utf-8")
                seguimiento = (x0, comandos)
            mp4 = tmp / (stem + ".mp4")
            _fase_vertical(config_vertical, pasada.base, mp4, bloques, tmp, progreso,
                           2 + i, total, degradar=False,
                           desde_original=pasada.base == pasada.fuente,
                           seguimiento=seguimiento, tramo=(c.inicio, c.fin))
            if bloques:
                generar_srt(bloques, mp4.with_suffix(".srt"))
            if config.caption_seo:  # escribe el .md o deja su propio aviso
                _fase_caption(config, mp4, mp4, tramo, progreso, 2 + i, total)

        # Todos han salido: sustituyen a los anteriores. El JSON lista antes
        # los viejos y los nuevos, para que un corte a medias no deje en la
        # carpeta archivos de la app que no lista.
        nuevos = [stem + sufijo for stem in nombres for sufijo in _SUFIJOS
                  if (tmp / (stem + sufijo)).is_file()]
        datos = {
            "version": 1, "video": nombre, "juez": juez, "maximo": maximo,
            "archivos": anteriores + [n for n in nuevos if n not in anteriores],
            # Los elegidos en orden y luego los demás, con su descarte.
            "candidatos": [asdict(c) for c in
                           elegidos + [c for c in candidatos if c.descarte]],
        }
        _escribir_json(carpeta / "shorts.json", datos)
        for anterior in anteriores:
            if anterior not in nuevos and (carpeta / anterior).is_file():
                (carpeta / anterior).unlink()
        for nuevo in nuevos:
            (tmp / nuevo).replace(carpeta / nuevo)
        _escribir_json(carpeta / "shorts.json", {**datos, "archivos": nuevos})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        with suppress(OSError):
            carpeta.rmdir()  # solo si ha quedado vacía: un primer intento fallido
    return Resultado(carpeta, len(elegidos))
