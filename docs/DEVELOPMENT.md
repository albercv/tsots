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
videopipeline/       pipeline (steps, subtitles, caption, glossary, ollama
                     client, errors → diagnostics, runner subprocess, i18n)
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
| `modelo.py` | Neutral types: `Plataforma` + `ORDEN` (TikTok, YouTube, Instagram, X, Facebook), `Publicacion` (incl. `texto_x`, the reviewed X post), `Opciones` (TikTok draft/public, Instagram trial/regular, Facebook reel/video/draft, YouTube category, `x_premium`), `Resultado` (ok, url, error, pendiente, referencia), `Cuenta` (connected account: name, handle, reconnect needed, capabilities, Premium if known), `Pagina` (Facebook Page) | No |
| `textos.py` | Platform limits: YouTube title ≤ 100, text ≤ 2200 (5000 for the YouTube description), ≤ 30 hashtags on Instagram, YouTube tags ≤ 500 chars. The caption is trimmed; hashtags never are. X: `longitud_x` counts like X and the default X text is title + hashtags within 280 (see below) | No |
| `limites.py` | Video limits: X without Premium takes ≤ 140 s (2:20) and ≤ 512 MB; `motivo_no_admite_x` returns the reason shown in the dialog | No |
| `proveedor.py` | `Proveedor` protocol, `ErrorConsulta`, registry `PROVEEDORES` (id → module), `PROVEEDOR_POR_DEFECTO`, `crear()` | Only its id |
| `upload_post.py` | URLs, `Apikey` header, form fields, response parsing, status polling, account and Facebook Page lookups | Yes, the only one |
| `publicador.py` | Fixed order, a failure never stops the rest, polls pending uploads (15 min max), writes the registry | No |
| `registro.py` | `name_limpio.publicado.json` next to the video: platform, date, url, provider id, mode. Never the key | No |

GUI: `app/widgets/dialogo_publicar.py` (texts, the X text with its live
counter, platforms, modes, confirmation, upload in a `QThread`,
per-platform status and links), `app/widgets/dialogo_redes.py` (provider,
profile, API key, **Check connection**, X Premium, Facebook Page, default
modes), `app/cuentas.py` (account lookup shared by both dialogs, always in
the background through `app/segundo_plano.py`),
the **Publish…** button in `panel_caption.py` and the **Networks…** button
in the bottom bar of `app/main.py`, next to the language selector (app
settings, not per video, so it is always visible; the Publish dialog also
opens it).
Settings (QSettings `redes/*`) store the provider id, the profile, the
default modes, X Premium, the chosen Facebook Page (per provider) and the
last successful account lookup (per provider, tied to the profile); never
the key. The checked platforms are remembered; a list saved before X and
Facebook existed keeps working (both stay unchecked), and a new user
starts with TikTok, YouTube and Instagram.

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

### Provider interface

```python
class Proveedor(Protocol):
    nombre: str
    def publicar(self, plataforma, publicacion, opciones) -> Resultado: ...
    def estado(self, plataforma, referencia) -> Resultado: ...
    def cuentas(self) -> dict[Plataforma, Cuenta | None]: ...
    def paginas_facebook(self) -> list[Pagina]: ...
```

- `publicar` uploads to one platform. It never raises for network or
  service errors: it returns `Resultado(ok=False, error=...)`, or
  `pendiente=True` plus an opaque `referencia` when the service keeps
  processing. Error texts never contain the key.
- `estado` checks a pending upload with that `referencia`, same rules.
- `cuentas` and `paginas_facebook` are lookups: they raise `ErrorConsulta`
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
