from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool

from app.widgets import vista_previa
from app.widgets.vista_previa import VistaPrevia

PNG_MINIMO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63f8cfc0f01f00050001ff89993d1d"
    "0000000049454e44ae426082"
)


def _mocks(monkeypatch, registro):
    def falso_extraer(video, destino, segundo=1.0):
        registro.append(("frame", video))
        destino.write_bytes(PNG_MINIMO)

    def falso_render(frame, preset, posicion, tamano, destino):
        registro.append(("render", preset, posicion, tamano))
        destino.write_bytes(PNG_MINIMO)

    monkeypatch.setattr(vista_previa, "extraer_frame", falso_extraer)
    monkeypatch.setattr(vista_previa, "renderizar_preview", falso_render)


def test_placeholder_sin_video(qtbot):
    vista = VistaPrevia()
    qtbot.addWidget(vista)
    assert "Selecciona un vídeo" in vista.etiqueta.text()


def test_debounce_agrupa_renders(qtbot, tmp_path, monkeypatch):
    registro: list = []
    _mocks(monkeypatch, registro)
    vista = VistaPrevia()
    qtbot.addWidget(vista)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    vista.establecer_video(video)
    # Tres cambios rápidos → un único render tras el debounce.
    vista.actualizar_opciones("reels_bold", 75, 100, True)
    vista.actualizar_opciones("reels_bold", 75, 110, True)
    vista.actualizar_opciones("caja", 80, 120, True)
    qtbot.wait(700)
    renders = [r for r in registro if r[0] == "render"]
    assert len(renders) == 1
    assert renders[0] == ("render", "caja", 80, 120)


def test_subs_off_muestra_frame_sin_render(qtbot, tmp_path, monkeypatch):
    registro: list = []
    _mocks(monkeypatch, registro)
    vista = VistaPrevia()
    qtbot.addWidget(vista)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    vista.establecer_video(video)
    vista.actualizar_opciones("reels_bold", 75, 100, False)
    qtbot.wait(700)
    assert [r[0] for r in registro] == ["frame"]  # extrae frame, no renderiza


def test_error_muestra_placeholder(qtbot, tmp_path, monkeypatch):
    def revienta(video, destino, segundo=1.0):
        raise RuntimeError("ffmpeg roto")

    monkeypatch.setattr(vista_previa, "extraer_frame", revienta)
    vista = VistaPrevia()
    qtbot.addWidget(vista)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    vista.establecer_video(video)
    vista.actualizar_opciones("reels_bold", 75, 100, True)
    qtbot.wait(700)
    assert "Preview no disponible" in vista.etiqueta.text()


def test_pool_serializado(qtbot):
    vista = VistaPrevia()
    qtbot.addWidget(vista)
    assert vista._pool.maxThreadCount() == 1
    assert vista._pool is not QThreadPool.globalInstance()


def test_repinta_al_redimensionar(qtbot, tmp_path, monkeypatch):
    registro: list = []
    _mocks(monkeypatch, registro)
    vista = VistaPrevia()
    qtbot.addWidget(vista)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    vista.establecer_video(video)
    vista.actualizar_opciones("reels_bold", 75, 100, True)
    qtbot.wait(700)
    assert not vista.etiqueta.pixmap().isNull()
    # Con dientes: el resize debe pasar por _repintar (rescalado desde el
    # pixmap original), no solo conservar el pixmap previo.
    repintados = []
    original_repintar = vista._repintar
    monkeypatch.setattr(
        vista, "_repintar",
        lambda: (repintados.append(True), original_repintar())[1],
    )
    # Un widget oculto no recibe QResizeEvent: hay que mostrarlo antes.
    vista.show()
    qtbot.waitExposed(vista)
    repintados.clear()  # descarta el resize inicial del show/layout
    vista.resize(vista.width() + 120, vista.height())
    qtbot.wait(50)
    assert repintados, "resizeEvent no invocó _repintar"
    assert not vista.etiqueta.pixmap().isNull()
