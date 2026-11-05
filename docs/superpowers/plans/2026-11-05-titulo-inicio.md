# Título al inicio del vídeo — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cada vídeo sale con un título de 3-5 palabras clave (Titan One, blanco con borde negro y contorno dorado desplazado) arriba al centro durante sus 5 primeros segundos, en el horizontal y en el vertical, con una casilla en «Subtítulos».

**Architecture:** módulo nuevo `videopipeline/titulo.py` con las dos funciones del contrato con shorts (`generar_titulo`, `lineas_titulo`). El título se pide a Ollama en su propia llamada antes de quemar y se añade como estilos y eventos extra al mismo `.ass` que ya se quema (un solo paso de codificación); la fuente va en el repo y se pasa a libass con `fontsdir`. En el reproceso, el título es un artefacto `titulo` de la ficha y una acción interna `TITULO`; el texto entra en los `ajustes` de las salidas quemadas, así que cambiar la casilla las rehace sin volver a transcribir.

**Tech Stack:** Python 3.11, PySide6, ffmpeg-full (libass), Ollama (`ollama.chat_json`), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-05-titulo-inicio-design.md`

## Global Constraints

- Código, comentarios y textos de la GUI en español; commits en inglés, sin atribución a IA (ni `Co-Authored-By` ni «Generated with»).
- Tests: `QT_QPA_PLATFORM=offscreen ~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m pytest -q` desde esta carpeta. Commit solo con la suite en verde.
- **Nunca** `-m ""` ni `-m lenta` (sube vídeos a TikTok con la cuenta real). Los 3 tests `slow` de modelos se saltan: es lo esperado.
- **No tocar** `~/Documents/personalProjects/limpiadorVideo` (producción): solo se usa su intérprete.
- Ningún test depende de Ollama, ffmpeg ni modelos, salvo el test `slow` de la tarea 1, que se salta sin ffmpeg-full.
- Duración 5 s; fundido 0,3 s al entrar y salir; mayúsculas; arriba al centro; tamaño ~7 % de la altura en horizontal y ~5,5 % en vertical; como mucho 90 % del ancho en 1-2 líneas, reduciendo la letra si no cabe; margen superior ~8 % de la altura.
- Dos capas ASS: capa 0 dorada con borde dorado grueso, desplazada abajo a la derecha; capa 1 blanca con borde negro.
- Fuente `TitanOne-Regular.ttf` + `OFL.txt` dentro del repo, pasada con `fontsdir`.
- Casilla en la sección «Subtítulos», activada por defecto, guardada con el resto del panel.
- Mismo modelo que el caption (`modelo_caption`), llamada propia antes de quemar, idioma de los subtítulos.
- Si falla el modelo: el vídeo sale sin título, con un aviso; nunca falla el procesado.
- Título activo sin subtítulos: se transcribe igualmente y se quema solo el título.
- Sin paso nuevo del panel ni pregunta nueva en el diálogo de reproceso.
- Traducciones con `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po`.
- La PR #25 (`fix/zoom-cara`) toca `vertical.py`: aquí solo cambia la línea `final = …` de `filtro_vertical`.

## Review Focus

- **Texto del modelo con `{`, `}` o `\`** (o una sola palabra larguísima): no debe inyectar etiquetas ASS ni salirse por los lados. Test en la tarea 2.
- **Carpeta de la app con espacios, comillas, comas o dos puntos en la ruta**: `fontsdir` debe seguir funcionando. Tests en la tarea 1 (unitario y con ffmpeg real).
- **Ollama apagado, modelo sin descargar, JSON roto, 2 palabras u 8 palabras**: el vídeo sale igual, sin título o recortado, con aviso. Tests en las tareas 3, 4 y 5.
- **Fichas y ajustes de antes de esta rama** (sin artefacto `titulo`, sin clave `panel/titulo`, JSON del runner sin `titulo`): el panel arranca con la casilla marcada; el JSON viejo vale como `titulo=False`; una ficha hecha añade el título sin retranscribir. Tests en las tareas 4, 5 y 6.
- **Salida antigua con subtítulos quemados y sin original** (`subs_quemados_sin_base`): nunca se quema el título encima. Test en la tarea 5.

---

### Task 1: Fuente en el repo y `fontsdir` en los filtros `ass`

**Files:**
- Create: `videopipeline/fuentes/TitanOne-Regular.ttf`, `videopipeline/fuentes/OFL.txt`
- Modify: `videopipeline/steps.py` (constante y dos funciones nuevas; `cmd_quemar_subtitulos`)
- Modify: `videopipeline/vertical.py:42` (solo la línea `final = …`)
- Test: `tests/test_steps.py`, `tests/test_vertical.py`, `tests/test_titulo.py` (nuevo)

**Interfaces:**
- Produces: `steps.DIR_FUENTES: Path` (`Path(__file__).resolve().parent / "fuentes"`); `steps.filtro_ass(ass_nombre: str) -> str` → `f"ass={ass_nombre}:fontsdir={_valor_filtro(str(DIR_FUENTES))}"`; `steps._valor_filtro(texto: str) -> str`, escape de dos niveles de un valor de opción dentro de un grafo de ffmpeg: nivel 1 antepone `\` a `\ ' :`; nivel 2, sobre el resultado, antepone `\` a `\ ' [ ] , ;`.

- [ ] **Step 1: Copiar la fuente.** Ya está descargada (autorizado por el usuario) en `/private/tmp/claude-501/-Users-albercv-Documents-personalProjects-tsots-titulo/d9b12cd8-1765-491c-9df8-6c1e219e8eff/scratchpad/fuente_descarga/`. Copia `TitanOne-Regular.ttf` y `OFL.txt` a `videopipeline/fuentes/`. Comprueba `shasum -a 256`: `563ff6de179bbd44bcd7d2a6c448d6dc3bf935834237cf1250e506e65cd86ff1` (ttf) y `61be7c29f4835e2be7243db12213d75d53ff028f29f4b493212a1688b1d3a1ba` (OFL). No descargues nada.

- [ ] **Step 2: Tests que fallan** en `tests/test_steps.py`:

```python
@pytest.mark.parametrize("ruta, esperado", [
    ("/Users/a/b c/fuentes", "/Users/a/b c/fuentes"),
    ("/x:y", "/x\\\\:y"),
    ("/a'b", "/a\\\\\\'b"),
    ("/a,b;c[d]", "/a\\,b\\;c\\[d\\]"),
])
def test_valor_filtro_escapa_los_dos_niveles(ruta, esperado):
    assert steps._valor_filtro(ruta) == esperado


def test_filtro_ass_pasa_la_carpeta_de_fuentes(monkeypatch, tmp_path):
    monkeypatch.setattr(steps, "DIR_FUENTES", tmp_path / "a b")
    assert steps.filtro_ass("subs.ass") == f"ass=subs.ass:fontsdir={tmp_path}/a b"
```

Y que `cmd_quemar_subtitulos(...)` lleve `"-vf", steps.filtro_ass("subs.ass")`; en `tests/test_vertical.py`, que `filtro_vertical(..., ass_nombre="subs_vertical.ass")` contenga `f",{filtro_ass('subs_vertical.ass')},format=yuv420p[v]"`. Ajusta los tests existentes que esperaban `ass=…` a secas.

- [ ] **Step 3: Ejecutar y ver que fallan** (`pytest tests/test_steps.py tests/test_vertical.py -q`): `AttributeError: … _valor_filtro`.

- [ ] **Step 4: Implementar** `DIR_FUENTES`, `_valor_filtro`, `filtro_ass` en `steps.py`; usar `filtro_ass` en `cmd_quemar_subtitulos` y en la línea `final` de `filtro_vertical` (importándolo de `.steps`). Un comentario de una línea: por qué `fontsdir` (no depender de que Titan One esté instalada).

- [ ] **Step 5: Test real (slow) que falla** en `tests/test_titulo.py`: `test_quema_real_usa_la_fuente_del_repo`, marcado `@pytest.mark.slow` y `skipif` si `steps.ffmpeg_con_ass()` lanza `PasoFallido`. Copia `videopipeline/fuentes` a `tmp_path / "a b'c,d"` y parchea `steps.DIR_FUENTES` a esa copia; escribe un `.ass` mínimo con un estilo `Fontname` = `Titan One` y un evento de 0 a 1 s; ejecuta ffmpeg (el de `ffmpeg_con_ass()`) sobre `-f lavfi -i color=c=gray:s=320x240:d=1` con `-vf steps.filtro_ass("t.ass")`, `cwd` la carpeta del `.ass`, `-loglevel verbose`, `-frames:v 1` a un `.png`. Asserts: código 0 y la línea `fontselect` del log nombra `TitanOne-Regular.ttf` dentro de la copia (si libass no registra esa línea en `verbose`, usa el nivel que la saque y deja dicho cuál en un comentario).

- [ ] **Step 6: Ejecutar** `pytest tests/test_titulo.py -q` → PASS (no SKIP: ffmpeg-full está en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`). Luego la suite entera → verde.

- [ ] **Step 7: Commit**

```bash
git add videopipeline/fuentes videopipeline/steps.py videopipeline/vertical.py tests/test_steps.py tests/test_vertical.py tests/test_titulo.py
git commit -m "feat: bundle Titan One and pass fontsdir to libass"
```

---

### Task 2: `lineas_titulo` y estilos/eventos extra en `generar_ass`

**Files:**
- Create: `videopipeline/titulo.py`
- Modify: `videopipeline/subtitles.py` (`partir_en_dos`, `_envolver`, `generar_ass`)
- Test: `tests/test_titulo.py`, `tests/test_subtitles.py`

**Interfaces:**
- Consumes: `subtitles._tiempo_ass`.
- Produces:
  - `subtitles.partir_en_dos(texto: str) -> str`: el corte de `_envolver` (espacio que minimiza la mitad más larga), con `\N`; `texto` igual si no hay espacios. `_envolver` pasa a usarla.
  - `subtitles.generar_ass(bloques, preset_id, posicion, resolucion, ruta, tamano=100, extra: tuple[list[str], list[str]] | None = None) -> None`: `extra` = (líneas `Style:`, líneas `Dialogue:`); los estilos van tras `Style: Sub`, los eventos antes de los de subtítulos. `bloques` puede ser `[]` (solo título).
  - `titulo.DURACION = 5.0` y `titulo.lineas_titulo(texto: str, resolucion: tuple[int, int], inicio: float = 0.0, duracion: float = DURACION) -> tuple[list[str], list[str]]` (función del contrato con shorts).

Constantes de `titulo.py` (valores iniciales; la tarea 8 los afina con un fotograma real): `FUENTE = "Titan One"`, `TAMANO_HORIZONTAL = 0.07`, `TAMANO_VERTICAL = 0.055` (fracción de la altura; vertical si `alto > ancho`), `ANCHO_UTIL = 0.90`, `MARGEN_SUPERIOR = 0.08`, `ANCHO_CARACTER = 0.62` (avance medio de una mayúscula de Titan One por punto de `Fontsize` de libass, medido), `BORDE = 0.08`, `BORDE_DORADO = 0.16`, `DESPLAZAMIENTO = 0.06` (fracciones del tamaño de letra), `DORADO = "&H0000C8FF"` (#FFC800 en `&HAABBGGRR`), `FUNDIDO_MS = 300`.

Algoritmo de `lineas_titulo` (lo que los tests no fijan):

```text
texto = quitar {, } y \ ; normalizar espacios; .upper()      → ([], []) si queda vacío
fs    = round(alto * (TAMANO_VERTICAL if alto > ancho else TAMANO_HORIZONTAL))
ancho_en_fs(n) = n * ANCHO_CARACTER + 2 * BORDE_DORADO + DESPLAZAMIENTO
si ancho_en_fs(len(texto)) * fs > ANCHO_UTIL * ancho:  texto = partir_en_dos(texto)
n  = caracteres de la línea más larga
fs = max(8, min(fs, int(ANCHO_UTIL * ancho / ancho_en_fs(n))))
borde = max(1, round(fs * BORDE)); dorado = round(fs * BORDE_DORADO); d = max(1, round(fs * DESPLAZAMIENTO))
x, y  = ancho // 2, round(alto * MARGEN_SUPERIOR)
estilos: "Style: TituloDorado,Titan One,{fs},{DORADO},&H00FFFFFF,{DORADO},&H00000000,0,0,0,0,100,100,0,0,1,{dorado},0,8,0,0,0,1"
         "Style: Titulo,Titan One,{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{borde},0,8,0,0,0,1"
eventos: "Dialogue: 0,{ini},{fin},TituloDorado,,0,0,0,,{\an8\pos(x+d,y+d)\fad(300,300)}TEXTO"
         "Dialogue: 1,{ini},{fin},Titulo,,0,0,0,,{\an8\pos(x,y)\fad(300,300)}TEXTO"
```

- [ ] **Step 1: Tests que fallan** en `tests/test_titulo.py` (helper `_estilo(linea) -> list[str]` = `linea.split(":", 1)[1].split(",")`, `_texto(evento)` = lo que va tras el bloque `{…}` inicial):
  - `test_dos_capas_arriba_centradas`: `lineas_titulo("Audio limpio ya", (1920, 1080))` → 2 estilos con nombres `TituloDorado` y `Titulo`, fuente `Titan One`, alineación `8`; `eventos[0]` empieza por `"Dialogue: 0,0:00:00.00,0:00:05.00,TituloDorado,"` y contiene `\pos(965,91)`; `eventos[1]` empieza por `"Dialogue: 1,0:00:00.00,0:00:05.00,Titulo,"` y contiene `\an8\pos(960,86)\fad(300,300)`; `_texto` de ambos = `"AUDIO LIMPIO YA"`; tamaño de los dos estilos `76`.
  - `test_vertical_usa_su_tamano`: `(1080, 1920)` → tamaño `106`, `\pos(540,154)`.
  - `test_largo_parte_en_dos_y_cabe`: `"Inteligencia artificial para limpiar audio"` en `(1080, 1920)` → `"\\N"` en `_texto(eventos[1])` y, con `n` = la línea más larga, `(n * ANCHO_CARACTER + 2 * BORDE_DORADO + DESPLAZAMIENTO) * fs <= ANCHO_UTIL * 1080`.
  - `test_palabra_sola_larguisima_reduce_la_letra`: `"Supercalifragilisticoespialidoso"` en `(1080, 1920)` → sin `\N`, cabe con la misma fórmula y `fs >= 8`.
  - `test_quita_llaves_y_barras`: `"{\\b1}Hola\\N mundo raro"` → `_texto` sin `{`, `}` ni `\` salvo un `\N` que ponga `partir_en_dos`.
  - `test_inicio_y_duracion`: `inicio=12.5, duracion=5.0` → `"0:00:12.50,0:00:17.50"` en los dos eventos.
  - `test_texto_vacio_no_da_nada`: `lineas_titulo("  {} ", (1920, 1080)) == ([], [])`.
  
  En `tests/test_subtitles.py`: `partir_en_dos("uno dos tres cuatro") == "uno dos\\Ntres cuatro"`, `partir_en_dos("palabra") == "palabra"`; `test_generar_ass_con_extra`: con `extra=lineas_titulo("Audio limpio ya", (1920, 1080))`, el archivo tiene `Style: Titulo,` entre `Style: Sub,` y `[Events]` y los dos `Dialogue` del título; con `bloques=[]` y `extra`, solo los del título.

- [ ] **Step 2: Ejecutar** → FAIL (`ModuleNotFoundError: videopipeline.titulo`).
- [ ] **Step 3: Implementar** `partir_en_dos`, `extra` en `generar_ass` y `lineas_titulo` según el algoritmo.
- [ ] **Step 4: Ejecutar** `pytest tests/test_titulo.py tests/test_subtitles.py -q` → PASS; suite entera → verde.
- [ ] **Step 5: Commit** `feat: ASS lines for the opening title`.

---

### Task 3: `generar_titulo` (prompt y validación)

**Files:**
- Modify: `videopipeline/titulo.py`
- Test: `tests/test_titulo.py`

**Interfaces:**
- Consumes: `ollama.chat_json`, `caption.recortar`, `steps.PasoFallido`.
- Produces:
  - `titulo.ESQUEMA = {"type": "object", "properties": {"titulo": {"type": "string"}}, "required": ["titulo"]}`.
  - `titulo.construir_mensajes(transcripcion: str, idioma: str) -> list[dict]`: system en inglés si `idioma == "en"`, en español si no (`"es"`, `"auto"`); user = `"Transcript:\n…"` / `"Transcripción:\n…"` con `recortar(transcripcion)`.
  - `titulo.pedir_titulo(transcripcion: str, idioma: str, modelo: str, cliente=chat_json) -> str`: lanza `PasoFallido` si la transcripción está vacía, si falta `titulo` o no es `str`, o si quedan menos de 3 palabras; recorta a 5.
  - `titulo.generar_titulo(transcripcion: str, idioma: str, modelo: str, cliente=chat_json) -> str | None` (función del contrato con shorts): `pedir_titulo`, o `None` con `log.warning` si lanza cualquier excepción.

Prompt (texto fijo del LLM, no se traduce con gettext; misma estructura que `caption._SYSTEM_ES/_EN`). Debe pedir: el título sobreimpreso en grande en los primeros segundos de un vídeo corto; de 3 a 5 palabras clave que digan de qué trata, con los temas, nombres o conceptos concretos que se mencionan; nada genérico («vídeo interesante», «mira esto»); sin emojis, hashtags, comillas ni punto final; en el mismo idioma que la transcripción; responder solo JSON.

Limpieza: quitar comillas `"'«»“”` y `#`, normalizar espacios, cortar a 5 palabras, quitar `.,;:` del final. Mensajes de `PasoFallido` (con `_()`): `"La transcripción está vacía; no hay texto para el título"`, `"La respuesta del modelo no trae un título"`, `"El modelo no propuso un título de 3 a 5 palabras: «{titulo}»"`.

- [ ] **Step 1: Tests que fallan** con un cliente falso que guarda sus argumentos y devuelve un dict:
  - `test_pedir_titulo_limpia_la_respuesta`: `{"titulo": "  «Limpia tu  audio con IA».  "}` → `"Limpia tu audio con IA"`; el cliente recibe `(modelo, mensajes, ESQUEMA)`.
  - `test_pedir_titulo_recorta_a_cinco_palabras`: `"uno dos tres cuatro cinco seis siete"` → `"uno dos tres cuatro cinco"`.
  - `test_pedir_titulo_con_menos_de_tres_palabras_falla`: `"Audio limpio"` → `PasoFallido`.
  - `test_pedir_titulo_sin_campo_falla`: `{}` y `{"titulo": 3}` → `PasoFallido`.
  - `test_generar_titulo_none_si_falla`: cliente que lanza `PasoFallido("Ollama no responde")` → `None`; transcripción `"   "` → `None` sin llamar al cliente.
  - `test_mensajes_por_idioma`: `"en"` → system contiene `"3 to 5"`; `"es"` y `"auto"` → contiene `"3 a 5"`; el user lleva la transcripción.
- [ ] **Step 2: Ejecutar** → FAIL. **Step 3: Implementar.** **Step 4:** PASS; suite → verde.
- [ ] **Step 5: Commit** `feat: generate the opening title with the caption model`.

---

### Task 4: `PipelineConfig.titulo` y el título en `pipeline.run`

**Files:**
- Modify: `videopipeline/config.py`, `videopipeline/pipeline.py`
- Modify: `tests/falsos_pipeline.py`
- Test: `tests/test_pipeline.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `titulo.pedir_titulo`, `titulo.lineas_titulo`, `generar_ass(..., extra=…)`.
- Produces (los usa la tarea 5):
  - `PipelineConfig.titulo: bool = False` (tras `caption_seo`). `False` por defecto: la CLI y los JSON antiguos siguen igual; la GUI manda su valor.
  - `pipeline._fase_titulo(config, palabras: list[Palabra] | None, on_progress, paso: int, total: int) -> str | None`: `None` sin palabras (sin aviso: ya avisó quien transcribió); si no, emite `_("Generando título")`, `asegurar_servidor()`, `pedir_titulo(texto_plano(palabras), config.idioma_subs, config.modelo_caption)` y cierra el servidor. Cualquier excepción → aviso `_("No se pudo generar el título: {error}. Vídeo guardado sin título.{sugerencia}")` y `None`. Saca de `_fase_caption` dos ayudantes que comparten: `_sugerencia(error) -> str` (el «Qué hacer» de `explicar`) y `_cerrar_servidor(servidor, on_progress)`.
  - `_quemar_subs(..., titulo: str | None = None)` y `_fase_vertical(..., titulo: str | None = None)`: generan el `.ass` si hay `bloques` **o** `titulo`, con `extra=lineas_titulo(titulo, resolución)` si hay título y `bloques or []`. En `_quemar_subs`, sin bloques la etiqueta es `_("Quemando el título")` y el aviso al degradar `_("El título no se pudo quemar: {error}. Vídeo guardado sin título.")`. En `_fase_vertical`, `usa_ass` y `ass_nombre` dependen de `bloques or titulo`.

Cambios en `run` y `total_pasos` (con `transcribe = config.subtitulos or config.titulo`):
- `total_pasos`: `+1 + hay_horizontal()` si `transcribe`; `+1` si `titulo`; caption `+1` si `transcribe`, si no `+2`.
- Tras los subtítulos: si no hay subtítulos y sí título, emitir `_("Transcribiendo")` y `_transcribir(config, base, on_progress)` (sin `.srt`); un fallo avisa `_("No se pudo transcribir para el título: {error}. Vídeo guardado sin título.")`. `paso += 1`. Luego, con título, `titulo = _fase_titulo(...)`, `paso += 1`.
- Horizontal: se quema si `bloques or titulo`; el paso de quemado cuenta si `transcribe`. El caption reutiliza `palabras` y suma `1 if transcribe else 2`.
- Vertical: `_fase_vertical(..., titulo=titulo)`.

- [ ] **Step 1: Falsos.** En `tests/falsos_pipeline.py`: `falso_ass` acepta `extra=None` y, si `extra` trae eventos, añade `"ass:titulo"`. Fixture nueva `entorno_titulo(entorno_caption, monkeypatch)` que parchea `pedir_titulo` (en `pipeline`) con un falso que añade `f"titulo:{modelo}:{idioma}"` y devuelve `"Audio limpio ya"`, y expone en el dict devuelto una forma de hacerlo fallar (p. ej. `estado["falla"] = True` → `PasoFallido("Ollama no responde")`).
- [ ] **Step 2: Tests que fallan** en `tests/test_pipeline.py`:
  - `test_titulo_sin_subtitulos_transcribe_y_quema_solo_el_titulo`: `paso_audio=False, paso_silencios=True, titulo=True` → en orden `cortar…`, `transcribir:es:turbo`, `ollama:asegurar`, `titulo:qwen3.5:9b:es`, `ollama:cerrar`, `ass:titulo`, `quemar`; sin `agrupar` ni `.srt` junto al final; el final existe.
  - `test_titulo_y_subtitulos_en_el_mismo_ass`: `subtitulos=True, titulo=True` → un solo `transcribir`, un solo `quemar`, `ass:titulo` presente.
  - `test_titulo_fallido_avisa_y_guarda_el_video`: falso que falla, `paso_silencios=True, titulo=True` → un `warning` que contiene `"título"`, sin `quemar`, el final existe.
  - `test_titulo_en_el_vertical`: `paso_silencios=True, paso_vertical=True, titulo=True` (con `entorno_vertical`) → la llamada `vertical:` tiene `usa_ass` `True` y el filtro contiene `ass=subs_vertical.ass`.
  - `test_caption_reutiliza_la_transcripcion_del_titulo`: `paso_silencios=True, titulo=True, caption_seo=True` → `transcribir` una sola vez.
  - `test_total_pasos_con_titulo` parametrizado: `(silencios, titulo) → 4`, `(subtitulos, titulo, sin base) → 3`, `(silencios, titulo, caption) → 5`; y en un `run` real con fakes, el mayor `step` emitido == `total`.
  - En `tests/test_config.py`: `PipelineConfig.from_json` de un JSON sin `titulo` → `titulo is False`; `to_json` lo incluye.
- [ ] **Step 3: Ejecutar** → FAIL. **Step 4: Implementar.** **Step 5:** PASS; suite → verde (los tests existentes del pipeline no cambian de comportamiento con `titulo=False`).
- [ ] **Step 6: Commit** `feat: burn the opening title in pipeline.run`.

---

### Task 5: El título en la ficha y en el reproceso

**Files:**
- Modify: `videopipeline/ficha.py` (constante `TITULO = "titulo"`), `videopipeline/reproceso_plan.py`, `videopipeline/reproceso.py`
- Test: `tests/test_reproceso_plan.py`, `tests/test_reproceso.py`

**Interfaces:**
- Consumes: `PipelineConfig.titulo`, `pipeline._fase_titulo`, `_quemar_subs(…, titulo=)`, `_fase_vertical(…, titulo=)`.
- Produces:
  - Artefacto `TITULO`: `Artefacto(clave(texto), None, {"texto": texto})`. No se usa `_vale` con él (no tiene archivo): vale si está.
  - `ajustes` de `HORIZONTAL` y `VERTICAL`: `"titulo": texto` cuando se quemó con título.
  - `Accion.TITULO = "titulo"`, entre `TRANSCRIBIR` y `QUEMAR`.
  - `Plan.config.titulo` = `quiere_titulo` (abajo).

Planificador (`planificar`); el resto de reglas no cambia:

```python
_NUEVO = object()  # título que esta pasada genera: distinto de cualquier quemado

titulo_art = ficha.artefactos.get(TITULO)
# R2: nunca sobre una salida antigua con subtítulos quemados y sin original.
quiere_titulo = config.titulo and not _subs_bloqueados(ficha)
titulo = (None if not quiere_titulo
          else titulo_art.ajustes["texto"] if titulo_art else _NUEVO)
efectiva = replace(efectiva, ..., titulo=quiere_titulo)

def titulo_de(tipo):  # el quemado en esa salida, o None
    artefacto = ficha.artefactos.get(tipo)
    return artefacto.ajustes.get("titulo") if artefacto else None

# sustituye a quemar_sin_base_nueva:
cambia_quemado = horizontal and (
    (subs is not None and (crea_horizontal or subs != subs_antes or retranscribir))
    or titulo != titulo_de(HORIZONTAL))

# en genera_vertical: cambia_titulo = titulo != titulo_de(VERTICAL); entra en
# `desactualizado` y fuerza `regenera` (cambiar la casilla rehace las salidas
# quemadas sin preguntar, R7 no se consulta).
# rehace_base usa cambia_quemado en lugar de quemar_sin_base_nueva.

quema = subs is not None or titulo is not None
quemar = horizontal and quema and (rehace_base or cambia_quemado)
# ESCRIBIR_FINAL: horizontal and not quema and (rehace_base or crea_horizontal or cambia_quemado)
transcribe_subs = subs is not None and not transcripcion_vale and (quemar or genera)
genera_titulo = titulo is not None and (quemar or genera) and (
    titulo is _NUEVO or transcribe_subs)  # transcripción nueva → título nuevo
# TRANSCRIBIR si transcribe_subs, o si genera_titulo y no hay transcripción.
# TITULO si genera_titulo.
```

Ejecutor (`_Pasada`):
- `_titulo(self) -> str | None`: el texto de `TITULO` si `self.c.titulo` y existe; si no, `None`.
- `titulo(self, paso)`: `_palabras()` (un `PasoFallido` de transcripción dañada se avisa y sale) y `_fase_titulo(...)`; con texto, guarda `TITULO` y la ficha. Si falla, el `TITULO` que hubiera se conserva.
- `transcribir`: `para_subs = c.subtitulos and (QUEMAR in acciones or VERTICAL in acciones)`, para que un fallo al transcribir solo para el título se degrade.
- `quemar`: palabras solo si `c.subtitulos`; se quema si `bloques or titulo` con `titulo=self._titulo()`; `ajustes` con `"subtitulos"` si hubo bloques y `"titulo"` si hubo título. Si no hay nada que quemar y la base no es de esta pasada: sin subtítulos se vuelve sin tocar nada (el final se queda como estaba); con subtítulos, el error de hoy. La base nueva se guarda aparte igual que hoy (R3: también con solo título).
- `escribir_final`: admite también `self.base == self.ficha.ruta("base.mp4")` (quitar el título de un final sin subtítulos); nunca el original ni `original.*` de la ficha.
- `vertical`: `titulo=self._titulo()` a `_fase_vertical` y `"titulo"` en sus `ajustes`.

- [ ] **Step 1: Tests que fallan** en `tests/test_reproceso_plan.py`. Helpers: `T = "Audio limpio ya"`, `_titulo(texto=T) -> Artefacto(clave(texto), None, {"texto": texto})`; `_horizontal(subs=True, titulo=None)` y `_vertical(..., titulo=None)` añaden `"titulo"` a sus ajustes si se pasa. Casos (añadir a `CASOS` o como tests sueltos):
  - ficha nueva con `TODO, paso_vertical=True, titulo=True` → `[LIMPIAR_AUDIO_ORIGINAL, CORTAR, TRANSCRIBIR, TITULO, QUEMAR, CAPTION, VERTICAL]`.
  - `_completa` + `titulo=True` → `[TITULO, QUEMAR]` (sin `TRANSCRIBIR`).
  - `{BASE: _base(silencios=True, aparte=False), HORIZONTAL: _horizontal(subs=False)}` + `titulo=True` → `[TRANSCRIBIR, TITULO, QUEMAR]`.
  - `_completa` con `HORIZONTAL: _horizontal(titulo=T), TITULO: _titulo()`: `titulo=True` → `[]`; `titulo=False` → `[QUEMAR]`; `subtitulos=True, titulo=True` + rehacer subtítulos → `[TRANSCRIBIR, TITULO, QUEMAR]`; `subtitulos=True, diseno="caja", titulo=True` + rehacer subtítulos → `[QUEMAR]`; `caption_seo=True, titulo=True` + rehacer caption → `[CAPTION]`.
  - `{BASE: _base(silencios=True), HORIZONTAL: _horizontal(subs=False, titulo=T), TITULO: _titulo()}` + `titulo=False` → `[ESCRIBIR_FINAL]`.
  - el mismo + `paso_silencios=True, margen="0.4s", titulo=True` + rehacer silencios → `[CORTAR, QUEMAR]`.
  - `_completa` con `VERTICAL: _vertical(subs=True)` + `titulo=True`, `Decisiones()` → `[TITULO, QUEMAR, VERTICAL]` y `plan.marcar_desactualizado is False`.
  - `_legado(tmp_path, original=False, legado=True)` + `paso_silencios=True, titulo=True` → `[CORTAR, ESCRIBIR_FINAL]` (como `test_legado_permite_recortar`) y `plan.config.titulo is False`.
  - `revisar(_completa(tmp_path), _panel(titulo=True)) == []`.

  En `tests/test_reproceso.py` (con `entorno_titulo` añadido a la fixture autouse `falsos`):
  - `test_titulo_se_guarda_y_se_quema`: ficha nueva, `paso_silencios=True, titulo=True` → `[CORTAR, TRANSCRIBIR, TITULO, QUEMAR]`; `TITULO.ajustes == {"texto": "Audio limpio ya"}`; `HORIZONTAL.ajustes["titulo"] == "Audio limpio ya"`; existe `base.mp4` en la ficha (R3); `"ass:titulo"` en las llamadas; `_sin_restos`.
  - `test_titulo_fallido_sale_sin_titulo`: falso que falla → un aviso con `"título"`; sin `TITULO`; `"titulo" not in HORIZONTAL.ajustes`; el final existe.
  - `test_quitar_el_titulo_sin_subtitulos_escribe_el_final_desde_la_base`: tras el anterior con éxito, pasada con `titulo=False` → `[ESCRIBIR_FINAL]`; no queda `base.mp4`; `BASE.archivo is None`; `HORIZONTAL.ajustes == {}`.
  - `test_titulo_en_el_vertical_se_registra`: `paso_silencios=True, paso_vertical=True, titulo=True` → `VERTICAL.ajustes["titulo"] == "Audio limpio ya"`.
  - `test_titulo_que_falla_al_regenerar_conserva_el_anterior`: ficha con título `"Viejo título aquí"` quemado y subtítulos; rehacer subtítulos con el falso fallando → `TITULO` sigue con el viejo y `HORIZONTAL.ajustes["titulo"] == "Viejo título aquí"`.
- [ ] **Step 2: Ejecutar** → FAIL. **Step 3: Implementar.** **Step 4:** PASS; suite → verde (los casos existentes no cambian con `titulo=False`).
- [ ] **Step 5: Commit** `feat: keep the opening title in the record and reprocess it`.

---

### Task 6: Casilla «Título al inicio» en la sección «Subtítulos»

**Files:**
- Modify: `app/widgets/panel_opciones.py`
- Test: `tests/test_app_widgets.py`

**Interfaces:**
- Consumes: `PipelineConfig.titulo` (`main.procesar` ya pasa `**valores` a la config y guarda el panel con `guardar_panel`: no cambia).
- Produces: `PanelOpciones.check_titulo: QCheckBox`; `valores()["titulo"]: bool`.

- Texto `_("Título al inicio")`; tooltip `_("Tres a cinco palabras clave arriba durante los 5 primeros segundos, escritas por el modelo del caption (Ollama) a partir de la transcripción.")`. Fila propia justo debajo de `check_subtitulos`; marcada por defecto; habilitada siempre (no depende de los subtítulos).
- `cargar`: `_como_bool(valores.get("titulo"), True)`.
- Idioma y modelo de Whisper (y su aviso de descarga) se habilitan con subtítulos **o** título; diseño, posición y tamaño, solo con subtítulos. El botón «Términos…», con subtítulos, caption o título.
- No es un paso: no entra en `_casillas_pasos`, `hay_pasos` ni «Marcar todo».

- [ ] **Step 1: Tests que fallan**:
  - `test_titulo_marcado_por_defecto_y_en_valores`: panel nuevo → `check_titulo.isChecked()`, `valores()["titulo"] is True`, `secciones["subtitulos"].contenido.isAncestorOf(check_titulo)`.
  - `test_cargar_titulo`: `cargar({"titulo": "false"})` → desmarcada; `cargar({"titulo": False})` → desmarcada; `cargar({})` → marcada.
  - `test_titulo_sin_subtitulos_habilita_idioma_y_modelo`: subtítulos off + título on → `combo_idioma_subs` y `combo_modelo_whisper` habilitados, `combo_diseno` no; los dos off → idioma deshabilitado.
  - `test_titulo_no_es_un_paso`: todos los pasos desmarcados y título marcado → `hay_pasos() is False`.
- [ ] **Step 2: Ejecutar** → FAIL. **Step 3: Implementar.** **Step 4:** PASS; suite → verde (ajusta los tests que comparan `valores()` entero).
- [ ] **Step 5: Commit** `feat: opening title checkbox in the subtitles section`.

---

### Task 7: Traducciones y documentación

**Files:**
- Modify: `locale/tsots.pot`, `locale/en/LC_MESSAGES/tsots.po`, `locale/en/LC_MESSAGES/tsots.mo` (los genera el script)
- Modify: `README.md`, `README.es.md`, `docs/DEVELOPMENT.md`, `docs/TODO.md`

- [ ] **Step 1:** `lanzador/traducir.sh`; traduce al inglés cada `msgid` nuevo de la rama en `tsots.po` (sin `fuzzy`); `lanzador/traducir.sh` otra vez para compilar. `test_i18n` → PASS.
- [ ] **Step 2: Documentación.**
  - READMEs: en la parte de subtítulos, una frase sobre la casilla «Título al inicio» (qué hace, que usa Ollama y que sin él el vídeo sale sin título) y que la fuente Titan One va incluida con licencia OFL (`videopipeline/fuentes/OFL.txt`).
  - `DEVELOPMENT.md`: fila `titulo` en la tabla de artefactos (`ajustes {"texto": …}`, sin archivo, se genera si falta o con una transcripción nueva de subtítulos); `"titulo"` en los `ajustes` de `horizontal` y `vertical`; la acción `TITULO`; que cambiar la casilla rehace las salidas quemadas sin preguntar (también el vertical) y que nunca se quema sobre `subs_quemados_sin_base`; `fontsdir` (`steps.filtro_ass`); y el contrato para shorts: `titulo.generar_titulo` y `titulo.lineas_titulo` con sus firmas y un ejemplo de uso con `generar_ass(..., extra=…)`.
  - `docs/TODO.md`: «Edit the opening title by hand before burning» (fuera de esta rama según el diseño).
- [ ] **Step 3:** suite → verde. **Commit** `docs: opening title, its translations and the shorts contract`.

---

### Task 8 (controlador): ajuste con un fotograma real y prueba del prompt

No es para un subagente: lo hace quien coordina, con criterio visual.

- [ ] Quemar con `pipeline._quemar_subs` (o ffmpeg directo con `filtro_ass`) un clip `testsrc2` de 1920x1080 y otro de 1080x1920, con y sin subtítulos, títulos de 3 y de 5 palabras; extraer el fotograma de t=2 s a PNG y mirarlo. Comprobar: legible, centrado, sin cortes por los lados, aire por arriba, contorno dorado visible abajo a la derecha. Ajustar las constantes de `titulo.py` si hace falta (y los números exactos de sus tests).
- [ ] Probar `generar_titulo` contra Ollama local (`gemma4:12b-mlx` u otro instalado) con dos o tres transcripciones de ejemplo en español y una en inglés: que salgan 3-5 palabras concretas. Ajustar el prompt si salen genéricas.
- [ ] Suite → verde. **Commit** `fix: tune the opening title look and prompt` (solo si hubo cambios).

---

## Desviaciones durante la ejecución

Lo que se hizo distinto de lo escrito arriba, y por qué:

- **Anchura del título (tarea 8).** `ANCHO_CARACTER = 0.62`, una media para
  todas las letras, se sustituye por una tabla medida por glifo, `_ANCHOS`
  (avance de cada carácter de Titan One por punto de tamaño de libass), con
  `ANCHO_DESCONOCIDO = 0.70` para lo que no está en la tabla. Se añade además
  el espaciado entre letras `ESPACIADO = 0.04` (fracción del tamaño de letra,
  `Spacing` del estilo). La media no reflejaba el ancho de cada letra;
  `_ancho_en_fs` suma ahora el avance de cada glifo más el espaciado.
- **`ESQUEMA` con `idioma` antes que `titulo` (tarea 3).** El esquema pide
  los dos campos, `idioma` primero: Ollama genera los campos en ese orden, así
  el modelo nombra el idioma de la transcripción antes de escribir el título.
  La validación sigue leyendo solo `titulo`.
- **El título solo fuerza a rehacer lo que hizo la app (tarea 5).** Un título
  distinto obliga a rehacer una salida solo si la hizo la app y su base vale
  (`_base_vale`). En salidas heredadas o adoptadas, o si no se puede rehacer
  la base, el título va con esa salida cuando se rehace por otro motivo. Nunca
  se quema sobre `subs_quemados_sin_base` (R2).
