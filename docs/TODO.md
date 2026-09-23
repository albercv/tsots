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

## Local models and Ollama

Findings from 2026-09-23. Local pulls are still free and need no account;
paid plans only cover cloud models.

- [ ] **Fix the Ollama CLI.** `ollama` on the PATH is Homebrew's 0.19.0,
      older than the app's server (0.33.2). Old clients get
      `412: The model you are attempting to pull requires a newer version of
      Ollama`. Fix: `brew uninstall ollama`, then restart Ollama.app so it
      installs the pending 0.34.3 update. The installer (`instalar.command`)
      installs the cask `ollama-app`; check it never adds the formula too.
- [ ] **Try newer models** within the app's memory budget on a 36 GB Mac
      (25.5 GB): `qwen3.8:27b` (quality, dense, send `think: false`) and
      `gemma4:26b` (MoE with 3.8B active, fast). Compare them with
      `qwen3.5:9b` on the same transcript before changing the default.
