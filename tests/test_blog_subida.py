import json

import httpx
import pytest

from videopipeline import blog_subida

URL = "https://blog.example.com/admin/media-upload?token=SECRETO123"


def _cliente(peticiones, estado=200, cuerpo=None):
    def manejar(peticion: httpx.Request) -> httpx.Response:
        peticiones.append((peticion, peticion.read()))
        return httpx.Response(estado, json=cuerpo if cuerpo is not None else {"ok": True})
    return httpx.Client(transport=httpx.MockTransport(manejar))


def _ficheros(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"png-bytes")
    b = tmp_path / "b.mp4"
    b.write_bytes(b"video-bytes")
    return a, b


def test_sube_cada_fichero_y_confirma(tmp_path):
    a, b = _ficheros(tmp_path)
    peticiones = []
    blog_subida.subir(URL, [(a, "portada"), (b, "video_1")], portada="portada",
                      alts={"portada": "Una portada"}, http=_cliente(peticiones))
    assert len(peticiones) == 3
    p1, cuerpo1 = peticiones[0]
    assert str(p1.url) == "https://blog.example.com/api/admin/media/upload"
    assert p1.headers["authorization"] == "Bearer SECRETO123"
    assert p1.headers["x-media-name"] == "portada"
    assert p1.headers["content-type"] == "image/png"
    assert cuerpo1 == b"png-bytes"
    assert peticiones[1][0].headers["content-type"] == "video/mp4"
    ultima, cuerpo = peticiones[2]
    assert str(ultima.url) == "https://blog.example.com/api/admin/media/upload/commit"
    assert json.loads(cuerpo) == {"files": [
        {"name": "portada", "alt": "Una portada", "caption": ""},
        {"name": "video_1", "alt": "", "caption": ""}], "cover": "portada"}


def test_sin_portada_no_envia_cover(tmp_path):
    a, _ = _ficheros(tmp_path)
    peticiones = []
    blog_subida.subir(URL, [(a, "foto")], http=_cliente(peticiones))
    assert "cover" not in json.loads(peticiones[-1][1])


def test_error_del_servidor_sin_token_en_el_mensaje(tmp_path):
    a, _ = _ficheros(tmp_path)
    with pytest.raises(RuntimeError) as e:
        blog_subida.subir(URL, [(a, "foto")],
                          http=_cliente([], 413, {"error": "demasiado grande"}))
    assert "demasiado grande" in str(e.value)
    assert "SECRETO123" not in str(e.value)
    with pytest.raises(RuntimeError, match="500"):
        blog_subida.subir(URL, [(a, "foto")], http=_cliente([], 500, ["x"]))


def test_slug_key_invalida_no_envia_nada(tmp_path):
    a, b = _ficheros(tmp_path)
    for ficheros in ([(a, "Mala-Key")], [(a, "igual"), (b, "igual")]):
        peticiones = []
        with pytest.raises(ValueError):
            blog_subida.subir(URL, ficheros, http=_cliente(peticiones))
        assert peticiones == []


def test_cli_parsea_ficheros_y_portada(tmp_path, monkeypatch, capsys):
    a, b = _ficheros(tmp_path)
    llamadas = []
    monkeypatch.setattr(blog_subida, "subir", lambda *args, **kw: llamadas.append((args, kw)))
    codigo = blog_subida.main([URL, "--fichero", f"{a}=portada", "--fichero", f"{b}=video_1",
                               "--portada", "portada", "--alt", "portada=Con = igual"])
    assert codigo == 0
    (url, ficheros), kw = llamadas[0]
    assert url == URL and ficheros == [(a, "portada"), (b, "video_1")]
    assert kw["portada"] == "portada" and kw["alts"] == {"portada": "Con = igual"}


def test_cli_error_a_stderr_sin_token(tmp_path, monkeypatch, capsys):
    a, _ = _ficheros(tmp_path)

    def falla(*args, **kw):
        raise RuntimeError("fallo del blog")
    monkeypatch.setattr(blog_subida, "subir", falla)
    assert blog_subida.main([URL, "--fichero", f"{a}=foto"]) == 1
    err = capsys.readouterr().err
    assert "fallo del blog" in err and "SECRETO123" not in err


def _cliente_409(peticiones, error="exists"):
    def manejar(peticion: httpx.Request) -> httpx.Response:
        peticiones.append((peticion, peticion.read()))
        if peticion.headers.get("x-media-name") == "portada":
            return httpx.Response(409, json={"error": error, "message": "ya existe"})
        return httpx.Response(200, json={"ok": True})
    return httpx.Client(transport=httpx.MockTransport(manejar))


def test_409_exists_se_da_por_subido_y_se_confirma(tmp_path):
    a, b = _ficheros(tmp_path)
    peticiones = []
    blog_subida.subir(URL, [(a, "portada"), (b, "video")], http=_cliente_409(peticiones))
    assert len(peticiones) == 3
    assert [f["name"] for f in json.loads(peticiones[-1][1])["files"]] == ["portada", "video"]


def test_409_con_otro_error_falla(tmp_path):
    a, b = _ficheros(tmp_path)
    with pytest.raises(RuntimeError, match="otro"):
        blog_subida.subir(URL, [(a, "portada"), (b, "video")],
                          http=_cliente_409([], error="otro"))
