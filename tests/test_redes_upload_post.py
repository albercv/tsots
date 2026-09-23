"""Proveedor Upload-Post contra un transporte HTTP falso: nunca sale a la red."""
from __future__ import annotations

from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx
import pytest

from videopipeline.redes import publicador, upload_post
from videopipeline.redes.modelo import (
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
)

CLAVE = "clave-secreta-123"


def _formulario(request: httpx.Request) -> tuple[dict[str, list[str]], dict[str, tuple[str, bytes]]]:
    cuerpo = request.read()
    cabecera = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    mensaje = BytesParser(policy=HTTP).parsebytes(cabecera + cuerpo)
    campos: dict[str, list[str]] = {}
    ficheros: dict[str, tuple[str, bytes]] = {}
    for parte in mensaje.iter_parts():
        nombre = parte.get_param("name", header="content-disposition")
        datos = parte.get_payload(decode=True)
        if parte.get_filename():
            ficheros[nombre] = (parte.get_filename(), datos)
        else:
            campos.setdefault(nombre, []).append(datos.decode("utf-8"))
    return campos, ficheros


class Servidor:
    """Transporte falso que registra peticiones y responde con una función."""

    def __init__(self, responder):
        self.peticiones: list[httpx.Request] = []
        self.formularios: list[dict[str, list[str]]] = []
        self.ficheros: list[dict[str, tuple[str, bytes]]] = []
        self._responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.peticiones.append(request)
        if request.method == "POST":
            campos, ficheros = _formulario(request)
            self.formularios.append(campos)
            self.ficheros.append(ficheros)
        return self._responder(request, self)

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _ok_sync(request, servidor):
    plataforma = servidor.formularios[-1]["platform[]"][0]
    return httpx.Response(200, json={
        "success": True,
        "results": {plataforma: {"success": True, "url": f"https://{plataforma}.example/v/1",
                                 "post_id": "1"}},
        "usage": {"count": 3, "limit": 10},
    })


@pytest.fixture
def video(tmp_path) -> Path:
    ruta = tmp_path / "clip_limpio.mp4"
    ruta.write_bytes(b"MP4DATA")
    return ruta


def _pub(video: Path) -> Publicacion:
    return Publicacion(video=video, titulo="Cómo usar IA en tu pyme",
                       caption="Tres ideas clave.", hashtags=("#ia", "#pymes"),
                       palabras_clave=("ia", "pymes", "automatización"))


def _proveedor(servidor: Servidor, esperas=None, perfil="mi_perfil"):
    return upload_post.ProveedorUploadPost(
        CLAVE, perfil, http=servidor.cliente(),
        espera=(esperas.append if esperas is not None else (lambda s: None)))


def test_tiktok_borrador_campos_cabecera_y_video(video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert r.ok and r.url == "https://tiktok.example/v/1"
    peticion = servidor.peticiones[0]
    assert str(peticion.url) == "https://api.upload-post.com/api/upload"
    assert peticion.headers["authorization"] == f"Apikey {CLAVE}"
    campos = servidor.formularios[0]
    assert campos["user"] == ["mi_perfil"]
    assert campos["platform[]"] == ["tiktok"]
    assert campos["post_mode"] == ["MEDIA_UPLOAD"]
    assert "privacy_level" not in campos
    assert campos["tiktok_title"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["is_aigc"] == ["false"]
    assert servidor.ficheros[0]["video"] == ("clip_limpio.mp4", b"MP4DATA")
    assert r.extra == {"uso": "3/10"}


def test_tiktok_publico(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video),
                                  Opciones(tiktok_modo=ModoTikTok.PUBLICO))
    campos = servidor.formularios[0]
    assert campos["post_mode"] == ["DIRECT_POST"]
    assert campos["privacy_level"] == ["PUBLIC_TO_EVERYONE"]


def test_youtube_short_publico_con_tags_y_categoria(video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video),
                                      Opciones(youtube_categoria="28"))
    assert r.ok
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["youtube"]
    assert campos["title"] == ["Cómo usar IA en tu pyme"]
    assert campos["youtube_title"] == ["Cómo usar IA en tu pyme"]
    assert campos["youtube_description"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["tags[]"] == ["ia", "pymes", "automatización"]
    assert campos["categoryId"] == ["28"]
    assert campos["privacyStatus"] == ["public"]
    assert campos["containsSyntheticMedia"] == ["false"]


def test_instagram_reel_de_prueba_por_defecto(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["instagram"]
    assert campos["media_type"] == ["REELS"]
    assert campos["share_mode"] == ["TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED"]
    assert "share_to_feed" not in campos
    assert campos["instagram_title"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["is_ai_generated"] == ["false"]


def test_instagram_reel_normal(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video),
                                  Opciones(instagram_modo=ModoInstagram.NORMAL))
    campos = servidor.formularios[0]
    assert campos["share_mode"] == ["CUSTOM"]
    assert campos["share_to_feed"] == ["true"]


def test_resultado_de_plataforma_fallido(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "results": {"instagram": {"success": False,
                                                   "error": "Expired access token"}}}))
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert not r.ok and not r.pendiente
    assert "Expired access token" in r.error


def test_asincrono_request_id_y_sondeo_hasta_terminar(video):
    estados = iter([
        {"request_id": "req-1", "status": "pending", "completed": 0, "total": 1},
        {"request_id": "req-1", "status": "in_progress", "results": []},
        {"request_id": "req-1", "status": "completed", "completed": 1, "total": 1,
         "results": [{"platform": "tiktok", "success": True,
                      "message": "Publicado en https://www.tiktok.com/@yo/video/9."}]},
    ])

    def responder(request, servidor):
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "request_id": "req-1",
                                             "total_platforms": 1})
        assert str(request.url).startswith("https://api.upload-post.com/api/uploadposts/status")
        assert request.url.params["request_id"] == "req-1"
        assert request.headers["authorization"] == f"Apikey {CLAVE}"
        return httpx.Response(200, json=next(estados))

    proveedor = _proveedor(Servidor(responder))
    r = proveedor.publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert r.pendiente and r.referencia == "req-1" and not r.ok
    esperas: list[float] = []
    final = publicador.publicar(
        proveedor, _pub(video), Opciones(), [Plataforma.TIKTOK], registrar=False,
        espera=esperas.append, intervalo=1.0)
    assert final[Plataforma.TIKTOK].ok
    assert final[Plataforma.TIKTOK].url == "https://www.tiktok.com/@yo/video/9"
    assert len(esperas) == 3


def test_estado_resultados_como_diccionario_y_fallo(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "status": "completed", "results": {"youtube": {"success": False,
                                                       "message": "quota"}}}))
    r = _proveedor(servidor).estado(Plataforma.YOUTUBE, "req-9")
    assert not r.ok and not r.pendiente and "quota" in r.error


def test_estado_completado_sin_resultado_es_error():
    servidor = Servidor(lambda req, s: httpx.Response(200, json={"status": "completed",
                                                                 "results": []}))
    r = _proveedor(servidor).estado(Plataforma.INSTAGRAM, "req-9")
    assert not r.ok and not r.pendiente and "Instagram" in r.error


def test_estado_forma_desconocida_sigue_pendiente():
    servidor = Servidor(lambda req, s: httpx.Response(200, json={"foo": "bar"}))
    r = _proveedor(servidor).estado(Plataforma.TIKTOK, "req-9")
    assert r.pendiente and r.referencia == "req-9"


@pytest.mark.parametrize("codigo, texto", [
    (400, "400"), (401, "401"), (403, "403"), (429, "429"),
])
def test_errores_http_no_llevan_la_clave(video, codigo, texto):
    servidor = Servidor(lambda req, s: httpx.Response(
        codigo, json={"success": False, "message": f"mal: {CLAVE}"}))
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok and texto in r.error
    assert CLAVE not in r.error
    assert len(servidor.peticiones) == 1  # sin reintentos


def test_503_se_reintenta_y_luego_falla(video):
    esperas: list[float] = []
    servidor = Servidor(lambda req, s: httpx.Response(503, text="down"))
    r = _proveedor(servidor, esperas).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "503" in r.error
    assert len(servidor.peticiones) == 3
    assert esperas == list(upload_post.ESPERAS_503)


def test_503_y_luego_bien(video):
    respuestas = iter([httpx.Response(503)])

    def responder(request, servidor):
        return next(respuestas, None) or _ok_sync(request, servidor)

    servidor = Servidor(responder)
    r = _proveedor(servidor, []).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert r.ok and len(servidor.peticiones) == 2
    # Cada reintento vuelve a enviar el vídeo completo.
    assert servidor.ficheros[1]["video"][1] == b"MP4DATA"


def test_error_401_en_youtube_no_impide_instagram(video):
    def responder(request, servidor):
        if servidor.formularios[-1]["platform[]"] == ["youtube"]:
            return httpx.Response(401, json={"success": False,
                                             "message": "Invalid or expired token"})
        return _ok_sync(request, servidor)

    servidor = Servidor(responder)
    resultados = publicador.publicar(
        _proveedor(servidor), _pub(video), Opciones(), list(Plataforma), registrar=False)
    assert [p for p in resultados] == [Plataforma.TIKTOK, Plataforma.YOUTUBE,
                                       Plataforma.INSTAGRAM]
    assert resultados[Plataforma.TIKTOK].ok
    assert not resultados[Plataforma.YOUTUBE].ok
    assert "401" in resultados[Plataforma.YOUTUBE].error
    assert resultados[Plataforma.INSTAGRAM].ok
    assert [f["platform[]"][0] for f in servidor.formularios] == [
        "tiktok", "youtube", "instagram"]


def test_error_de_red_no_lanza(video):
    def responder(request, servidor):
        raise httpx.ConnectError("sin red", request=request)

    r = _proveedor(Servidor(responder)).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "ConnectError" in r.error


def test_sin_video_o_sin_perfil_no_envia_nada(tmp_path, video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(
        Plataforma.TIKTOK, _pub(tmp_path / "no.mp4"), Opciones())
    assert not r.ok and "no.mp4" in r.error
    r = _proveedor(servidor, perfil=" ").publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "perfil" in r.error.lower()
    assert servidor.peticiones == []


def test_repr_y_crear_no_muestran_la_clave():
    proveedor = upload_post.crear(CLAVE, {"perfil": "yo"})
    assert CLAVE not in repr(proveedor)
    assert CLAVE not in str(proveedor)
    assert proveedor.nombre == "Upload-Post"
