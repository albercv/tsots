# TODO

Pending work, most urgent first. Remove an item when it is merged into
`develop`.

## Features

- [ ] **Change the time of a scheduled post** from the calendar (Upload-Post
      `PATCH /api/uploadposts/schedule/<job_id>`; today: cancel and
      schedule again).
- [ ] **Outcome of a scheduled post after its time** (link or error): the
      local record keeps "scheduled for…" (Upload-Post
      `status?job_id=` or the upload history).

- [ ] **Verify `GET /api/uploadposts/users` against the real service.** The
      response shape of the profiles list is unverified; if it fails, the
      profile is typed by hand.
- [ ] **TikTok places of a removed profile stay orphaned in the Keychain.**

- [ ] **Choose horizontal or vertical when publishing.** With both outputs,
      **Publish…** always uses the horizontal one.
- [ ] **Show the horizontal output in the queue before the vertical one
      finishes.** Today the row learns both at the end; with face tracking
      on a long video the horizontal is on disk minutes earlier.
- [ ] **Exact shot cuts for face tracking** (`scdet` in the sampling pass):
      today a cut is detected when the face jumps more than 25% of the
      width, so cuts between similar shots pan for ~1.5 s.

- [ ] **Header alignment.** The header (`app/widgets/cabecera.py`) sits too
      far to the left. Review spacing and alignment with the rest of the
      window, ideally with the user looking at the real app.

- [ ] **Dark version of the app.** The app already follows the macOS
      appearance setting. The user wants a dark version too: clarify whether
      that means an in-app light/dark selector, a darker visual style, or a
      dark app icon and logo.

- [ ] **Publish to Threads.** Add Threads as a sixth platform in
      Publicar… and Redes…, following the X/Facebook pattern
      (`videopipeline/redes/upload_post.py`, per-platform text, accounts
      check). Upload-Post takes `platform[]=threads` with `threads_title`
      (falls back to `title`), `threads_topic_tag` (1-50 chars, no `.` or
      `&`), `threads_alt_text` and `threads_reply_control`; the global
      `description` is ignored for Threads videos, so the post text must go
      in `threads_title`. Check Threads' own text and video limits before
      building the text field.

- [ ] **Verify X and Facebook publishing with a real upload.** Needs the
      user: Task 6 of `docs/superpowers/plans/2026-09-23-publicar-x.md`
      (free plan, single post instead of a thread, Premium detection,
      Facebook draft, real shape of the accounts and Pages responses).
- [ ] **List of processed videos.** Today a video removed from the queue is
      reprocessed by dragging the original or one of its outputs again; its
      record in `fichas/` is kept until **Forget this video**. Add a way to
      see and reopen processed videos without looking for the file. The form
      (window, panel, menu…) is still to be decided with the user.
      `ficha.todas()` already lists the records.
- [ ] **Edit the opening title by hand before burning it.** Out of scope of
      the first version: the app writes the title and burns it without
      asking. The text already lives in the record (`titulo`), so an edit
      would only change that text (design:
      `docs/superpowers/specs/2026-11-05-titulo-inicio-design.md`).

## Improvements

- [ ] **Reprocessing edge cases.** None loses data:
      - A record left with no original and no outputs (the original was
        edited outside the app) still reserves its output names, so another
        video with the same name gets "(2)". `Ficha._salidas()` in
        `videopipeline/ficha.py` should return nothing for it.
      - When **Process** adopts an old `x_limpio.mp4` by name, the warning
        appears but the job started by the same click still runs
        (`procesar()` in `app/main.py`).
      - An edited original can adopt a stray `x_limpio_vertical.mp4`
        without a warning.

- [ ] **Blog and LinkedIn: accepted gaps of the first version.**
      - The CLI path (`limpiarVideo.py`, `runner` calling `pipeline.run`
        without a record) never runs the blog/LinkedIn step: it only runs
        through `reproceso` (the GUI).
      - The «Blog» and «LinkedIn» checkboxes have a tooltip but no info-icon help
        card (`AYUDAS` in `app/widgets/panel_opciones.py`).
      - **Publish…** needs a caption to open, so publishing only to
        LinkedIn from a video without a caption is not possible.
      - No automatic closed-eyes filter for the frames: OpenCV's eye
        cascade was not reliable and there is no detector without new
        dependencies. A cover or photo with closed eyes is swapped by hand
        in **Publish…** (LinkedIn) or in the blog draft.
      - A failed blog/LinkedIn step (Ollama down, no frame with a face, no
        title) is not recorded, so it is retried on every later reprocess
        of that video while the box is ticked.
      - Blog folders are only processed while the app is running: the app
        starts the agent when a video finishes and when it opens. Only a
        folder written in the instant between the agent's last scan and its
        exit waits for the next start.

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

- [ ] **Pick a lighter default caption model.** `gemma4:26b` (18 GB) gives
      better titles and hooks than `qwen3.5:9b` (24 s vs 11 s, tested on
      2026-09-23) but slows a 36 GB Mac down while ClearVoice and Whisper run;
      the panel now flags it as heavy. Benchmark `gemma4:12b-mlx` (7.7 GB, MLX
      backend) and `gemma4:12b` (7.6 GB) against it on a real transcript
      (time, `ollama ps` memory, title/hook quality) and set the default in
      `videopipeline/config.py`, `app/settings.py` and `videopipeline/errores.py`.
      `qwen3.8:27b` would be as heavy as `gemma4:26b`.
