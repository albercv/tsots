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

- `main`: stable. Only receives fast-forward merges from `develop` once
  the full test suite passes and the app has been smoke-tested. Every
  release is an annotated tag `vX.Y.Z` on `main`. Users install from here.
- `develop`: integration branch. Day-to-day work lands here.
- `feature/*`: short-lived branches off `develop`, merged back with
  `--no-ff`.

To cut a release:

```bash
git checkout main && git merge --ff-only develop
git tag -a vX.Y.Z -m "vX.Y.Z: summary"
git push origin main develop --follow-tags
```

## Tests

```bash
QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow"
```

Add `-m slow` for the integration tests that load the real models (and
call the real Ollama if it is running; they skip otherwise).

## Architecture

```
app/                 PySide6 GUI (main window, queue model, worker, widgets)
videopipeline/       pipeline (steps, subtitles, caption, glossary, ollama
                     client, errors → diagnostics, runner subprocess, i18n)
clearvoice/          ClearVoice library (upstream, Apache-2.0)
lanzador/            native launcher + build script for the .app bundle
locale/              gettext catalogs (see Translations)
tests/               pytest + pytest-qt
```

The GUI never runs the pipeline in-process: `app/worker.py` launches
`python -m videopipeline.runner --config <json>` and parses JSON progress
lines (`step/total/label/percent`, `warning`, `error` + `diagnostico`,
`done`). Heavy imports (torch, mlx, faster-whisper) therefore only happen in
the subprocess.

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
