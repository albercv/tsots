"""Utilidades de texto compartidas por el plan y la lectura de pantalla."""
import re
import unicodedata


def normalizar(s: str) -> str:
    """Minúsculas, sin acentos ni signos: para comparar lo dicho con lo escrito."""
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^\w]|_", "", "".join(c for c in s if not unicodedata.combining(c)))
