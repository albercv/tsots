# The Silence of the Shorts — development notes

Desktop app (PySide6) that cleans a video's audio with ClearVoice
(MossFormer2_SE_48K), cuts silences with auto-editor, optionally
transcribes/burns subtitles with Whisper and writes an SEO caption
with a local LLM through Ollama. User docs: `README.md` / `README.es.md`.

## Running

Double-click `TheSilenceOfTheShorts.command`, or from a terminal:

```bash
./TheSilenceOfTheShorts.command
```

CLI without GUI:

```bash
source .venv-clearvoice/bin/activate
python limpiarVideo.py input.mov output.mp4 [--caption --marca "…"]
```

## System requirements (Homebrew)

```bash
brew install python@3.11 ffmpeg ffmpeg-full auto-editor gettext
brew install --cask ollama-app && ollama pull qwen3.5:9b   # SEO caption
```

- `ffmpeg` / `ffprobe`: audio extraction and remux.
- `ffmpeg-full`: the only build with the `ass` filter (libass) needed to
  burn subtitles. Looked up at `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`
  (see `videopipeline/steps.py`).
- `auto-editor`: silence cutting.

`instalar.command` does all of this idempotently; `lanzador/construir_app.sh`
rebuilds the app bundle.

## Python environment (recreate if the folder moves)

The venv bakes absolute paths. If you move the folder, delete and recreate:

```bash
rm -rf .venv-clearvoice
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv-clearvoice
.venv-clearvoice/bin/python -m pip install -r requirements.txt
.venv-clearvoice/bin/python -m pip install -e .
```

`requirements.txt` pins arm64 wheels (torch, PySide6): Apple Silicon only.

## Models

- `checkpoints/MossFormer2_SE_48K/` (221 MB) is NOT in git; the installer
  downloads it from HuggingFace. If missing, ClearVoice downloads it on
  first use.
- Whisper runs on two engines with the same model names (`small`, `medium`,
  `turbo`; default `turbo` = large-v3-turbo). `mlx-whisper` uses the Apple
  GPU and needs macOS 14+ (`mlx-community/whisper-*` repos, ~10x faster
  than CPU). On macOS 13 mlx is not installed (marker in
  `requirements.txt`) and `faster-whisper` on CPU is used instead. The
  choice is automatic (`subtitles.usa_mlx()`). Models live in the global
  cache `~/.cache/huggingface/hub/` and are downloaded on first use
  (turbo ~1.6 GB).
- Ollama models are managed by Ollama (`ollama list`). The GUI lists them
  from `GET /api/tags` and disables the ones that exceed the GPU memory
  budget (75 % of RAM minus 1.5 GB of context, see `videopipeline/ollama.py`).

## Branches and releases

**Nobody pushes to `develop` or `main`. Every change goes in through a
pull request.** The repository ruleset requires it; as an admin GitHub lets
you bypass it and warns "Bypassed rule violations". Treat that warning as a
mistake, never as a shortcut.

- `main`: stable. Only receives PRs from `develop`, once the full test suite
  passes and the app has been smoke-tested. Every release is an annotated tag
  `vX.Y.Z` on `main`. Users install from here. A PR opened against `main`
  from any other branch is moved to `develop` automatically
  (`.github/workflows/retarget-pr.yml`).
- `develop`: integration branch and GitHub default. Receives PRs from
  short-lived branches.
- `feature/*`, `fix/*`, `docs/*`: branches off `develop`, one per change.

Day to day:

```bash
git checkout develop && git pull
git checkout -b feature/my-change
# ...commits...
git push -u origin feature/my-change
gh pr create --base develop --fill
```

Merge the PR on GitHub with **Create a merge commit**, then delete the
branch.

To cut a release:

```bash
gh pr create --base main --head develop --title "Release vX.Y.Z" --body "..."
# after merging it on GitHub:
git checkout main && git pull
git tag -a vX.Y.Z -m "vX.Y.Z: summary"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
```

## Tests

```bash
QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow"
```

Add `-m slow` for the integration tests that load the real models (and
call the real Ollama if it is running; they skip otherwise).

Tests never reach the Internet or the real Keychain: an autouse fixture in
`tests/conftest.py` blocks outbound `httpx` traffic and routes every
`security` call to an in-memory Keychain (`tests/redes_falsos.py`); `slow`
tests may only reach Hugging Face (Whisper model). Another autouse fixture
makes every real modal dialog (`exec()`, the `QMessageBox`/`QFileDialog`/
`QInputDialog` statics) raise instead of blocking the offscreen run forever;
tests that need one replace it with `monkeypatch`. The only
exception to the network rule is `-m lenta` (deselected by default in `pytest.ini`):
`tests/test_redes_real.py` uploads a 5 s test video to **TikTok as a draft
only**, using the key in the Keychain and the profile from Networks… (or
`TSOTS_PERFIL_REDES`); it skips when there is no key.

```bash
QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m lenta tests/test_redes_real.py -s
```

## Architecture

```
app/                 PySide6 GUI (main window, queue model, worker, widgets)
videopipeline/       pipeline (steps, subtitles, caption, opening title,
                     glossary, ollama client, errors → diagnostics, runner
                     subprocess, i18n)
videopipeline/redes/ publishing to TikTok, YouTube, Instagram, X, Facebook
clearvoice/          ClearVoice library (upstream, Apache-2.0)
lanzador/            native launcher + build script for the .app bundle
locale/              gettext catalogs (see Translations)
tests/               pytest + pytest-qt
```

Main window (`app/main.py`): header on top; drop zone and queue on the
left; on the right, the option sections (`PanelOpciones`, one
`SeccionPlegable` per group from `app/widgets/seccion_plegable.py`, joined
by an `Acordeon` that keeps exactly one open) inside a `QScrollArea`, and
below it, outside the scroll and with a fixed height, a `QTabWidget` with
`VistaPrevia` and `PanelCaption`. Controls live in each section's
`contenido`, so enable/disable logic never touches the headers, and
`valores()` does not depend on which section is open.

The GUI never runs the pipeline in-process: `app/worker.py` launches
`python -m videopipeline.runner --config <json>` and parses JSON progress
lines (`step/total/label/percent`, `warning`, `error` + `diagnostico`,
`done`). Heavy imports (torch, mlx, faster-whisper) therefore only happen in
the subprocess.

### Fichas y reproceso

A *ficha* (record) remembers what was done to one video so a later pass
reuses it instead of starting over. Design:
`docs/superpowers/specs/2026-11-01-reprocesar-design.md`. The CLI
(`limpiarVideo.py`, `limpiarAudio.py`) does not use records.

| Module | Role |
|---|---|
| `videopipeline/ficha.py` | `Ficha`, `Artefacto`, `Huella`; storage (`guardar`, `cargar`, `olvidar`, `ocupa`) and recognition (`reconocer`). No Qt. |
| `videopipeline/reproceso_plan.py` | Pure logic, writes nothing: `revisar` (what to ask before Process), `planificar` (ordered list of `Accion`s). Rules R0–R10. |
| `videopipeline/reproceso.py` | `ejecutar`: runs a plan, one method per `Accion`, saving the record after each. |
| `videopipeline/runner.py` | The `reproceso` key (below). |
| `app/queue_model.py`, `app/widgets/dialogo_reproceso.py`, `app/main.py` | Queue summary and size, "Process again", "Forget this video", the "Steps already done" dialog. |

**Where records live.** `fichas/<id>/` in the app folder, next to
`audio_procesado/` (`DIR_FICHAS = BASE_DIR / "fichas"`; both gitignored).
`<id>` is `uuid4().hex[:12]`. `desinstalar.command` deletes the folder;
"Forget this video" deletes one record (`olvidar`) and never touches the
outputs. The folder holds:

- `ficha.json`: original, outputs, artifacts and their settings, and the
  fingerprint (`Huella`: real path, size, mtime) of every file it
  recognises. Written atomically: hidden temp file, then `replace`.
  `cargar` returns `None` for a missing file, and for a damaged one
  (type-checked, so a valid JSON that is not a record counts too) with a
  log warning; it never breaks the queue.
- the artifact files below, and `tmp/` for the pass in progress (emptied
  at the start, deleted at the end, whatever the outcome).
- `original.<ext>`: only for an old output that has no known original and
  is about to be overwritten; it is moved here first. It stays when the
  real original is adopted later, and "Forget this video" names any
  `original.*` it is about to delete.

**Artifacts and keys.** `Ficha.artefactos` maps a key to an `Artefacto`
(`clave`, `archivo`, `ajustes`, `linea_tiempo`). An artifact is valid if
its file exists and its `clave` (and `linea_tiempo`, where it applies)
equals what the planner computes now. `clave()` is a short hash of the
settings that matter. The timeline of the base is `clave(audio, silencios)`
when it was cut and, uncut, `Ficha.linea_original()`: `"original"` with a
real original, `"legado"` when the old final (or its copy in the record)
stands in for it. Planner and executor use the same helper.

| Key | File in `fichas/<id>/` | `clave` hashes | `ajustes` holds |
|---|---|---|---|
| `audio` | `audio_limpio.flac` | task + model | `tarea`, `modelo`; `linea_tiempo` is that of the video it was cleaned from (R9) |
| `base` | `base.mp4`, or none when the final is the base (R3) | settings of the steps applied + timeline | `{"audio": …, "silencios": …}`, only the steps applied |
| `transcripcion` | `transcripcion.json` | language, Whisper model, glossary key | the same; `linea_tiempo` is that of the base it came from |
| `titulo` | none: the text is the whole artifact | `clave(texto)` | `{"texto": …}`, from the transcript (action `TITULO`); no timeline, so valid while present |
| `horizontal` | none: the final `.mp4` is in `ficha.final` | timeline + subtitle settings + title text | `{"subtitulos": …}` if burned, `"titulo"` if it has a title |
| `caption` | `caption.md` (the `.md` next to the final is a copy) | `modelo_caption` | `{"caption": …}` |
| `seguimiento` | `cara.cmd` | timeline of the base only: the picture depends on the cuts, not the audio | `x_inicial` |
| `vertical` | none: `ficha.vertical`, or `ficha.final` if it is the only output | timeline + framing (+ subtitle and title settings) | `{"vertical": …}`, `{"subtitulos": …}` if burned, `"titulo"` if it has a title |

`Ficha.pasos_hechos()` derives the ✓ in the queue from these.
`ficha.desactualizado` (`{"vertical"}`) marks an output that no longer
matches its base.

**Opening title in a record.** `TITULO` is an internal action, not a
panel step, and asks nothing in the reprocess dialog. It runs between
`TRANSCRIBIR` and `QUEMAR` (progress label "Generando título"). The text
is generated when it is missing (box just ticked, new video, or a new
subtitle transcript, e.g. "redo the subtitles"), reused when only the cut
changes and no subtitles are burned (with subtitles, a new cut means a new
transcript, hence a new title), and not touched by redoing the caption. If
regenerating fails, the previous title stays and is the one burned. Ticking
or unticking the box re-burns only the outputs the app made, still on disk
and unchanged since (its `Huella` matches the file), whose base still holds,
and only on a record with a true original (`Ficha.original_verdadero()`):
horizontal and vertical, without the R7 question. An output the user edited
or deleted outside the app is never touched for the title alone. It does not
transcribe again when the record already has a transcript; with none (e.g. a
video processed without subtitles or caption), ticking the box transcribes
first. On legacy or adopted outputs, or when no base can be rebuilt, the title
is only added when that output is rebuilt for another reason. Without a true
original the old final stands in for it and may already carry subtitles or a
title, so no title is burned on it at all (R2, wider than
`subs_quemados_sin_base`). With the box on and the model
unavailable, each "Process again" retries the title and burns it again.
The title text is part of the `clave` of the burned outputs, so a different
title re-burns them.

**Rules.** Implemented in `reproceso_plan.py` (the executor only does what
the plan says); numbers match comments in the code.

| Rule | In short |
|---|---|
| R0 | An artifact is reused if its `clave` matches; otherwise it is redone from the nearest valid ancestor, never further back. Redoing it invalidates what depends on it, nothing it depends on. |
| R1 | Unticking a step keeps what exists (caption, subtitles). |
| R2 | Subtitles are never burned over a video that has them: always onto the base. |
| R3 | The base is kept apart (`base.mp4`) only if the final has subtitles; without them the final is the base. |
| R4 | The caption depends on the text, not the timing: cutting silences or redoing subtitles does not touch it. |
| R5 | Any transcript serves the caption, whatever its timeline; with none, only the final's audio is transcribed (no video encode). |
| R6 | A step already done with other settings is "done, with other settings": ask, and keep by default. |
| R7 | If the base, transcript or subtitle design changes and a vertical exists, offer to regenerate it; if declined, mark it `desactualizado`. |
| R8 | What is redone unasked (subtitles after a cut, an outdated vertical) uses the settings saved in the record: subtitle design, language, Whisper model, framing. Glossary and brand context are the current ones. |
| R9 | Cleaned audio is tied to its timeline. If it was cleaned from an already-cut base and the cut changes, the audio is cleaned again from the whole original (the only case). |
| R10 | The app replaces its own outputs instead of duplicating them: when a vertical-only video gains a horizontal, `x_vertical.mp4` is deleted and `x_limpio.mp4` + `x_limpio_vertical.mp4` are written; the `.md` and `.srt` move with the final. Only files the record lists, with a matching fingerprint, are ever deleted. |

**Recognition (`reconocer`).** A dragged file belongs to a record if its
real path is the original's or an output's and size and mtime match. If
the path matches but the fingerprint does not (edited outside the app),
the user is warned and the record drops that fingerprint and what only
described that file (`_soltar`); nothing else is deleted. An edited
original is adopted back into its record; an edited output starts a new
legacy record. Outputs written before records existed (`*_limpio.mp4`,
`*_vertical.mp4`) become a *legacy* record: the file is its own final and
overwrites itself, and a `.md` / `.srt` next to it are imported as caption
and transcript (an `.srt` also sets `subs_quemados_sin_base`, which blocks
subtitles and subtitled verticals until the original is dragged in).

Dragging the real original later adopts (`_adoptar`) the record whose final
is its computed output (horizontal, vertical-only, or else the companion
`x_limpio_vertical.mp4`) when that record has no real original
(`Ficha.original_verdadero()`: `original` missing, `legado`, or the copy in
the record folder), instead of creating a second one with the same
outputs. An output on disk that no record owns is adopted the same way,
with a warning (it may be another video's), unless it is more than 1 s
longer than the original (`duracion_video`; adopted if it cannot be
measured). Adopting drops `audio`, `base`, `seguimiento`, `horizontal`,
`vertical` and any transcript not on the `"legado"` timeline: they were
made from the old final. A dropped horizontal with subtitles sets
`subs_quemados_sin_base`; an existing vertical is marked `desactualizado`.
A record without outputs gets `name (2)` when another record uses its
outputs or a file it does not own is in the way (`_nombre_libre`), both
when it is created and when Process moves it to the current output folder
(`mover_salidas`).

**Writes.** Outputs are written to a hidden temp (`.{stem}_tmp{suffix}`)
and replace the previous file only when complete; moves across folders use
`shutil.move` (the output folder can be on another disk). The record is
saved after each action with only what finished, so a cancelled or failed
pass leaves the earlier outputs and record as they were.
`_comprobar_propio` refuses to replace or delete a file the record does
not list or that changed outside the app; `ejecutar` checks every
destination once before the first action, and again when replacing it. Degradation is unchanged: a
failed caption or vertical leaves a warning, and failed subtitles with
other steps save the video without them.

**Runner protocol.** The job JSON passed with `--config` is a
`PipelineConfig` as before; without the `reproceso` key the runner calls
`pipeline.run` exactly as it always did. The GUI never sends that: a row
without `ficha_id` (e.g. after "Forget this video") is recognised again
with `reconocer` before planning. With it:

```json
{ "video": "…", "caption_seo": true, "…": "…",
  "reproceso": { "ficha": "3f9c1a2b7d40",
                 "rehacer": ["subtitulos"],
                 "regenerar_vertical": false } }
```

- `ficha`: record id. If `fichas/<id>/ficha.json` is missing or damaged
  the job fails with a message telling the user to drag the original in.
- `rehacer`: panel steps (`audio`, `silencios`, `subtitulos`, `caption`,
  `vertical`) the user chose to redo in the dialog; steps not ticked in
  the config are ignored.
- `regenerar_vertical`: the R7 answer.

The runner pops the key before `PipelineConfig.from_datos`, validates with
`validar(exigir_paso_de_video=False)` ("caption only" ticks no video
step), calls `planificar`, and then `ejecutar`. A plan with `error` fails
the job (e.g. the original is missing); an empty plan runs nothing and
returns what already exists. Progress events are the usual
`step/total/label/percent` and `warning`; the final event adds the record
id: `{"done": true, "salida": …, "salida_vertical": …, "ficha": "<id>"}`.
The GUI reads the record again afterwards for the row's ✓ summary, size
and outputs. It evaluates `planificar` itself before launching so that
"nothing to do" never starts a subprocess.

**Strings.** Everything user-facing is marked with `_()` / `N_()`;
translate with `lanzador/traducir.sh` (see Translations). Step names appear
inside sentences ("… already has {paso} …") and in the queue summary, so
their `msgstr`s must work as bare nouns.

**Testing.** No test needs ffmpeg or a model:
`tests/falsos_pipeline.py` replaces the steps in both `pipeline` and
`reproceso`, and `tests/conftest.py` makes `ficha.duracion_video` return
0.0 ("could not measure") unless a test sets durations.

- `tests/test_ficha.py`: storage, damaged files, recognition, legacy
  outputs, same-name originals.
- `tests/test_reproceso_plan.py`: the cases table of the design, rule by
  rule.
- `tests/test_reproceso.py`: the executor (which files it writes, cancel
  and failure, outputs on another disk, files changed outside the app).
- `tests/test_runner.py`, `tests/test_app_queue.py`,
  `tests/test_app_main.py`, `tests/test_app_widgets.py`: protocol, queue,
  dialog and forget.
- `tests/test_cli_compat.py`: the CLI is untouched and the uninstaller
  deletes `fichas/`.

```bash
QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -q
```

The `slow` tests (models loaded for real) skip when the checkpoints are
missing. To check by hand with a short clip: process it with audio,
silences, subtitles and caption; look inside `fichas/<id>/` (`ficha.json`,
`audio_limpio.flac`, `base.mp4`, `transcripcion.json`, `caption.md`); drag
`clip_limpio.mp4` in again (same row, back to "waiting", ✓ summary) and
tick only **Vertical** (no new transcription, one video encode); then tick
**Silence cutting** with another margin and read the warning.

### Opening title

The first 5 seconds of the horizontal and the vertical (and, through the
contract below, of the shorts) can carry a title: 3 to 5 keywords in large
type at the top, Titan One, white with a black border and a gold outline
shifted down-right. The checkbox **Título al inicio** (*Opening title* in
the English UI) sits in the Subtitles section and is on by default.
`PipelineConfig.titulo` defaults to `False`, so the CLI (which has no flag
for it) and old runner JSON are unchanged.

- `videopipeline/titulo.py`: `generar_titulo` (never raises: `None` and a
  log warning), `pedir_titulo` (the same, but raises `PasoFallido`), the
  prompt and its validation, and `lineas_titulo`, which turns the text into
  ASS styles and events (`DURACION = 5.0`). The size is fitted to the width
  with the measured per-glyph table `_ANCHOS` (advance of each glyph of
  Titan One per point of font size) and the letter spacing `ESPACIADO`.
- `subtitles.generar_ass(..., extra=(estilos, eventos))` appends those lines
  to the subtitles' `.ass`; `bloques` may be `[]`. The title is burned in the
  same encoding pass as the subtitles (`pipeline._quemar_subs`), or alone
  when there are none.
- `steps.filtro_ass` adds `fontsdir=videopipeline/fuentes/`, so libass finds
  `TitanOne-Regular.ttf` without the font installed. The licence, `OFL.txt`,
  sits next to it.
- The text comes from `pipeline._fase_titulo`: one call to the caption model
  (`modelo_caption`, through `ollama.chat_json`) on the transcript, before
  anything is burned. The JSON is `{"idioma", "titulo"}` with `idioma` first,
  so the model names the transcript's language before writing the title.
  Validation keeps the first 5 words and drops answers with fewer than 3. If
  Ollama fails, the video is saved without a title and the row shows a
  warning. The prompt is not in gettext: it is two fixed texts in `titulo.py`.

**Contract for shorts.** Two public functions are shared with the shorts
branch (`feature/shorts`); keep their names and signatures:

```python
generar_titulo(transcripcion: str, idioma: str, modelo: str, cliente=chat_json) -> str | None
lineas_titulo(texto: str, resolucion: tuple[int, int], inicio: float = 0.0,
              duracion: float = DURACION) -> tuple[list[str], list[str]]
```

`generar_titulo` returns `None` on any failure, and `lineas_titulo` returns
`([], [])` for an empty text. `generar_titulo` does **not** start Ollama: the
caller must run `servidor = asegurar_servidor()` (from `videopipeline.ollama`)
before it and `servidor.cerrar()` after, as `pipeline._fase_titulo` does. With
the server down every title comes back `None` and the only trace is a log
line. Writing a short's `.ass` with its title:

```python
servidor = asegurar_servidor()  # may raise PasoFallido (Ollama missing)
try:
    texto = generar_titulo(tramo_transcripcion, idioma, modelo_caption)  # None on failure
finally:
    servidor.cerrar()
generar_ass(bloques, diseno, posicion, resolucion, ass_path,
            extra=lineas_titulo(texto or "", resolucion))
```

Tests: `tests/test_titulo.py` (validation, ASS lines and width, with the
client passed in as a fake, so no Ollama is needed).

## Glossary of terms

`videopipeline/glosario.py` (pure, no I/O). The user's text (QSettings key
`transcripcion/glosario`, CLI `--glosario FILE`) travels raw in
`PipelineConfig.glosario` and is applied in `pipeline._transcribir`:

1. The correct forms go to Whisper as `initial_prompt`, capped at
   `MAX_CHARS_PROMPT` (600 chars, below Whisper's 224-token context).
2. Known mishearings (`Term = variant, variant`) are replaced once in the
   word list, keeping timestamps, so subtitles and caption share the fix.
   This also covers long videos, where the prompt leaves Whisper's window.
3. The caption prompt asks the LLM to keep the terms' spelling.

A failing glossary only emits a warning.

## Publishing to social networks

TikTok only lets audited apps post publicly (and rejects "a utility tool to
help upload contents to the account(s) you or your team manages"); YouTube
keeps uploads from unaudited API projects private. So TSOTS publishes
through a third-party service that already has approved apps. Today that is
Upload-Post, but the provider may change: everything provider-specific is
isolated in one module.

Package `videopipeline/redes/`:

| Module | Role | Knows the provider? |
|---|---|---|
| `modelo.py` | Neutral types: `Plataforma` + `ORDEN` (TikTok, YouTube, Instagram, X, Facebook), `Publicacion` (incl. `texto_x`, the reviewed X post), `Opciones` (TikTok draft/public, Instagram trial/regular, Facebook reel/video/draft, YouTube category, `x_premium`, `ubicacion`), `Ciudad` (catalog of cities with their public Instagram and X place ids), `Ubicacion` (a `Ciudad` and the TikTok `Lugar` chosen with the account; `plataformas()` says which networks get it), `Opciones.programada` (aware datetime to schedule, `None` = now), `Programada` (a pending post in the service: opaque reference, aware date, platforms, title, modes when known), `Lugar` (TikTok place from the lookup; its id is private and hidden from `repr`), `elegir_lugar` (exact-name match, accents and case ignored), `UBICACION_POR_DEFECTO` (Madrid), `Resultado` (ok, url, error, pendiente, referencia, `programada` when the service will publish it later), `Cuenta` (connected account: name, handle, reconnect needed, capabilities, Premium if known, TikTok location permission if known), `Pagina` (Facebook Page) | No |
| `textos.py` | Platform limits: YouTube title ≤ 100, text ≤ 2200 (5000 for the YouTube description), ≤ 30 hashtags on Instagram, YouTube tags ≤ 500 chars. The caption is trimmed; hashtags never are. X: `longitud_x` counts like X and the default X text is title + hashtags within 280 (see below) | No |
| `limites.py` | Video limits: X without Premium takes ≤ 140 s (2:20) and ≤ 512 MB; `motivo_no_admite_x` returns the reason shown in the dialog | No |
| `proveedor.py` | `Proveedor` protocol (publish, status, accounts, Facebook Pages, TikTok places, `programadas()` and `cancelar()`), `ErrorConsulta`, registry `PROVEEDORES` (id → module), `PROVEEDOR_POR_DEFECTO`, `crear()` | Only its id |
| `upload_post.py` | URLs, `Apikey` header, form fields, response parsing, status polling, account, Facebook Page and TikTok place lookups, scheduling (`scheduled_date` in local time + IANA `timezone`, no `async_upload`; list and cancel scheduled jobs) | Yes, the only one |
| `publicador.py` | Fixed order, a failure never stops the rest, polls pending uploads (15 min max), writes the registry. Before TikTok, looks up the place by name when none was chosen (no exact match or a failed lookup: TikTok goes out without a location) | No |
| `registro.py` | `name_limpio.publicado.json` next to the video: platform, date, url, provider id, mode; for a scheduled post also `programada` and `referencia`, and `olvidar()` drops it when cancelled. Never the key | No |

GUI: `app/widgets/dialogo_publicar.py` (texts, the X text with its live
counter, platforms, modes, confirmation, upload in a `QThread`,
per-platform status and links), `app/widgets/dialogo_redes.py` (provider,
profile, API key, **Check connection**, X Premium, Facebook Page, default
modes, location), `app/widgets/selector_ubicacion.py` (the location
selector, opened in its own window from both dialogs; inline it pushed
Networks… past a 14" laptop screen),
`app/cuentas.py` (account and TikTok place lookups shared by both dialogs,
always in the background through `app/segundo_plano.py`),
the **Publish…** button in `panel_caption.py` and the **Networks…** button
in the bottom bar of `app/main.py`, next to the language selector (app
settings, not per video, so it is always visible; the Publish dialog also
opens it).
Settings (QSettings `redes/*`) store the provider id, the profile, the
default modes, X Premium, the chosen Facebook Page (per provider), the
location city (`redes/ciudad`; the TikTok place lives in the Keychain, see
Location) and the
last successful account lookup (per provider, tied to the profile); never
the key. The checked platforms are remembered; a list saved before X and
Facebook existed keeps working (both stay unchecked), and a new user
starts with TikTok, YouTube and Instagram.

### Scheduling

The Publish dialog's **When** row (`radio_ahora` / `radio_programar` +
`campo_fecha`, a `QDateTimeEdit`) sets `Opciones.programada` in the Mac's
zone (`zona_local()`: the IANA name from `QTimeZone.systemTimeZoneId()`; a
fixed-offset fallback is sent as UTC). Allowed range: 15 minutes to 365
days ahead (`MARGEN_MINIMO`, `MAXIMO`); outside it the button is disabled
and the reason shows next to the field. The upload is the same as
publishing now, one request per network, but the service answers 202 with
a `job_id` and stores the video: `Resultado(ok=True, programada=…,
referencia=job_id)`, which the publisher records without polling. With a
`scheduled_date` but no `job_id` the post counts as scheduled without a
reference (it can still be cancelled from the calendar); with only a
`request_id` it is left unconfirmed. The time is checked again after the
confirmation, and the publisher skips a network whose scheduled time is
less than a minute away (uploads run one network after another).

The app keeps `job_id → video + date` in QSettings (`redes/programadas`),
written as each network's result arrives, so that cancelling from the
calendar can also clear the video's record; entries whose date has passed
are pruned each time the calendar loads.

`app/widgets/dialogo_programadas.py` is the **Scheduled…** window opened
from the bottom bar: a 6-week month grid (Monday first) with one label per
video and time (`agrupar`: jobs with the same title and local time are one
label, since the app uploads once per network). It lists and cancels
through `app/cuentas.py` (`programadas`, `cancelar`), in the background,
and cannot be closed while cancelling. `Proveedor.cancelar` returns `False`
on a 404: the post is gone (cancelled before, or already published), so it
leaves the calendar but its record entry stays to keep warning about
duplicates. A 409 `scheduled_post_in_progress` is explained. Not done yet: changing the time (`PATCH`), the outcome after
the time, Upload-Post's queue slots (see `docs/TODO.md`).

### X and Facebook

- **Order:** TikTok → YouTube → Instagram → X → Facebook.
- **X text:** an X post takes 280 characters counted the X way.
  `textos.longitud_x` approximates `twitter-text` v3: NFC first; every URL
  (http(s)://, www., or a domain with a common TLD) counts 23; an emoji,
  including skin tones, ZWJ sequences, flags and keycaps, counts 2; code
  points in the "light" ranges (U+0000–U+10FF, U+2000–U+200D,
  U+2010–U+201F, U+2032–U+2037) count 1 and the rest 2. Rare symbols or
  uncommon TLDs may be off by a few characters. The default text is title +
  hashtags: hashtags are dropped from the end, then the title is shortened.
  The dialog shows it in its own field with a live counter; while the user
  has not edited it, it follows the title and hashtags. Without Premium a
  text over 280 blocks publishing (a longer text would become a thread);
  the provider also trims it as a safety net.
- **X video limits:** without Premium, ≤ 140 s and ≤ 512 MB. The dialog
  measures the duration with `steps.duracion_video` (ffprobe) in the
  background; X stays disabled with "Comprobando…" until it is known, and
  disabled with the reason if the video is too long or too heavy. An
  unreadable duration does not block. With Premium (a user setting in
  Networks…) nothing is checked.
- **Facebook:** Meta only allows posting to Pages. The Page id is a
  non-secret setting passed to the provider as `pagina_facebook` in
  `ajustes_proveedor()`. Modes: reel (default), regular video, draft.

### Connected accounts

`Proveedor.cuentas()` returns one entry per `Plataforma` (`None` = not
connected) and `Proveedor.paginas_facebook()` the Pages the profile can post
to; both raise `ErrorConsulta` (readable, never the key) and nothing else.
The Networks… dialog runs them on **Check connection** (with the key just
typed or the one in the Keychain): it lists each platform as connected
(@handle), not connected or "reconnect", fills the Page list (a single
Page is picked automatically; if the list call fails, a manual id field
appears) and pre-ticks X Premium when the provider reports it. The Publish
dialog repeats the lookup in the background when it opens (and after
Networks… closes): not-connected platforms are disabled, reconnect ones
show a warning, a single Page is stored automatically. If the lookup fails
it keeps the cached result, or leaves everything enabled when there is
none. The publication log records which accounts were used and whether
they came from a live lookup or the cache.

### Location

Every post can carry a location. Through Upload-Post only three networks
take one, and each identifies the place its own way:

| Network | What it needs | Whose id | Lookup in Upload-Post |
|---|---|---|---|
| Instagram | Facebook Places id of the place | Public: the same for every account | No |
| X | X place id (hexadecimal) | Public: the same for every account | No |
| TikTok | Place id **and** name, from TikTok | **Private**: only valid for the connected account that looked it up | Yes: `lugares_tiktok(texto)`, up to 20 places |
| YouTube, Facebook | Nothing: no location field | — | — |

That split drives the design: public ids ship in the code, the TikTok id
never does.

**City catalog** (`videopipeline/redes/modelo.py`). The user picks a city
by name; ids are never shown. `Ciudad` is an Enum whose members carry
`nombre`, `instagram_id` and `x_id` (empty: that network goes without a
location). It holds the 15 biggest Spanish cities with known ids: Madrid,
Barcelona, Valencia, Sevilla, Zaragoza, Málaga, Murcia, Palma, Las Palmas
de Gran Canaria, Alicante, Bilbao, Córdoba, Valladolid, Vigo and Granada
(all with both ids except Murcia, which has no Facebook Places id in
Wikidata, so Instagram goes without a location there). Where the ids come
from, checked on 2026-10-30:

- Instagram: each city's "Facebook location ID" (P1997) in Wikidata; the
  Wikidata item is noted next to each member. Every id was checked:
  `facebook.com/<id>` redirects to that city's page (for example
  `Madrid-106504859386230`, `Córdoba-España-108957072462073`).
- X: there is no public lookup, so the ids come from raw X API data
  published on GitHub (tweet datasets whose `places` objects carry
  `country`, `full_name` and `id`). An id was only accepted from an object
  with country Spain and `full_name` "<City>, Spain"; each name maps to a
  single id across all the files. Madrid, Barcelona, Alicante, Palma and
  Vigo also appear in a second, independent object (`place_type` city,
  country ES). `x.com/search?q=place%3A<id>` lists the posts tagged there.

None of these ids has been confirmed by a real upload yet.

To add a city, add one member to `Ciudad` (`SEVILLA = ("Sevilla",
"<facebook places id>", "<x place id>")`) with a comment saying where each
id comes from. `tests/test_redes_ubicacion.py` checks that every member
has a name and valid ids; nothing else changes. Never add TikTok ids.

Finding the ids of a new city:

- Instagram: search the city on wikidata.org and read "Facebook location
  ID" (P1997), or take the Page id of the place's Facebook page ("Page
  transparency"). Check: `facebook.com/<id>` must open that place.
- X: there is no public lookup. Wikidata's "X place ID" (P12431) is rarely
  filled; otherwise the id has to come from a post geotagged in that place
  (its `place` object), which is how Madrid's was found. Check:
  `x.com/search?q=place%3A<id>` must list posts from there. Without an id,
  leave it empty: X goes out without a location.

**Model.** `Ubicacion(ciudad, tiktok)`: the city, and the TikTok `Lugar`
chosen with the account (or `None`: looked up when publishing). `nombre`,
`instagram_id` and `x_id` come from the city. `plataformas()` lists the
networks that will get it. `Lugar.id` is excluded from `repr`, so it
cannot leak through a printed `Opciones`. `UBICACION_POR_DEFECTO` is
`Ubicacion(Ciudad.MADRID)`.

**Where it is stored.**

- The city: `Ajustes.ciudad` (QSettings `redes/ciudad`, the member name).
  Never saved: Madrid. "No location" is saved as an empty value. A name no
  longer in the catalog falls back to Madrid.
- The TikTok place: only in the macOS Keychain
  (`credenciales.guardar_lugar_tiktok` / `leer_lugar_tiktok`), service
  `tsots-<provider>`, account `tiktok-lugar-<CITY>-<profile hash>`, value
  base64 JSON sent through stdin (never in the `ps` argument list). It is
  per provider, profile and city, so another account never sees it. It is
  never written to QSettings, files, logs or the repository.
- `selector_ubicacion.ubicacion_guardada` / `guardar_ubicacion` join both.
  Reading the place is reading a secret, so it only happens on "Change…"
  or "Publish", never when a dialog opens (the rows only need the city).
  A Keychain failure only loses the chosen place: TikTok then looks it up.

**Logs.** The TikTok id never reaches a log: the upload fields log it as
`(privado)`, the place lookup does not log its response body, the
publisher and the Publish dialog log only the place name, and the Publish
dialog also masks the chosen id in its publication log.

**Screens.** The selector (`app/widgets/selector_ubicacion.py`) opens in
its own window (`DialogoUbicacion`) from both dialogs and only shows
names: a city drop-down (catalog plus "No location"), the TikTok place
("Automatic: the place called «Madrid»" or one picked after "Search
TikTok"), and which networks it will tag. Changing the city drops the TikTok
results.

- Networks… has a "Location: Madrid (TikTok, Instagram, X) · Change…"
  row under "When publishing". Save stores the city and, in the Keychain,
  the TikTok place (none chosen: the stored one for that city is
  forgotten). If the last account lookup says TikTok lacks the `location`
  capability (`Cuenta.ubicacion is False`), the row asks to reconnect it.
- The Publish dialog shows the location and "Change…" sets one for that
  video only; it is never saved. The confirmation and the publication log
  state it.

**Publishing.** With a city but no TikTok place chosen, `publicador` looks
the city up right before TikTok (`_con_lugar_de_tiktok`) and uses the
first exact match (`elegir_lugar`: accents, case and a ", country" suffix
ignored). The other networks get the location unchanged. The provider only
adds the fields that are valid (`tiktok_location_id` +
`tiktok_location_name`, `location_id`, `geo_place_id`). A location never
costs a post: no match, a failed lookup or a missing permission post
TikTok without one, and a field the service refuses is ignored by
Upload-Post, which says so in `warnings` (kept in the publication log).

### Provider interface

```python
class Proveedor(Protocol):
    nombre: str
    def publicar(self, plataforma, publicacion, opciones) -> Resultado: ...
    def estado(self, plataforma, referencia) -> Resultado: ...
    def cuentas(self) -> dict[Plataforma, Cuenta | None]: ...
    def paginas_facebook(self) -> list[Pagina]: ...
    def lugares_tiktok(self, texto) -> list[Lugar]: ...
```

- `publicar` uploads to one platform. It never raises for network or
  service errors: it returns `Resultado(ok=False, error=...)`, or
  `pendiente=True` plus an opaque `referencia` when the service keeps
  processing. Error texts never contain the key.
- `estado` checks a pending upload with that `referencia`, same rules.
- `cuentas`, `paginas_facebook` and `lugares_tiktok` are lookups: they raise `ErrorConsulta`
  with a readable message (never the key) and no other exception.

A provider module exposes `NOMBRE` (display name), `USA_PERFIL` (whether it
needs a profile/account name) and `crear(clave, ajustes, http=None)`, where
`ajustes` holds the non-secret settings (`{"perfil": ..., "pagina_facebook": ...}`) and `http` is an
optional `httpx.Client` that tests replace with `httpx.MockTransport`.

### Adding a provider

1. Write `videopipeline/redes/<id>.py` with `NOMBRE`, `USA_PERFIL` and
   `crear()` returning a `Proveedor`. Map the neutral `Opciones` to the
   service's fields there.
2. Add `"<id>": "videopipeline.redes.<id>"` to `PROVEEDORES`.
3. Run the tests: `tests/test_redes_contrato.py` runs the common contract
   against every registered provider (never raises, never leaks the key,
   uses the injected HTTP client, sends nothing without a video, lookups
   only raise `ErrorConsulta`). Add
   field-level tests like `tests/test_redes_upload_post.py`.

`tests/test_redes_contrato.py` also fails if Upload-Post strings (its name,
domain, `Apikey`, field names such as `post_mode`, `share_mode`,
`privacyStatus`, `x_title`, `facebook_page_id`, `social_accounts`) appear
outside `upload_post.py`; the only allowed mentions
are the registry entry and `PROVEEDOR_POR_DEFECTO` in `proveedor.py`. The
new provider appears in Networks… automatically; its key goes to the
Keychain under `tsots-<id>`.

### Keychain

`app/credenciales.py` wraps macOS `security`: service `tsots-<provider>`,
account `api-key`. `guardar` pipes
`add-generic-password -U -s … -a api-key -w <key>` into `security -i`
through stdin, so the key never shows up in the process list, then reads it
back to confirm. Keys with spaces or quotes are rejected. `leer` uses
`find-generic-password -w`; `hay_clave` checks without `-w` (the Networks…
dialog never reads the secret); `borrar` uses `delete-generic-password`. The
key is read when the user confirms a publication and, in a background
thread, for the account lookups (when the Publish dialog opens and on
**Check connection**). It is never logged, shown, stored in QSettings,
`PipelineConfig` or the registry.

### Upload-Post assumptions to confirm with a real upload

- Multipart arrays go as repeated `platform[]` / `tags[]` fields.
- Uploads longer than ~59 s turn async (`request_id`). The status response
  (`GET /api/uploadposts/status`) follows `openapi.json`
  (`status`: pending/in_progress/completed, `results`: list of
  `{platform, success, message}`), which does not document a post URL; the
  parser also accepts a dict of results and looks for `url`, `post_url`,
  `platform_post_url`, `permalink` or a URL inside `message`.
- A TikTok draft (`MEDIA_UPLOAD`) returns no public URL.
- Each platform is a separate request (to keep the order and isolate
  failures); whether the free plan counts one upload per video or per
  platform is unknown.
- X: `x_title` is the post text; `x_long_text_as_post=true` only with
  Premium and a text over 280, otherwise the text is ≤ 280 so it never
  becomes a thread. Results may come back as `x` or `twitter`. Unused:
  `reply_settings`, `nullcast`, `community_id`, `x_alt_text`,
  `x_paid_partnership`, `x_subtitles_url` (public URL only).
- Facebook: `facebook_page_id`, `facebook_title`, `facebook_description`,
  `facebook_media_type` (`REELS` or `VIDEO`) and `video_state`
  (`PUBLISHED` or `DRAFT`); a draft is sent as a reel in `DRAFT`.
- Whether X and Facebook are in the free plan is unknown; a refusal is
  shown with the service's own reason.
- Accounts: `GET /api/uploadposts/users/{profile}` → `social_accounts` per
  platform (`null`/`""` = not connected; otherwise `display_name`,
  `handle`, `username`, `reauth_required`, `capabilities`), found even
  inside wrappers such as `{"profile": {...}}`. An X capability naming
  Premium or long video/text/post is taken as Premium; otherwise Premium is
  unknown (never assumed false).
- Facebook Pages: `GET /api/uploadposts/facebook/pages?profile=` → list of
  `{page_id, page_name, profile}`, also inside `{"pages": [...]}` or
  `{"data": [...]}`; entries of another profile are dropped.
- Location: TikTok `tiktok_location_id` + `tiktok_location_name` (both or
  none), Instagram `location_id` (numeric Facebook Page/place id), X
  `geo_place_id`; YouTube and Facebook have no field. TikTok places come
  from `GET /api/uploadposts/tiktok/locations?profile=&q=` (`q` ≤ 100,
  up to 20 results, ids valid only for that account); without the
  `location` capability it answers 400 `tiktok_reconnect_required`. A
  location field the service rejects is ignored: it publishes anyway and
  says so in `warnings` (kept in the publication log).

## App bundle (Dock icon)

`TheSilenceOfTheShorts.app` is a minimal bundle inside the project: a
native launcher (`lanzador/lanzador.c`) that `exec`s a copy of the Python
interpreter with the venv active (`__PYVENV_LAUNCHER__`) plus
`caffeinate -i`. One process with the app's own identity: Dock icon and
macOS permissions (Documents, Desktop) under "The Silence of the Shorts".

- Launched without Terminal; whatever python/Qt print goes to
  `logs/lanzador.log`.
- The main executable must NOT be a script: macOS would attribute it to
  `/bin/bash` and deny Documents without prompting.
- After `brew upgrade python@3.11` the embedded binary stops loading (it
  links the Cellar by absolute path); the launcher detects it
  (`interprete_funciona`) and runs `lanzador/construir_app.sh` itself.
- The icon comes from `docs/img/icon.png` via `lanzador/generar_icono.py`
  (background flood-filled to alpha, padded to Apple's margins).

## Translations (i18n)

gettext, one mechanism for GUI and pipeline (the runner is a subprocess
without Qt). Spanish is the source language: the strings in the code are
the `msgid`s.

- `videopipeline/i18n.py`: `_()` translates at call time, `N_()` marks
  constants for extraction, `instalar(idioma)`, `detectar()`.
- Language: system locale by default; forced with the 🌐 selector in the
  app (QSettings `ui/idioma`), the env var `TSOTS_LANG=es|en`, or the CLI
  locale. The GUI passes `idioma_ui` to the runner in the config so
  progress labels, warnings and diagnostics come back translated.
- Catalogs: `locale/<lang>/LC_MESSAGES/tsots.po` (source) and `tsots.mo`
  (compiled, committed; `construir_app.sh` recompiles).

Update after changing strings:

```bash
lanzador/traducir.sh          # xgettext → locale/tsots.pot, msgmerge → *.po, msgfmt → *.mo
```

Add a language: copy `locale/en/LC_MESSAGES/tsots.po` to
`locale/<lang>/LC_MESSAGES/tsots.po`, translate the `msgstr`s, add the
code to `IDIOMAS` in `videopipeline/i18n.py` and to the 🌐 selector in
`app/main.py`, run `lanzador/traducir.sh`.

The known-error patterns in `videopipeline/errores.py` match messages
raised by our own code, which are translated at raise time, so those
patterns carry both the Spanish and the English wording.

## Errors and logs

- Each job writes `logs/<video>_<date>.log` with the config, timed steps
  and, on failure, the full diagnosis (cause, what to do, raw tool
  output).
- In the queue, a failed row shows the problem title. Double-click opens
  a dialog with cause, solution, technical detail and an "Open log"
  button.
- Each publishing attempt writes `logs/publicacion_<video>_<date>.log`
  (`videopipeline/redes/diario.py`): settings (profile present yes/no,
  never its value), every request with its HTTP status and sanitized
  body, async request ids and each status poll, per-platform results and
  full tracebacks. The `videopipeline.redes` logger never propagates to
  the console, and every line goes through `diario.limpiar`, so the API
  key never reaches disk. The Publish dialog's "Show log" button reveals
  the file in the Finder.
- Known errors are translated into diagnoses in `videopipeline/errores.py`
  (`_CONOCIDOS` table). An error that shows up as "unknown" is a
  candidate for that table.
- auto-editor 31.x fails with "Could not write packet" on the H.264 of
  some exports. The cutting step re-encodes with `h264_videotoolbox` and
  retries by itself; the row gets ⚠.

## Origin

Extracted from a local fork of
https://github.com/modelscope/ClearerVoice-Studio (subfolder
`clearvoice/`). Demos, samples and video outputs were dropped.
