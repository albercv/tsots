<p align="center"><img src="docs/img/logo.png" alt="The Silence of the Shorts" width="560"></p>

<p align="center"><b>English</b> · <a href="README.es.md">Español</a></p>

# The Silence of the Shorts

A Mac desktop app that gets a talking-head video ready to publish: it
cleans the noise out of the voice, cuts the silences, burns Reels-style
subtitles and writes an SEO title, caption and hashtags with a local AI
model. Everything runs on your Mac; nothing is uploaded anywhere.

| Input | Output |
|---|---|
| `talk.mov` (any video with speech) | `talk_limpio.mp4` (clean voice, no silences, optional subtitles) |
| | `talk_limpio.srt` (subtitles, if enabled) |
| | `talk_limpio.md` (SEO title, caption and hashtags, if enabled) |

## Requirements

- Mac with **Apple Silicon** (M1, M2, M3, M4…). Intel Macs are not supported.
- **macOS 13** Ventura or later.
- **10 GB free** on disk: Python environment (2.5 GB), audio models
  (0.7 GB) and, if you want the SEO caption, the language model (6 GB).
- Internet during installation (downloads) and the first time you use
  subtitles. After that it works offline.
- Memory: 16 GB is enough for everything except large language models;
  the app tells you which ones fit on your Mac.

The installer takes care of Homebrew, Python, ffmpeg, auto-editor and
Ollama. No programming knowledge needed.

## Installation

1. Download the project from the **`main`** branch, which is the stable
   version (**Code → Download ZIP** on GitHub, the latest entry under
   **Releases**, or `git clone -b main …`) and unzip it where you want to
   keep it, for example in `~/Documents`. The `develop` branch is work in
   progress and may not work. **Do not move the folder after
   installing**; if you do, run the installer again.
2. Double-click **`instalar.command`**. If macOS says it cannot be opened
   because it is from an unidentified developer: right-click → **Open**
   → **Open**. A Terminal window opens.
3. Follow the Terminal. It will ask for your password once or twice (for
   Homebrew) and take 10 to 30 minutes depending on your connection. When
   it finishes you will see **Installation complete**.

You will end up with the 🐑 **The Silence of the Shorts** icon in the Dock.

If something fails halfway, run `instalar.command` again: it resumes
where it stopped. To uninstall: `desinstalar.command`.

Variants:

```bash
SIN_OLLAMA=1 ./instalar.command   # without SEO caption (saves 6 GB)
SIN_DOCK=1 ./instalar.command     # without the Dock icon
```

## First launch

- The app follows your Mac's language (English or Spanish). You can force
  one with the 🌐 selector at the bottom of the window; the app asks for
  confirmation and restarts (any process in progress is cancelled).
- macOS will ask whether the app may access **Documents** (or wherever
  your videos are). Accept; otherwise it cannot read them. If you
  declined: System Settings → Privacy & Security → Files and Folders →
  The Silence of the Shorts.
- The first time you enable subtitles or the caption it downloads the
  Whisper model (~1.6 GB with turbo, the recommended one). Only once.

## How it works

1. **Drag** one or more videos onto the area on the left (or click to
   choose them). They appear in the queue.
2. **Pick options** on the right:
   - **Mode**: full pipeline (clean + cut), clean audio only, or cut
     silences only.
   - **Audio cleaning**: AI model that removes noise. The default
     (MossFormer2 48 kHz) is the best for voice.
   - **Silence cutting**: margin kept around each sentence and volume
     threshold. "Speed up" plays the silences faster instead of cutting
     them.
   - **Subtitles**: style (8 to choose from: Reels bold, karaoke, green
     karaoke, Impact, yellow, minimal, black box and white box), position,
     size, language and Whisper model size. The preview shows how they look on
     a real frame of the selected video.
   - **SEO caption**: writes `name_limpio.md` with a title, caption and
     the 5 hashtags that best describe what is said in the video. **Brand…** stores a text
     about who you are, your tone and your call to action so the copy
     sounds like you. **Model** lists the Ollama models installed on your
     Mac; the ones that do not fit in memory appear disabled and the
     tooltip says why. The caption is written in the subtitle language.
   - **Terms…**: your brands and proper names, one per line, so Whisper
     spells them right in the subtitles and the caption. After `=`, the
     ways Whisper gets them wrong; they are fixed automatically:

     ```
     Claude Code = Cloud Code, Claus Code
     Anthropic
     ```
3. **Output**: next to the original as `name_limpio.mp4` by default;
   **Change…** picks another folder.
4. **▶ Process**. The queue advances one video at a time, showing the
   step (extracting audio, cleaning, cutting, transcribing…). It takes
   roughly as long as the video lasts. The Mac will not sleep while the
   app is open.
5. When done, **double-click** a finished video to open it. If you
   generated a caption, it appears under the preview with buttons to copy
   the title, caption, hashtags or everything, and **Publish…** (see
   [Publish to social networks](#publish-to-social-networks)).

You can keep using the Mac while it processes. Locking the screen does
not stop anything; closing the lid without an external display does.

### From the terminal

```bash
./TheSilenceOfTheShorts.command                              # the same app
.venv-clearvoice/bin/python limpiarVideo.py video.mov        # no GUI
.venv-clearvoice/bin/python limpiarVideo.py video.mov --caption --marca "I am…"
TSOTS_LANG=en ./TheSilenceOfTheShorts.command                # force a language
```

## Publish to social networks

From a finished video with a caption, **Publish…** sends it to **TikTok →
YouTube → Instagram**, in that order. Nothing is published automatically:
you review the title, caption and hashtags, tick the platforms, press
**Publish** and confirm. A failure on one platform does not stop the
others; each row shows its progress and, at the end, a link or the error.

TikTok and YouTube only let audited apps post publicly, so TSOTS publishes
through a service that already has that approval: **Upload-Post**
([upload-post.com](https://www.upload-post.com), free plan with 10
uploads a month). Requirements:

1. An Upload-Post account.
2. In Upload-Post, a **profile** with TikTok, YouTube and Instagram
   connected. Instagram must be a **professional** account (Business or
   Creator).
3. Your Upload-Post **API key**.

Save them once in **Networks…** (bottom bar, next to the language; always
visible, also reachable from Publish…): the profile name and
the API key. The key goes straight to the **macOS Keychain** (service
`tsots-upload_post`); the app never shows it or writes it to disk. To
remove it: **Forget key** in the same dialog, or delete the entry in
Keychain Access.

What each mode does:

| Platform | Mode | Result |
|---|---|---|
| TikTok | **Draft** (default) | The video lands in your TikTok drafts; you finish and publish it in the app. |
| TikTok | **Public** | Published straight away, visible to everyone. |
| YouTube | **Public Short** | Published as a public Short in the category chosen in Networks… (People & Blogs by default). |
| Instagram | **Trial reel** (default) | Shown to non-followers first; Instagram shares it with your followers only if it performs. |
| Instagram | **Regular reel** | A normal reel, also shown in your feed. |

TSOTS writes `name_limpio.publicado.json` next to the video (platform,
date, link, service). If you open Publish again for that video, it warns
you that it was already published.

## If something goes wrong

- A **red** row in the queue is a failed video. **Double-click** it: you
  get the cause, what to do, and an **Open log** button with the full
  detail. Logs live in `logs/`.
- A row with **⚠** finished, but with a warning (for example, subtitles
  or the caption failed and the video was saved without them). Hover to
  read it.
- "**Missing dependencies**" on launch: run `instalar.command` again.
- The **caption** is not generated: check that the Ollama app is open
  (menu bar icon) and press ↻ next to the model selector. To add models:
  `ollama pull name` in Terminal, then ↻.
- After a Homebrew (Python) upgrade the app rebuilds itself on launch (a
  few seconds longer that one time). If it still does not open, run
  `instalar.command` again.

## What is inside

[ClearVoice](https://github.com/modelscope/ClearerVoice-Studio) (voice
cleaning, Apache-2.0), [auto-editor](https://auto-editor.com) (silences),
[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
(transcription on the Apple GPU; faster-whisper on macOS 13), ffmpeg (video), [Ollama](https://ollama.com) (local
language model), [Upload-Post](https://www.upload-post.com) (publishing,
optional), PySide6 (interface). Technical docs in
`docs/DEVELOPMENT.md`; translations live in `locale/` (add a language by
adding a `.po` file — see the development docs).

License: Apache-2.0 (see `LICENSE`). Includes code from
ClearerVoice-Studio, © Alibaba, under the same license.
