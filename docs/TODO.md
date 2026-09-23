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

- [ ] **Publish to TikTok, YouTube and Instagram, in that order.**
      Findings from 2026-09-23:
      - TikTok's API is not an option for us: unaudited apps only post
        privately, and its guidelines reject "a utility tool to help upload
        contents to the account(s) you or your team manages".
      - YouTube: uploads from an unaudited API project stay private and
        can't be made public. Needs the API audit.
      - Instagram: works now with "Instagram API with Instagram Login",
        Standard Access, no App Review, resumable upload (no public URL).
      - Self-hosted Postiz doesn't avoid this: it uses your own TikTok and
        Google apps (same audits) and needs a public HTTPS domain.
      - Realistic path: a service with approved apps and an API, such as
        Upload-Post (free tier 10 uploads/month) or Blotato. Try it with 2-3
        videos first. The API key goes in the macOS Keychain.

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
