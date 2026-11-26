"""Shorts (1:00-2:59) cortados de un vídeo largo a partir de su transcripción.

Flujo: la transcripción por palabras se trocea en frases numeradas; el LLM las
segmenta en temas; los temas (o tramos de temas seguidos) de 60 a 179 s son
candidatos y los más largos se trocean en fragmentos; `tev1` (o el modelo del
caption) los puntúa y se eligen los mejores, repartidos y sin solapes. `crear` corta cada uno de la base
de la ficha y publica la carpeta.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from . import edicion
from .caption import Caption, leer_md, texto_plano
from .config import ENCUADRES, PipelineConfig
from .edicion import entregar, estilos
from .edicion import zonas as zonas_edicion
from .ficha import HORIZONTAL, TRANSCRIPCION, VERTICAL, Ficha, _escribir_json
from .i18n import _
from .ollama import asegurar_servidor, chat_json, descargar, systemone
from .pipeline import Progreso, _avisar, _emitir, _fase_caption, _fase_vertical
from .redes import registro
from .reproceso import _Pasada, ejecutar
from .reproceso_plan import (
    Accion, Plan, _base_vale, _subs_bloqueados, _vale, seguimiento_vale,
)
from .seguimiento import recortar_comandos
from .steps import PasoFallido, duracion_video, resolucion_video
from .subtitles import Palabra, agrupar, generar_srt
from .titulo import generar_titulo
from .vertical import banner_vertical

log = logging.getLogger(__name__)

DURACION_MIN = 60.0
DURACION_MAX = 179.0
UMBRAL_INTERES = 2.0
UMBRAL_INDEPENDIENTE = 0.5
PAUSA_FRASE = 1.0  # s de silencio que cierran una frase sin puntuación
MAX_PALABRAS_FRASE = 60
MARGEN_CORTE = 0.25  # s de aire antes y después del trozo
MINUTOS_VENTANA = 10  # ventana de la segmentación en temas
TEMPERATURA_TEMAS = 0.2
KEEP_ALIVE_SHORTS = "5m"  # el modelo sigue cargado entre las llamadas de un vídeo
MAX_NOMBRE = 60
JUEZ = "tev1:4b-nvfp4"

_PUNTUACION_FINAL = (".", "!", "?", "…")
_CIERRES = "\"'”’»)]}›"  # pueden ir pegados detrás del punto: `."`, `?»`, `!)`
_NO_VALIDOS_EN_NOMBRE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f-\x9f]')

# Por qué se descarta un candidato (`Candidato.descarte`; "" = sigue en pie).
DESCARTES = (
    "fuera_de_rango", "duracion", "repetido", "flojo", "no_se_entiende_solo",
    "solapa", "sobra", "tema_corto",
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
class Tema:
    frase_inicio: int  # de 1 a n, globales, ambas incluidas
    frase_fin: int
    titulo: str
    sigue_al_anterior: bool
    inicio: float = 0.0  # segundos de las frases, sin margen
    fin: float = 0.0


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
    titulo_video: str = ""  # el título quemado en el short, si salió
    origen: str = ""  # "tema" | "tramo" | "fragmento"; "" en shorts.json v1


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
    # Hasta MAX_POR_TRAMO por cada tramo de MINUTOS_TRAMO minutos, contando el
    # último aunque esté incompleto: el tope real es el de cada tramo.
    if duracion < 180:
        return 0
    return MAX_POR_TRAMO * -(-int(duracion) // (MINUTOS_TRAMO * 60))


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
    frases vecinas, y nunca dentro de las del propio short.
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
            # Si Whisper solapa a las vecinas, el corte no entra en las frases
            # del propio short: pisa a la vecina antes que perder palabras.
            primera, ultima = frases[ini - 1], frases[fin - 1]
            c.inicio = min(primera.inicio, max(primera.inicio - MARGEN_CORTE, anterior))
            c.fin = max(ultima.fin, min(ultima.fin + MARGEN_CORTE, siguiente))
    return candidatos


def bloques(temas: list[Tema]) -> list[list[Tema]]:
    """Agrupa temas consecutivos mientras el siguiente siga al anterior."""
    grupos: list[list[Tema]] = []
    for t in temas:
        if grupos and t.sigue_al_anterior:
            grupos[-1].append(t)
        else:
            grupos.append([t])
    return grupos


def candidatos_de_temas(
    temas: list[Tema], frases: list[Frase], duracion: float,
) -> tuple[list[Candidato], list[Tema]]:
    """Candidatos de temas enteros y de tramos de temas seguidos.

    Devuelve `(candidatos, temas_largos)`; los temas de más de DURACION_MAX
    quedan para trocearlos aparte.
    """
    def largo(ini: int, fin: int) -> float:
        return frases[fin - 1].fin - frases[ini - 1].inicio

    entradas: list[dict] = []
    largos: list[Tema] = []
    cubiertos: set[int] = set()  # id() de los temas dentro de algún tramo
    for t in temas:
        d = largo(t.frase_inicio, t.frase_fin)
        if d > DURACION_MAX:
            largos.append(t)
        elif d >= DURACION_MIN:
            entradas.append({"frase_inicio": t.frase_inicio,
                             "frase_fin": t.frase_fin, "titulo": t.titulo})
    for bloque in bloques(temas):
        for i, t in enumerate(bloque):
            mejor = None
            for j in range(i + 1, len(bloque)):
                if DURACION_MIN <= largo(t.frase_inicio, bloque[j].frase_fin) <= DURACION_MAX:
                    mejor = j
            if mejor is not None:
                entradas.append({"frase_inicio": t.frase_inicio,
                                 "frase_fin": bloque[mejor].frase_fin,
                                 "titulo": t.titulo})
                cubiertos.update(id(x) for x in bloque[i:mejor + 1])
    candidatos = validar({"candidatos": entradas}, frases, duracion)
    for c in candidatos:
        tema = any(t.frase_inicio == c.frase_inicio and t.frase_fin == c.frase_fin
                   for t in temas)
        c.origen = "tema" if tema else "tramo"
    for t in temas:
        if id(t) not in cubiertos and largo(t.frase_inicio, t.frase_fin) < DURACION_MIN:
            candidatos.append(Candidato(t.frase_inicio, t.frase_fin, t.titulo, "",
                                        descarte="tema_corto", origen="tema"))
    candidatos.sort(key=lambda c: (c.frase_inicio, c.frase_fin))
    return candidatos, largos


MINUTOS_TRAMO = 10
MAX_POR_TRAMO = 3  # shorts como mucho por cada tramo de MINUTOS_TRAMO minutos
EMPATE_INTERES = 0.3  # diferencia de nota en la que gana el short más largo


def _se_solapan(a: Candidato, b: Candidato) -> bool:
    return a.frase_inicio <= b.frase_fin and b.frase_inicio <= a.frase_fin


def elegir(candidatos: list[Candidato], maximo: int,
           duracion: float) -> list[Candidato]:
    """Los mejores candidatos puntuados, repartidos por el vídeo y sin solapes.

    Primera vuelta: el mejor de cada tramo de `MINUTOS_TRAMO` minutos; segunda,
    el resto por nota, hasta `MAX_POR_TRAMO` por tramo y `maximo` en total. Un
    tramo sin candidatos que pasen la nota se queda sin short. Entre dos que se
    solapan con casi la misma nota gana el más largo. Marca en `descarte` el motivo de los que no entran
    y devuelve los elegidos de mejor a peor. Un candidato sin nota no pasa. Se
    solapan los que comparten alguna frase, no los que solo se tocan por el
    margen del corte.
    """
    vivos = [c for c in candidatos if not c.descarte]
    for c in vivos:
        if (c.interes or 0.0) < UMBRAL_INTERES:
            c.descarte = "flojo"
        elif (c.independiente or 0.0) < UMBRAL_INDEPENDIENTE:
            c.descarte = "no_se_entiende_solo"
    pasan = [c for c in vivos if not c.descarte]
    pasan.sort(key=lambda c: (-c.interes, -c.independiente, c.inicio))
    orden = {id(c): k for k, c in enumerate(pasan)}
    elegidos: list[Candidato] = []
    # Mejor interés de la cadena de reemplazos, para que no se aleje de él más
    # de EMPATE_INTERES.
    techo: dict[int, float] = {}

    def en_tramo(t: int) -> int:
        return sum(1 for e in elegidos if tramo(e) == t)

    def cabe_cambio(c: Candidato, e: Candidato) -> bool:
        # Cambiar `e` por `c` no puede pasar del tope del tramo de `c` ni dejar
        # sin short el tramo de `e`.
        if tramo(c) == tramo(e):
            return True
        return en_tramo(tramo(c)) < MAX_POR_TRAMO and en_tramo(tramo(e)) > 1

    def colocar(c: Candidato, por_tramo: bool = False) -> bool:
        choques = [e for e in elegidos if _se_solapan(c, e)]
        if not choques:
            if por_tramo and en_tramo(tramo(c)) >= MAX_POR_TRAMO:
                c.descarte = "sobra"
                return False
            elegidos.append(c)
            return True
        e = choques[0]
        alto = techo.get(id(e), e.interes)
        if (len(choques) == 1 and alto - c.interes <= EMPATE_INTERES + 1e-9
                and c.fin - c.inicio > e.fin - e.inicio
                and (not por_tramo or cabe_cambio(c, e))):
            elegidos[next(k for k, x in enumerate(elegidos) if x is e)] = c
            techo[id(c)] = alto
            e.descarte = "solapa"
            return True
        c.descarte = "solapa"
        return False

    def tramo(c: Candidato) -> int:
        return int(c.inicio // (MINUTOS_TRAMO * 60))

    for c in pasan:
        # Recalculado cada vez: un reemplazo puede dejar sin short el tramo del
        # sustituido.
        # También puede retar a un elegido de su tramo con el que se solape.
        if (tramo(c) not in {tramo(e) for e in elegidos}
                or any(tramo(e) == tramo(c) and _se_solapan(c, e) for e in elegidos)):
            colocar(c)
    elegidos.sort(key=lambda c: orden[id(c)])
    for c in elegidos[maximo:]:
        c.descarte = "sobra"
    del elegidos[maximo:]
    for c in pasan:
        if c.descarte or any(c is e for e in elegidos):
            continue
        if len(elegidos) >= maximo:
            c.descarte = "sobra"
        else:
            colocar(c, por_tramo=True)
    elegidos.sort(key=lambda c: orden[id(c)])
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

# El interés es la media de estas tres preguntas, cada una de 0 a 4.
PARTES_INTERES = ("gancho", "valor", "publico")
# `tev1` corre con num_ctx 2048 y responde 400 si se pasa: la marca se recorta.
MAX_MARCA = 1500


def _escala(instrucciones: str, niveles: list[str]) -> dict:
    return {"type": "score", "instructions": instrucciones, "criteria": niveles}


def preguntas_juez(marca: str = "") -> dict:
    """Las preguntas al juez; `marca` es el contexto de marca de quien publica."""
    marca = marca.strip()[:MAX_MARCA]
    publico = "¿Cuánto le importa este fragmento al público al que va dirigido el vídeo?"
    if marca:
        publico = ("El canal es de esta marca:\n" + marca + "\n\n¿Cuánto le importa "
                   "este fragmento al público al que se dirige esa marca?")
    return {
        "independiente": {
            "type": "choice",
            "instructions": ("Alguien que no ha visto nada más, ¿entiende de qué se "
                             "habla y qué se concluye?"),
            "criteria": {
                "si": ("El tema se sabe pronto, las referencias se entienden y la "
                       "idea llega a una conclusión."),
                "no": ("Empieza a mitad de conversación, remite a algo no explicado "
                       "o se corta antes de concluir."),
            },
        },
        "gancho": _escala(
            "Mira solo las dos primeras frases. ¿Dan un motivo para seguir viendo?",
            ["Saludo, relleno o frase a medias", "Anuncia el tema sin más",
             "Plantea un tema o pregunta concreta", "Promete algo útil o sorprendente",
             "Abre con un problema, dato u opinión fuerte"]),
        "valor": _escala(
            "¿Qué se lleva quien ve el fragmento entero?",
            ["Nada concreto", "Comentarios generales", "Una idea clara",
             "Un ejemplo, dato o paso que puede aplicar",
             "Un caso real con resultado o varios datos aplicables"]),
        "publico": _escala(
            publico,
            ["Nada", "Poco", "Le suena interesante", "Le afecta de cerca",
             "Resuelve algo que le preocupa ahora"]),
    }


# Juez de respaldo: con gemma4 a temperatura 0 da lo mismo en dos pasadas
# (unos 9 s por trozo). «Se entiende solo» no usa el texto de `tev1`: con él,
# gemma4 rechazaba 3 de 4 trozos que antes aprobaba.
_INDEPENDIENTE_RESERVA = {
    "type": "choice",
    "instructions": "¿Este fragmento de vídeo se entiende solo, sin haber visto el resto del vídeo?",
    "criteria": {"si": "Se entiende solo: tiene contexto, desarrollo y cierre.",
                 "no": "Depende de lo anterior o se corta a medias."},
}


def _system_juez(marca: str) -> str:
    """Las mismas partes del interés y niveles que `tev1`, para no cambiar de escala."""
    lineas = ["Juzgas fragmentos de vídeo para publicarlos como short en redes. "
              "Responde solo JSON con estas claves."]
    preguntas = {**preguntas_juez(marca), "independiente": _INDEPENDIENTE_RESERVA}
    for clave, p in preguntas.items():
        if p["type"] == "choice":
            niveles = "; ".join(f'"{k}": {v}' for k, v in p["criteria"].items())
        else:
            niveles = "; ".join(f"{k}: {v}" for k, v in enumerate(p["criteria"]))
        lineas.append(f"{clave}: {p['instructions']} ({niveles})")
    return "\n".join(lineas)


ESQUEMA_JUEZ = {
    "type": "object",
    "properties": {
        "independiente": {"type": "string", "enum": ["si", "no"]},
        **{parte: {"type": "integer", "minimum": 0, "maximum": 4}
           for parte in PARTES_INTERES},
    },
    "required": ["independiente", *PARTES_INTERES],
}


_SYSTEM_TEMAS = (
    "Eres editor de vídeo. Te doy un trozo de la transcripción de un vídeo largo "
    "en frases numeradas con su segundo de inicio y fin. Devuelve los temas que "
    "EMPIEZAN en este texto: para cada uno, frase_inicio (el número de su primera "
    "frase), un título de 3 a 5 palabras en el idioma de la transcripción y "
    "sigue_al_anterior. Un tema es un asunto que se puede contar entero. "
    "sigue_al_anterior es true si es otro punto de la misma conversación que el "
    "tema anterior y false si cambia de asunto. Responde solo JSON."
)

ESQUEMA_TEMAS = {
    "type": "object",
    "properties": {
        "temas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase_inicio": {"type": "integer"},
                    "titulo": {"type": "string"},
                    "sigue_al_anterior": {"type": "boolean"},
                },
                "required": ["frase_inicio", "titulo", "sigue_al_anterior"],
            },
        },
    },
    "required": ["temas"],
}


def ventana(frases: list[Frase], desde: int) -> int:
    """`hasta` (exclusivo) de la ventana que empieza en `frases[desde]`: las
    frases que acaban como mucho `MINUTOS_VENTANA` minutos después. Al menos una."""
    limite = frases[desde].inicio + MINUTOS_VENTANA * 60
    hasta = desde + 1
    while hasta < len(frases) and frases[hasta].fin <= limite:
        hasta += 1
    return hasta


def construir_mensajes_temas(frases: list[Frase], desde: int, hasta: int
                             ) -> list[dict]:
    lineas = [
        f"[{i}] {f.inicio:.0f}s-{f.fin:.0f}s: {f.texto}"
        for i, f in enumerate(frases[desde:hasta], desde + 1)
    ]
    return [
        {"role": "system", "content": _SYSTEM_TEMAS},
        {"role": "user", "content": "Transcripción:\n" + "\n".join(lineas)},
    ]


def validar_temas(datos: dict, desde: int, hasta: int
                  ) -> list[tuple[int, str, bool]]:
    """`(frase_inicio, título, sigue_al_anterior)` de los temas válidos, con
    inicios en `[desde + 1, hasta]`, crecientes y sin repetir."""
    entradas = datos.get("temas") if isinstance(datos, dict) else None
    if not isinstance(entradas, list):
        raise PasoFallido(
            _("La respuesta del modelo no es válida: faltan los temas"),
            detalle=json.dumps(datos, ensure_ascii=False, default=str)[:2000],
        )
    temas: dict[int, tuple[str, bool]] = {}
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        ini = _entero(entrada.get("frase_inicio"))
        if ini is None or not desde + 1 <= ini <= hasta or ini in temas:
            continue
        temas[ini] = (" ".join(str(entrada.get("titulo") or "").split()),
                      entrada.get("sigue_al_anterior") is True)
    return [(ini, *temas[ini]) for ini in sorted(temas)]


def segmentar(frases: list[Frase], modelo: str,
              on_percent: Callable[[float], None] | None = None) -> list[Tema]:
    """Los temas del vídeo, en ventanas encadenadas de `MINUTOS_VENTANA` minutos.

    Cada ventana vuelve a mirar desde el inicio del último tema, que puede
    seguir; lo que dice la ventana posterior manda. Sin frases, ninguno.
    """
    inicios: dict[int, tuple[str, bool]] = {}  # frase global -> (título, sigue)
    desde = 0
    while desde < len(frases):
        hasta = ventana(frases, desde)
        for intento in (1, 2):
            try:
                datos = chat_json(
                    modelo, construir_mensajes_temas(frases, desde, hasta),
                    ESQUEMA_TEMAS, temperatura=TEMPERATURA_TEMAS,
                    keep_alive=KEEP_ALIVE_SHORTS)
                nuevos = validar_temas(datos, desde, hasta)
                break
            except PasoFallido:
                if intento == 2:
                    raise
        for ini, titulo, sigue in nuevos:
            inicios[ini] = (titulo, sigue)  # la ventana posterior manda
        if on_percent is not None:
            on_percent(100.0 * hasta / len(frases))
        if hasta == len(frases):
            break
        ultimo = max((i for i in inicios if i <= hasta), default=desde + 1)
        # Si el último tema empieza en la primera frase de la ventana (más largo
        # que ella), se sigue por `hasta`: mirar desde su inicio no avanzaría.
        desde = ultimo - 1 if ultimo - 1 > desde else hasta
    if frases:
        inicios.setdefault(1, ("", False))
    orden = sorted(inicios)
    temas = []
    for k, ini in enumerate(orden):
        fin = orden[k + 1] - 1 if k + 1 < len(orden) else len(frases)
        titulo, sigue = inicios[ini]
        temas.append(Tema(ini, fin, titulo, sigue and k > 0,
                          frases[ini - 1].inicio, frases[fin - 1].fin))
    return temas


MAX_FRAGMENTOS_LLAMADA = 3

_SYSTEM_FRAGMENTOS = (
    "Eres editor de vídeo para redes. Te doy un trozo de la transcripción de un "
    "tema largo, en frases numeradas con su segundo de inicio y fin (desde el "
    "principio del tema). Elige hasta {k} fragmentos autocontenidos de 60 a 179 "
    "segundos (fin de la última frase menos inicio de la primera) que no se "
    "solapen entre sí. Que sean los más largos posibles sin dejar la idea a "
    "medias, con gancho al empezar y un cierre claro al acabar. Cada fragmento "
    "empieza al inicio de una frase y acaba al final de otra. Para cada uno da: "
    "frase_inicio y frase_fin (números de frase), un título de 3 a 5 palabras y "
    "una línea con el motivo, en el idioma de la transcripción. Si no hay ninguno "
    "bueno, devuelve la lista vacía. Responde solo JSON."
)


def construir_mensajes_fragmentos(frases: list[Frase], desde: int, hasta: int,
                                  k: int, cero: float) -> list[dict]:
    """Mensajes de la subventana `frases[desde:hasta]`, con los segundos relativos a `cero` (inicio del tema)."""
    lineas = [
        f"[{i}] {f.inicio - cero:.0f}s-{f.fin - cero:.0f}s: {f.texto}"
        for i, f in enumerate(frases[desde:hasta], desde + 1)
    ]
    return [
        {"role": "system", "content": _SYSTEM_FRAGMENTOS.format(k=k)},
        {"role": "user", "content": "Transcripción:\n" + "\n".join(lineas)},
    ]


def fragmentos(tema: Tema, frases: list[Frase], duracion: float, modelo: str,
               on_percent: Callable[[float], None] | None = None) -> list[Candidato]:
    """Los mejores fragmentos autocontenidos de un tema de más de DURACION_MAX.

    Una llamada por subventana del tema; lo que se sale del tema queda como
    `"fuera_de_rango"` y lo de duración mala tiene una sola corrección. Una
    respuesta inválida salta esa subventana en vez de abortar todo.
    """
    fin_tema = tema.frase_fin
    salida: list[Candidato] = []

    def pedir(mensajes: list[dict]) -> tuple[dict, list[Candidato]]:
        datos = chat_json(modelo, mensajes, ESQUEMA_CANDIDATOS,
                          keep_alive=KEEP_ALIVE_SHORTS)
        cs = validar(datos, frases, duracion)
        for c in cs:
            if not (tema.frase_inicio <= c.frase_inicio <= c.frase_fin <= fin_tema):
                c.descarte = "fuera_de_rango"
            c.origen = "fragmento"
        return datos, cs

    desde = tema.frase_inicio - 1
    while desde < fin_tema:
        hasta = min(ventana(frases, desde), fin_tema)
        if hasta < fin_tema and frases[fin_tema - 1].fin - frases[hasta].inicio < DURACION_MIN:
            hasta = fin_tema  # un resto corto no da para un short: va con esta subventana
        dura = frases[hasta - 1].fin - frases[desde].inicio
        k = min(MAX_FRAGMENTOS_LLAMADA, max(1, int(dura // 180)))
        mensajes = construir_mensajes_fragmentos(frases, desde, hasta, k, tema.inicio)
        try:
            datos, cs = pedir(mensajes)
            for c in cs:
                if c.descarte != "duracion":
                    salida.append(c)
                    continue
                s = frases[c.frase_fin - 1].fin - frases[c.frase_inicio - 1].inicio
                correccion = mensajes + [
                    {"role": "assistant",
                     "content": json.dumps(datos, ensure_ascii=False)},
                    {"role": "user", "content": (
                        f"El fragmento {c.frase_inicio}-{c.frase_fin} dura {s:.0f} s: "
                        "ajústalo para que dure entre 60 y 179 s sin dejar la idea a medias")},
                ]
                correccion[0] = {"role": "system",
                                 "content": _SYSTEM_FRAGMENTOS.format(k=1)}
                try:
                    nuevos = [n for n in pedir(correccion)[1] if not n.descarte]
                except PasoFallido:
                    nuevos = []
                salida.append(nuevos[0] if nuevos else c)
        except PasoFallido as e:
            log.warning("Subventana %d-%d de «%s» omitida: %s",
                        desde + 1, hasta, tema.titulo, e)
        if on_percent is not None:
            on_percent(100.0 * (hasta - tema.frase_inicio + 1)
                       / (fin_tema - tema.frase_inicio + 1))
        desde = hasta
    return salida


def _respuesta_invalida(juez: str, datos) -> PasoFallido:
    return PasoFallido(
        _("La respuesta de {juez} no es válida").format(juez=juez),
        detalle=json.dumps(datos, ensure_ascii=False, default=str)[:2000],
    )


def nota_tev1(texto: str, marca: str = "") -> tuple[float, float]:
    """`(probabilidad de que se entienda solo, interés de 0 a 4)` según `tev1`."""
    respuestas = systemone(JUEZ, texto, preguntas_juez(marca))
    try:
        return (float(respuestas["independiente"]["probabilities"]["si"]),
                sum(float(respuestas[p]["score"]) for p in PARTES_INTERES)
                / len(PARTES_INTERES))
    except (KeyError, TypeError, ValueError):
        raise _respuesta_invalida(JUEZ, respuestas) from None


def nota_chat(texto: str, modelo: str, marca: str = "") -> tuple[float, float]:
    """Lo mismo que `nota_tev1` con el modelo del caption: `(1.0 o 0.0, interés)`."""
    datos = chat_json(
        modelo,
        [{"role": "system", "content": _system_juez(marca)},
         {"role": "user", "content": "Fragmento:\n" + texto}],
        ESQUEMA_JUEZ,
        temperatura=0,
        keep_alive=KEEP_ALIVE_SHORTS,
    )
    try:
        return (1.0 if datos["independiente"] == "si" else 0.0,
                sum(min(4.0, max(0.0, float(datos[p]))) for p in PARTES_INTERES)
                / len(PARTES_INTERES))
    except (KeyError, TypeError, ValueError):
        raise _respuesta_invalida(modelo, datos) from None


def puntuar(
    candidatos: list[Candidato],
    frases: list[Frase],
    modelo: str,
    on_aviso: Callable[[str], None],
    on_percent: Callable[[float], None] | None = None,
    marca: str = "",
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
        puntuar_con(lambda texto: nota_tev1(texto, marca))
        return JUEZ
    except PasoFallido as error:
        on_aviso(_("No se pudo usar {juez} para puntuar ({error}): puntúa {modelo}, más despacio.")
                 .format(juez=JUEZ, error=error, modelo=modelo))
    try:
        puntuar_con(lambda texto: nota_chat(texto, modelo, marca))
    except PasoFallido as error:
        raise PasoFallido(
            _("No se pudieron puntuar los trozos: ni {juez} ni {modelo} responden.")
            .format(juez=JUEZ, modelo=modelo),
            detalle=str(error),
        ) from error
    return modelo


@dataclass
class Seleccion:
    temas: list[Tema]
    candidatos: list[Candidato]
    elegidos: list[Candidato]
    juez: str


def seleccionar(
    frases: list[Frase], duracion: float, modelo: str,
    on_aviso: Callable[[str], None],
    avance_temas: Callable[[float], None] | None = None,
    avance_momentos: Callable[[float], None] | None = None,
    avance_notas: Callable[[float], None] | None = None,
    marca: str = "",
) -> Seleccion:
    """Temas, candidatos, notas y elegidos de un vídeo; descarga el modelo al acabar."""
    try:
        temas = segmentar(frases, modelo, avance_temas)
        candidatos, largos = candidatos_de_temas(temas, frases, duracion)
        for k, tema in enumerate(largos):
            def parcial(p: float, k: int = k) -> None:
                if avance_momentos is not None:
                    avance_momentos(100.0 * (k + p / 100) / len(largos))
            candidatos += fragmentos(tema, frases, duracion, modelo, parcial)
        vistos: set[tuple[int, int]] = set()
        for c in candidatos:
            if c.descarte:
                continue
            if (c.frase_inicio, c.frase_fin) in vistos:
                c.descarte = "repetido"
            vistos.add((c.frase_inicio, c.frase_fin))
        juez = puntuar(candidatos, frases, modelo, on_aviso, avance_notas, marca)
        elegidos = elegir(candidatos, maximo_shorts(duracion), duracion)
    finally:
        descargar(modelo)
    return Seleccion(temas, candidatos, elegidos, juez)


def datos_seleccion(sel: Seleccion) -> dict:
    """Lo de `shorts.json` que describe la selección (sin ficha ni archivos)."""
    return {
        "juez": sel.juez,
        "temas": [asdict(t) for t in sel.temas],
        # Los elegidos en orden y luego los demás, con su descarte.
        "candidatos": [asdict(c) for c in
                       sel.elegidos + [c for c in sel.candidatos if c.descarte]],
    }


# --- Generar y publicar la carpeta ------------------------------------------

TMP = ".shorts_tmp"
_SUFIJOS = (".mp4", ".srt", ".md")


@dataclass(frozen=True)
class OpcionesShorts:
    subtitulos: bool = True
    encuadre: str = "cara"
    editar: bool = False
    estilo: str = "divertido"
    banner: Path | None = None  # la imagen que se quema bajo los subtítulos

    @classmethod
    def de_datos(cls, datos: dict) -> OpcionesShorts:
        """Las del JSON del runner. ValueError si el encuadre o el estilo no existen."""
        opciones = cls(bool(datos.get("subtitulos", True)),
                       datos.get("encuadre", "cara"),
                       bool(datos.get("editar", False)),
                       datos.get("estilo", "divertido"),
                       Path(datos["banner"]) if datos.get("banner") else None)
        if opciones.estilo not in estilos.IDS:
            raise ValueError(f"estilo inválido: {opciones.estilo!r} "
                             f"(esperado uno de {estilos.IDS})")
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


@dataclass(frozen=True)
class Corto:
    """Un short ya creado, tal como se ofrece para publicarlo."""
    mp4: Path
    titulo: str
    duracion: float  # s, según el JSON (el vídeo real puede diferir una fracción)
    caption: Caption | None  # `None`: sin `.md`, no se puede publicar
    editado: bool = False  # `mp4` es el `<stem>.editado.mp4`, no el original


def listar(carpeta: Path) -> list[Corto]:
    """Los shorts elegidos de `carpeta/shorts.json`, de mejor a peor, que siguen
    en disco. Un JSON ausente o dañado no lista nada."""
    try:
        candidatos = json.loads((carpeta / "shorts.json").read_text(
            encoding="utf-8"))["candidatos"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    cortos = []
    for c in candidatos if isinstance(candidatos, list) else []:
        try:
            archivo, duracion = c["archivo"], float(c["fin"]) - float(c["inicio"])
            if not archivo or Path(archivo).name != archivo:
                continue
            mp4 = carpeta / archivo
            if mp4.is_file():
                caption = leer_md(mp4.with_suffix(".md"))  # siempre el del original
                editado = mp4.with_name(mp4.stem + ".editado.mp4")
                # nunca el `.tmp`; un editado más viejo que su original es de otro lote
                es_editado = (editado.is_file()
                              and editado.stat().st_mtime >= mp4.stat().st_mtime)
                cortos.append(Corto(editado if es_editado else mp4,
                                    str(c.get("titulo_video") or c.get("titulo") or
                                        mp4.stem), duracion, caption, es_editado))
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return cortos


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


def _anteriores(carpeta: Path, ficha_id: str) -> list[str]:
    """Lo que la app escribió la vez anterior, según su `shorts.json`. Solo
    nombres sueltos: nunca se borra fuera de la carpeta. Dañado, o de otra
    ficha (un registro olvidado, otro vídeo con el mismo nombre), nada."""
    try:
        datos = json.loads((carpeta / "shorts.json").read_text(encoding="utf-8"))
        archivos = datos["archivos"]
        if datos["ficha"] != ficha_id:
            return []
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


def _comprobar_banner(opciones: OpcionesShorts) -> None:
    """PasoFallido si el banner elegido no se puede quemar: antes de empezar,
    no a mitad de los shorts."""
    if opciones.banner is None:
        return
    if not opciones.banner.is_file():
        raise PasoFallido(_('No se encuentra la imagen del banner "{ruta}". '
                            'Elígela otra vez en la sección Shorts.'
                            ).format(ruta=opciones.banner))
    try:
        banner_vertical(opciones.banner, 0)
    except (OSError, ValueError) as error:
        raise PasoFallido(_('No se puede usar "{ruta}" como banner: {error}.'
                            ).format(ruta=opciones.banner.name, error=error)) from error


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
    _comprobar_banner(opciones)
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

    def avance(paso: int, etiqueta: str, ahora: bool = True) -> Callable[[float], None]:
        if ahora:  # los demás anuncian su etiqueta con el primer porcentaje
            _emitir(on_progress, paso, total, etiqueta)
        return lambda p: _emitir(on_progress, paso, total, etiqueta, p)

    servidor = asegurar_servidor()
    try:
        seleccion = seleccionar(
            frases, duracion, config.modelo_caption,
            on_aviso=lambda texto: _avisar(on_progress, texto),
            avance_temas=avance(1, _("Buscando temas")),
            avance_momentos=avance(1, _("Buscando los mejores momentos"), False),
            avance_notas=avance(2, _("Puntuando los trozos"), False),
            marca=config.contexto_marca)
        elegidos = seleccion.elegidos
        # Todo short lleva su título quemado, con o sin el de inicio del panel:
        # el del modelo sobre su trozo o, si falla, el del candidato.
        titulado = avance(2, _("Generando título")) if elegidos else None
        for k, c in enumerate(elegidos, 1):
            tramo = tramo_palabras(palabras, c.inicio, c.fin)
            c.titulo_video = generar_titulo(
                texto_plano(tramo), config.idioma_subs, config.modelo_caption
            ) or c.titulo
            titulado(100.0 * k / len(elegidos))
    finally:
        servidor.cerrar()

    carpeta = carpeta_shorts(ficha)
    if not elegidos:
        _avisar(on_progress, _('Ningún trozo de "{nombre}" es lo bastante bueno '
                               'para un short: no se ha creado ninguno.'
                               ).format(nombre=nombre))
        return Resultado(carpeta, 0)

    anteriores = _anteriores(carpeta, ficha.id)
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
    tramos = {}
    tmp = carpeta / TMP
    comandos = tmp / "tramo.cmd"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for i, (c, stem) in enumerate(zip(elegidos, nombres), 1):
            progreso = _con_etiqueta(on_progress, _("Creando short {n} de {total}")
                                     .format(n=i, total=len(elegidos)))
            tramo = tramo_palabras(palabras, c.inicio, c.fin)
            tramos[stem] = tramo
            bloques = (agrupar(tramo, config.diseno)
                       if opciones.subtitulos and tramo else None)
            seguimiento = None
            if opciones.encuadre == "cara":
                # Siempre con seguimiento: sin él, `_fase_vertical` buscaría la
                # cara en toda la base. Sin uno válido, x None: ventana centrada.
                x0 = None
                if cara is not None:
                    texto, x0 = recortar_comandos(cara, c.inicio, c.fin)
                    comandos.write_text(texto, encoding="utf-8")
                seguimiento = (x0, comandos)
            mp4 = tmp / (stem + ".mp4")
            _fase_vertical(config_vertical, pasada.base, mp4, bloques, tmp, progreso,
                           2 + i, total, degradar=False,
                           desde_original=pasada.base == pasada.fuente,
                           seguimiento=seguimiento, titulo=c.titulo_video,
                           tramo=(c.inicio, c.fin), banner=opciones.banner)
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
            "version": 2, "ficha": ficha.id, "video": nombre, "maximo": maximo,
            "archivos": anteriores + [n for n in nuevos if n not in anteriores],
            **datos_seleccion(seleccion),
        }
        _escribir_json(carpeta / "shorts.json", datos)
        for anterior in anteriores:
            if anterior not in nuevos and (carpeta / anterior).is_file():
                (carpeta / anterior).unlink()
            # Un short nuevo con el mismo nombre no hereda un «ya publicado».
            if anterior.endswith(".mp4"):
                registro.ruta(carpeta / anterior).unlink(missing_ok=True)
                editado = carpeta / (anterior[:-4] + ".editado.mp4")
                editado.unlink(missing_ok=True)
                editado.with_name(editado.name + ".tmp").unlink(missing_ok=True)
        for nuevo in nuevos:
            (tmp / nuevo).replace(carpeta / nuevo)
        _escribir_json(carpeta / "shorts.json", {**datos, "archivos": nuevos})
        if opciones.editar:
            try:  # editar es un extra: nunca hace fallar la creación
                _encolar_edicion(carpeta, nombre, config, opciones, pasada.base,
                                 [(stem, tramos[stem], c.titulo_video)
                                  for c, stem in zip(elegidos, nombres)])
            except Exception as error:  # noqa: BLE001
                log.warning("No se pudieron encolar los shorts para edición: %s", error)
                _avisar(on_progress, _("No se pudieron encolar los shorts para la edición "
                                       "con Claude: {error}").format(error=error))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        with suppress(OSError):
            carpeta.rmdir()  # solo si ha quedado vacía: un primer intento fallido
    return Resultado(carpeta, len(elegidos))


def _encolar_edicion(carpeta: Path, nombre: str, config: PipelineConfig,
                     opciones: OpcionesShorts, base: Path,
                     cortes: list[tuple[str, list[Palabra], str]]) -> list[Path]:
    """Un trabajo de «Editar con Claude» por short (`stem`, sus palabras, su
    título quemado), con las zonas de los subtítulos de los shorts, no los del
    vídeo principal."""
    resolucion = resolucion_video(base)
    config_shorts = replace(config, subtitulos=opciones.subtitulos)
    zonas = {stem: zonas_edicion.calcular(config_shorts, opciones.encuadre, resolucion,
                                          con_titulo=bool(titulo), banner=opciones.banner)
             for stem, _palabras, titulo in cortes}
    return edicion.encolar(carpeta, nombre, [stem for stem, *_resto in cortes],
                           {stem: palabras for stem, palabras, _titulo in cortes},
                           opciones.estilo, zonas, config.idioma_subs, opciones.encuadre,
                           dir_edicion=edicion.DIR_EDICION)


def _ya_en_cola(archivo: Path) -> bool:
    """`archivo` ya espera su edición en `pendientes/`: algún trabajo cuyo origen
    es él y que sigue vigente. Se mira el origen, no el nombre de la carpeta
    (`encolar` añade «-2», «-3»… si el nombre está tomado); uno obsoleto, de un
    original que cambió, no cuenta porque el agente lo va a rechazar."""
    for trabajo in (edicion.DIR_EDICION / "pendientes").glob("*/trabajo.json"):
        if trabajo.parent.name.startswith("."):
            continue
        try:
            datos = json.loads(trabajo.read_text(encoding="utf-8"))
            if datos["origen"] == str(archivo) and entregar.origen_cambiado(datos) is None:
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


def editar_existentes(ficha: Ficha, config: PipelineConfig,
                      opciones: OpcionesShorts) -> int:
    """Botón «Editar con Claude…»: encola para Claude los shorts que ya
    tiene `ficha`, con las palabras de su transcripción, como si se acabaran de
    crear. Los que ya esperan en `pendientes/` no se repiten. Devuelve cuántos
    encola; PasoFallido si no tiene shorts o le falta la transcripción."""
    carpeta = carpeta_shorts(ficha)
    try:
        datos = json.loads((carpeta / "shorts.json").read_text(encoding="utf-8"))
        candidatos = datos["candidatos"] if datos.get("ficha") == ficha.id else []
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        candidatos = []
    creados = [c for c in candidatos if isinstance(c, dict) and c.get("archivo")
               and not c.get("descarte") and Path(c["archivo"]).name == c["archivo"]
               and (carpeta / c["archivo"]).is_file()]
    if not creados:
        raise PasoFallido(_('"{nombre}" no tiene shorts creados que editar.'
                            ).format(nombre=ficha.nombre))
    _comprobar_banner(opciones)
    pasada = _Pasada(ficha, Plan([], config, []), None)
    if not _transcrita(ficha, pasada.linea):
        raise PasoFallido(_('"{nombre}" no tiene la transcripción de sus shorts: '
                            'créalos de nuevo con «Editar con Claude» marcado.'
                            ).format(nombre=ficha.nombre))
    palabras = pasada._palabras() or []
    cortes = []
    for c in creados:
        stem = Path(c["archivo"]).stem
        if _ya_en_cola(carpeta / c["archivo"]):
            continue  # ya espera su edición (p. ej. un doble clic)
        cortes.append((stem, tramo_palabras(palabras, float(c["inicio"]), float(c["fin"])),
                       c.get("titulo_video") or ""))
    if not cortes:
        return 0
    return len(_encolar_edicion(carpeta, ficha.nombre, config, opciones, pasada.base, cortes))


def es_final_vertical(ficha: Ficha) -> bool:
    """El final de `ficha` existe y ya es un vertical de 1080×1920. Nunca lanza."""
    try:
        return (ficha.final is not None and ficha.final.ruta.is_file()
                and resolucion_video(ficha.final.ruta) == (1080, 1920))
    except Exception:  # noqa: BLE001 — ffprobe roto o vídeo ilegible: no lo es
        return False


def editado_al_dia(final: Path) -> Path | None:
    """El `.editado.mp4` de `final` si existe y no es más viejo que él."""
    editado = final.with_name(final.stem + ".editado.mp4")
    if editado.is_file() and editado.stat().st_mtime >= final.stat().st_mtime:
        return editado
    return None


def editar_video(ficha: Ficha, config: PipelineConfig, opciones: OpcionesShorts) -> int:
    """Encola para Claude el final de `ficha` entero (ya vertical 1080×1920),
    con todas las palabras de su transcripción y las zonas de los subtítulos y
    el título que se le quemaron. Devuelve 1 si lo encola y 0 si ya esperaba;
    PasoFallido si no hay final, no es 1080×1920 o falta la transcripción."""
    if ficha.final is None or not ficha.final.ruta.is_file():
        raise PasoFallido(_('"{nombre}" no tiene un vídeo final que editar.'
                            ).format(nombre=ficha.nombre))
    final = ficha.final.ruta
    if not es_final_vertical(ficha):
        raise PasoFallido(_('El vídeo final de "{nombre}" no mide 1080×1920: '
                            'solo se puede editar un vídeo vertical de ese tamaño.'
                            ).format(nombre=ficha.nombre))
    pasada = _Pasada(ficha, Plan([], config, []), None)
    if not _transcrita(ficha, pasada.linea):
        raise PasoFallido(_('"{nombre}" no tiene la transcripción de su vídeo: '
                            'procésalo de nuevo para poder editarlo.'
                            ).format(nombre=ficha.nombre))
    if _ya_en_cola(final):
        return 0  # ya espera su edición (p. ej. un doble clic)
    palabras = pasada._palabras() or []

    horizontal = final != ficha.ruta_final(False)
    artefacto = ficha.artefactos.get(HORIZONTAL if horizontal else VERTICAL)
    ajustes = artefacto.ajustes if artefacto else {}
    subs = ajustes.get("subtitulos") or {}
    campos = {campo: subs[clave] for clave, campo in
              (("diseno", "diseno"), ("posicion", "posicion_subs"),
               ("tamano", "tamano_subs")) if clave in subs}
    config_video = replace(config, subtitulos="subtitulos" in ajustes, **campos)
    if horizontal:  # un vertical hecho aparte: ocupa el marco entero
        encuadre, resolucion = "central", (1080, 1920)
    else:  # el vertical único se recortó de la base con su encuadre
        encuadre = (ajustes.get("vertical") or {}).get("encuadre", "central")
        resolucion = resolucion_video(pasada.base)
    zonas = zonas_edicion.calcular(config_video, encuadre, resolucion,
                                   con_titulo=bool(ajustes.get("titulo")))
    idioma = subs.get("idioma") or config.idioma_subs
    return len(edicion.encolar(
        final.parent, ficha.nombre, [final.stem], {final.stem: palabras},
        opciones.estilo, {final.stem: zonas}, idioma, encuadre,
        dir_edicion=edicion.DIR_EDICION, grupo=str(final)))
