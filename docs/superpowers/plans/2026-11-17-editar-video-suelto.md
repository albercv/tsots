# Editar con Claude un vídeo que ya es un short — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que «Editar con Claude» edite también el propio vídeo final cuando es vertical 1080×1920 (botón contextual y automático al procesar), publicando el editado.

**Architecture:** `shorts.editar_video` encola un único trabajo con el final del vídeo, las palabras de su transcripción y zonas calculadas con los ajustes guardados en la ficha, reutilizando `_encolar_edicion`/`edicion.encolar`. Cada trabajo lleva un `grupo` para que la barra no mezcle vídeos de la misma carpeta. La ventana elige qué editar al pulsar el botón, encola automáticamente al terminar el procesado de las filas del lote, y `_publicar` sube el editado si está al día.

**Tech Stack:** Python 3 (`.venv-clearvoice`), PySide6, pytest-qt, ffprobe.

**Spec:** `docs/superpowers/specs/2026-11-17-editar-video-suelto-design.md` (y, de fondo, `docs/superpowers/specs/2026-11-17-edicion-shorts-design.md`).

## Global Constraints

- Repo `~/Documents/personalProjects/limpiadorVideo`; worktree `~/Documents/personalProjects/tsots-editar-video`, rama `feature/editar-video-suelto` desde `origin/develop`, sin upstream. Nunca push a `develop`/`main`.
- Commits en inglés, **sin atribución de IA**. Código, comentarios y GUI en español; textos nuevos con `_()`/`N_()`, traducidos en `locale/en/LC_MESSAGES/tsots.po` y compilados con `lanzador/traducir.sh`.
- Tests: `PY=~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python; QT_QPA_PLATFORM=offscreen $PY -m pytest -q` (puede fallar solo `tests/test_pipeline.py::test_solo_vertical_cara_con_subs`, por el modelo de caras que no está en el worktree).
- Solo finales de exactamente 1080×1920. El final limpio nunca se toca ni se borra. Destino `<stem>.editado.mp4`.
- Ningún test escribe en el `~/TSOTS` real (las protecciones de `tests/conftest.py` ya apuntan `DIR_EDICION` y `DIR_MUSICA` a temporales).

## Review Focus

1. **Dos vídeos sueltos que salen a la misma carpeta** (p. ej. `~/Downloads`): cada fila ve solo su barra. → Task 1.
2. **Trabajos encolados por versiones anteriores, sin `grupo`**: siguen agrupándose por carpeta. → Task 1.
3. **Final que no es 1080×1920** (horizontal, o vertical 720×1280): el botón lo explica y el automático no hace nada. → Tasks 2, 4 y 5.
4. **Pulsar «Procesar» otra vez con la casilla marcada sin que haya nada que hacer**, o con un editado ya al día: no se encola otra edición. → Task 5.
5. **Editado más viejo que el final** (el final se rehízo): «Publicar…» sube el final, no el editado. → Tasks 3 y 6.

---

### Task 1: `grupo` en el trabajo y agrupación por tanda

**Files:**
- Modify: `videopipeline/edicion/__init__.py` (`encolar`, ~l.46-81), `videopipeline/edicion/estado.py` (`_Trabajo`, `_trabajos`, `leer`), `videopipeline/shorts.py` (`_encolar_edicion`)
- Test: `tests/test_edicion_encolar.py`, `tests/test_edicion_estado.py`

**Interfaces:**
- Produces: `encolar(..., encuadre: str, dir_edicion: Path = DIR_EDICION, grupo: str | None = None) -> list[Path]` → `trabajo.json["grupo"] = grupo or str(carpeta)`. `estado.leer` agrupa por `Path(trabajo["grupo"])` si existe, si no por `Path(origen).parent`; la clave del dict devuelto es ese `Path`.

- [ ] **Step 1: Worktree.** `git -C ~/Documents/personalProjects/limpiadorVideo fetch origin && git -C ~/Documents/personalProjects/limpiadorVideo worktree add ../tsots-editar-video -b feature/editar-video-suelto origin/develop && git -C ../tsots-editar-video branch --unset-upstream`; copiar spec y plan desde `~/Documents/personalProjects/VideoEditor/docs/superpowers/` a `docs/superpowers/specs|plans/`.
- [ ] **Step 2: Tests.**
  - `test_encolar_guarda_el_grupo`: con `grupo="/x/v.mp4"` → `trabajo.json["grupo"] == "/x/v.mp4"`; sin él → `== str(carpeta)`.
  - `test_estado_agrupa_por_grupo`: dos trabajos con origen en la misma carpeta y grupos distintos → dos entradas, cada una con `total == 1`.
  - `test_estado_sin_grupo_agrupa_por_carpeta`: trabajo sin `"grupo"` (como los viejos) → clave `Path(origen).parent`.
- [ ] **Step 3: Run → FAIL.**
- [ ] **Step 4: Implement.** `_encolar_edicion` sigue sin pasar `grupo` (sale la carpeta de shorts).
- [ ] **Step 5: Run → PASS** (`tests/test_edicion_encolar.py tests/test_edicion_estado.py tests/test_shorts.py`).
- [ ] **Step 6: Commit** `feat: group edit jobs by batch so videos in one folder don't mix` (incluye spec y plan).

### Task 2: `shorts.editar_video`

**Files:**
- Modify: `videopipeline/shorts.py` (junto a `editar_existentes`)
- Test: `tests/test_shorts.py` (fixtures `ficha_con_base`, `dir_edicion`)

**Interfaces:**
- Consumes: `_encolar_edicion(carpeta, nombre, config, opciones, base, cortes, grupo=None)` (añadir `grupo` y pasarlo a `edicion.encolar`), `_Pasada`, `_transcrita`, `zonas_edicion.calcular`, `resolucion_video`, `HORIZONTAL`, `VERTICAL` de `videopipeline.ficha`.
- Produces: `editar_video(ficha: Ficha, config: PipelineConfig, opciones: OpcionesShorts) -> int` (1 encolado, 0 si ya esperaba; `PasoFallido` si no hay final, no es 1080×1920 o falta la transcripción). `es_final_vertical(ficha: Ficha) -> bool` (final existe y `resolucion_video(final) == (1080, 1920)`; nunca lanza). `editado_al_dia(final: Path) -> Path | None` (`final.with_name(final.stem + ".editado.mp4")` si existe y su mtime ≥ el del final).

- [ ] **Step 1: Tests** (monkeypatch `shorts.resolucion_video` para devolver `(1080, 1920)` del final y lo que toque de la base; escribir `ficha.final` como un fichero y los `artefactos` con `ajustes`):
  - `test_editar_video_encola_el_final_con_todas_las_palabras`: `editar_video(...) == 1`; un único trabajo; `trabajo.json`: `origen == str(final)`, `destino == str(final.with_suffix(".editado.mp4"))`, `grupo == str(final)`, `estilo`; `palabras.json` == todas las palabras de `_palabras()` (no un tramo).
  - `test_zonas_con_los_ajustes_guardados_del_final_horizontal`: `artefactos[HORIZONTAL].ajustes = {"subtitulos": {"diseno": <un diseño de PRESETS distinto del panel>, "posicion": 75, "tamano": 150}, "titulo": "X"}` y el panel con otros valores → `zonas.json == zonas_edicion.calcular(replace(config, subtitulos=True, diseno=<ese>, posicion_subs=75, tamano_subs=150), "central", (1080, 1920), con_titulo=True)` y `zonas["franja_zoom"] is None`.
  - `test_sin_subtitulos_ni_titulo_guardados`: ajustes `{}` (aunque el panel tenga subtítulos) → `zonas["subtitulos"] is None` y `zonas["titulo"] is None`.
  - `test_vertical_unico_usa_los_ajustes_del_vertical`: `ficha.final.ruta == ficha.ruta_final(False)`, `artefactos[VERTICAL].ajustes = {"vertical": {"encuadre": "difuminado"}, "subtitulos": {...}}`, base 1920×1080 → `zonas.json == zonas_edicion.calcular(<config con esos subtítulos>, "difuminado", (1920, 1080), con_titulo=False)` y `franja_zoom` no es `None`.
  - `test_editado_al_dia`: sin editado → `None`; editado con mtime ≥ final → su ruta; más viejo → `None`.
  - `test_editar_video_rechaza_lo_que_no_es_1080x1920`: `resolucion_video` → `(1920, 1080)` y luego `(720, 1280)` → `PasoFallido` en los dos; `es_final_vertical` → `False`.
  - `test_editar_video_sin_transcripcion` → `PasoFallido`; `test_editar_video_dos_veces` → `1` y luego `0`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** según el spec 4.1. Ajustes: `HORIZONTAL` si `ficha.final.ruta != ficha.ruta_final(False)`, si no `VERTICAL`; encuadre `"central"` y resolución `(1080, 1920)` en el primer caso; en el segundo, el encuadre de `ajustes["vertical"]["encuadre"]` y `resolucion_video(pasada.base)`. `config` = `replace(config, subtitulos="subtitulos" in ajustes, diseno=…, posicion_subs=…, tamano_subs=…)` (solo los que estén). `con_titulo=bool(ajustes.get("titulo"))`. No duplica si existe `pendientes/f"{ficha.nombre} - {final.stem}"`.
- [ ] **Step 4: Run → PASS** (`tests/test_shorts.py`).
- [ ] **Step 5: Commit** `feat: queue a single vertical final for Claude editing`.

### Task 3: Rehacer un final borra su editado

**Files:**
- Modify: `videopipeline/reproceso.py` (donde se asigna `ficha.final = Huella.de(destino)`: ~l.418 y la rama del vertical único ~l.502-505)
- Test: `tests/test_reproceso.py`

**Interfaces:**
- Produces: helper `_borrar_editado(final: Path) -> None` en `reproceso.py`: `final.with_name(final.stem + ".editado.mp4")` y su `.tmp`, `unlink(missing_ok=True)`.

- [ ] **Step 1: Test** `test_escribir_un_final_nuevo_borra_su_editado`: con un `<final_stem>.editado.mp4` y su `.tmp` junto al final, la pasada que vuelve a escribir el final los deja sin existir; el final sigue ahí. Uno igual para el vertical único si el fichero de tests ya tiene un caso de solo vertical.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implement** (llamar al helper justo después de cada asignación de `ficha.final`). **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `fix: drop a stale edited file when its final is rebuilt`.

### Task 4: Botón «Editar con Claude…» y barra por vídeo

**Files:**
- Modify: `app/widgets/panel_opciones.py` (botón ~l.474-482, señal l.222, tooltip de la casilla ~l.462-471), `app/main.py` (`_editar_shorts_existentes` → `_editar_con_claude` ~l.673-717, conexión ~l.271, `_refrescar_boton` ~l.1068-1072, `_refrescar_edicion` ~l.719-735), `locale/en/LC_MESSAGES/tsots.po`
- Test: `tests/test_app_widgets.py`, `tests/test_app_main.py` (helpers `_ventana`, `_ficha_hecha`, `_con_shorts_hechos`, `_eligiendo_la_fila`, `_editando_shorts`)

**Interfaces:**
- Consumes: `shorts.editar_video`, `shorts.es_final_vertical`, `shorts.editar_existentes`.
- Produces: `PanelOpciones.boton_editar_con_claude` (texto `_("Editar con Claude…")`) y señal `editar_con_claude`; `MainWindow._editar_con_claude()`.

- [ ] **Step 1: Tests.**
  - `test_boton_editar_activo_con_shorts_o_con_final` (claude disponible): fila sin nada → inactivo; con shorts → activo; solo con `ficha.final` → activo; procesando → inactivo; sin claude → inactivo.
  - `test_editar_elige_el_video_si_no_hay_shorts`: `es_final_vertical` → `True`, sin shorts → llama a `editar_video` con el estilo y el encuadre del panel, lanza el agente.
  - `test_editar_elige_los_shorts_si_no_hay_final_vertical` → llama a `editar_existentes`.
  - `test_editar_pregunta_si_hay_las_dos_cosas`: monkeypatch del diálogo de elección (un método `_preguntar_que_editar(n_shorts, nombre) -> str | None` en la ventana, que devuelve `"shorts"`, `"video"` o `None`) → con `"video"` llama a `editar_video`; con `None` no llama a nada.
  - `test_editar_avisa_si_no_hay_nada_que_editar`: final no vertical y sin shorts → `QMessageBox.warning` con un texto que menciona «1080×1920».
  - `test_la_barra_del_video_va_en_su_fila`: `estado_edicion.leer` monkeypatcheado → `{ficha.final.ruta: estado}` → la fila tiene ese `edicion`; y con `{carpeta_shorts: e2}` y sin estado del final → `e2`.
  - Ajustar los tests existentes de `boton_editar_shorts`/`editar_shorts` a los nombres nuevos.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** según el spec 4.3. Tooltip del botón: explica los dos casos (shorts o el vídeo final vertical 1080×1920), que usa el estilo de arriba y que cada uno es una ejecución de Claude. Tooltip de la casilla: «Edita con Claude los shorts al crearlos y los vídeos verticales al procesarlos». `_refrescar_edicion`: para cada fila, primero `estados.get(ficha.final.ruta.resolve())`, luego la carpeta de shorts.
- [ ] **Step 4: Run → PASS** (`tests/test_app_main.py tests/test_app_widgets.py`), traducciones con `lanzador/traducir.sh`.
- [ ] **Step 5: Commit** `feat: one Claude edit button for shorts or the vertical video itself`.

### Task 5: Automático al procesar

**Files:**
- Modify: `app/main.py` (`procesar` ~l.763-830, `_al_terminar_trabajo` ~l.979-1008)
- Test: `tests/test_app_main.py`

**Interfaces:**
- Consumes: `shorts.editar_video`, `shorts.es_final_vertical`, `shorts.editado_al_dia` (Task 2).
- Produces: `MainWindow._editar_al_terminar: dict[int, tuple[PipelineConfig, OpcionesShorts]]` (fila → config y opciones del lote al lanzar).

- [ ] **Step 1: Tests** (monkeypatch `app.main.shorts.editar_video` para registrar llamadas y `_lanzando` para el ejecutor):
  - `test_procesar_con_la_casilla_encola_el_video_al_terminar`: casilla marcada, `procesar()`, luego `_al_terminar_trabajo(fila, True, …)` → `editar_video` llamado una vez con el estilo del panel.
  - `test_sin_la_casilla_no_encola`.
  - `test_crear_shorts_no_encola_el_video`: `_crear_shorts()` y su fin → sin llamada.
  - `test_plan_vacio_no_encola`: vídeo ya procesado sin nada que hacer (la rama `plan.vacio`) → sin llamada.
  - `test_editado_al_dia_no_se_repite`: existe `<final>.editado.mp4` más nuevo que el final → sin llamada.
  - `test_final_no_vertical_no_avisa`: `editar_video` lanza `PasoFallido` por resolución → la fila queda `HECHO` sin aviso; otro error → aviso en la fila.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** En `procesar`, para cada fila que se envía de verdad (no la rama `plan.vacio`), si la casilla está marcada y hay claude: `self._editar_al_terminar[fila] = (config, opciones)`. En `_al_terminar_trabajo`, `pop(fila)`; si `ok`, `es_final_vertical(ficha)` y no hay editado al día → `editar_video` en `try`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: edit vertical videos with Claude right after processing`.

### Task 6: Publicar el editado

**Files:**
- Modify: `app/main.py` (`_publicar` ~l.624-640), `app/widgets/dialogo_publicar.py` (cabecera ~l.281)
- Test: `tests/test_app_main.py`, `tests/test_app_publicar_shorts.py`

**Interfaces:**
- Consumes: `shorts.editado_al_dia` (Task 2).

- [ ] **Step 1: Tests.**
  - `test_publicar_sube_el_editado_al_dia`: con `<final>.editado.mp4` más nuevo → `DialogoPublicar` (monkeypatcheado) recibe esa ruta; con uno más viejo → recibe el final.
  - `test_cabecera_marca_el_editado`: `DialogoPublicar(<x>.editado.mp4, …).cabecera.text()` termina en «(editado)»; con un vídeo normal, no.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: publish the edited video when it is up to date`.

### Task 7: Docs, suite y prueba real

**Files:**
- Modify: `README.md`, `README.es.md` (sección «Edit shorts with Claude»/«Editar shorts con Claude»), `docs/superpowers/specs/2026-11-17-edicion-shorts-design.md` (sección 12 que remita al spec nuevo)

- [ ] **Step 1: Docs.** README (ES/EN): el botón edita los shorts o el propio vídeo vertical 1080×1920; la casilla también edita los vídeos verticales al procesarlos; «Publicar…» sube el editado.
- [ ] **Step 2: Suite completa → PASS.**
- [ ] **Step 3: Prueba real** (controlador, con permiso del usuario ya dado para editar su `odin_17_11`): `editar_video` sobre la ficha `72b77b019f5e` con el agente del worktree (`TSOTS_EDICION_PYTHON` = Python del venv principal) → `odin_17_11_limpio.editado.mp4` junto al final; revisar `verificacion.png`.
- [ ] **Step 4: Commit** `docs: edit a single vertical video with Claude`; push y PR a `develop` (con la confirmación del usuario).
