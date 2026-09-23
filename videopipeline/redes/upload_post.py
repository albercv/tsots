"""Proveedor Upload-Post (https://www.upload-post.com).

Único módulo de la app que conoce Upload-Post: URLs, cabecera, nombres de
campo y formato de las respuestas. El resto solo ve `Proveedor`.

API (docs y openapi.json consultados el 2026-09-23):
- `POST /api/upload`, multipart, cabecera `Authorization: Apikey <clave>`.
  Campos comunes: `user` (perfil), `platform[]`, `video`, `title`.
- Respuesta síncrona: `{"success", "results": {plataforma: {success, url,
  post_id, error}}, "usage": {count, limit}}`.
- Si la subida pasa de ~59 s pasa a segundo plano: `{"success", "request_id",
  "total_platforms"}`; se consulta en `GET /api/uploadposts/status?request_id=`.
  Según openapi.json: `{"status": "pending|in_progress|completed", "results":
  [{"platform", "success", "message"}]}`. No documenta la URL de la
  publicación en esa respuesta: se busca en varios campos y en el mensaje.
  Pendiente de confirmar con la prueba real.

Cada petición, su código HTTP, su cuerpo (limpio y acotado) y cada sondeo
se anotan con `logging` en el registro de la publicación (`diario`).
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

from ..i18n import N_, _
from . import diario
from .modelo import (
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
)
from .textos import etiquetas_youtube, texto_para, titulo_para

NOMBRE = "Upload-Post"
USA_PERFIL = True
AYUDA_PERFIL = N_(
    "En Upload-Post es el nombre del perfil que aparece en Manage Users "
    "(app.upload-post.com/manage-users), donde conectaste tus redes. "
    "No es el email de tu cuenta.")

URL_API = "https://api.upload-post.com/api"
URL_SUBIDA = f"{URL_API}/upload"
URL_ESTADO = f"{URL_API}/uploadposts/status"

# Solo el 503 (servicio no disponible) se reintenta: el resto de errores no
# cambian al repetir y un reintento tras un 429 gastaría cuota.
ESPERAS_503 = (2.0, 5.0)

# httpx aplica cada límite a cada operación (conectar, enviar un trozo, leer),
# no a la petición entera; aun así, un vídeo de cientos de MB por una conexión
# doméstica puede tardar muchos minutos y el envío se atasca a ratos. Ninguna
# espera es corta, y la de escritura crece con el tamaño del vídeo.
VELOCIDAD_MINIMA = 250_000  # bytes/s que se dan por buenos en el peor caso
ESPERA_ESCRITURA_MINIMA = 600.0
ESPERA_LECTURA = 300.0  # tras enviar todo, el servicio puede tardar en responder
ESPERA_CONEXION = 30.0

log = logging.getLogger(__name__)

_PLATAFORMAS = {
    Plataforma.TIKTOK: "tiktok",
    Plataforma.YOUTUBE: "youtube",
    Plataforma.INSTAGRAM: "instagram",
}
_ESTADOS_TERMINADOS = {"completed", "complete", "finished", "done", "success", "failed", "error"}
_RE_URL = re.compile(r"https?://\S+")
_RE_ETIQUETA = re.compile(r"<[^>]+>")
_RE_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
# Dónde buscar el motivo de un fallo, por prioridad: primero el texto pensado
# para el usuario (Meta: `error_user_msg`), luego el mensaje técnico y, al
# final, los códigos. Vale para `{"error": {...}}` anidados y listas.
_CAMPOS_USUARIO = ("error_user_msg", "user_message", "error_user_title")
_CAMPOS_MOTIVO = ("error_message", "message", "error", "errors", "details", "detail",
                  "msg", "reason", "description", "error_description")
_CAMPOS_CODIGO = ("code", "error_code", "error_subcode", "subcode", "type")
MAX_DETALLE = 200
# Respuesta del servicio cuando `user` no es un perfil de Manage Users (p. ej.
# cuando se escribe el email de la cuenta).
_RE_PERFIL_DESCONOCIDO = re.compile(
    r"not associated with any profile|profile\s+(?:was\s+)?not\s+found|"
    r"user(?:name)?\s+(?:was\s+)?not\s+found", re.IGNORECASE)


def tiempos(tamano: int) -> httpx.Timeout:
    """Límites de espera para subir un vídeo de `tamano` bytes."""
    escritura = max(ESPERA_ESCRITURA_MINIMA, tamano / VELOCIDAD_MINIMA)
    return httpx.Timeout(connect=ESPERA_CONEXION, read=ESPERA_LECTURA,
                         write=escritura, pool=ESPERA_CONEXION)


def campos(plataforma: Plataforma, publicacion: Publicacion, opciones: Opciones,
           perfil: str) -> dict[str, str | list[str]]:
    """Campos del formulario multipart (sin el vídeo) para una plataforma."""
    datos: dict[str, str | list[str]] = {
        "user": perfil,
        "platform[]": [_PLATAFORMAS[plataforma]],
        # Obligatorio para YouTube; las demás usan su título propio.
        "title": titulo_para(Plataforma.YOUTUBE, publicacion),
    }
    texto = texto_para(plataforma, publicacion)
    if plataforma == Plataforma.TIKTOK:
        datos["tiktok_title"] = texto
        datos["is_aigc"] = "false"
        if opciones.tiktok_modo == ModoTikTok.PUBLICO:
            datos["post_mode"] = "DIRECT_POST"
            datos["privacy_level"] = "PUBLIC_TO_EVERYONE"
        else:
            datos["post_mode"] = "MEDIA_UPLOAD"
    elif plataforma == Plataforma.YOUTUBE:
        datos["youtube_title"] = titulo_para(Plataforma.YOUTUBE, publicacion)
        datos["youtube_description"] = texto
        etiquetas = etiquetas_youtube(publicacion)
        if etiquetas:
            datos["tags[]"] = etiquetas
        datos["categoryId"] = opciones.youtube_categoria or "22"
        datos["privacyStatus"] = "public"
        datos["containsSyntheticMedia"] = "false"
    elif plataforma == Plataforma.INSTAGRAM:
        datos["instagram_title"] = texto
        datos["media_type"] = "REELS"
        datos["is_ai_generated"] = "false"
        if opciones.instagram_modo == ModoInstagram.NORMAL:
            datos["share_mode"] = "CUSTOM"
            datos["share_to_feed"] = "true"
        else:
            datos["share_mode"] = "TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED"
    return datos


class ProveedorUploadPost:
    nombre = NOMBRE

    def __init__(self, clave: str, perfil: str, http: httpx.Client | None = None,
                 espera: Callable[[float], None] = time.sleep):
        self._clave = clave
        self._perfil = perfil.strip()
        self._http = http
        self._espera = espera

    def __repr__(self) -> str:  # nunca la clave
        return f"ProveedorUploadPost(perfil={self._perfil!r})"

    # --- API neutra ---

    def publicar(self, plataforma: Plataforma, publicacion: Publicacion,
                 opciones: Opciones) -> Resultado:
        video = Path(publicacion.video)
        if not self._clave:
            return self._error(plataforma, _("Falta la API key. Guárdala en Redes…"))
        if not self._perfil:
            return self._error(plataforma, _("Falta el perfil. Escríbelo en Redes…"))
        if not video.is_file():
            return self._error(plataforma, _("No se encuentra el vídeo: {nombre}").format(
                nombre=video.name))
        datos = campos(plataforma, publicacion, opciones, self._perfil)
        try:
            tamano = video.stat().st_size
        except OSError:
            tamano = 0
        limites = tiempos(tamano)
        # El perfil (`user`) no va al registro.
        log.info("%s: POST %s · vídeo %s (%d bytes) · campos %s · esperas máx.: "
                 "conexión %.0f s, escritura %.0f s, lectura %.0f s",
                 plataforma.nombre, URL_SUBIDA, video, tamano,
                 {k: v for k, v in datos.items() if k != "user"},
                 limites.connect, limites.write, limites.read)

        def enviar(http: httpx.Client) -> httpx.Response:
            with video.open("rb") as fichero:
                return http.post(
                    URL_SUBIDA, headers=self._cabeceras(), data=datos,
                    files={"video": (video.name, fichero, "video/mp4")},
                    timeout=limites,
                )

        inicio = time.monotonic()
        try:
            respuesta = self._con_reintentos(enviar)
        except httpx.HTTPError as e:
            log.warning("%s: la subida falló tras %.1f s: %s", plataforma.nombre,
                        time.monotonic() - inicio, self._traza(e))
            return self._error(plataforma, _("No se pudo conectar con el servicio ({tipo}).").format(
                tipo=type(e).__name__))
        except OSError as e:
            log.warning("%s: no se pudo leer el vídeo: %s", plataforma.nombre, self._traza(e))
            return self._error(plataforma, _("No se pudo leer el vídeo ({tipo}).").format(
                tipo=type(e).__name__))
        self._registrar_respuesta(plataforma, "subida", respuesta, time.monotonic() - inicio)
        resultado = self._interpretar_subida(plataforma, respuesta)
        self._registrar_resultado(resultado)
        return resultado

    def estado(self, plataforma: Plataforma, referencia: str) -> Resultado:
        if not referencia:
            return self._error(plataforma, _("Publicación sin referencia para consultar."))
        log.info("%s: GET %s request_id=%s", plataforma.nombre, URL_ESTADO, referencia)
        inicio = time.monotonic()
        try:
            respuesta = self._con_reintentos(lambda http: http.get(
                URL_ESTADO, headers=self._cabeceras(), params={"request_id": referencia},
                timeout=tiempos(0)))
        except httpx.HTTPError as e:
            # Fallo de red pasajero: se sigue esperando.
            log.warning("%s: consulta request_id=%s falló: %s: %s", plataforma.nombre,
                        referencia, type(e).__name__, self._limpiar(str(e)))
            return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
        self._registrar_respuesta(plataforma, f"estado request_id={referencia}", respuesta,
                                  time.monotonic() - inicio)
        resultado = self._interpretar_estado(plataforma, referencia, respuesta)
        self._registrar_resultado(resultado)
        return resultado

    def _interpretar_estado(self, plataforma: Plataforma, referencia: str,
                            respuesta: httpx.Response) -> Resultado:
        if respuesta.status_code >= 400:
            if respuesta.status_code in (500, 502, 503, 504):
                return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
            return self._error(plataforma, self._mensaje_http(respuesta, plataforma))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, dict):
            return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
        propio = self._resultado_de(cuerpo.get("results"), plataforma)
        if propio is not None and "success" in propio:
            return self._resultado_plataforma(plataforma, propio)
        estado = str(cuerpo.get("status", "")).strip().lower()
        if estado in _ESTADOS_TERMINADOS:
            return self._error(plataforma, _("El servicio terminó sin resultado para {plataforma}.").format(
                plataforma=plataforma.nombre))
        return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)

    # --- detalles ---

    def _cabeceras(self) -> dict[str, str]:
        return {"Authorization": f"Apikey {self._clave}"}

    @contextmanager
    def _cliente(self) -> Iterator[httpx.Client]:
        if self._http is not None:
            yield self._http
            return
        with httpx.Client(timeout=tiempos(0)) as http:
            yield http

    def _con_reintentos(self, llamada: Callable[[httpx.Client], httpx.Response]) -> httpx.Response:
        with self._cliente() as http:
            respuesta = llamada(http)
            for segundos in ESPERAS_503:
                if respuesta.status_code != 503:
                    break
                log.info("HTTP 503: nuevo intento en %.0f s", segundos)
                self._espera(segundos)
                respuesta = llamada(http)
            return respuesta

    def _registrar_respuesta(self, plataforma: Plataforma, que: str,
                             respuesta: httpx.Response, segundos: float) -> None:
        log.info("%s: %s → HTTP %d en %.1f s · cuerpo: %s", plataforma.nombre, que,
                 respuesta.status_code, segundos,
                 diario.cuerpo(respuesta.text, [self._clave]) or "(vacío)")

    @staticmethod
    def _registrar_resultado(resultado: Resultado) -> None:
        nombre = resultado.plataforma.nombre
        if resultado.ok:
            log.info("%s: publicado %s", nombre, resultado.url or "(sin enlace)")
        elif resultado.pendiente:
            log.info("%s: pendiente en el servicio, request_id=%s", nombre, resultado.referencia)
        else:
            log.warning("%s: error: %s", nombre, resultado.error)

    def _interpretar_subida(self, plataforma: Plataforma, respuesta: httpx.Response) -> Resultado:
        if respuesta.status_code >= 400:
            return self._error(plataforma, self._mensaje_http(respuesta, plataforma))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, dict):
            texto = self._texto_plano(respuesta.text)
            return self._error(plataforma, _("Respuesta inesperada del servicio (HTTP {codigo}).").format(
                codigo=respuesta.status_code) + (f" {texto}" if texto else ""))
        extra = self._uso(cuerpo)
        propio = self._resultado_de(cuerpo.get("results"), plataforma)
        if propio is not None:
            resultado = self._resultado_plataforma(plataforma, propio)
            return Resultado(resultado.plataforma, resultado.ok, resultado.url,
                             resultado.error, extra=extra)
        if cuerpo.get("request_id"):
            return Resultado(plataforma, ok=False, pendiente=True,
                             referencia=str(cuerpo["request_id"]), extra=extra)
        if cuerpo.get("success") is False or str(cuerpo.get("success")).lower() == "false":
            return self._error(plataforma, self._legible(
                self._texto(cuerpo) or _("El servicio rechazó la publicación.")))
        motivo = self._texto(cuerpo)
        if motivo:
            return self._error(plataforma, _(
                "El servicio no devolvió resultado para {plataforma}: {motivo}").format(
                plataforma=plataforma.nombre, motivo=motivo))
        return self._error(plataforma, _(
            "Respuesta inesperada del servicio: no trae resultado para {plataforma}.").format(
            plataforma=plataforma.nombre))

    @staticmethod
    def _resultado_de(resultados: Any, plataforma: Plataforma) -> dict | None:
        """Resultado de una plataforma, sea `{plataforma: {...}}` o
        `[{"platform": ..., ...}]`."""
        clave = _PLATAFORMAS[plataforma]
        if isinstance(resultados, dict):
            for nombre, valor in resultados.items():
                if str(nombre).lower() == clave and isinstance(valor, dict):
                    return valor
        elif isinstance(resultados, list):
            for valor in resultados:
                if isinstance(valor, dict) and str(valor.get("platform", "")).lower() == clave:
                    return valor
        return None

    def _resultado_plataforma(self, plataforma: Plataforma, datos: dict) -> Resultado:
        log.info("%s: resultado del servicio: %s", plataforma.nombre, diario.cuerpo(
            json.dumps(datos, ensure_ascii=False, default=str), [self._clave]))
        if datos.get("success") is True or str(datos.get("success")).lower() == "true":
            return Resultado(plataforma, ok=True, url=self._url(datos))
        return self._error(plataforma, self._legible(
            self._texto(datos) or _("{plataforma} rechazó la publicación.").format(
                plataforma=plataforma.nombre)))

    def _perfil_desconocido(self) -> str:
        return _("El perfil «{perfil}» no existe en Upload-Post. Usa el nombre del "
                 "perfil que aparece en Manage Users, no el email de tu cuenta.").format(
            perfil=self._perfil)

    def _legible(self, motivo: str) -> str:
        """Motivo del servicio; los que tienen arreglo conocido, explicados."""
        if _RE_PERFIL_DESCONOCIDO.search(motivo):
            return f"{self._perfil_desconocido()} ({motivo})"
        return motivo

    @staticmethod
    def _url(datos: dict) -> str:
        for campo in ("url", "post_url", "platform_post_url", "permalink", "link"):
            valor = datos.get(campo)
            if isinstance(valor, str) and valor.startswith("http"):
                return valor
        encontrada = _RE_URL.search(str(datos.get("message", "")))
        return encontrada.group(0).rstrip(".,)") if encontrada else ""

    @classmethod
    def _texto(cls, datos: Any, profundidad: int = 0) -> str:
        """Motivo legible de una respuesta o de un resultado, aunque venga
        anidado (`{"error": {"message": ...}}`), en lista o con códigos."""
        if isinstance(datos, str):
            return " ".join(datos.split())
        if isinstance(datos, bool) or datos is None or profundidad > 4:
            return ""
        if isinstance(datos, (int, float)):
            return str(datos)
        if isinstance(datos, list):
            return cls._unir(cls._texto(v, profundidad + 1) for v in datos[:5])
        if not isinstance(datos, dict):
            return ""
        textos = [cls._texto(datos.get(campo), profundidad + 1)
                  for campo in _CAMPOS_USUARIO + _CAMPOS_MOTIVO]
        texto = cls._unir(textos)
        codigos = [f"{campo} {datos[campo]}" for campo in _CAMPOS_CODIGO
                   if isinstance(datos.get(campo), (str, int)) and not isinstance(
                       datos.get(campo), bool) and str(datos[campo]).strip()]
        if codigos and texto:
            return f"{texto} ({', '.join(codigos)})"
        return texto or ", ".join(codigos)

    @staticmethod
    def _unir(textos) -> str:
        """Junta textos sin repetir (ni los contenidos en otro ya elegido)."""
        elegidos: list[str] = []
        for texto in textos:
            if texto and not any(texto in otro for otro in elegidos):
                elegidos = [otro for otro in elegidos if otro not in texto] + [texto]
        return " · ".join(elegidos[:3])

    @staticmethod
    def _texto_plano(texto: str) -> str:
        """Texto de una respuesta que no es JSON (p. ej. la página HTML de un
        proxy), sin etiquetas y acotado."""
        texto = _RE_ETIQUETA.sub(" ", _RE_SCRIPT.sub(" ", texto or ""))
        texto = " ".join(html.unescape(texto).split())
        return texto if len(texto) <= MAX_DETALLE else texto[:MAX_DETALLE - 1] + "…"

    @staticmethod
    def _uso(cuerpo: dict) -> dict:
        uso = cuerpo.get("usage")
        if isinstance(uso, dict) and "count" in uso:
            return {"uso": f"{uso.get('count')}/{uso.get('limit', '?')}"}
        return {}

    @staticmethod
    def _json(respuesta: httpx.Response) -> Any:
        try:
            return respuesta.json()
        except ValueError:
            return None

    def _mensaje_http(self, respuesta: httpx.Response, plataforma: Plataforma) -> str:
        codigo = respuesta.status_code
        cuerpo = self._json(respuesta)
        if isinstance(cuerpo, dict):
            # El motivo propio de la plataforma (p. ej. «fuera del plan») antes que el general.
            propio = self._resultado_de(cuerpo.get("results"), plataforma)
            detalle = (self._texto(propio) if propio else "") or self._texto(cuerpo)
        elif cuerpo is None:
            detalle = self._texto_plano(respuesta.text)
        else:
            detalle = self._texto(cuerpo)
        if _RE_PERFIL_DESCONOCIDO.search(detalle):
            return self._limpiar(f"{self._perfil_desconocido()} ({codigo}: {detalle})")
        if codigo == 401:
            base = _("La API key no es válida o ha caducado (401). Revísala en Redes…")
        elif codigo == 403:
            base = _("Sin permiso o fuera del plan contratado (403).")
        elif codigo == 413:
            base = _("El vídeo es demasiado grande para el servicio (413).")
        elif codigo == 429:
            base = _("Límite de subidas del plan alcanzado (429).")
        elif codigo == 503:
            base = _("Servicio no disponible (503). Prueba más tarde.")
        else:
            base = _("Error {codigo} del servicio.").format(codigo=codigo)
        return self._limpiar(f"{base} {detalle}".strip())

    def _traza(self, excepcion: BaseException) -> str:
        """Traceback completo, sin la clave (el mensaje de la excepción podría
        llevarla: p. ej. una URL o una cabecera repetidas por la librería)."""
        return diario.limpiar("".join(traceback.format_exception(excepcion)).rstrip(),
                              [self._clave])

    def _limpiar(self, texto: str) -> str:
        """Quita la clave (por si el servicio la repite) y acota la longitud."""
        texto = diario.limpiar(texto, [self._clave])
        return texto if len(texto) <= 400 else texto[:399] + "…"

    def _error(self, plataforma: Plataforma, texto: str) -> Resultado:
        return Resultado(plataforma, ok=False, error=self._limpiar(texto))


def crear(clave: str, ajustes: dict, http: httpx.Client | None = None) -> ProveedorUploadPost:
    return ProveedorUploadPost(clave, str(ajustes.get("perfil", "") or ""), http=http)
