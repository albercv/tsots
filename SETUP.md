# Limpiador de Vídeo — instalación

Aplicación de escritorio (PySide6) que limpia el audio de un vídeo con
ClearVoice (MossFormer2_SE_48K), recorta silencios con auto-editor y
opcionalmente genera/quema subtítulos con faster-whisper.

## Arrancar

Doble clic en `LimpiadorVideo.command`, o desde terminal:

```bash
./LimpiadorVideo.command
```

CLI sin GUI:

```bash
source .venv-clearvoice/bin/activate
python limpiarVideo.py entrada.mov salida.mp4
```

## Requisitos del sistema (Homebrew)

```bash
brew install python@3.11 ffmpeg ffmpeg-full auto-editor
```

- `ffmpeg` / `ffprobe`: extracción de audio y remux.
- `ffmpeg-full`: único build con filtro `ass` (libass) para quemar
  subtítulos. Se busca en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`
  (ver `videopipeline/steps.py`).
- `auto-editor`: recorte de silencios.

## Entorno Python (recrear si se mueve la carpeta)

El venv tiene rutas absolutas cocidas. Si mueves la carpeta, bórralo y
recréalo:

```bash
rm -rf .venv-clearvoice
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv-clearvoice
.venv-clearvoice/bin/python -m pip install -r requirements.txt
.venv-clearvoice/bin/python -m pip install -e .
```

## Modelos

- `checkpoints/MossFormer2_SE_48K/` (221 MB) va incluido en la carpeta.
  Si falta, ClearVoice lo descarga de HuggingFace al primer uso.
- Whisper (`Systran/faster-whisper-small`, ~460 MB) vive en la caché
  global `~/.cache/huggingface/hub/`. Se descarga solo la primera vez
  que se activan subtítulos.

## Tests

```bash
QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow"
```

Añade `-m slow` para los dos tests de integración que cargan el modelo
real (~40 s).

## Origen

Extraído del fork local de
https://github.com/modelscope/ClearerVoice-Studio (subcarpeta
`clearvoice/`). Se descartaron demos, samples y salidas de vídeo.
