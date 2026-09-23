# TODO

Pending work, most urgent first. Remove an item when it is merged into
`develop`.

## Features

- [ ] **Blog post from the video, published as a draft on evolve2digital.**
      Agreed design:
      1. Register the e2d MCP in Claude Code and check that `claude -p` sees
         the posts tools:
         `claude mcp add --transport http --scope user e2d https://evolve2digital.com/mcp`,
         then `/mcp` inside `claude` to authenticate.
      2. TSOTS option "Prepare for blog": when a video finishes, write
         `~/TSOTS/blog/pendientes/<date>-<name>/` with `video.mp4`,
         `transcripcion.txt` and `meta.json` (language, brand context,
         provisional title).
      3. launchd agent watching `pendientes/` runs a script that calls
         `claude -p` per folder, with an instructions file (e2d tone and
         structure, upload steps). Flow: `posts_create` with
         `published: false`, `posts_request_upload`, POST the video and a
         cover frame to `/api/admin/media/upload`, `posts_validate`,
         `posts_set_cover`. Move the folder to `hechos/` with
         `resultado.json` (draft URL) or to `errores/` with the reason.
      Fallback if CLI auth fails: a scheduled task in the Claude desktop app,
      which already has the e2d connector (not verified).

- [ ] **Header alignment.** The header (`app/widgets/cabecera.py`) sits too
      far to the left. Review spacing and alignment with the rest of the
      window, ideally with the user looking at the real app.

- [ ] **Dark version of the app.** The app already follows the macOS
      appearance setting. The user wants a dark version too: clarify whether
      that means an in-app light/dark selector, a darker visual style, or a
      dark app icon and logo.

- [ ] **Verify X and Facebook publishing with a real upload.** Needs the
      user: Task 6 of `docs/superpowers/plans/2026-09-23-publicar-x.md`
      (free plan, single post instead of a thread, Premium detection,
      Facebook draft, real shape of the accounts and Pages responses).

## Improvements

- [ ] **Burn subtitles on the GPU.** `cmd_quemar_subtitulos` in
      `videopipeline/steps.py` encodes with `libx264` on the CPU. Try
      `h264_videotoolbox` (already used for re-encoding) with `-q:v` around
      60-65 and compare size, quality and time.
- [ ] **Version check script.** `lanzador/revisar_versiones.sh`: print
      outdated Homebrew formulas (ffmpeg, auto-editor), outdated pip packages
      in the venv, the Ollama version and new upstream commits in
      ClearerVoice-Studio.
- [ ] **Monthly research task.** Scheduled Claude task that looks for new
      local LLMs, Whisper successors and voice-cleaning models, and adds
      findings to this file.

## Local models

- [ ] **Compare `qwen3.8:27b`** with `gemma4:26b` (installed and tested on
      2026-09-23: better titles and hooks than `qwen3.5:9b`, 24 s vs 11 s).
      Send `think: false`. Decide the default caption model.
