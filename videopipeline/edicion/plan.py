"""Plan de edición (plan.json): esquema, lectura/escritura y validación.

Los mensajes de error los lee Haiku: en español, con el índice del momento,
qué falla y qué se permite.
"""
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from videopipeline.edicion import broll, callouts, emojis, graficos, numeros, pantalla as pant, rotulos
from videopipeline.edicion.estilos import Estilo
from videopipeline.edicion.texto import normalizar
from videopipeline.subtitles import Palabra

TIPOS = ("etiqueta", "titulo", "contador", "emoji", "golpe", "error", "transicion", "zoom",
         "senalar", "lupa", "broll", "icono", "dato")
# Duración por defecto (s) de cada tipo; el renderizador (Task 6) usa las mismas.
DURACION = {"etiqueta": 2.2, "titulo": 3.0, "contador": 2.4, "emoji": 1.4,
            "golpe": 1.4, "error": 0.8, "transicion": 0.5,
            "senalar": 2.0, "lupa": 2.6, "broll": broll.DURACION, "icono": 1.6, "dato": 2.4}
DURACION_FINAL = 3.7
TOLERANCIA_PALABRA = 0.4
MAX_CONTADOR = 22
_VISUALES = ("etiqueta", "titulo", "contador", "emoji", "error", "final", "icono", "senalar", "lupa", "dato")
FORMAS = ("circulo", "flecha", "subrayado")
_BUSCAR = re.compile(r"^[A-Za-z][A-Za-z' -]*$")
_LATERALES = ("emoji", "icono")  # conviven en el lateral con lo que ocupa la zona superior
_ZONA_SUP = ("etiqueta", "contador", "lupa", "dato")


@dataclass
class Momento:
    tipo: str
    t: float = 0.0
    palabra: str | None = None
    texto: list[str] | None = None
    emoji: str | None = None
    lista: int | None = None
    num: int | None = None
    t0: float | None = None
    t1: float | None = None
    pantalla: str | None = None
    forma: str | None = None
    buscar: str | None = None
    icono: str | None = None
    valor: float | None = None
    unidad: str | None = None


@dataclass
class Plan:
    momentos: list[Momento]
    final: dict | None = None


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def leer(ruta: Path) -> Plan:
    try:
        datos = json.loads(Path(ruta).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"plan.json no es un JSON válido: {e}")
    if not isinstance(datos, dict) or set(datos) - {"momentos", "final"}:
        raise ValueError("plan.json debe ser un objeto con solo las claves 'momentos' y 'final'")
    crudos = datos.get("momentos", [])
    if not isinstance(crudos, list):
        raise ValueError("'momentos' debe ser una lista")
    campos = set(Momento.__dataclass_fields__)
    momentos = []
    for i, m in enumerate(crudos):
        if not isinstance(m, dict):
            raise ValueError(f"Momento {i}: debe ser un objeto")
        if m.get("tipo") not in TIPOS:
            raise ValueError(f"Momento {i}: tipo {m.get('tipo')!r} desconocido; tipos válidos: {', '.join(TIPOS)}")
        extra = set(m) - campos
        if extra:
            raise ValueError(f"Momento {i}: claves desconocidas {sorted(extra)}; permitidas: {sorted(campos)}")
        for k in ("t", "t0", "t1", "valor"):
            if k in m and m[k] is not None and not _num(m[k]):
                raise ValueError(f"Momento {i}: '{k}' debe ser un número (segundos)")
        for k in ("lista", "num"):
            if k in m and m[k] is not None and (not isinstance(m[k], int) or isinstance(m[k], bool)):
                raise ValueError(f"Momento {i}: '{k}' debe ser un entero")
        for k in ("palabra", "emoji", "pantalla", "forma", "buscar", "icono", "unidad"):
            if k in m and m[k] is not None and not isinstance(m[k], str):
                raise ValueError(f"Momento {i}: '{k}' debe ser un texto")
        tx = m.get("texto")
        if tx is not None and not (isinstance(tx, str) or (isinstance(tx, list) and all(isinstance(x, str) for x in tx))):
            raise ValueError(f"Momento {i}: 'texto' debe ser una lista de textos (o un texto en contador)")
        momentos.append(Momento(**m))
    final = datos.get("final")
    if final is not None:
        if (not isinstance(final, dict) or set(final) - {"texto", "check"}
                or not isinstance(final.get("texto"), list)
                or not all(isinstance(x, str) for x in final["texto"])
                or not isinstance(final.get("check", False), bool)):
            raise ValueError("'final' debe ser {\"texto\": [líneas], \"check\": true|false}")
        final = {"texto": final["texto"], "check": final.get("check", False)}
    return Plan(momentos, final)


def guardar(plan: Plan, ruta: Path) -> None:
    ms = []
    for m in plan.momentos:
        d = {k: v for k, v in asdict(m).items() if v is not None}
        if m.tipo == "zoom":
            d.pop("t", None)
        ms.append(d)
    datos = {"momentos": ms}
    if plan.final is not None:
        datos["final"] = plan.final
    Path(ruta).write_text(json.dumps(datos, ensure_ascii=False, indent=2), "utf-8")


def _malos(texto: str, check: bool) -> str:
    return "".join(dict.fromkeys(c for c in texto if not rotulos.glifos_validos(c, check)))


def _revisar_lineas(lineas, check, grande, estilo, etq: str) -> list[str]:
    if (not isinstance(lineas, list) or not 1 <= len(lineas) <= 2
            or not all(isinstance(l, str) and l.strip() for l in lineas)):
        return [f"{etq}: 'texto' debe ser una lista de 1 o 2 líneas no vacías, p. ej. \"texto\": [\"HOLA\"]"]
    errs = []
    for l in lineas:
        m = _malos(l, check)
        if m:
            errs.append(f"{etq}: la línea {l!r} contiene caracteres no permitidos ({m}); "
                        "solo letras latinas, dígitos y puntuación básica")
    if not errs and not rotulos.cabe(lineas, grande, estilo.paleta):
        errs.append(f"{etq}: el texto {lineas} no cabe en 1080 px; acórtalo o pártelo en más líneas")
    return errs


def _coincidencias_txt(muestras, palabras, t: float) -> str:
    """Las 5 coincidencias más cercanas a t, en orden temporal."""
    cs = sorted(sorted(pant.coincidencias(muestras, palabras), key=lambda c: abs(c.t_palabra - t))[:5],
                key=lambda c: c.t_palabra)
    if not cs:
        return "ahora mismo no hay ninguna coincidencia entre lo dicho y lo visible"
    return "; ".join(f"{c.visible!r} visible en {c.t0:.1f}-{c.t1:.1f} s (palabra {c.palabra!r} en t={c.t_palabra:.2f})"
                     for c in cs)


def _revisar_pantalla(m, etq, pantalla, palabras) -> list[str]:
    if pantalla is None:
        return [f"{etq}: este vídeo no tiene lectura de pantalla; quita el momento"]
    if not m.pantalla or not m.pantalla.strip():
        return [f"{etq}: falta 'pantalla' (el texto que se ve en el vídeo en ese momento)"]
    if m.forma is not None and m.forma not in FORMAS:
        return [f"{etq}: forma {m.forma!r} no válida; permitidas: {', '.join(FORMAS)}"]
    d = pant.buscar(pantalla, m.pantalla, m.t)
    if d is None:
        return [f"{etq}: el texto {m.pantalla!r} no está visible en pantalla en t={m.t:g} (±0.5 s); "
                f"coincidencias disponibles: {_coincidencias_txt(pantalla, palabras, m.t)}"]
    if m.tipo == "lupa" and not callouts.cabe_en_lupa(d.caja):
        return [f"{etq}: el texto {m.pantalla!r} es demasiado ancho para la lupa (no se ampliaría); "
                "usa senalar o un fragmento más corto"]
    return []


def _revisar_dato(m, etq, numeros_) -> list[str]:
    if not _num(m.valor):
        return [f"{etq}: un dato necesita 'valor' (un número dicho en el vídeo), 'texto' (etiqueta, máx. {MAX_CONTADOR}) "
                "y opcionalmente 'unidad': \"%\""]
    cerca = [n for n in numeros_ if abs(n[0] - m.t) <= 1.5]
    hit = next((n for n in cerca if abs(n[1] - m.valor) <= 1e-6), None)
    if hit is None:
        dichos = ", ".join(f"{n[1]:g} (t={n[0]:.2f})" for n in cerca) or "ninguno"
        return [f"{etq}: el valor {m.valor:g} no se dice en ±1.5 s de t={m.t:g}; números dichos ahí: {dichos}"]
    errs = []
    if not isinstance(m.texto, str) or not m.texto.strip():
        errs.append(f"{etq}: 'texto' debe ser una cadena no vacía")
    elif len(m.texto) > MAX_CONTADOR:
        errs.append(f"{etq}: el texto del dato tiene {len(m.texto)} caracteres; máximo {MAX_CONTADOR}")
    elif _malos(m.texto, False):
        errs.append(f"{etq}: el texto {m.texto!r} contiene caracteres no permitidos ({_malos(m.texto, False)})")
    if m.unidad not in (None, "%"):
        errs.append(f"{etq}: unidad {m.unidad!r} no válida; solo se permite \"%\" o nada")
    elif m.unidad == "%" and not hit[3]:
        errs.append(f"{etq}: unidad \"%\" pero el número se dice sin porcentaje; quita 'unidad'")
    return errs


def validar(plan: Plan, palabras: list[Palabra], zonas: dict, estilo: Estilo,
            duracion: float, pantalla: list | None = None,
            broll_disponible: bool = False) -> tuple[Plan, list[str]]:
    errs: list[str] = []
    numeros_ = numeros.numeros_dichos(palabras)
    ventanas = []  # rangos donde la imagen se mueve por un zoom
    if zonas.get("franja_zoom") is not None:
        ventanas = [(z.t0, z.t1) for z in plan.momentos if z.tipo == "zoom" and z.t0 is not None and z.t1 is not None]
        if estilo.zoom_lento > 0:
            ventanas += [(0.0, 5.0), (duracion - 3, duracion)]
    nuevos: list[Momento] = []
    busca = [(normalizar(p.texto), p) for p in palabras]
    hasta = (zonas.get("titulo") or {}).get("hasta")
    for i, m in enumerate(plan.momentos):
        etq = f"Momento {i} ({m.tipo})"
        m = replace(m)
        nuevos.append(m)
        if m.tipo not in estilo.tipos:
            errs.append(f"{etq}: el estilo '{estilo.id}' no permite el tipo '{m.tipo}'; "
                        f"permitidos: {', '.join(sorted(estilo.tipos))}")
            continue
        if m.tipo == "zoom":
            if m.t0 is None or m.t1 is None:
                errs.append(f"{etq}: un zoom necesita 't0' y 't1'")
            elif not (0 <= m.t0 < m.t1 <= duracion):
                errs.append(f"{etq}: zoom con t0={m.t0}, t1={m.t1}; debe cumplirse 0 <= t0 < t1 <= {duracion:g}")
            elif not 1.0 <= m.t1 - m.t0 <= 6.0:
                errs.append(f"{etq}: el zoom dura {m.t1 - m.t0:.2f} s; debe durar entre 1 y 6 s")
            if zonas.get("franja_zoom") is None:
                errs.append(f"{etq}: este vídeo no tiene franja de zoom disponible; quita el zoom")
            continue
        if not 0 <= m.t <= duracion:
            errs.append(f"{etq}: t={m.t} fuera del vídeo; debe estar entre 0 y {duracion:g} s")
            continue
        if m.tipo != "transicion":
            if not m.palabra:
                errs.append(f"{etq}: falta 'palabra' (la palabra del transcript donde cae el momento)")
                continue
            w = normalizar(m.palabra)
            cand = [p for n, p in busca if n == w and w]
            if not cand:
                errs.append(f"{etq}: la palabra {m.palabra!r} no aparece en el transcript")
                continue
            p = min(cand, key=lambda p: abs(p.inicio - m.t))
            if abs(p.inicio - m.t) > TOLERANCIA_PALABRA:
                errs.append(f"{etq}: la palabra {m.palabra!r} está en t={p.inicio:.2f} (la más cercana), "
                            f"no cerca de t={m.t}; ajusta t a ese valor o elige otra palabra")
                continue
            m.t = round(p.inicio, 2)
        if hasta is not None and m.t < hasta and m.tipo != "golpe":
            errs.append(f"{etq}: t={m.t} cae antes de {hasta:g} s, donde está el título del vídeo; "
                        "ahí solo se permiten 'zoom' y 'golpe'")
        if m.tipo in ("etiqueta", "titulo"):
            errs += _revisar_lineas(m.texto, False, m.tipo == "titulo", estilo, etq)
        elif m.tipo == "contador":
            if m.lista not in (1, 2) or m.num is None or not isinstance(m.texto, str) or not m.texto.strip():
                errs.append(f"{etq}: un contador necesita 'lista' (1 o 2), 'num' y 'texto' (una cadena)")
            elif len(m.texto) > MAX_CONTADOR:
                errs.append(f"{etq}: el texto del contador tiene {len(m.texto)} caracteres; máximo {MAX_CONTADOR}")
            elif _malos(m.texto, False):
                errs.append(f"{etq}: el texto {m.texto!r} contiene caracteres no permitidos ({_malos(m.texto, False)})")
        elif m.tipo == "emoji":
            if not m.emoji or not emojis.disponible(m.emoji):
                errs.append(f"{etq}: el emoji {m.emoji!r} no está disponible; usa un emoji común")
        elif m.tipo in ("senalar", "lupa"):
            e = _revisar_pantalla(m, etq, pantalla, palabras)
            errs += e
            if not e:
                m.forma = m.forma or "circulo"
            if any(m.t < v1 and m.t + DURACION[m.tipo] > v0 for v0, v1 in ventanas):
                errs.append(f"{etq}: coincide con un zoom (del plan o automático); el zoom mueve la imagen y "
                            "el señalado no caería sobre el texto; muévelo fuera de los zooms")
        elif m.tipo == "broll":
            if not broll_disponible:
                errs.append(f"{etq}: no hay clave de Pexels configurada; quita el B-roll")
            elif (not m.buscar or not 2 <= len(m.buscar.split()) <= 6 or not _BUSCAR.match(m.buscar)):
                errs.append(f"{etq}: 'buscar' debe ser una búsqueda de 2 a 6 palabras en inglés (solo letras latinas), "
                            "p. ej. \"person typing laptop\"")
        elif m.tipo == "icono":
            if not m.icono or not graficos.icono_disponible(m.icono):
                errs.append(f"{etq}: el icono {m.icono!r} no está disponible; parecidos: "
                            f"{', '.join(graficos.parecidos(m.icono or '')) or 'ninguno'}")
        elif m.tipo == "dato":
            errs += _revisar_dato(m, etq, numeros_)

    max_broll = math.ceil(duracion / 15)
    n_broll = sum(1 for m in plan.momentos if m.tipo == "broll")
    if n_broll > max_broll:
        errs.append(f"Hay {n_broll} B-roll; en {duracion:g} s se permiten como máximo {max_broll}. Quita {n_broll - max_broll}")

    n_dens = sum(1 for m in plan.momentos if m.tipo != "zoom")
    maximo = math.ceil(estilo.densidad_max * duracion)
    if n_dens > maximo:
        errs.append(f"Hay {n_dens} momentos (sin contar zoom); el estilo '{estilo.id}' permite como máximo "
                    f"{maximo} en {duracion:g} s. Quita {n_dens - maximo}")

    if plan.final is not None:
        etq = "Final"
        errs += _revisar_lineas(plan.final["texto"], plan.final["check"], True, estilo, etq)

    # solapes (solo momentos con tiempo ya válido)
    def ok(m): return m.tipo != "zoom" and 0 <= m.t <= duracion
    items = [(i, m.tipo, m.t, m.t + DURACION[m.tipo], m) for i, m in enumerate(nuevos) if m.tipo in DURACION and ok(m)]
    if plan.final is not None:
        items.append(("final", "final", max(0.0, duracion - DURACION_FINAL), duracion, None))
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            ia, ta, sa, ea, ma = items[a]
            ib, tb, sb, eb, mb = items[b]
            sol = min(ea, eb) - max(sa, sb)
            nom = lambda i, t: "el final" if i == "final" else f"el momento {i} ({t})"
            if ta == tb == "transicion":
                if abs(sa - sb) < 1.0:
                    errs.append(f"Momentos {ia} y {ib}: dos transiciones a menos de 1 s; sepáralas")
                continue
            if sol <= 1e-9:
                continue
            if "broll" in (ta, tb):  # el B-roll tapa la pantalla: choca con todo lo visual (y con otro B-roll)
                if (tb if ta == "broll" else ta) not in _VISUALES + ("broll",):
                    continue
                errs.append(f"{nom(ia, ta).capitalize()} y {nom(ib, tb)} coinciden en pantalla "
                            f"({sol:.2f} s de solape); el B-roll tapa la imagen, sepáralos en el tiempo")
                continue
            if ta not in _VISUALES or tb not in _VISUALES:
                continue
            if "senalar" in (ta, tb):  # solo choca con una lupa sobre el mismo texto
                otro, mo = (mb, tb) if ta == "senalar" else (ma, ta)
                ms = ma if ta == "senalar" else mb
                if mo != "lupa" or normalizar(otro.pantalla or "") != normalizar(ms.pantalla or ""):
                    continue
            elif ta != tb and ((ta in _LATERALES and tb in _ZONA_SUP) or (tb in _LATERALES and ta in _ZONA_SUP)):
                continue
            if ta == tb == "contador" and ma.lista == mb.lista and sol <= 0.2 + 1e-9:
                continue
            errs.append(f"{nom(ia, ta).capitalize()} y {nom(ib, tb)} coinciden en la zona superior "
                        f"({sol:.2f} s de solape); sepáralos en el tiempo")

    # zooms solapados
    zs = [(i, m) for i, m in enumerate(nuevos) if m.tipo == "zoom" and m.t0 is not None and m.t1 is not None]
    for a in range(len(zs)):
        for b in range(a + 1, len(zs)):
            if min(zs[a][1].t1, zs[b][1].t1) > max(zs[a][1].t0, zs[b][1].t0):
                errs.append(f"Momentos {zs[a][0]} y {zs[b][0]}: dos zooms solapados; separa sus rangos")

    # contadores consecutivos por lista
    for lista in (1, 2):
        cs = sorted((m for m in nuevos if m.tipo == "contador" and m.lista == lista and m.num is not None),
                    key=lambda m: m.t)
        nums = [m.num for m in cs]
        if nums and nums != list(range(1, len(nums) + 1)):
            errs.append(f"Lista {lista} de contadores: los números en orden temporal son {nums}; "
                        f"deben ser consecutivos desde 1 ({list(range(1, len(nums) + 1))})")
    return Plan(nuevos, plan.final), errs


def _palabras(s: str) -> list[str]:
    return [w for w in (normalizar(x) for x in re.split(r"\W+", s)) if w]


def _repite(a: list[str], b: list[str]) -> bool:
    """Una lista de palabras está dentro de la otra, con palabras enteras y al menos MIN_LETRAS letras."""
    corta, larga = sorted((a, b), key=len)
    return (len("".join(corta)) >= pant.MIN_LETRAS
            and any(larga[i:i + len(corta)] == corta for i in range(len(larga) - len(corta) + 1)))


def sugerencias(plan: Plan, pantalla: list | None) -> list[str]:
    """Avisos que no bloquean: Haiku puede aplicarlos o ignorarlos."""
    sug = []
    for i, m in enumerate(plan.momentos):
        if m.tipo != "etiqueta" or not pantalla or not isinstance(m.texto, list):
            continue
        lineas = [_palabras(l) for l in m.texto] + [_palabras(" ".join(m.texto))]
        ya = [normalizar(o.pantalla or "") for o in plan.momentos if o.tipo in ("senalar", "lupa")
              and o.t < m.t + DURACION["etiqueta"] and m.t < o.t + DURACION[o.tipo]]  # ya señalado a la vez
        for ms in (x for x in pantalla if abs(x.t - m.t) <= 0.5):
            vis = next((d.texto for d in ms.detecciones for l in lineas if _repite(l, _palabras(d.texto))
                        and not any(s and s in normalizar(d.texto) for s in ya)), None)
            if vis:
                sug.append(f"Sugerencia: la etiqueta del momento {i} repite lo que ya se ve en pantalla ({vis!r}); "
                           f"considera un momento 'senalar' con \"pantalla\": {vis!r} en su lugar")
                break
    orden = sorted((m for m in plan.momentos if m.tipo not in ("zoom", "transicion")), key=lambda m: m.t)
    racha = 1
    for a, b in zip(orden, orden[1:]):
        racha = racha + 1 if a.tipo == b.tipo else 1
        if racha == 3:
            sug.append(f"Sugerencia: tres momentos '{b.tipo}' seguidos (el último en t={b.t:g}); "
                       "alterna con otros tipos para dar variedad")
    return sug
