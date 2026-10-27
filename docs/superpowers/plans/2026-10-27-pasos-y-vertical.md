# Pasos combinables y conversión a vertical — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir los modos fijos por pasos combinables (audio, silencios, subtítulos, caption, vertical) y añadir la conversión a vertical 9:16 con cuatro encuadres.

**Architecture:** Se portan de la implementación de referencia los módulos autocontenidos `videopipeline/vertical.py` y `videopipeline/seguimiento.py`. `PipelineConfig` pasa de `modo` a booleanos `paso_*`, con `modo` como alias de entrada. `pipeline.run()` encadena los pasos pedidos y añade una fase vertical tras publicar el horizontal. Runner, worker, cola y panel se adaptan.

**Tech Stack:** Python 3.11, ffmpeg/ffprobe (`ffmpeg-full` para `ass`), auto-editor, S3FD (torch, torchvision, cv2, gdown ya en requirements), PySide6, pytest + pytest-qt, gettext (`lanzador/traducir.sh`).

**Spec:** `docs/superpowers/specs/2026-10-27-pasos-y-vertical-design.md`

## Global Constraints

- Repo `~/Documents/personalProjects/tsots-vertical`, rama `feature/vertical`, base `fix/sync-audio-caption-ligero` (PR #15, c0755c3). Nunca push a `develop`/`main`.
- Commits en inglés, **sin atribución a IA** (ni `Co-Authored-By` ni "Generated with"). Código, comentarios y GUI en español.
- Tests antes de cada commit, y solo se commitea en verde: `PY=~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python; QT_QPA_PLATFORM=offscreen $PY -m pytest -q` desde la raíz de la worktree (la worktree no tiene venv propio; el usuario autorizó usar el de producción solo para ejecutar).
- Tests lentos con modelo real: marcador `slow` (no `lenta`, reservado a servicios reales con la cuenta del usuario). Para ejecutarlos, enlazar temporalmente `checkpoints` → `~/Documents/personalProjects/limpiadorVideo/checkpoints` y quitar el enlace al acabar; nunca commitearlo.
- Todo texto visible o de aviso nuevo: `_("… {x}").format(x=…)` (nunca f-string dentro de `_()`); etiquetas de combo con `N_()` + `addItem(_(e), valor)` + `currentData()`/`findData()`.
- Referencia: `git -C /Users/albercv/Documents/autoeditor/ClearerVoice-Studio show 258bdb6:clearvoice/<ruta>`. Abreviado `REF:<ruta>`.
- Salida vertical: 1080x1920, `format=yuv420p`, `setsar=1`, `-r <fps_objetivo(fuente)>`, `libx264 -crf 18 -preset medium`, `+faststart`.
- Encuadres `ENCUADRES = ("central", "difuminado", "barras", "cara")`, defecto `"central"`. Pasos por defecto: `paso_audio=True`, `paso_silencios=True`, `paso_vertical=False`, `subtitulos=False`, `caption_seo=False`.
- Nombres: horizontal `<n>_limpio.mp4`; vertical acompañante `<n>_limpio_vertical.mp4` (o `X_vertical.mp4` si la salida es `X.mp4`); vertical único `<n>_vertical.mp4`.
- Etiquetas de progreso: `_("Detectando caras")`, `_("Descargando detector de caras")`, `_("Convirtiendo a vertical")`. Avisos (prefijos): `_("Versión vertical falló: …")`, `_("El vídeo ya era vertical…")`, `_("No se detectó ninguna cara…")`, `_("No se pudo preparar el detector de caras…")`.

## Review Focus

1. **Vídeo del iPhone con tasa variable y huecos de audio, solo vertical**: la salida tiene tasa entera (`fps_objetivo`) y audio AAC sin desincronizar. → Task 2, `test_convertir_desde_original_fuerza_fps_y_rellena_audio`.
2. **Ajustes guardados por la versión de hoy** (`panel/modo = "solo_silencios"`, sin claves `paso_*`): la app nueva arranca con solo silencios marcado. → Task 5, `test_panel_cargar_modo_antiguo`.
3. **La versión anterior sigue arrancando** tras usar la nueva (lee `panel/modo`): se guarda siempre un modo antiguo válido. → Task 6, `test_procesar_guarda_modo_equivalente`.
4. **Primera vez con "Seguir la cara" sin pesos**: se descargan con la API de gdown; si falla, central + aviso, sin romper el trabajo. → Task 3, `test_pesos_descarga_atomica` y Task 4, `test_cara_sin_detector_cae_a_central`.
5. **Cancelar durante el vertical**: el horizontal se conserva y no quedan temporales de ningún destino. → Task 6, `test_cancelado_limpia_temporales_vertical`.

---

### Task 1: `PipelineConfig` — pasos, encuadre, salidas y alias `modo`

**Files:** Modify `videopipeline/config.py`; Test `tests/test_config.py`, `tests/test_cli_compat.py`.

**Interfaces — Produces:**
- Campos `paso_audio: bool = True`, `paso_silencios: bool = True`, `paso_vertical: bool = False`, `encuadre: str = "central"`; `modo: InitVar[str | None] = None` (alias de entrada; `__post_init__` lo traduce con `pasos_desde_modo`).
- `ENCUADRES`; `pasos_desde_modo(modo: str) -> dict[str, bool]` (claves `paso_audio`, `paso_silencios`; `ValueError` si el modo no está en `MODOS`); `modo_equivalente(paso_audio: bool, paso_silencios: bool) -> str` (`completo` si ambos o ninguno, `solo_audio`, `solo_silencios`).
- Métodos: `hay_horizontal() -> bool` (`paso_audio or paso_silencios or not paso_vertical`); `ruta_salida_final() -> Path` (salida principal); `ruta_salida_vertical() -> Path | None` (vertical acompañante, `None` si no hay dos salidas).
- `from_json` acepta y traduce `"modo"`; `to_json` no lo escribe.

- [ ] **Step 1: Write the failing tests** (añadir a `tests/test_config.py`)

```python
def test_pasos_por_defecto():
    c = PipelineConfig(video=Path("/v/a.mp4"))
    assert (c.paso_audio, c.paso_silencios, c.paso_vertical) == (True, True, False)
    assert c.encuadre == "central" and c.hay_horizontal()
    assert c.ruta_salida_vertical() is None

@pytest.mark.parametrize("modo, audio, silencios", [
    ("completo", True, True), ("solo_audio", True, False), ("solo_silencios", False, True)])
def test_alias_modo(modo, audio, silencios):
    c = PipelineConfig(video=Path("/v/a.mp4"), modo=modo)
    assert (c.paso_audio, c.paso_silencios) == (audio, silencios)
    assert "modo" not in json.loads(c.to_json())
    assert PipelineConfig.from_json(json.dumps({"video": "/v/a.mp4", "modo": modo})) == c

def test_modo_equivalente():
    assert modo_equivalente(True, True) == "completo"
    assert modo_equivalente(True, False) == "solo_audio"
    assert modo_equivalente(False, True) == "solo_silencios"
    assert modo_equivalente(False, False) == "completo"

def test_encuadre_invalido():
    with pytest.raises(ValueError, match="encuadre"):
        PipelineConfig(video=Path("/v/a.mp4"), encuadre="zoom").validar()

def test_sin_pasos_de_video_invalido():
    c = PipelineConfig(video=Path("/v/a.mp4"), paso_audio=False, paso_silencios=False,
                       caption_seo=True)
    with pytest.raises(ValueError, match="paso"):
        c.validar()

@pytest.mark.parametrize("salida, principal, vertical", [
    (None, "/v/a_limpio.mp4", "/v/a_limpio_vertical.mp4"),
    (Path("/out"), "/out/a_limpio.mp4", "/out/a_limpio_vertical.mp4"),
    (Path("/out/X.mp4"), "/out/X.mp4", "/out/X_vertical.mp4"),
])
def test_dos_salidas(salida, principal, vertical):
    c = PipelineConfig(video=Path("/v/a.mp4"), salida=salida, paso_vertical=True,
                       paso_audio=False)  # silencios + vertical
    assert c.ruta_salida_final() == Path(principal)
    assert c.ruta_salida_vertical() == Path(vertical)

@pytest.mark.parametrize("subtitulos", [False, True])
def test_solo_vertical_una_salida(subtitulos):
    c = PipelineConfig(video=Path("/v/a.mp4"), salida=Path("/out"), paso_audio=False,
                       paso_silencios=False, paso_vertical=True, subtitulos=subtitulos)
    c.validar()
    assert not c.hay_horizontal()
    assert c.ruta_salida_final() == Path("/out/a_vertical.mp4")
    assert c.ruta_salida_vertical() is None

def test_solo_subtitulos_es_horizontal():
    c = PipelineConfig(video=Path("/v/a.mp4"), paso_audio=False, paso_silencios=False,
                       subtitulos=True)
    c.validar()
    assert c.hay_horizontal() and c.ruta_salida_final() == Path("/v/a_limpio.mp4")
```

Actualizar `tests/test_cli_compat.py:26` a `assert (config.paso_audio, config.paso_silencios) == (True, True)` y cualquier aserción de `c.modo` en `tests/test_config.py` (`MODOS` sigue igual: no cambia `test_config.py:76`).

- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest tests/test_config.py tests/test_cli_compat.py -q` — Expected: FAIL (`unexpected keyword argument 'paso_vertical'`, `cannot import name 'modo_equivalente'`).
- [ ] **Step 3: Implement** en `config.py`. `validar()`: mensajes crudos, como el resto de `validar()`; `encuadre` → `f"encuadre inválido: …"`; sin paso de vídeo → `"no hay ningún paso de vídeo seleccionado (audio, silencios, subtítulos o vertical)"`. `ruta_salida_final()`: sufijo `_vertical` si `not hay_horizontal()`, si no `_limpio`; regla carpeta/archivo actual intacta. `ruta_salida_vertical()`: `None` si `not paso_vertical or not hay_horizontal()`; si no `final.with_name(f"{final.stem}_vertical{final.suffix}")`.
- [ ] **Step 4: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q` — Expected: PASS todo (los tests que construyen `PipelineConfig(modo=…)` siguen pasando por el alias).
- [ ] **Step 5: Commit** `git add videopipeline/config.py tests/test_config.py tests/test_cli_compat.py && git commit -m "feat: combinable pipeline steps with modo as an input alias"`

---

### Task 2: `vertical.py` — encuadres, tasa entera y conversión

**Files:** Create `videopipeline/vertical.py` (desde `REF:videopipeline/vertical.py`); Modify `videopipeline/steps.py`; Modify `tests/conftest.py`; Create `tests/test_vertical.py` (desde `REF:tests/test_vertical.py`).

**Interfaces — Produces** (`vertical.py`): `ANCHO_VERTICAL`, `ALTO_VERTICAL`, `ancho_recorte(alto)`, `es_ya_vertical(ancho, alto)`, `filtro_vertical(encuadre, ancho, alto, x_cara=None, ass_nombre=None) -> str`, `audio_cabe_en_mp4(video) -> bool`, y con firmas nuevas:
- `cmd_convertir_vertical(ffmpeg: str, video: Path, filtro: str, salida: Path, fps: str, audio: str) -> list[str]` — `audio` ∈ `{"copiar", "aac", "rellenar"}` (`rellenar` = AAC 192k + `-af FILTRO_HUECOS_AUDIO`).
- `convertir_vertical(video: Path, salida: Path, filtro: str, cwd: Path, usa_ass: bool, desde_original: bool = False, on_percent=None) -> None` — `fps = fps_objetivo(video)`; `audio = "rellenar" if desde_original else ("copiar" if audio_cabe_en_mp4(video) else "aac")`.
- `steps.ejecutar_ffmpeg_con_progreso(cmd, cwd, duracion, on_percent) -> tuple[int, str]` (extraído de `quemar_subtitulos`, acotando el % a [0, 100]); `steps.cmd_quemar_subtitulos` y `steps.quemar_subtitulos` ganan `desde_original: bool = False` (añade `-r fps_objetivo(video)` y audio `rellenar`).

- [ ] **Step 1:** Fixture `video_720p` en `conftest.py` = `REF:tests/conftest.py` (`testsrc2=s=1280x720:d=2:r=10`, `sine`, AAC).
- [ ] **Step 2: Write the failing tests:** `tests/test_vertical.py` = `REF:tests/test_vertical.py` con: llamadas a `convertir_vertical` con el argumento nuevo `desde_original=False`; `test_cmd_convertir_*` adaptados a `cmd_convertir_vertical(..., fps="30", audio=...)` (asserts: `cmd[cmd.index("-r")+1] == "30"`, `"copy"` / `["aac","-b:a","192k"]` / `-af FILTRO_HUECOS_AUDIO`). Más:

```python
def test_convertir_desde_original_fuerza_fps_y_rellena_audio(tmp_path):
    # Fuente de tasa variable (como el iPhone): la salida debe tener tasa entera.
    vfr = tmp_path / "vfr.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=1280x720:d=2:r=30", "-f", "lavfi", "-i", "sine=d=2",
                    "-vf", "setpts='PTS+0.02*sin(N)/TB'", "-fps_mode", "vfr",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(vfr)], check=True)
    salida = tmp_path / "o.mp4"
    convertir_vertical(vfr, salida, filtro_vertical("central", 1280, 720), tmp_path,
                       usa_ass=False, desde_original=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=r_frame_rate,avg_frame_rate", "-of", "csv=p=0", str(salida)],
                       capture_output=True, text=True, check=True).stdout.strip().split(",")
    assert r[0] == r[1] and r[0] in ("30/1", "30000/1001")
    assert _probe(salida)[3] == "aac"

def test_quemar_desde_original_fuerza_fps():
    cmd = cmd_quemar_subtitulos("ffmpeg", Path("v.mov"), "s.ass", Path("o.mp4"),
                                desde_original=True, fps="30")
    assert cmd[cmd.index("-r") + 1] == "30" and FILTRO_HUECOS_AUDIO in cmd
```

(`cmd_quemar_subtitulos` recibe `fps: str | None = None` además de `desde_original`; `quemar_subtitulos` calcula `fps_objetivo(video)` cuando `desde_original`.)
- [ ] **Step 3: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest tests/test_vertical.py tests/test_steps.py -q` — Expected: FAIL (`No module named 'videopipeline.vertical'`).
- [ ] **Step 4: Implement:** extraer el helper en `steps.py` (`quemar_subtitulos` conserva su mensaje `_()` actual y sus comprobaciones); copiar `vertical.py` de la referencia, cambiar `PasoFallido(f"…")` por `_("…{x}").format(x=…)`, añadir `fps`/`audio` según Interfaces (importar `fps_objetivo` y `FILTRO_HUECOS_AUDIO` de `steps`).
- [ ] **Step 5: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q` — Expected: PASS.
- [ ] **Step 6: Commit** `feat: vertical framings with integer frame rate and gap-filled audio`

---

### Task 3: `seguimiento.py` — seguimiento de cara y pesos del detector

**Files:** Create `videopipeline/seguimiento.py` (desde `REF:videopipeline/seguimiento.py`); Create `tests/test_seguimiento.py` (desde `REF:tests/test_seguimiento.py`).

**Interfaces — Consumes:** Task 2 (`ancho_recorte`, `convertir_vertical`, `filtro_vertical`). **Produces:** todo lo de la referencia (`FPS_MUESTREO = 2.0`, `dispositivo()`, `suavizar`, `posiciones_recorte`, `escribir_comandos(..., salto_px=None)`, `muestrear_centros`, `preparar_seguimiento`) y además:
- `RUTA_PESOS = BASE_DIR / "clearvoice/models/av_mossformer2_tse/faceDetector/s3fd/sfd_face.pth"`, `ID_PESOS = "1KafnHz7ccT-3IyddBsL5yi2xGtxAKypt"`.
- `asegurar_pesos_s3fd(ruta: Path = RUTA_PESOS) -> bool` — `True` si ya existían; si no, `gdown.download(id=ID_PESOS, output=str(tmp), quiet=True)` a `ruta.with_suffix(".pth.tmp")` y `replace`; devuelve `False` tras descargar. Cualquier fallo → `PasoFallido(_("No se pudieron descargar los pesos del detector de caras: {error}"))` sin dejar el `.tmp`.
- `_detector_s3fd()` llama a `asegurar_pesos_s3fd()` antes de crear `S3FD`.

- [ ] **Step 1: Write the failing tests:** `tests/test_seguimiento.py` = `REF:tests/test_seguimiento.py` (marcador `slow` como en la referencia). Más:

```python
def test_pesos_ya_presentes_no_descarga(tmp_path, monkeypatch):
    ruta = tmp_path / "sfd_face.pth"; ruta.write_bytes(b"W")
    monkeypatch.setattr(seguimiento.gdown, "download", lambda **k: pytest.fail("descargó"))
    assert asegurar_pesos_s3fd(ruta) is True

def test_pesos_descarga_atomica(tmp_path, monkeypatch):
    ruta = tmp_path / "sfd_face.pth"
    def falso(id, output, quiet):
        assert id == ID_PESOS and output.endswith(".tmp")
        Path(output).write_bytes(b"PESOS")
    monkeypatch.setattr(seguimiento.gdown, "download", falso)
    assert asegurar_pesos_s3fd(ruta) is False
    assert ruta.read_bytes() == b"PESOS" and not ruta.with_suffix(".pth.tmp").exists()

def test_pesos_fallo_no_deja_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "sfd_face.pth"
    def falso(id, output, quiet):
        Path(output).write_bytes(b"MEDIO"); raise OSError("sin red")
    monkeypatch.setattr(seguimiento.gdown, "download", falso)
    with pytest.raises(PasoFallido):
        asegurar_pesos_s3fd(ruta)
    assert not ruta.exists() and not ruta.with_suffix(".pth.tmp").exists()
```

(`import gdown` al principio de `seguimiento.py` para poder parchearlo; `gdown` es ligero y no importa torch.)
- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest tests/test_seguimiento.py -q` — Expected: FAIL (`No module named 'videopipeline.seguimiento'`).
- [ ] **Step 3: Implement:** copiar la referencia; mensajes a `_()`; añadir `asegurar_pesos_s3fd`.
- [ ] **Step 4: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q`, y con checkpoints enlazados `$PY -m pytest tests/test_seguimiento.py -m slow -q` (descarga real de los pesos la primera vez) — Expected: PASS ambos; `RUTA_PESOS` existe y no aparece en `git status` (`*.pth` ignorado).
- [ ] **Step 5: Commit** `feat: S3FD face tracking with its own weight download`

---

### Task 4: `pipeline.run()` — pasos combinables y fase vertical

**Files:** Modify `videopipeline/pipeline.py`; Test `tests/test_pipeline.py`.

**Interfaces — Consumes:** Tasks 1–3 (importados en el espacio de nombres de `pipeline` para poder mockearlos: `convertir_vertical`, `preparar_seguimiento`, `es_ya_vertical`, `filtro_vertical`, `ANCHO_VERTICAL`, `ALTO_VERTICAL`). **Produces:** `run(config, on_progress) -> Path` (salida principal); `total_pasos(config) -> int`; `pasos_extra` se conserva tal cual.

Orden fijado (el cuerpo es del implementador):

```text
total_pasos = 3·audio + 1·silencios + (1 + horizontal)·subtítulos
            + caption·(1 si subtítulos, si no 2) + vertical·(1 + [encuadre == cara])
base: audio → remux (a .mov PCM intermedio si hay silencios, si no a tmp_final)
      silencios → auto-editor sobre el intermedio, o sobre rellenar_huecos_audio(original) si no hay audio
      sin audio ni silencios → base = original (desde_original=True)
subtítulos: _transcribir una vez sobre base → bloques
horizontal (si hay_horizontal): quemar bloques sobre base (desde_original si base es el original);
            si el quemado falla y base es el original → el trabajo falla; si no, degrada como hoy
            caption sobre lo publicable → publicar en final
vertical (si paso_vertical): _fase_vertical(fuente = base sin subtítulos — `final` si se publicó sin quemar, si no tmp_final o el original),
            destino = ruta_salida_vertical() si hay horizontal, si no final; degradar = hay_horizontal()
            si no hay horizontal y hay caption: caption sobre el vertical publicado
limpieza: borrar tmp_final y el intermedio; _fase_subtitulos ya no borra tmp_final
```

`_fase_vertical` = la de la referencia (`REF:videopipeline/pipeline.py`) con `desde_original`, mensajes `_()`, y: si `encuadre == "cara"` y `preparar_seguimiento` lanza (p. ej. pesos), aviso `_("No se pudo preparar el detector de caras: {error}. Se usa recorte central.")` y central. Etiqueta `_("Descargando detector de caras")` en el paso de caras cuando `RUTA_PESOS` no existe.

- [ ] **Step 1: Write the failing tests:** portar de `REF:tests/test_pipeline.py` la fixture `entorno_vertical` y los tests `test_vertical_*`, `test_solo_vertical*`, `test_ya_vertical_*`, `test_cara_sin_caras_cae_a_central`, sustituyendo `vertical=True` por `paso_vertical=True` y `modo="solo_vertical"` por `paso_audio=False, paso_silencios=False, paso_vertical=True`; el falso `convertir_vertical` recibe `desde_original` y lo registra (`f"vertical:{nombre}:{usa_ass}:{desde_original}:{filtro}"`). Más:

```python
def test_silencios_y_vertical(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    eventos = []
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_audio=False,
                                paso_vertical=True), eventos.append)
    assert [l.split(":")[0] for l in llamadas] == ["rellenar", "cortar", "vertical"]
    assert llamadas[-1].startswith("vertical:f.mp4:False:False:")
    assert {e["total"] for e in eventos if "step" in e} == {2}

def test_audio_y_vertical_sin_silencios(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                paso_silencios=False, paso_vertical=True), None)
    assert [l.split(":")[0] for l in llamadas][-1] == "vertical"
    assert (tmp_path / "f.mp4").exists() and (tmp_path / "f_vertical.mp4").exists()

def test_solo_vertical_desde_original(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    pipeline.run(PipelineConfig(video=video, salida=tmp_path, paso_audio=False,
                                paso_silencios=False, paso_vertical=True), None)
    assert llamadas == [l for l in llamadas if l.startswith("vertical")]
    assert llamadas[0].startswith("vertical:charla.mov:False:True:")

def test_solo_subtitulos_quema_desde_original(entorno_vertical, tmp_path):
    llamadas, video, _, _ = entorno_vertical
    r = pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4",
                                    paso_audio=False, paso_silencios=False,
                                    subtitulos=True), None)
    assert r.read_bytes() == b"MP4SUBS" and "quemar:original" in llamadas

def test_solo_subtitulos_falla_si_falla_el_quemado(entorno_vertical, tmp_path, monkeypatch):
    _, video, _, _ = entorno_vertical
    monkeypatch.setattr(pipeline, "quemar_subtitulos",
                        lambda *a, **k: (_ for _ in ()).throw(PasoFallido("boom")))
    with pytest.raises(PasoFallido):
        pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_audio=False,
                                    paso_silencios=False, subtitulos=True), None)

def test_solo_vertical_con_caption_lo_genera_sobre_el_vertical(entorno_vertical, tmp_path,
                                                              monkeypatch):
    llamadas, video, _, _ = entorno_vertical
    monkeypatch.setattr(pipeline, "_fase_caption",
                        lambda config, v, final, *a: llamadas.append(f"caption:{final.name}"))
    pipeline.run(PipelineConfig(video=video, salida=tmp_path, paso_audio=False,
                                paso_silencios=False, paso_vertical=True, subtitulos=True,
                                caption_seo=True), None)
    assert llamadas[-1] == "caption:charla_vertical.mp4"

def test_cara_sin_detector_cae_a_central(entorno_vertical, tmp_path, monkeypatch):
    llamadas, video, _, _ = entorno_vertical
    monkeypatch.setattr(pipeline, "preparar_seguimiento",
                        lambda *a, **k: (_ for _ in ()).throw(PasoFallido("sin pesos")))
    eventos = []
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4", paso_vertical=True,
                                encuadre="cara"), eventos.append)
    assert "crop=606:1080" in llamadas[-1]
    assert any("detector de caras" in e.get("warning", "") for e in eventos)
```

(La fixture `entorno` existente ya mockea extraer/limpiar/remux/cortar; añadir falso `rellenar_huecos_audio` que registre `"rellenar"`, y que el falso `quemar_subtitulos` registre `"quemar:original"` cuando `desde_original=True`.) Los totales ya fijados en `test_pipeline.py` (4, 6, 3, 7, 6) no cambian.
- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest tests/test_pipeline.py -q` — Expected: los nuevos FAIL; los existentes PASS.
- [ ] **Step 3: Implement** según el orden fijado.
- [ ] **Step 4: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: combinable steps and vertical phase in the pipeline`

---

### Task 5: Panel — "Pipeline completo", casillas por sección y sección Vertical

**Files:** Modify `app/widgets/panel_opciones.py`, `app/widgets/seccion_plegable.py` (solo si hace falta un setter del título), `app/main.py` (`_refrescar_boton`); Test `tests/test_app_widgets.py`, `tests/test_app_main.py`.

**Interfaces — Produces:** `check_completo` (tres estados, encima del acordeón), `check_audio` (primera fila de "audio"), `check_silencios` (primera fila de "silencios"), `check_vertical` + `combo_encuadre` + `aviso_encuadre` (sección nueva `"vertical"`, título `_("Formato vertical")`), `ETIQUETA_ENCUADRE` con `N_()`; `pasos_cambiados = Signal()`; `hay_pasos_de_video() -> bool`; `valores()` con `paso_audio`, `paso_silencios`, `paso_vertical`, `encuadre` y **sin** `modo`; la sección `"modo"` y los `radio_*` desaparecen. Secciones: `["audio", "silencios", "subtitulos", "caption", "vertical"]`, abierta por defecto `"audio"`. Cabecera: `"✓ " + título` con el paso activo.

- [ ] **Step 1: Write the failing tests:** reescribir los tests que usan `radio_*` o la sección `modo` (`test_app_widgets.py:33, 50-52, 82-85, 138, 683-709`) en términos de las casillas, y añadir:

```python
def test_panel_pasos_por_defecto(qtbot):
    panel = PanelOpciones(); qtbot.addWidget(panel)
    v = panel.valores()
    assert (v["paso_audio"], v["paso_silencios"], v["paso_vertical"]) == (True, True, False)
    assert (v["subtitulos"], v["caption_seo"], v["encuadre"]) == (False, False, "central")
    assert "modo" not in v
    assert panel.check_completo.checkState() == Qt.CheckState.PartiallyChecked

def test_panel_pipeline_completo_marca_y_desmarca_todo(qtbot):
    panel = PanelOpciones(); qtbot.addWidget(panel)
    panel.check_completo.click()
    casillas = (panel.check_audio, panel.check_silencios, panel.check_subtitulos,
                panel.check_caption, panel.check_vertical)
    assert all(c.isChecked() for c in casillas)
    assert panel.check_completo.checkState() == Qt.CheckState.Checked
    panel.check_completo.click()
    assert not any(c.isChecked() for c in casillas)
    assert not panel.hay_pasos_de_video()

def test_panel_cabecera_marca_pasos_activos(qtbot):
    panel = PanelOpciones(); qtbot.addWidget(panel)
    assert panel.secciones["audio"].cabecera.text().startswith("✓ ")
    assert not panel.secciones["vertical"].cabecera.text().startswith("✓ ")
    panel.check_vertical.setChecked(True)
    assert panel.secciones["vertical"].cabecera.text().startswith("✓ ")

def test_panel_vertical_habilita_encuadre_y_aviso_cara(qtbot):  # de la referencia
    ...

def test_panel_cargar_modo_antiguo(qtbot):
    panel = PanelOpciones(); qtbot.addWidget(panel)
    panel.cargar({"modo": "solo_silencios"})
    v = panel.valores()
    assert (v["paso_audio"], v["paso_silencios"]) == (False, True)

def test_panel_cargar_no_restaura_vertical(qtbot):
    panel = PanelOpciones(); qtbot.addWidget(panel)
    panel.cargar({"paso_audio": "false", "paso_silencios": "true", "paso_vertical": "true",
                  "encuadre": "difuminado"})
    v = panel.valores()
    assert (v["paso_audio"], v["paso_vertical"], v["encuadre"]) == (False, False, "difuminado")

def test_panel_encuadres_traducidos():
    # mismo patrón que el test de ETIQUETA_DISENO (test_app_widgets.py:425-428)
    ...

# test_app_main.py
def test_procesar_deshabilitado_sin_pasos(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    assert ventana.boton_procesar.isEnabled()
    for c in (ventana.panel.check_audio, ventana.panel.check_silencios):
        c.setChecked(False)
    assert not ventana.boton_procesar.isEnabled()
    assert ventana.boton_procesar.toolTip() != ""
```

- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest tests/test_app_widgets.py tests/test_app_main.py -q` — Expected: los nuevos FAIL.
- [ ] **Step 3: Implement.** `check_completo`: `setTristate(True)`; su estado se recalcula (con `blockSignals`) en cada `toggled` de un paso; en `clicked`, si no estaban todos → marcar todos, si estaban todos → desmarcar todos. Cada sección habilita sus controles solo con su paso marcado (patrón `_actualizar_subtitulos`). `cargar`: si no hay ninguna clave `paso_*` pero sí `modo` → `pasos_desde_modo`; nunca restaura `paso_vertical`; mantener la tolerancia actual a `"true"`/`"1"`. `main._refrescar_boton`: `setEnabled(pendientes and panel.hay_pasos_de_video())` y tooltip `_("Marca al menos un paso: audio, silencios, subtítulos o vertical.")` cuando no hay pasos; conectar `panel.pasos_cambiados` a `_refrescar_boton`.
- [ ] **Step 4: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: step checkboxes, select-all and a vertical section in the options panel`

---

### Task 6: Runner, worker, cola y ventana

**Files:** Modify `videopipeline/runner.py`, `app/worker.py`, `app/queue_model.py`, `app/main.py`; Test `tests/test_runner.py`, `tests/test_app_worker.py`, `tests/test_app_queue.py`, `tests/test_app_main.py`.

**Interfaces — Consumes:** Task 1 (`ruta_salida_vertical`, `modo_equivalente`), Task 5 (`PanelOpciones.check_audio`, `valores()` con `paso_*`). **Produces:** `done.salida_vertical: str | None` (solo si el fichero se escribió en esta ejecución: `st_mtime >= inicio - 1`); `EjecutorCola.salida_vertical = Signal(int, str)`; `Trabajo.salida_vertical: Path | None`; fila con `_("+ vertical")` y tooltip `_("Vertical: {ruta}")`.

- [ ] **Step 1: Write the failing tests:** portar de la referencia `test_done_salida_vertical` (parametrizado) y `test_done_ignora_vertical_de_ejecucion_anterior` (runner, con `paso_vertical=True, paso_audio=False`), `test_done_salida_vertical` (worker, parametrizado con `"None"`), `test_fila_muestra_vertical` (cola), `test_salida_vertical_actualiza_fila` y `test_cancelado_limpia_temporales_vertical` (ventana: temporales `.a_limpio_vertical_tmp.mp4` y `.a_vertical_tmp.mp4`). Más:

```python
def test_procesar_guarda_modo_equivalente(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    monkeypatch.setattr(ventana.ejecutor, "iniciar", lambda trabajos: None)
    ventana.panel.check_audio.setChecked(False)  # solo silencios
    ventana.procesar()
    guardado = ventana.ajustes.cargar_panel()
    assert guardado["modo"] == "solo_silencios"
    assert str(guardado["paso_audio"]).lower() in ("false", "0")
```

(Si `_procesando` queda a `True`, parchear `app.main.QMessageBox.question` para que el cierre del test no se quede esperando un diálogo modal, como en la referencia.)
- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest tests/test_runner.py tests/test_app_worker.py tests/test_app_queue.py tests/test_app_main.py -q` — Expected: los nuevos FAIL.
- [ ] **Step 3: Implement:** runner (`inicio = time.time() - 1` antes de `run`); worker (emitir en la rama `done`); cola; `main.py`: conectar la señal, `_limpiar_temporal` recorre los destinos de `PipelineConfig(video, salida=carpeta)`, `(..., paso_audio=False, paso_vertical=True).ruta_salida_vertical()` y `(..., paso_audio=False, paso_silencios=False, paso_vertical=True).ruta_salida_final()` con sufijos `_tmp`/`_subs_tmp`; `procesar()` guarda `{**valores, "modo": modo_equivalente(valores["paso_audio"], valores["paso_silencios"])}`.
- [ ] **Step 4: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: report the vertical output in the queue and clean its temp files`

---

### Task 7: Traducciones, documentación y verificación

**Files:** `locale/en/LC_MESSAGES/tsots.po` (+ `.mo`), `docs/TODO.md`, `README.md`, `README.es.md`.

- [ ] **Step 1:** `lanzador/traducir.sh`; rellenar en inglés todos los `msgstr ""` nuevos; volver a ejecutarlo para compilar. Expected: `msgfmt --statistics` sin cadenas sin traducir.
- [ ] **Step 2:** `docs/TODO.md`: añadir "elegir horizontal o vertical al publicar", "cortes exactos con scdet en el seguimiento de cara", "mostrar el horizontal en la cola antes de que termine el vertical". README (es/en): una línea en la lista de funciones sobre pasos combinables y vertical 9:16.
- [ ] **Step 3: Run** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q` y, con checkpoints enlazados, `$PY -m pytest -m slow -q` — Expected: PASS; quitar el enlace.
- [ ] **Step 4:** Prueba real con el runner sobre un clip derivado de un vídeo del usuario (en el scratchpad, sin modificar el original): silencios+vertical(cara)+subtítulos y solo vertical; comprobar 1080x1920, tasa entera, audio AAC, y que la app de la rama arranca con icono y cabecera.
- [ ] **Step 5: Commit** `docs: translate new strings and document combinable steps and vertical output`
