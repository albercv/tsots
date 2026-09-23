from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.redes_falsos import ProveedorFalso
from videopipeline.redes import publicador, registro
from videopipeline.redes.modelo import (
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
)
from videopipeline.redes.publicador import Estado

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM


@pytest.fixture
def pub(tmp_path) -> Publicacion:
    video = tmp_path / "clip_limpio.mp4"
    video.write_bytes(b"MP4")
    return Publicacion(video=video, titulo="t", caption="c", hashtags=("#a",))


def _publicar(proveedor, pub, plataformas, **kw):
    eventos: list[tuple] = []
    kw.setdefault("espera", lambda s: None)
    resultados = publicador.publicar(
        proveedor, pub, Opciones(), plataformas,
        progreso=lambda p, e, r: eventos.append((p, e)), nombre_proveedor="falso", **kw)
    return resultados, eventos


def test_orden_fijo_aunque_se_pidan_desordenadas(pub):
    proveedor = ProveedorFalso()
    resultados, eventos = _publicar(proveedor, pub, [I, T, Y])
    assert [c[1] for c in proveedor.llamadas] == [T, Y, I]
    assert list(resultados) == [T, Y, I]
    assert eventos == [(T, Estado.SUBIENDO), (T, Estado.HECHO),
                       (Y, Estado.SUBIENDO), (Y, Estado.HECHO),
                       (I, Estado.SUBIENDO), (I, Estado.HECHO)]


def test_solo_las_marcadas(pub):
    proveedor = ProveedorFalso()
    resultados, _ = _publicar(proveedor, pub, {Y})
    assert list(resultados) == [Y]
    assert [c[1] for c in proveedor.llamadas] == [Y]


def test_un_fallo_no_corta_las_siguientes(pub):
    proveedor = ProveedorFalso(respuestas={
        T: Resultado(T, ok=False, error="mal"),
        Y: RuntimeError("explota con datos sensibles"),
    })
    resultados, eventos = _publicar(proveedor, pub, [T, Y, I])
    assert not resultados[T].ok and resultados[T].error == "mal"
    assert not resultados[Y].ok and "RuntimeError" in resultados[Y].error
    assert "sensibles" not in resultados[Y].error
    assert resultados[I].ok
    assert (T, Estado.ERROR) in eventos and (I, Estado.HECHO) in eventos


def test_pendientes_se_sondean_tras_enviar_todas(pub):
    proveedor = ProveedorFalso(
        respuestas={T: Resultado(T, ok=False, pendiente=True, referencia="r1")},
        estados={T: [Resultado(T, ok=False, pendiente=True, referencia="r1"),
                     Resultado(T, ok=True, url="https://tt/1")]},
    )
    esperas: list[float] = []
    resultados, eventos = _publicar(proveedor, pub, [T, Y], espera=esperas.append,
                                    intervalo=3.0)
    # TikTok queda procesando, YouTube se envía sin esperar y luego se sondea.
    assert [c[0:2] for c in proveedor.llamadas] == [
        ("publicar", T), ("publicar", Y), ("estado", T), ("estado", T)]
    assert proveedor.llamadas[2][2] == "r1"
    assert eventos[:2] == [(T, Estado.SUBIENDO), (T, Estado.PROCESANDO)]
    assert eventos[-1] == (T, Estado.HECHO)
    assert resultados[T].url == "https://tt/1"
    assert list(resultados) == [T, Y]
    assert esperas == [3.0, 3.0]


def test_pendiente_que_no_termina_se_rinde_con_aviso(pub):
    proveedor = ProveedorFalso(
        respuestas={I: Resultado(I, ok=False, pendiente=True, referencia="r")})
    reloj = iter(range(0, 10_000, 100))
    resultados, eventos = _publicar(proveedor, pub, [I], reloj=lambda: next(reloj),
                                    espera_maxima=300)
    r = resultados[I]
    assert not r.ok and r.pendiente and "Instagram" in r.error
    assert eventos[-1] == (I, Estado.ERROR)
    assert I not in registro.ya_publicado(pub.video)


def test_excepcion_en_estado_se_reintenta(pub):
    proveedor = ProveedorFalso(
        respuestas={T: Resultado(T, ok=False, pendiente=True, referencia="r")})
    llamadas = {"n": 0}
    original = proveedor.estado

    def estado(p, ref):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise TimeoutError()
        return Resultado(p, ok=True, url="u")

    proveedor.estado = estado
    resultados, _ = _publicar(proveedor, pub, [T])
    assert resultados[T].ok and llamadas["n"] == 2
    assert original  # el falso original sigue intacto


def test_exitos_se_registran_con_proveedor_y_modo(pub):
    proveedor = ProveedorFalso(respuestas={Y: Resultado(Y, ok=False, error="x")})
    publicador.publicar(proveedor, pub,
                        Opciones(tiktok_modo=ModoTikTok.PUBLICO,
                                 instagram_modo=ModoInstagram.NORMAL),
                        [T, Y, I], nombre_proveedor="falso", espera=lambda s: None)
    entradas = registro.leer(pub.video)
    assert [(e.plataforma, e.proveedor, e.modo) for e in entradas] == [
        (T, "falso", "publico"), (I, "falso", "normal")]
    assert registro.ya_publicado(pub.video) == {T, I}


def test_sin_registrar(pub):
    publicador.publicar(ProveedorFalso(), pub, Opciones(), [T], registrar=False,
                        espera=lambda s: None)
    assert not registro.ruta(pub.video).exists()


def test_cancelado_detiene_las_siguientes(pub):
    proveedor = ProveedorFalso()
    llamadas = {"n": 0}

    def cancelado():
        llamadas["n"] += 1
        return llamadas["n"] > 1  # tras la primera plataforma

    resultados, _ = _publicar(proveedor, pub, [T, Y, I], cancelado=cancelado)
    assert list(resultados) == [T]
