"""Estado de la edición con Claude leído de ~/TSOTS/edicion (pendientes,
hechos, errores) para mostrarlo en la cola."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from videopipeline.edicion import estado

AHORA = 1_800_000_000.0


def _trabajo(dir_ed: Path, sub: str, carpeta: Path, stem: str, encolado: float,
             inicio: float | None = None, fin: float | None = None,
             archivos: tuple[str, ...] = ()) -> Path:
    """Una carpeta de trabajo con sus marcas de tiempo."""
    t = dir_ed / sub / f"Ep - {stem}"
    t.mkdir(parents=True)
    tj = t / "trabajo.json"
    tj.write_text(json.dumps({"origen": str(carpeta / f"{stem}.mp4")}))
    os.utime(tj, (encolado, encolado))
    if inicio is not None:
        (t / "inicio").write_text(str(int(inicio)))
    for nombre in archivos:
        (t / nombre).write_text("x")
    if fin is not None:
        final = t / ("resultado.json" if sub == "hechos" else "motivo.txt")
        final.write_text("{}")
        os.utime(final, (fin, fin))
    return t


def _bloqueo(dir_ed: Path, cuando: float) -> None:
    b = dir_ed / ".bloqueo"
    b.mkdir(parents=True, exist_ok=True)
    os.utime(b, (cuando, cuando))


def test_sin_carpeta_no_hay_estado(tmp_path):
    assert estado.leer(tmp_path / "no-existe", ahora=AHORA) == {}


def test_tanda_en_marcha(tmp_path):
    ep = tmp_path / "Episodio20"
    t0 = AHORA - 400
    _trabajo(tmp_path, "hechos", ep, "02 - B", t0, inicio=t0 + 10, fin=t0 + 110)
    _trabajo(tmp_path, "errores", ep, "01 - A", t0, inicio=t0 + 1, fin=t0 + 9)
    _trabajo(tmp_path, "pendientes", ep, "03 - C", t0, inicio=AHORA - 30,
             archivos=("contexto.md", "plan.json", "plan.validado.json"))
    _trabajo(tmp_path, "pendientes", ep, "04 - D", t0)
    _trabajo(tmp_path, "pendientes", ep, "05 - E", t0)
    _bloqueo(tmp_path, AHORA - 30)
    [(carpeta, e)] = estado.leer(tmp_path, ahora=AHORA).items()
    assert carpeta == ep
    assert (e.total, e.hechos, e.errores, e.en_cola) == (5, 1, 1, 2)
    assert (e.actual, e.fase) == ("03 - C", "montando")
    assert e.agente_activo is True
    assert e.con_error == ("01 - A",)
    # 100 s por short (el hecho): el actual lleva 30 s → ~70 s + 2 en cola
    assert e.restante_s == pytest.approx(70 + 2 * 100)
    assert 40 < e.porcentaje < 60


@pytest.mark.parametrize("archivos, fase", [
    ((), "preparando"),
    (("contexto.md",), "decide"),
    (("contexto.md", "plan.json"), "validando"),
    (("contexto.md", "plan.json", "plan.validado.json"), "montando"),
    (("contexto.md", "plan.json", "plan.validado.json", "salida.mp4"), "revisando"),
])
def test_fase_del_actual(tmp_path, archivos, fase):
    ep = tmp_path / "Ep"
    _trabajo(tmp_path, "pendientes", ep, "01 - A", AHORA - 50, inicio=AHORA - 20,
             archivos=archivos)
    _bloqueo(tmp_path, AHORA - 20)
    assert estado.leer(tmp_path, ahora=AHORA)[ep].fase == fase


def test_sin_agente_en_marcha_no_hay_actual(tmp_path):
    ep = tmp_path / "Ep"
    # un reintento movido de errores/ conserva su `inicio` viejo
    _trabajo(tmp_path, "pendientes", ep, "01 - A", AHORA - 900, inicio=AHORA - 800,
             archivos=("contexto.md",))
    _trabajo(tmp_path, "pendientes", ep, "02 - B", AHORA - 900)
    e = estado.leer(tmp_path, ahora=AHORA)[ep]
    assert e.agente_activo is False
    assert e.actual is None and e.en_cola == 2
    assert e.restante_s == pytest.approx(2 * estado.SEGUNDOS_POR_DEFECTO)


def test_reintento_viejo_no_pasa_por_el_actual(tmp_path):
    ep = tmp_path / "Ep"
    _trabajo(tmp_path, "pendientes", ep, "01 - A", AHORA - 900, inicio=AHORA - 800)
    _trabajo(tmp_path, "pendientes", ep, "02 - B", AHORA - 900, inicio=AHORA - 10)
    _bloqueo(tmp_path, AHORA - 10)
    e = estado.leer(tmp_path, ahora=AHORA)[ep]
    assert e.actual == "02 - B"


def test_tanda_terminada_se_resume_y_caduca(tmp_path):
    ep = tmp_path / "Ep"
    t0 = AHORA - 3600
    _trabajo(tmp_path, "hechos", ep, "01 - A", t0, inicio=t0 + 5, fin=t0 + 100)
    _trabajo(tmp_path, "errores", ep, "02 - B", t0, inicio=t0 + 100, fin=t0 + 120)
    e = estado.leer(tmp_path, ahora=AHORA)[ep]
    assert (e.total, e.hechos, e.errores, e.en_cola) == (2, 1, 1, 0)
    assert e.restante_s is None and e.porcentaje == 100
    # pasadas las horas de la ventana ya no se muestra
    assert estado.leer(tmp_path, ahora=AHORA + estado.VENTANA_S) == {}


def test_tandas_viejas_no_cuentan(tmp_path):
    ep = tmp_path / "Ep"
    viejo = AHORA - 3 * 86400
    _trabajo(tmp_path, "hechos", ep, "01 - A", viejo, inicio=viejo, fin=viejo + 90)
    _trabajo(tmp_path, "pendientes", ep, "01 - A2", AHORA - 60)
    e = estado.leer(tmp_path, ahora=AHORA)[ep]
    assert (e.total, e.hechos, e.en_cola) == (1, 0, 1)


def test_trabajo_ilegible_se_ignora(tmp_path):
    (tmp_path / "pendientes" / "roto").mkdir(parents=True)
    (tmp_path / "pendientes" / "roto" / "trabajo.json").write_text("{no es json")
    (tmp_path / "pendientes" / ".oculto.tmp").mkdir()
    assert estado.leer(tmp_path, ahora=AHORA) == {}
