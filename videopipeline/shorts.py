"""Shorts (1:00-2:59) cortados de un vídeo largo a partir de su transcripción.

Flujo: la transcripción por palabras se trocea en frases numeradas; el LLM
propone trozos como rangos de frases; el código valida esos rangos (existen,
duran entre 60 y 179 s, no se repiten), `tev1` (o el modelo del caption) los
puntúa y se eligen los mejores sin solapes. La generación va aparte.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from .i18n import _
from .ollama import chat_json, systemone
from .steps import PasoFallido
from .subtitles import Palabra

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
