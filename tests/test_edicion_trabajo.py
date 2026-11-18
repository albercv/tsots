import hashlib
import json
import os
import shutil
import subprocess

import pytest
from PIL import Image

from videopipeline import subtitles
from videopipeline.edicion import entregar as ent
from videopipeline.edicion.entregar import entregar
from videopipeline.edicion.preparar import preparar
from videopipeline.edicion.verificar import hoja
from videopipeline.subtitles import Palabra

ZONAS = {"contenido": [0, 1920], "subtitulos": None, "titulo": {"y": [0, 100], "hasta": 2.5},
         "franja_zoom": [100, 1800], "graficos_hasta": 1500}


def _trabajo(tmp_path, video, estilo="formal", palabras=True, **extra):
    t = tmp_path / "trabajo"
    t.mkdir()
    shutil.copy(video, t / "video.mp4")
    origen = tmp_path / "Episodio ¿20?.mp4"
    origen.write_bytes(b"original")
    st = origen.stat()
    datos = {"version": 1, "origen": str(origen),
             "destino": str(tmp_path / "Episodio ¿20?.editado.mp4"), "origen_tam": st.st_size,
             "origen_mtime": st.st_mtime, "estilo": estilo, "idioma": "es",
             "resolucion": [1080, 1920], "encuadre": None, "zonas": ZONAS}
    datos.update(extra)
    (t / "trabajo.json").write_text(json.dumps(datos))
    if palabras:
        (t / "palabras.json").write_text(json.dumps([
            {"texto": "hola", "inicio": 0.1, "fin": 0.4},
            {"texto": "melón", "inicio": 31.76, "fin": 32.0},
            {"texto": "adiós", "inicio": 32.1, "fin": 32.5}]))
    return t


def test_contexto_tiene_palabras_y_reglas(tmp_path, video_vertical):
    t = _trabajo(tmp_path, video_vertical)
    txt = preparar(t).read_text("utf-8")
    assert "31.76 melón" in txt and "emojis: no" in txt
    assert "## Caption" not in txt and "como mucho" in txt
    assert "[31.76-32.50] melón adiós" in txt and "desde el segundo 2.5" in txt
    (t / "caption.md").write_text("mi caption")
    assert "## Caption\nmi caption" in preparar(t).read_text("utf-8")


def _con_ocr(monkeypatch, llamadas=None):
    from videopipeline.edicion import pantalla
    from videopipeline.edicion.pantalla import Deteccion, Muestra

    def analizar(video, zonas, destino):
        if llamadas is not None:
            llamadas.append(destino)
        m = [Muestra(0.5 * i, (Deteccion("Documentos de la empresa", (0, 500, 600, 80), 0.9),))
             for i in range(3, 9)]
        destino.write_text(json.dumps({"version": 1, "muestras": [
            {"t": x.t, "detecciones": [{"texto": d.texto, "caja": list(d.caja), "confianza": d.confianza}
                                       for d in x.detecciones]} for x in m]}))
        return m

    monkeypatch.setattr(pantalla, "ocr_disponible", lambda: True)
    monkeypatch.setattr(pantalla, "analizar", analizar)


def _pals(t, *extra):
    (t / "palabras.json").write_text(json.dumps([
        {"texto": "documentos", "inicio": 1.9, "fin": 2.3},
        {"texto": "diez", "inicio": 3.2, "fin": 3.4}, *extra]))


def test_contexto_con_pantalla_numeros_iconos_y_broll(tmp_path, video_vertical, monkeypatch, llavero_falso):
    from videopipeline.edicion import broll
    _con_ocr(monkeypatch)
    monkeypatch.setattr(broll, "hay_clave", lambda: True)
    t = _trabajo(tmp_path, video_vertical)
    _pals(t, {"texto": "veinte", "inicio": 4.0, "fin": 4.2}, {"texto": "por", "inicio": 4.3, "fin": 4.4},
          {"texto": "ciento", "inicio": 4.4, "fin": 4.6})
    txt = preparar(t).read_text("utf-8")
    assert "- lectura de pantalla: sí" in txt and "- B-roll: disponible" in txt
    assert "## En pantalla\n1.50-4.00 «Documentos de la empresa» (dicha «documentos» en 1.90)" in txt
    assert "3.20 10 «diez»" in txt and "4.00 20 «veinte» %" in txt
    assert "## Iconos\n" in txt and txt.index("## Iconos") < txt.index("## Frases")


def test_contexto_sin_ocr(tmp_path, video_vertical):
    t = _trabajo(tmp_path, video_vertical)
    txt = preparar(t).read_text("utf-8")
    assert "- lectura de pantalla: no" in txt and "## En pantalla\n- no disponible" in txt
    assert "## Números dichos\n- ninguno" in txt


def test_contexto_sin_clave_pixabay(tmp_path, video_vertical):
    txt = preparar(_trabajo(tmp_path, video_vertical)).read_text("utf-8")
    assert "- B-roll: no disponible (falta la clave de Pixabay)" in txt


def test_preparar_no_repite_ocr(tmp_path, video_vertical, monkeypatch):
    llamadas = []
    _con_ocr(monkeypatch, llamadas)
    t = _trabajo(tmp_path, video_vertical)
    _pals(t)
    preparar(t)
    txt = preparar(t).read_text("utf-8")
    assert len(llamadas) == 1 and "- lectura de pantalla: sí" in txt
    assert "1.50-4.00 «Documentos de la empresa»" in txt  # leído del json cacheado


def test_ocr_que_falla_no_rompe_preparar(tmp_path, video_vertical, monkeypatch):
    from videopipeline.edicion import pantalla
    _con_ocr(monkeypatch)

    def roto(video, zonas, destino):
        destino.write_text("{")
        raise RuntimeError("vision")

    monkeypatch.setattr(pantalla, "analizar", roto)
    t = _trabajo(tmp_path, video_vertical)
    txt = preparar(t).read_text("utf-8")
    assert "- lectura de pantalla: no" in txt and not (t / "pantalla.json").exists()


def test_contexto_transcribe_si_falta_palabras(tmp_path, video_vertical, monkeypatch):
    t = _trabajo(tmp_path, video_vertical, palabras=False)
    llamadas = []
    monkeypatch.setattr(subtitles, "transcribir",
                        lambda v, i, m, prompt=None: llamadas.append((v.name, i)) or [Palabra("ey", 0, 0.2)])
    assert "0.00 ey" in preparar(t).read_text("utf-8")
    assert llamadas == [("video.mp4", "es")] and (t / "palabras.json").exists()


def test_hoja_de_verificacion(tmp_path, video_vertical):
    t = _trabajo(tmp_path, video_vertical)
    shutil.copy(video_vertical, t / "salida.mp4")
    (t / "plan.validado.json").write_text(json.dumps({"momentos": [
        {"tipo": "etiqueta", "t": 1.0, "palabra": "x", "texto": ["A"]},
        {"tipo": "zoom", "t0": 1.0, "t1": 2.5}]}))
    with Image.open(hoja(t)) as im:
        assert im.size == (270 * 4, 480)


def _listo(tmp_path, video):
    t = _trabajo(tmp_path, video)
    shutil.copy(video, t / "salida.mp4")
    return t


def test_entrega_ok(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    origen = tmp_path / "Episodio ¿20?.mp4"
    h = hashlib.sha256(origen.read_bytes()).hexdigest()
    assert entregar(t) is None
    assert (tmp_path / "Episodio ¿20?.editado.mp4").exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert hashlib.sha256(origen.read_bytes()).hexdigest() == h
    assert (t / "resultado.json").exists() and not (t / "salida.mp4").exists()


def test_duracion_no_cuadra(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    subprocess.run(["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "-v", "error", "-y", "-i", str(video_vertical),
                    "-t", "2", "-c", "copy", str(t / "salida.mp4")], check=True)
    assert "duración" in entregar(t)
    assert not (tmp_path / "Episodio ¿20?.editado.mp4").exists()


def test_origen_cambiado(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    o = tmp_path / "Episodio ¿20?.mp4"
    os.utime(o, (1, 1))
    assert "origen cambiado" in entregar(t)
    assert not (tmp_path / "Episodio ¿20?.editado.mp4").exists()


def test_origen_ausente(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    (tmp_path / "Episodio ¿20?.mp4").unlink()
    assert "origen cambiado" in entregar(t)
    assert not (tmp_path / "Episodio ¿20?.editado.mp4").exists()


def test_solo_origen(tmp_path, video_vertical, capsys):
    t = _trabajo(tmp_path, video_vertical)  # sin salida.mp4: solo mira el original
    assert ent.main(["--solo-origen", str(t)]) == 0
    os.utime(tmp_path / "Episodio ¿20?.mp4", (1, 1))
    assert ent.main(["--solo-origen", str(t)]) == 1
    assert "origen cambiado" in capsys.readouterr().out


def test_sin_salida(tmp_path, video_vertical):
    assert "salida.mp4" in entregar(_trabajo(tmp_path, video_vertical))


def test_sin_audio(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    subprocess.run(["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "-v", "error", "-y", "-i", str(video_vertical),
                    "-an", "-c:v", "copy", str(t / "salida.mp4")], check=True)
    assert "audio" in entregar(t)


def test_fallo_de_copia_limpia_tmp(tmp_path, video_vertical, monkeypatch):
    t = _listo(tmp_path, video_vertical)
    monkeypatch.setattr(ent.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disco")))
    assert "disco" in entregar(t)
    assert not list(tmp_path.glob("*.tmp")) and (t / "salida.mp4").exists()


def test_frases_sin_silencios_se_cortan(tmp_path, video_vertical):
    t = _trabajo(tmp_path, video_vertical)
    (t / "palabras.json").write_text(json.dumps([
        {"texto": f"w{i}" + ("," if i % 6 == 5 else ""), "inicio": round(i * 0.3, 2),
         "fin": round(i * 0.3 + 0.3, 2)} for i in range(40)]))
    frases = preparar(t).read_text("utf-8").split("## Frases\n")[1].split("\n\n")[0].splitlines()
    spans = [tuple(float(x) for x in f[1:f.index("]")].split("-")) for f in frases]
    assert len(frases) > 1 and all(b - a <= 8 for a, b in spans)
    assert any(f.endswith(",") for f in frases)


def test_fallo_de_limpieza_tras_entregar_devuelve_none(tmp_path, video_vertical, monkeypatch):
    t = _listo(tmp_path, video_vertical)
    monkeypatch.setattr(ent.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(OSError("escritura")))
    assert entregar(t) is None
    assert (tmp_path / "Episodio ¿20?.editado.mp4").exists()


def _cambiar_destino(t, destino):
    d = json.loads((t / "trabajo.json").read_text())
    d["destino"] = str(destino)
    (t / "trabajo.json").write_text(json.dumps(d))


def test_destino_igual_al_origen(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    o = tmp_path / "Episodio ¿20?.mp4"
    _cambiar_destino(t, o)
    assert "original" in entregar(t)
    assert o.read_bytes() == b"original"


def test_destino_sin_sufijo_editado(tmp_path, video_vertical):
    t = _listo(tmp_path, video_vertical)
    _cambiar_destino(t, tmp_path / "otro.mp4")
    assert ".editado.mp4" in entregar(t)
    assert not (tmp_path / "otro.mp4").exists()


def test_preparar_desde_un_video_suelto(tmp_path, video_vertical, monkeypatch, capsys):
    from videopipeline.edicion import preparar as prep
    monkeypatch.setattr(subtitles, "transcribir",
                        lambda v, i, m, prompt=None: [Palabra("ey", 0, 0.2)])
    video = tmp_path / "Mi vídeo.mp4"
    shutil.copy(video_vertical, video)
    assert prep.main(["--video", str(video), "--estilo", "formal", "--encuadre", "cara"]) == 0
    t = tmp_path / "Mi vídeo.edicion"
    assert capsys.readouterr().out.strip() == str(t)
    datos = json.loads((t / "trabajo.json").read_text("utf-8"))
    assert datos["origen"] == str(video.resolve())
    assert datos["destino"] == str(video.resolve().with_name("Mi vídeo.editado.mp4"))
    assert datos["origen_tam"] == video.stat().st_size
    assert (datos["estilo"], datos["idioma"], datos["resolucion"]) == ("formal", "es", [1080, 1920])
    assert datos["zonas"]["subtitulos"] is not None and datos["zonas"]["titulo"] is not None
    assert (t / "video.mp4").is_file() and (t / "contexto.md").is_file()
    assert "0.00 ey" in (t / "contexto.md").read_text("utf-8")
    assert prep.main(["--video", str(video), "--estilo", "nada"]) == 1
