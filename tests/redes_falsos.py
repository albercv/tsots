"""Dobles de prueba del paquete `videopipeline.redes` (sin red)."""
from __future__ import annotations

from videopipeline.redes.modelo import (
    Cuenta,
    Opciones,
    Pagina,
    Plataforma,
    Publicacion,
    Resultado,
)


def todas_conectadas() -> dict[Plataforma, Cuenta]:
    return {p: Cuenta(p, nombre=f"Yo en {p.nombre}", usuario=f"yo_{p.value}")
            for p in Plataforma}


class ProveedorFalso:
    """Proveedor en memoria. `respuestas[plataforma]` es el Resultado de
    `publicar` (o una excepción a lanzar); `estados[plataforma]` la lista de
    Resultados que devuelve `estado` en cada consulta. `cuentas_conectadas` y
    `paginas` son lo que devuelven `cuentas()` y `paginas_facebook()` (o una
    excepción a lanzar); se anotan en `consultas`, no en `llamadas`."""

    nombre = "Falso"

    def __init__(self, respuestas=None, estados=None, cuentas_conectadas=None,
                 paginas=None):
        self.respuestas = dict(respuestas or {})
        self.estados = {p: list(v) for p, v in (estados or {}).items()}
        self.cuentas_conectadas = (todas_conectadas() if cuentas_conectadas is None
                                   else cuentas_conectadas)
        self.paginas = [Pagina("111", "Mi página")] if paginas is None else paginas
        self.llamadas: list[tuple] = []
        self.consultas: list[str] = []

    def cuentas(self):
        self.consultas.append("cuentas")
        if isinstance(self.cuentas_conectadas, BaseException):
            raise self.cuentas_conectadas
        return {p: self.cuentas_conectadas.get(p) for p in Plataforma}

    def paginas_facebook(self):
        self.consultas.append("paginas")
        if isinstance(self.paginas, BaseException):
            raise self.paginas
        return list(self.paginas)

    def publicar(self, plataforma: Plataforma, publicacion: Publicacion,
                 opciones: Opciones) -> Resultado:
        self.llamadas.append(("publicar", plataforma, publicacion, opciones))
        respuesta = self.respuestas.get(
            plataforma, Resultado(plataforma, ok=True, url=f"https://x/{plataforma.value}"))
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta

    def estado(self, plataforma: Plataforma, referencia: str) -> Resultado:
        self.llamadas.append(("estado", plataforma, referencia))
        cola = self.estados.get(plataforma) or []
        if cola:
            return cola.pop(0)
        return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)


class LlaveroFalso:
    """Imita `subprocess.run` para el comando `security` (en memoria).

    Nunca ejecuta `security` de verdad. Entiende las órdenes que usa
    `app/credenciales.py`: `-i` con add-generic-password por stdin,
    find-generic-password (con y sin -w) y delete-generic-password."""

    def __init__(self):
        self.elementos: dict[tuple[str, str], str] = {}
        self.llamadas: list[tuple[list[str], str | None]] = []

    @staticmethod
    def _opcion(tokens, nombre):
        return tokens[tokens.index(nombre) + 1] if nombre in tokens else None

    def __call__(self, args, *a, input=None, **kw):
        import subprocess

        args = [str(x) for x in args]
        self.llamadas.append((args, input))
        orden = args[1:]
        codigo, salida = 0, ""
        if orden[:1] == ["-i"]:
            for linea in (input or "").splitlines():
                tokens = linea.split()
                if tokens[:1] == ["add-generic-password"]:
                    clave = (self._opcion(tokens, "-s"), self._opcion(tokens, "-a"))
                    self.elementos[clave] = self._opcion(tokens, "-w") or ""
        elif orden[:1] == ["find-generic-password"]:
            clave = (self._opcion(orden, "-s"), self._opcion(orden, "-a"))
            if clave in self.elementos:
                salida = self.elementos[clave] + "\n" if "-w" in orden else "keychain: ...\n"
            else:
                codigo = 44
        elif orden[:1] == ["delete-generic-password"]:
            clave = (self._opcion(orden, "-s"), self._opcion(orden, "-a"))
            codigo = 0 if self.elementos.pop(clave, None) is not None else 44
        else:
            codigo = 1
        return subprocess.CompletedProcess(args, codigo, salida, "")
