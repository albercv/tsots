"""Números dichos en la transcripción: cifras y palabras en español."""
import re

from videopipeline.subtitles import Palabra

_UNIDADES = {"cero": 0, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
             "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
             "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
             "diecinueve": 19, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
             "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
             "mil": 1000}
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


def numeros_dichos(palabras: list[Palabra]) -> list[tuple[float, float, str, bool]]:
    """(t, valor, palabra, es_porcentaje) por cada número dicho."""
    sal = []
    for i, w in enumerate(palabras):
        v = valor_de(w.texto)
        if v is None or (i and palabras[i - 1].texto.lower() == "por"):  # 'por ciento' no es un número
            continue
        sig = [_sin_tilde(x.texto.lower().strip(".,;:!?")) for x in palabras[i + 1:i + 3]]
        pct = w.texto.rstrip(".,;:!?").endswith("%") or sig == ["por", "ciento"]
        sal.append((w.inicio, v, w.texto, pct))
    return sal
