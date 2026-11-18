"""Números dichos en la transcripción: cifras y palabras en español."""
import re

from videopipeline.subtitles import Palabra

_UNIDADES = {"cero": 0, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
             "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
             "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
             "diecinueve": 19, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
             "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
             "mil": 1000, "un": 1,
             "doscientos": 200, "trescientos": 300, "cuatrocientos": 400, "quinientos": 500,
             "seiscientos": 600, "setecientos": 700, "ochocientos": 800, "novecientos": 900}
_DECENAS = {"veinti": 20}
_CIFRA = re.compile(r"^\d{1,3}(\.\d{3})+$|^\d+(,\d+)?$")


def _sin_tilde(s: str) -> str:
    return s.translate(str.maketrans("áéíóú", "aeiou"))


def valor_de(palabra: str) -> float | None:
    """Valor numérico de una palabra ('1.000', '3,5', '20%', 'veintiuno', 'mil') o None."""
    p = _sin_tilde(palabra.strip().lower().rstrip(".,;:!?"))
    p = p.removesuffix("%")
    if _CIFRA.match(p):
        return float(p.replace(".", "").replace(",", ".")) if "," in p or "." in p else int(p)
    if p in _UNIDADES:
        return _UNIDADES[p]
    # shortcut: solo compuestos 'veinti…' en una palabra; 'treinta y cinco' no se une, ampliar si hace falta
    if p.startswith("veinti") and p[6:] in _UNIDADES and 0 < _UNIDADES[p[6:]] < 10:
        return 20 + _UNIDADES[p[6:]]
    return None


def _limpia(t: str) -> str:
    return _sin_tilde(t.lower().strip(".,;:!?"))


def _compuesto(toks: list[str]) -> tuple[float, int] | None:
    """Pliega palabras sueltas ('tres mil quinientos', 'treinta y cinco') en (valor, nº de palabras)."""
    total, cur, n, mil = 0, 0, 0, False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "y" and n and 30 <= cur % 100 and cur % 10 == 0 and i + 1 < len(toks) \
                and toks[i + 1] in _UNIDADES and 0 < _UNIDADES[toks[i + 1]] < 10:
            i += 1
            continue
        v = valor_de(t)
        if v is None or v == 0 and n or not float(v).is_integer() or t.isdigit():
            break
        v = int(v)
        if t == "mil":
            if mil:
                break
            total, cur, mil = total + (cur or 1) * 1000, 0, True
        elif v >= 100:
            if cur:
                break
            cur = v
        elif v >= 10:
            if cur % 100:
                break
            cur += v
        elif cur % 100 and not (cur % 100 >= 30 and cur % 10 == 0 and toks[i - 1] == "y"):
            break
        else:
            cur += v
        n = i + 1
        i += 1
    return (total + cur, n) if n else None


def numeros_dichos(palabras: list[Palabra]) -> list[tuple[float, float, str, bool]]:
    """(t, valor, palabra, es_porcentaje); un número hablado compuesto da una sola entrada."""
    sal, i = [], 0
    while i < len(palabras):
        w = palabras[i]
        toks = [_limpia(x.texto) for x in palabras[i:i + 6]]
        if valor_de(w.texto) is not None and not toks[0].replace(".", "").replace(",", "").removesuffix("%").isdigit():
            v, n = _compuesto(toks) or (valor_de(w.texto), 1)
        else:
            v, n = valor_de(w.texto), 1
        if v is None or (i and _limpia(palabras[i - 1].texto) == "por"):  # 'por ciento' no es un número
            i += 1
            continue
        pct = w.texto.rstrip(".,;:!?").endswith("%") and n == 1 or palabras[i + n - 1].texto.endswith("%") or _limpia(palabras[i + n].texto if i + n < len(palabras) else "") == "%" \
            or [_limpia(x.texto) for x in palabras[i + n:i + n + 2]] == ["por", "ciento"]
        if not (toks[0] in ("un", "una", "uno") and n == 1 and not pct):  # artículo, no cifra
            sal.append((w.inicio, v, w.texto, pct))
        i += n
    return sal
