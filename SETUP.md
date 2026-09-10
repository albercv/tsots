# The Silence of the Shorts — instalación

Aplicación de escritorio (PySide6) que limpia el audio de un vídeo con
ClearVoice (MossFormer2_SE_48K), recorta silencios con auto-editor y
opcionalmente genera/quema subtítulos con faster-whisper.

## Arrancar

Doble clic en `TheSilenceOfTheShorts.command`, o desde terminal:

```bash
./TheSilenceOfTheShorts.command
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

## Acceso directo en el Dock (TheSilenceOfTheShorts.app)

`TheSilenceOfTheShorts.app` es un bundle mínimo dentro del proyecto: un lanzador
nativo (`lanzador/lanzador.c`) que hace `exec` de una copia del intérprete
de Python con el venv activado (`__PYVENV_LAUNCHER__`) y `caffeinate -i`.
Un solo proceso, con la identidad de la app: icono propio en el Dock y
permisos de macOS (Documentos, Escritorio) a nombre de "The Silence of the Shorts".

- Se lanza sin Terminal. Lo que escriban python/Qt va a `logs/lanzador.log`.
- El ejecutable principal NO puede ser un script: macOS lo atribuye a
  `/bin/bash` y deniega Documentos sin preguntar.
- Tras `brew upgrade python@3.11` (o si no arranca): `lanzador/construir_app.sh`.
- Para arrastrarlo al Dock otra vez: Finder → arrastrar `TheSilenceOfTheShorts.app`
  a la parte izquierda del Dock.

## Caption SEO (título, caption, hashtags)

Casilla "Caption SEO" en el panel. Al terminar el vídeo se escribe
`nombre_limpio.md` junto a él con título (≤ 60 caracteres), caption
(120-200 palabras) y 8-15 hashtags, generados desde la transcripción por un
modelo local en Ollama. Al seleccionar el vídeo hecho en la cola aparece el
panel con botones de copiar.

- Requisitos: `brew install ollama` y `ollama pull qwen3.5:9b`. La app
  arranca `ollama serve` sola si no está corriendo y lo cierra al acabar.
- "Marca…": texto libre (quién eres, tono, CTA, hashtags fijos) que se
  añade al prompt. Se guarda en los ajustes.
- Modelo: `qwen3.5:9b` por defecto. Para cambiarlo, editar la clave
  `caption/modelo` de los ajustes (`defaults write com.albercv.LimpiadorVideo caption.modelo <modelo>`).
- Nunca hace fallar el vídeo: si Ollama no responde o el modelo no está
  descargado, la fila queda con ⚠ y el log dice qué instalar.
- CLI: `python limpiarVideo.py video.mp4 --caption --marca "Soy …"`.

## Errores y logs

- Cada trabajo escribe `logs/<vídeo>_<fecha>.log` con la config, los pasos
  con tiempos y, si falla, el diagnóstico completo (causa, qué hacer, salida
  cruda de la herramienta que falló).
- En la cola, una fila en error muestra el título del problema. Doble clic
  abre un diálogo con causa, solución, detalle técnico y botón "Abrir log".
- Los errores conocidos se traducen en `videopipeline/errores.py`
  (tabla `_CONOCIDOS`). Un error que salga como "desconocido" es un
  candidato a añadir ahí.
- auto-editor 31.x falla con "Could not write packet" en el H.264 de
  algunas exportaciones (p. ej. los mp4 del podcast). El paso de recorte
  reencoda con `h264_videotoolbox` y reintenta solo; la fila queda con ⚠.

## Origen

Extraído del fork local de
https://github.com/modelscope/ClearerVoice-Studio (subcarpeta
`clearvoice/`). Se descartaron demos, samples y salidas de vídeo.
