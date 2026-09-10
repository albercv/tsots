# Caption SEO generado por LLM local — diseño

Fecha: 2026-09-10. Estado: aprobado en chat, pendiente de revisión escrita.

## Objetivo

Al procesar un vídeo, generar título orientado a SEO, caption para redes
(Reels / TikTok / Shorts, una sola versión) y hashtags, a partir de la
transcripción, usando un modelo local servido por Ollama. El resultado se
guarda junto al vídeo y se muestra en la app con botones de copiar.

Decisiones tomadas con el usuario:

- Modelo local vía Ollama (ya instalado, `qwen3.5:9b` descargado). Sin API
  externa. Se deja una costura para otros proveedores, sin implementarlos.
- Casilla propia "Caption SEO", independiente de subtítulos.
- Salida: fichero `.md` junto al vídeo + panel en la app.
- Una versión única de caption, no por plataforma.
- Contexto de marca configurable (texto libre en Ajustes) que entra en el
  prompt.

Medido en spike (M3 Max, 36 GB): `qwen3.5:9b` carga en 6,5 s, genera ~440
tokens en 11 s (40 tok/s), ocupa 5,6 GB de GPU y Ollama lo descarga a los 5
min de inactividad. Calidad del borrador: aceptable.

## Fuera de alcance

- Captions por plataforma, descripción larga de YouTube, capítulos.
- Elegir modelo desde la GUI (queda en config/QSettings, editable a mano).
- Reintentos automáticos de generación, evaluación de calidad, traducción.
- Proveedores distintos de Ollama.

## Arquitectura

Un paso opcional más al final del pipeline, con la misma filosofía que los
subtítulos: **nunca hace fallar el vídeo**. Si algo falla, el vídeo se
publica igual, la fila queda con ⚠ y el log recoge el diagnóstico.

```
run(config)
  … pasos actuales …
  _fase_subtitulos  → (publicar, palabras | None)      # devuelve la transcripción
  _fase_caption(config, final, palabras, …)            # nuevo, opcional
      palabras = palabras or transcribir(publicar…)    # reutiliza si ya existe
      texto = texto_plano(palabras)
      caption = caption.generar(texto, config.contexto_marca, config.modelo_caption)
      caption.escribir_md(caption, final.with_suffix(".md"))
  publicar.replace(final)
```

### Módulos nuevos

`videopipeline/ollama.py` — cliente mínimo, sin dependencias externas
(`urllib`).

- `URL = "http://localhost:11434"`.
- `disponible(timeout=1.0) -> bool`: `GET /api/version`.
- `asegurar_servidor() -> Servidor`: si no responde, lanza `ollama serve`
  como hijo (`subprocess.Popen`, salida a `DEVNULL`), espera hasta 15 s a que
  responda. Devuelve un objeto con `cerrar()` que termina el hijo **solo si
  lo arrancó él**. Si `ollama` no está en PATH: `PasoFallido("Ollama no está
  instalado…")`.
- `chat_json(modelo, mensajes, esquema, timeout=300) -> dict`: `POST
  /api/chat` con `stream: false`, `format: esquema`, `think: false`,
  `options: {temperature: 0.7, num_ctx: 16384}`. Parsea
  `message.content` como JSON. Errores HTTP 404 con "not found" →
  `PasoFallido("Modelo no descargado: ollama pull <modelo>")`.

`videopipeline/caption.py` — lógica de negocio, funciones puras salvo la
llamada al cliente.

- `@dataclass Caption(titulo, caption, hashtags: list[str], palabras_clave:
  list[str])`.
- `MAX_PALABRAS = 3500`: la transcripción se recorta a las primeras 3500
  palabras (≈ 20 min de habla) para no desbordar el contexto.
- `texto_plano(palabras: list[Palabra]) -> str`.
- `construir_mensajes(transcripcion, contexto_marca) -> list[dict]`: system
  prompt (SEO + copywriting en español de España, límites: título ≤ 60
  caracteres con la palabra clave al inicio; caption 120-200 palabras con
  gancho, desarrollo y CTA; 8-15 hashtags en minúsculas sin espacios;
  5-8 palabras clave) + bloque "Contexto de marca" si no está vacío + user
  con la transcripción.
- `ESQUEMA`: JSON Schema con los cuatro campos, `required` todos.
- `generar(transcripcion, contexto_marca, modelo, cliente=chat_json) ->
  Caption`: construye, llama, valida (tipos, hashtags con `#`, sin
  duplicados, título recortado a 60 si se pasa).
- `escribir_md(caption, ruta)` y `leer_md(ruta) -> Caption | None`. Formato:

```markdown
# <título>

## Caption
<caption>

## Hashtags
#a #b #c

## Palabras clave
- a
- b
```

`leer_md` es el inverso exacto de `escribir_md`; la GUI lo usa para
mostrar el panel sin volver a llamar al modelo.

### Cambios en módulos existentes

`videopipeline/config.py`

- `caption_seo: bool = False`, `contexto_marca: str = ""`,
  `modelo_caption: str = "qwen3.5:9b"`.
- `validar()`: `modelo_caption` no vacío.

`videopipeline/pipeline.py`

- `_fase_subtitulos` devuelve `(publicar, palabras | None)`; `palabras` es
  `None` si la transcripción falló. Los llamadores actuales se adaptan.
- Nueva `_fase_caption(config, publicar, final, palabras, on_progress,
  paso, total) -> None`. Pasos que emite: "Transcribiendo" (solo si
  `palabras is None`) y "Generando caption SEO". Todo dentro de
  `try/except Exception` → `{"warning": "Caption SEO falló: … Vídeo guardado
  sin caption."}`. Borra un `.md` anterior antes de empezar para no dejar
  uno obsoleto.
- Conteo de pasos: `extra = (2 if subtitulos else 0) + (1 if caption_seo
  and subtitulos else 2 if caption_seo else 0)`.
- Cierre del servidor Ollama arrancado bajo demanda en `finally`.

`videopipeline/errores.py` — tres entradas en `_CONOCIDOS`:

- `Ollama no está instalado` → "brew install ollama".
- `Modelo no descargado` → "ollama pull <modelo>" (el detalle lleva el
  nombre).
- `Ollama no responde` (tras intentar arrancarlo) → revisar que el puerto
  11434 esté libre; `ollama serve` a mano para ver el error.

`videopipeline/runner.py` — sin cambios. El log ya recoge los warnings.

`limpiarVideo.py` — flags `--caption` y `--marca TEXTO`.

### GUI

`app/settings.py` — propiedades `contexto_marca` (clave
`caption/contexto_marca`) y `modelo_caption` (clave `caption/modelo`,
por defecto `qwen3.5:9b`).

`app/widgets/panel_opciones.py` — grupo "Caption SEO" con casilla
"Generar título, caption y hashtags" y botón "Marca…". `valores()` incluye
`caption_seo`. `cargar()` lo restaura. Señal `editar_marca` al pulsar el
botón.

`app/widgets/dialogo_marca.py` — `QDialog` con `QPlainTextEdit` y
Aceptar/Cancelar. Texto de ayuda: "Quién eres, tono, llamada a la acción
habitual, hashtags fijos". `texto()` devuelve el contenido.

`app/widgets/panel_caption.py` — widget bajo la previsualización. Método
`mostrar(caption: Caption | None)`. Muestra título (negrita), caption
(`QTextEdit` solo lectura, alto fijo), hashtags en una línea, y cuatro
botones: Copiar título, Copiar caption, Copiar hashtags, Copiar todo
(`QApplication.clipboard()`). Con `None` se oculta.

`app/main.py`

- `procesar()`: añade `contexto_marca` y `modelo_caption` desde `Ajustes`
  a `PipelineConfig`.
- Botón "Marca…" → abre `DialogoMarca` con el texto actual; al aceptar
  guarda en `Ajustes`.
- `_al_cambiar_seleccion`: si el trabajo está HECHO, `leer_md(salida.with_suffix(".md"))`
  y `panel_caption.mostrar(...)`; si no, `mostrar(None)`.
- `_al_terminar_trabajo` con ok: si la fila es la seleccionada, refresca
  el panel.

`app/queue_model.py` — sin cambios; la ruta del `.md` se deriva de
`salida`.

`app/worker.py` — sin cambios.

## Flujo de datos

1. Usuario marca "Caption SEO", opcionalmente rellena "Marca…", pulsa
   Procesar. `PipelineConfig` viaja al runner como hasta ahora (JSON).
2. Runner ejecuta el pipeline. Al final, `_fase_caption` obtiene la
   transcripción (reutilizada o nueva), llama a Ollama, escribe
   `nombre_limpio.md`.
3. Runner emite `done` con `salida`. La GUI, al seleccionar la fila,
   lee `salida.with_suffix(".md")` y lo muestra.
4. El usuario copia bloques al portapapeles.

## Errores y degradación

| Situación | Efecto |
|---|---|
| Ollama no instalado | warning en fila, diagnóstico "brew install ollama" en log |
| Modelo no descargado | warning, "ollama pull qwen3.5:9b" |
| Servidor no arranca en 15 s | warning, "Ollama no responde" |
| JSON inválido o campos faltantes | warning "respuesta del modelo no válida", detalle con la respuesta cruda |
| Transcripción vacía | warning "la transcripción no produjo palabras" |
| Timeout (300 s) | warning con el tiempo |

En todos los casos el vídeo se publica.

## Tests

- `test_caption.py`: recorte a 3500 palabras; mensajes incluyen marca
  solo si no está vacía; `generar` valida y normaliza (hashtags sin `#` se
  corrigen, duplicados fuera, título > 60 recortado); `escribir_md` /
  `leer_md` son inversos; `leer_md` de fichero inexistente → `None`.
- `test_ollama.py`: `disponible` contra servidor HTTP falso en hilo;
  `asegurar_servidor` arranca `ollama serve` (Popen falseado) cuando no
  responde y lo cierra solo si lo arrancó; 404 modelo → mensaje "ollama
  pull"; `ollama` ausente en PATH → mensaje "no está instalado".
- `test_pipeline.py`: caption con subtítulos reutiliza `palabras` (no se
  llama a `transcribir` dos veces); caption sin subtítulos transcribe;
  fallo del generador → warning y vídeo publicado; `.md` anterior borrado;
  conteo de pasos.
- `test_config.py`: nuevos campos, JSON ida y vuelta, validación.
- `test_errores.py`: tres patrones nuevos.
- `test_app_widgets.py`: casilla en `valores()`/`cargar()`; diálogo de
  marca devuelve texto; panel de caption muestra y copia al portapapeles
  (`QApplication.clipboard().text()`).
- `test_app_main.py`: seleccionar trabajo hecho con `.md` muestra el
  panel; sin `.md` lo oculta; "Marca…" persiste en `Ajustes`;
  `procesar()` mete `contexto_marca` en la config.
- Integración lenta (`-m slow`, se salta si Ollama no responde): pipeline
  real con caption sobre el vídeo sintético.
