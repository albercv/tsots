# Edición automática de shorts con Claude — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TSOTS edita en segundo plano cada short creado (rótulos, contadores, emojis, transiciones, zoom, SFX, música) con `claude -p --model claude-haiku-5-5` y publica la versión editada.

**Architecture:** Motor determinista nuevo en `videopipeline/edicion/` (port de los scripts probados en `VideoEditor/tools/` y `chatcut/tools/`). `shorts.crear` encola un trabajo por short en `~/TSOTS/edicion/pendientes/`; la app lanza `lanzador/edicion/procesar_pendientes.sh` (gemelo del agente del blog), que ejecuta Haiku con `SKILL.md` inline: Haiku solo escribe `plan.json` (qué y cuándo); el código deriva posiciones, sonidos y montaje, y un comprobador en Python decide si el resultado se entrega como `NN - título.editado.mp4`.

**Tech Stack:** Python 3 (`.venv-clearvoice`: Pillow 12.3, numpy 1.26, scipy 1.17), ffmpeg-full, PySide/Qt + pytest-qt, bash, Claude Code CLI.

**Spec:** `docs/superpowers/specs/2026-11-17-edicion-shorts-design.md` (léelo antes de cada tarea; este plan argumenta desde él).

## Global Constraints

- Repo `~/Documents/personalProjects/limpiadorVideo`; trabajar en el worktree `~/Documents/personalProjects/tsots-edicion`, rama `feature/edicion-shorts` desde `develop`. Nunca push a `develop`/`main`; PR a `develop` con descripción completa.
- Commits en inglés, **sin atribución de IA** (sin `Co-Authored-By`, sin "Generated with"). Código, comentarios y textos de GUI en español.
- Tests antes de cada commit; commit solo si pasan. Comando (el worktree no tiene venv propio):
  `PY=~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python; QT_QPA_PLATFORM=offscreen $PY -m pytest -q`
- Textos de GUI nuevos con `_()`/`N_()` de `videopipeline.i18n`, traducidos en `locale/en/LC_MESSAGES/tsots.po` y compilados con `lanzador/traducir.sh`.
- ffmpeg: `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` (como `videopipeline/steps.py:117`). Overlays con alpha: ProRes 4444 `prores_ks -profile:v 4444 -pix_fmt yuva444p10le`. Nunca WebM.
- Modelo: `claude-haiku-5-5`. Límite por trabajo: `TSOTS_EDICION_LIMITE`, por defecto `1200` s (render completo medido: 32 s para 112 s de vídeo).
- Credenciales: ningún fichero nuevo lee, guarda, copia ni define credenciales de Claude (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`…). `claude -p` usa la sesión del usuario de ese Mac.
- Rutas: `~/TSOTS/edicion/{pendientes,hechos,errores}`, log `~/TSOTS/edicion/agente.log`. Resultado junto al original: `<stem>.editado.mp4` (temporal `<stem>.editado.mp4.tmp`). Nunca se toca ni borra el `<stem>.mp4` limpio.
- Audio: voz normalizada a `-16 LUFS` (TP -1.5) antes de mezclar; salida `loudnorm I=-14:TP=-1.5:LRA=11`, 48 kHz. Easing nunca lineal (`ease_out_cubic`/`ease_out_back`).
- Estilos `divertido`, `formal`, `academico` con los valores de la tabla 5.6 del spec.
- Nada de `whisper` CLI ni entornos `uv` nuevos.

## Review Focus

1. **Short sin voz o con muy pocas palabras** (plan vacío): debe salir un editado válido (boom de entrada, música, sin gráficos), no un error. → Task 6.
2. **Texto con glifos que la fuente no tiene** (emoji o "→" dentro de una etiqueta, "✓" fuera de `check`): el validador lo rechaza con un mensaje que Haiku pueda corregir; nunca sale "tofu". → Task 5.
3. **Rutas con espacios, acentos y "¿"** (`01 - ¿Juniors o Seniors`): encolado, agente, ffmpeg y entrega funcionan. → Tasks 8 y 9.
4. **Agente interrumpido** (app cerrada, `claude` matado): un `.editado.mp4.tmp` a medias nunca se publica y el bloqueo caduca. → Tasks 8 y 10.
5. **Short regenerado con un trabajo aún pendiente**: el trabajo viejo va a `errores/` ("origen cambiado") y el editado viejo desaparece. → Tasks 8 y 9.

---

## File Structure

```
lanzador/edicion/procesar_pendientes.sh   agente (Task 8)
lanzador/edicion/SKILL.md                 instrucciones de Haiku y del chat (Task 8)
lanzador/edicion/estilos/{divertido,formal,academico}.json   (Task 1)
videopipeline/edicion/__init__.py         DIR_EDICION, AGENTE, claude_disponible, encolar, lanzar_agente_edicion (Tasks 8, 9)
videopipeline/edicion/estilos.py          Paleta, Estilo, cargar (Task 1)
videopipeline/edicion/zonas.py            calcular (Task 1)
videopipeline/edicion/rotulos.py          etiquetas, títulos, contadores, transiciones (Task 2)
videopipeline/edicion/emojis.py           emojis y viñeta (Task 3)
videopipeline/edicion/sonidos.py          SFX sintetizados (Task 3)
videopipeline/edicion/musica.py           música sintetizada (Task 3)
videopipeline/edicion/componer.py         zoom por franja, overlays, mezcla (Task 4)
videopipeline/edicion/plan.py             Momento, Plan, leer, validar (Task 5)
videopipeline/edicion/validar_plan.py     CLI (Task 5)
videopipeline/edicion/renderizar.py       derivar, renderizar, CLI (Task 6)
videopipeline/edicion/preparar.py         contexto.md, CLI (Task 7)
videopipeline/edicion/verificar.py        hoja de fotogramas, CLI (Task 7)
videopipeline/edicion/entregar.py         comprobación + entrega atómica, CLI (Task 7)
tests/test_edicion_*.py                   uno por módulo
```

Formato del trabajo (carpeta en `pendientes/`): `video.mp4`, `subs.srt`, `caption.md` (opcional), `palabras.json` (`[{"texto","inicio","fin"}]`), `trabajo.json` (spec 5.2). Generados: `contexto.md`, `plan.json`, `plan.validado.json`, `tmp/`, `salida.mp4`, `verificacion.png`, `claude.log`, `resultado.json` | `motivo.txt`.

---

### Task 1: Worktree, estilos y zonas

**Files:**
- Create: `lanzador/edicion/estilos/{divertido,formal,academico}.json`, `videopipeline/edicion/__init__.py` (vacío por ahora), `videopipeline/edicion/estilos.py`, `videopipeline/edicion/zonas.py`
- Copy: spec y este plan a `docs/superpowers/specs/` y `docs/superpowers/plans/`
- Test: `tests/test_edicion_estilos.py`, `tests/test_edicion_zonas.py`

**Interfaces:**
- Produces: `estilos.IDS = ("divertido", "formal", "academico")`; `@dataclass(frozen=True) Paleta(acento: tuple[int,int,int], fondo: tuple[int,int,int,int], texto: tuple[int,int,int], fuente: tuple[str,int])`; `@dataclass(frozen=True) Estilo(id: str, densidad_max: float, tipos: frozenset[str], transiciones: str, zoom_max: float, zoom_lento: float, sfx: dict[str, float], musica: dict | None, paleta: Paleta)` — `densidad_max` en momentos por segundo; `transiciones` = letras permitidas (`"ABCDEFG"`, `"BG"`, `"A"`); `musica = {"bpm": int, "db": float, "progresion": "lofi"|"tranquila", "fade_out": 1.5}`; `estilos.cargar(id: str) -> Estilo` (ValueError si no existe).
- Produces: `zonas.calcular(config: PipelineConfig, encuadre: str, resolucion_fuente: tuple[int,int], con_titulo: bool) -> dict` con claves `contenido: [x,y,w,h]`, `subtitulos: [y0,y1] | None`, `titulo: {"y":[y0,y1],"hasta":5.0} | None`, `franja_zoom: [y0,y1] | None`, `graficos_hasta: int`.

- [ ] **Step 1: Worktree.** `git -C ~/Documents/personalProjects/limpiadorVideo worktree add ../tsots-edicion -b feature/edicion-shorts develop`; copiar spec y plan desde `~/Documents/personalProjects/VideoEditor/docs/superpowers/`.
- [ ] **Step 2: Tests de estilos.**
  - `test_cargar_los_tres_estilos`: `cargar(i).id == i` para cada id de `IDS`.
  - `test_estilo_inexistente`: `pytest.raises(ValueError)` con `"neon"`.
  - `test_divertido_permite_emojis_y_formal_no`: `"emoji" in cargar("divertido").tipos`, `"emoji" not in cargar("formal").tipos`, `"golpe" not in cargar("academico").tipos`.
  - `test_densidades_de_la_tabla`: divertido `0.4`, formal `≈1/6`, academico `0.2`.
  - `test_academico_sin_musica_ni_zoom`: `musica is None`, `zoom_max == 0`, `zoom_lento == 0`.
- [ ] **Step 3: Tests de zonas** (config `PipelineConfig(video=..., diseno="karaoke_verde", posicion_subs=75, tamano_subs=150)`, fuente `(1920,1080)`):
  - `test_difuminado`: `contenido == [0, 656, 1080, 608]`, `subtitulos == [1269, 1440]` (karaoke_verde `tamano_rel=0.07` al 150 % → fuente 201), `franja_zoom == [656, 1264]`.
  - `test_cara`: `contenido[1] == 555`, `contenido[3] == 810`; `franja_zoom[1] == min(1365, subtitulos[0])`.
  - `test_central_sin_franja`: `contenido == [0,0,1080,1920]`, `franja_zoom is None` (se solapa con subtítulos).
  - `test_sin_titulo`: `con_titulo=False` → `titulo is None`.
  - `test_graficos_por_encima`: `graficos_hasta == 656` en difuminado; `graficos_hasta == subtitulos[0] - 201` en central.
- [ ] **Step 4: Run → FAIL** (`ModuleNotFoundError`).
- [ ] **Step 5: Implement.** JSON con los valores de la tabla 5.6 (paleta divertido: acento `[255,90,0]`, fondo `[10,10,10,235]`, texto `[255,255,255]`, fuente `["/System/Library/Fonts/Helvetica.ttc",1]`; `sfx` = ganancias por tipo de `chatcut/tools/gen_sfx.py::DEFAULT_GAIN_DB` + `golpe:-10`, `error:-14`; formal/académico con los tipos que la tabla deja y `-24` donde lo dice). `estilos.py` lee `BASE_DIR/"lanzador"/"edicion"/"estilos"/f"{id}.json"`. `zonas.py` usa `ancho_ventana_cara`, `PRESETS[config.diseno].tamano_rel`, `titulo.DURACION/TAMANO_VERTICAL/MARGEN_SUPERIOR`:
  - difuminado/barras: imagen escalada al ancho 1080, `h = round(1080*alto/ancho)//2*2`, `y = (1920-h)//2`; cara: igual con la ventana `ancho_ventana_cara(ancho, alto) x alto`; central: frame completo.
  - `subtitulos`: `y1 = 1920 - int(1920*(100-posicion)/100)`, `y0 = y1 - round(0.85*fuente)` con `fuente = int(1920*tamano_rel*tamano/100)` (0.85 ≈ altura de mayúsculas + contorno, medido en el short 11: texto en y≈1285–1440); `None` si `config.subtitulos` es falso. Comentario en el código: `# shortcut: asume subtítulos de 1 línea; si un preset parte en 2, la franja de zoom puede pisar la de arriba — ampliar a 2 líneas si pasa`.
  - `franja_zoom = [contenido.y, min(contenido.y + contenido.h, subtitulos.y0)]`; `None` si queda < 200 px.
  - `titulo.y = [round(MARGEN_SUPERIOR*1920), round(MARGEN_SUPERIOR*1920 + 2.4*TAMANO_VERTICAL*1920)]`.
  - `graficos_hasta = contenido.y` si `contenido.y > 0`; si no (frame completo), `subtitulos.y0 - fuente` (o `1920*0.6` sin subtítulos).
- [ ] **Step 6: Run → PASS.**
- [ ] **Step 7: Commit** `feat: editing styles and screen zones for short editing` (incluye spec y plan).

### Task 2: Rótulos (port de `gen_overlays.py`)

**Files:**
- Create: `videopipeline/edicion/rotulos.py` (port de `/Users/albercv/Documents/personalProjects/chatcut/tools/gen_overlays.py`)
- Test: `tests/test_edicion_rotulos.py`

**Interfaces:**
- Consumes: `Paleta` (Task 1).
- Produces: `render_slot(frames: Iterable[Image.Image], destino: Path, fps: int) -> Path`; `frames_etiqueta(lineas: list[str], dur: float, paleta: Paleta, fps: int, grande: bool = False, check: bool = False, cx: int = 540, y0: int = 330)`; `frames_contador(num: int, texto: str, dur: float, lado: str, paleta: Paleta, fps: int)` (`lado` `"L"|"R"`, cx 280/800, cy 360); `frames_transicion(tipo: str, dur: float, paleta: Paleta, fps: int)` (`tipo` en `"ABCDEFG"`); `cabe(lineas: list[str], grande: bool, paleta: Paleta, ancho_max: int = 1000) -> bool`; `glifos_validos(texto: str, check: bool) -> bool`.

- [ ] **Step 1: Tests.**
  - `test_etiqueta_render_prores_alpha(tmp_path)`: `render_slot(frames_etiqueta(["HOLA"], 0.5, p, 30), tmp/"a.mov", 30)` → ffprobe `pix_fmt == "yuva444p10le"`, `nb_frames == 15`; un frame central tiene alpha > 0 en `(540, 360)` y alpha 0 en `(540, 1800)`.
  - `test_cabe`: `cabe(["CORTO"], False, p)`; `not cabe(["X"*60], False, p)`.
  - `test_glifos`: `glifos_validos("¿QUÉ PUEDE FALLAR? «SÍ» · 1", False)`; `not glifos_validos("HOLA 🍉", False)`; `not glifos_validos("A → B", False)`; `glifos_validos("LISTO ✓", True)`.
  - `test_transiciones_todas`: para cada letra de `"ABCDEFG"`, `len(list(frames_transicion(l, 0.5, p, 30))) == 15`.
  - `test_contador_lados`: el píxel opaco más a la izquierda del frame final de `"L"` está en x < 540 y el de `"R"` en x > 540.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** portando las plantillas tal cual (pill negra con borde de acento y radio = mitad de altura, `→`/`✓` vectoriales, cascada de tamaño de letra en contadores, 7 transiciones de 0.5 s), sustituyendo las constantes `ORANGE/PILL_BG/FPS/FONT_CANDIDATES` por `paleta` y `fps`. `glifos_validos`: letras (incl. acentuadas y Ñ), dígitos, espacio y `.,:;¿?¡!«»"'·-%&()/`; `✓` solo con `check=True`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: overlay templates for short editing`.

### Task 3: Emojis, sonidos y música

**Files:**
- Create: `videopipeline/edicion/emojis.py`, `sonidos.py`, `musica.py` (port de `/Users/albercv/Documents/personalProjects/VideoEditor/tools/extras.py` y `/Users/albercv/Documents/personalProjects/chatcut/tools/gen_sfx.py`)
- Test: `tests/test_edicion_audio_emojis.py`

**Interfaces:**
- Produces: `emojis.frames_emoji(emoji: str, dur: float, cx: int, cy: int, tam: int, fps: int)`, `emojis.frames_vineta(dur: float, fps: int)`, `emojis.disponible(emoji: str) -> bool`.
- Produces: `@dataclass(frozen=True) sonidos.EventoSfx(t: float, tipo: str, db: float, num: int | None = None, freq: float | None = None)`; `sonidos.TIPOS` = `whoosh_a..whoosh_g, pop, pluck, tick, tick2, tap, boom, impact, riser, ding, golpe, error`; `sonidos.pista(eventos: list[EventoSfx], total: float, destino: Path) -> Path` (WAV estéreo 44.1 kHz, pico ≤ -10 dBFS).
- Produces: `musica.pista(total: float, bpm: int, progresion: str, fade_out: float, destino: Path) -> Path` (`progresion` `"lofi"` | `"tranquila"`; pico -1 dBFS).

- [ ] **Step 1: Tests.**
  - `test_emoji_disponible`: `disponible("🍉")`, `not disponible("\U000E0001")`.
  - `test_frames_emoji_pop`: 30 fps, 1 s → 30 frames; el primero casi vacío (bbox < 40 px), el del 0.3 s con bbox ≥ `tam*0.9`.
  - `test_vineta_bordes`: frame en 0.1 s: alpha en esquina > alpha en centro (centro 0).
  - `test_pista_sfx`: eventos en `t=0.5` (`tick`) y `t=1.0` (`golpe`) → duración `== total`, silencio antes de 0.49 s, energía tras 1.0 s, pico ≤ -10 dBFS; `tipo` desconocido → `ValueError`.
  - `test_musica`: `pista(10, 96, "lofi", 1.5, f)` dura 10 s ±0.01, último 0.1 s casi en silencio (fade); `progresion="x"` → `ValueError`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** portando: `gen_sfx.py` (todos sus tipos, con `num` obligatorio en pop/pluck y `freq` en tap), `extras.sting` → `golpe`, `extras.buzzer` → `error`, `extras.music` → `musica.pista` (`"lofi"` = progresión actual; `"tranquila"` = misma con 80 bpm de referencia, sin caja ni hats, teclado más largo), `extras.frames_emoji/frames_vignette`. `disponible`: renderiza a 160 con `embedded_color=True` y comprueba `getbbox()` no vacío.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: emoji, sound effect and music synthesis for short editing`.

### Task 4: Componer

**Files:**
- Create: `videopipeline/edicion/componer.py` (port de `/Users/albercv/Documents/personalProjects/VideoEditor/tools/compose.py`)
- Test: `tests/test_edicion_componer.py` (usa la fixture de sesión `video_con_voz` de `tests/conftest.py`, o genera un vertical 1080x1920 de 4 s con `testsrc2` + seno)

**Interfaces:**
- Produces: `@dataclass(frozen=True) Overlay(archivo: Path, t: float, dur: float)`; `@dataclass(frozen=True) Zoom(t0: float, t1: float, z0: float, z1: float)`; `componer(fuente: Path, destino: Path, overlays: list[Overlay], franja: tuple[int,int] | None, zooms: list[Zoom], sfx: list[Path], musica: Path | None, musica_db: float, borrador: bool = False) -> None` (zoom centrado en la franja; `borrador` = 720p CRF 26 veryfast; si no, CRF 18 `slow`, fps de la fuente).

- [ ] **Step 1: Tests.**
  - `test_salida_mismas_dimensiones_y_duracion`: sin overlays ni zoom → 1080x1920, mismo fps, duración ±0.1 s, hay audio.
  - `test_zoom_no_toca_fuera_de_franja`: franja `(600, 1200)`, zoom 1.3 en todo el clip; un fotograma de salida y de entrada en t=2 s: filas y 300 y 1500 casi idénticas (diferencia media < 3), fila 900 distinta.
  - `test_overlay_en_su_ventana`: un overlay rojo opaco 1080x1920 en `t=1, dur=1` → fotograma en 1.5 s rojo; en 0.5 s y 2.5 s no.
  - `test_loudness_final`: con música → `ebur128` I entre -15.5 y -13.5 LUFS.
  - `test_sin_musica_sin_sfx`: `sfx=[]`, `musica=None` → no falla.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** el grafo de `compose.py`: `split`→`crop` de la franja→`zoompan` (z por tramos con `it`, `d=1`, `fps` de la fuente)→`overlay` de vuelta; overlays con `setpts=PTS-STARTPTS+t/TB` + `enable=between(t,…)`+`eof_action=pass`; voz `loudnorm=I=-16:TP=-1.5` → `asplit` como sidechain; música `volume={musica_db}dB` + `sidechaincompress=threshold=0.02:ratio=8:attack=15:release=400`; `amix normalize=0` → `loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000`. Sin zooms o `franja=None` → sin `zoompan`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: single-pass compositor for edited shorts`.

### Task 5: Plan y validador

**Files:**
- Create: `videopipeline/edicion/plan.py`, `videopipeline/edicion/validar_plan.py`
- Test: `tests/test_edicion_plan.py`

**Interfaces:**
- Consumes: `Estilo` (Task 1), `rotulos.cabe/glifos_validos` (Task 2), `emojis.disponible` (Task 3), `subtitles.Palabra`.
- Produces: `TIPOS = ("etiqueta","titulo","contador","emoji","golpe","error","transicion","zoom")`; `@dataclass Momento(tipo: str, t: float = 0.0, palabra: str | None = None, texto: list[str] | None = None, emoji: str | None = None, lista: int | None = None, num: int | None = None, t0: float | None = None, t1: float | None = None)`; `@dataclass Plan(momentos: list[Momento], final: dict | None)` (`final = {"texto": list[str], "check": bool}`); `leer(ruta: Path) -> Plan` (ValueError con mensaje legible si el JSON no cuadra); `guardar(plan: Plan, ruta: Path)`; `validar(plan: Plan, palabras: list[Palabra], zonas: dict, estilo: Estilo, duracion: float) -> tuple[Plan, list[str]]` (devuelve el plan con `t` ajustado a la palabra y la lista de errores en español, cada uno con el índice del momento).
- Produces CLI: `python -m videopipeline.edicion.validar_plan <trabajo>` → lee `plan.json`, `palabras.json`, `trabajo.json`, `video.mp4`; si no hay errores escribe `plan.validado.json` e imprime `OK` (exit 0); si los hay, uno por línea (exit 1).

- [ ] **Step 1: Tests** (palabras de ejemplo con "melón" en 31.76, duración 60, zonas de difuminado, estilo divertido salvo que se diga):
  - `test_ajusta_t_a_la_palabra`: momento `t=31.5, palabra="melón"` → `t == 31.76`, sin errores.
  - `test_palabra_inexistente`: `palabra="sandía"` → un error que contiene `"sandía"`.
  - `test_palabra_lejos`: `t=20, palabra="melón"` → error (más de 0.4 s).
  - `test_fuera_de_duracion`: `t=61` → error.
  - `test_emoji_no_permitido_en_formal` y `test_emoji_sin_glifo` (`"\U000E0001"`) → error.
  - `test_texto_con_glifo_raro`: etiqueta `["HOLA 🍉"]` → error que menciona el carácter.
  - `test_texto_no_cabe`: etiqueta con 60 letras → error.
  - `test_solape_misma_zona`: dos etiquetas solapadas en el tiempo → error; etiqueta + emoji solapados → sin error.
  - `test_nada_antes_del_titulo`: etiqueta en `t=3` con `zonas["titulo"]["hasta"] == 5.0` → error; con `titulo=None` → OK.
  - `test_presupuesto`: 30 momentos en 60 s en formal → error de densidad.
  - `test_contadores_consecutivos`: lista 1 con nums 1,3 → error.
  - `test_zoom`: `zoom` con `z>estilo.zoom_max`, solapado con otro, o con `zonas["franja_zoom"] is None` → error.
  - `test_plan_vacio_valido`: `Plan([], None)` → sin errores.
  - `test_cli(tmp_path)`: trabajo mínimo con `plan.json` válido → exit 0 y existe `plan.validado.json`; inválido → exit 1 y no existe.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Duraciones por defecto para comprobar solapes: etiqueta 2.2, titulo 3.0, contador 2.4, emoji 1.4, golpe 1.4, error 0.8, transicion 0.5 (las mismas que usará Task 6: defínelas aquí como `DURACION` y que Task 6 las importe). Búsqueda de palabra: normalizar a minúsculas sin acentos ni puntuación y elegir la ocurrencia más cercana a `t`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: edit plan schema and validator`.

### Task 6: Derivar y renderizar

**Files:**
- Create: `videopipeline/edicion/renderizar.py`
- Test: `tests/test_edicion_renderizar.py`

**Interfaces:**
- Consumes: Tasks 1–5 (`plan.DURACION`, `rotulos.*`, `emojis.*`, `sonidos.EventoSfx/pista`, `musica.pista`, `componer.Overlay/Zoom/componer`).
- Produces: `@dataclass Pieza(clase: str, t: float, dur: float, params: dict)`; `@dataclass Specs(piezas: list[Pieza], sfx: list[EventoSfx], zooms: list[Zoom], musica: dict | None)`; `derivar(plan: Plan, zonas: dict, estilo: Estilo, duracion: float) -> Specs` (pura); `renderizar(trabajo: Path, borrador: bool = False) -> Path` (lee `plan.validado.json`, escribe `salida.mp4`, temporales en `trabajo/tmp/`); CLI `python -m videopipeline.edicion.renderizar <trabajo> [--borrador]`.

- [ ] **Step 1: Tests de `derivar`** (puros, sin ffmpeg):
  - `test_sonido_emparejado`: etiqueta→`tick`/`tick2` alternos en `t+0.08`; contador lista 1 → `pop` con `num`; lista 2 → `pluck`; transición → `whoosh_*` en `t-0.12`; titulo → `riser` en `t-1.07` + `impact` en `t`; golpe → `golpe` + pieza `vineta`; error → `error` + pieza emoji `❌`; emoji → `tap` con `freq` distinta a la del emoji anterior; final → `ding`; siempre `boom` en 0.05. Ganancias = `estilo.sfx[tipo]`; tipo ausente en `estilo.sfx` → sin evento.
  - `test_transiciones_rotan`: 5 transiciones → ninguna letra igual a la anterior y todas en `estilo.transiciones`.
  - `test_contadores_alternan_lado`: lista de 4 → `L,R,L,R`; misma `dur` en toda la lista.
  - `test_emoji_lateral_con_etiqueta`: emoji solapado con etiqueta → `cx` 950; solo → 540.
  - `test_zoom_y_entrada_lenta`: momento zoom con divertido → `Zoom(t0,t1,z,z)`; `zoom_lento>0` añade `Zoom(0,2.5,1,zoom_lento)` y cierre `Zoom(duracion-3, duracion, 1, zoom_lento)`; `franja_zoom is None` → `zooms == []`.
  - `test_final_ocupa_hasta_el_fin`: `final` → pieza `etiqueta` grande con `check`, `t = max(duracion-3.7, …)`, `dur` hasta `duracion`.
  - `test_plan_vacio`: `Plan([], None)` → `piezas == []`, `sfx == [boom]`, música según estilo.
- [ ] **Step 2: Test de humo** `test_renderizar_clip(tmp_path)`: trabajo sintético de 6 s (vertical con voz, `palabras.json`, `trabajo.json` de difuminado) con un plan de etiqueta + emoji + transición + zoom → `renderizar(trabajo, borrador=True)` crea `salida.mp4` 720x1280 de 6 s ±0.1 con audio. Y `test_renderizar_plan_vacio` → también crea `salida.mp4` (Review Focus 1).
- [ ] **Step 3: Run → FAIL.**
- [ ] **Step 4: Implement** `derivar` (reglas del spec 5.5) y `renderizar` (renderiza cada pieza con `rotulos`/`emojis` a `tmp/slot_NN.mov` con el fps de la fuente redondeado a 30 si es >30 —shortcut: 30 fps de overlay sobre 60 de base, como en las pruebas—, genera `tmp/sfx.wav` y `tmp/musica.wav`, llama a `componer` con `franja = zonas["franja_zoom"]` y `musica_db = estilo.musica["db"]`).
- [ ] **Step 5: Run → PASS.**
- [ ] **Step 6: Commit** `feat: derive overlays and sounds from the edit plan and render`.

### Task 7: Preparar, verificar y entregar

**Files:**
- Create: `videopipeline/edicion/preparar.py`, `verificar.py`, `entregar.py`
- Test: `tests/test_edicion_trabajo.py`

**Interfaces:**
- Produces: `preparar(trabajo: Path) -> Path` (si falta `palabras.json` —modo interactivo— lo genera con la misma transcripción mlx-whisper que usa `shorts.crear` vía `pasada._palabras()`, sobre `video.mp4`) → `contexto.md` con, en este orden: `## Estilo` (id, tipos permitidos, densidad máx. como "como mucho N momentos en este vídeo", emojis sí/no), `## Zonas` (si hay zoom posible, desde cuándo se puede poner gráficos), `## Caption` (contenido de `caption.md` si existe), `## Frases` (líneas `[inicio-fin] texto`, cortando en silencios ≥ 0.5 s), `## Palabras` (`inicio palabra`, una por línea). CLI imprime la ruta.
- Produces: `hoja(trabajo: Path) -> Path` → `verificacion.png`: un fotograma de `salida.mp4` por momento de `plan.validado.json` (en `t + 0.4`, o centro del zoom) más 0.5 s y `duración-0.3`, escalados a 270 px de ancho, rejilla de 6 columnas, cada uno con su tiempo rotulado. CLI imprime la ruta.
- Produces: `entregar(trabajo: Path) -> str | None` → `None` si entrega; si no, el motivo en español. Comprueba: existe `salida.mp4`; ffprobe 1080x1920 con audio; `|dur(salida) - dur(video.mp4)| ≤ 0.25`; `trabajo.json["origen"]` existe y su tamaño y mtime coinciden con `origen_tam`/`origen_mtime`. Si todo cuadra: copia a `<destino>.tmp` (mismo directorio que `destino`), `os.replace` a `destino`, borra `video.mp4` y `salida.mp4` del trabajo y escribe `resultado.json` `{destino, estilo, duracion, fecha}`. CLI: exit 0 / exit 1 imprimiendo el motivo.

- [ ] **Step 1: Tests.**
  - `test_contexto_tiene_palabras_y_reglas`: con `palabras.json` de 3 palabras y estilo formal → `contexto.md` contiene `"31.76 melón"`, `"emojis: no"` y la sección `## Caption` solo si hay `caption.md`.
  - `test_hoja_de_verificacion`: plan de 2 momentos + vídeo de 6 s → PNG de 270*… con 4 celdas (2 + inicio + final).
  - `test_entrega_ok(tmp_path)`: episodio en `tmp/"Episodio ¿20?"` → crea `<stem>.editado.mp4`, no queda `.tmp`, el original intacto (mismo hash), `resultado.json` existe.
  - `test_duracion_no_cuadra` → motivo con "duración"; no existe `destino`.
  - `test_origen_cambiado` (tocar mtime del original) → motivo con "origen cambiado"; no existe `destino`.
  - `test_sin_salida` → motivo; `test_sin_audio` → motivo.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** con ffprobe del sistema (ya usado en el repo) y `os.replace`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: job context, verification sheet and atomic delivery`.

### Task 8: Agente y SKILL.md

**Files:**
- Create: `lanzador/edicion/procesar_pendientes.sh` (desde `lanzador/blog/procesar_pendientes.sh`), `lanzador/edicion/SKILL.md`
- Modify: `videopipeline/edicion/__init__.py`; `tests/conftest.py` (fixture autouse `sin_agente_de_edicion`, como `sin_agente_del_blog` l.235)
- Test: `tests/test_edicion_agente.py` (helpers como `tests/test_blog_agente.py::_ejecutar`)

**Interfaces:**
- Produces: `DIR_EDICION = Path.home() / "TSOTS" / "edicion"`; `AGENTE = BASE_DIR / "lanzador" / "edicion" / "procesar_pendientes.sh"`; `claude_disponible() -> bool` (`shutil.which("claude")`, `~/.local/bin/claude`, `/opt/homebrew/bin/claude`); `lanzar_agente_edicion(dir_edicion: Path = DIR_EDICION) -> bool` (igual que `difusion.lanzar_agente`: solo si hay subcarpetas no ocultas en `pendientes/`, `Popen` suelto, log en `agente.log`, nunca lanza).
- Script: `procesar_pendientes.sh <dir_edicion>`; `LIMITE="${TSOTS_EDICION_LIMITE:-1200}"`; `PYTHON="$RAIZ/.venv-clearvoice/bin/python"` con `TSOTS_EDICION_PYTHON` para tests; bloqueo, bucle, `mover` y `perl alarm` idénticos al del blog. Por carpeta: `claude -p "$INSTRUCCIONES\n\nTrabajo: $carpeta" --model claude-haiku-5-5 --add-dir "$carpeta" --allowedTools "Read,Write($carpeta/plan.json),Bash($PYTHON -m videopipeline.edicion.preparar:*),Bash($PYTHON -m videopipeline.edicion.validar_plan:*),Bash($PYTHON -m videopipeline.edicion.renderizar:*),Bash($PYTHON -m videopipeline.edicion.verificar:*)" --disallowedTools "Edit,NotebookEdit,WebFetch,WebSearch" --setting-sources project,local > claude.log 2>&1`; luego `"$PYTHON" -m videopipeline.edicion.entregar "$carpeta"`: exit 0 → `mover hechos`; si no → `motivo.txt` = salida de `entregar` + "Tiempo agotado…" si rc 142 + `tail -n 40 claude.log` → `mover errores`. Si no hay `claude` → errores "sin claude" (como el blog).

- [ ] **Step 1: Tests del script** (claude falso por PATH, `TSOTS_EDICION_PYTHON` apuntando al python del venv):
  - `test_exito`: el claude falso copia `video.mp4` a `salida.mp4` → carpeta en `hechos/`, existe `<stem>.editado.mp4` junto al origen; los args recibidos contienen `--model`, `claude-haiku-5-5` y `Trabajo: `.
  - `test_salida_mala_va_a_errores`: claude falso no escribe nada → `errores/<n>/motivo.txt` existe, no hay editado.
  - `test_origen_cambiado`: el claude falso toca el mtime del origen → errores con "origen cambiado".
  - `test_tiempo_agotado`: `exec sleep 30`, `TSOTS_EDICION_LIMITE=1` → errores con "Tiempo agotado" en < 15 s.
  - `test_sin_claude` → errores "sin claude".
  - `test_bloqueo`: con `.bloqueo` reciente → no procesa nada.
  - `test_nombre_con_interrogacion`: trabajo `"Episodio 20 - 01 - ¿Juniors o Seniors"` → `hechos/`.
  - `test_no_define_credenciales`: `SCRIPT.read_text()` no contiene `ANTHROPIC_API_KEY` ni `OAUTH_TOKEN`.
  - `test_lanzar_agente_sin_pendientes` → `False`; con una carpeta → `True` (Popen monkeypatcheado); `test_claude_disponible` con PATH vacío y HOME temporal → `False`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** el script y `__init__.py`.
- [ ] **Step 4: Write `SKILL.md`** (frontmatter `name: editar-short`, `description` en español). Secciones: *Qué haces* (decidir momentos, nunca posiciones ni sonidos); *Modo trabajo* (los 5 comandos exactos con `@PYTHON@` sustituido por el script como hace el blog con `instrucciones.md`: `preparar` → leer `contexto.md` → escribir `plan.json` → `validar_plan` hasta `OK` (máx. 3) → `renderizar` → `verificar` → `Read verificacion.png` → si algo tapa subtítulos, texto cortado o falta un elemento, corregir y volver a validar/renderizar una vez; terminar sin más); *Formato de `plan.json`* (el ejemplo del spec 5.5 y la tabla de tipos con cuándo usar cada uno: etiqueta = frase clave dicha; contador = enumeraciones habladas, ancladas a la palabra clave de cada ítem; titulo = nombre propio o tesis del vídeo, 1 por vídeo; emoji = chiste o imagen concreta; golpe = el chiste principal, máx. 2; error = negación rotunda ("no es…"); transición = cambio de tema; zoom = frases enfáticas, 2–5 s); *Reglas* (`palabra` = palabra exacta de `## Palabras`; mayúsculas en textos; ≤ 26 caracteres por línea; no repetir el mismo emoji seguido; respetar la densidad); *Modo interactivo* (vídeo + srt sueltos: crear carpeta de trabajo con `trabajo.json` preguntando el encuadre si no se sabe, y `borrador` para la primera vista).
- [ ] **Step 5: Run → PASS** (también `tests/test_blog_agente.py`, que no debe cambiar).
- [ ] **Step 6: Commit** `feat: background agent that edits queued shorts with Claude Haiku`.

### Task 9: Opciones y encolado en `shorts.crear`

**Files:**
- Modify: `videopipeline/shorts.py:440-453` (`OpcionesShorts`), `:647-695` (`crear`), `videopipeline/edicion/__init__.py`
- Test: `tests/test_shorts.py` (fixture `ficha_con_base`, helper `_crear`), `tests/test_edicion_encolar.py`

**Interfaces:**
- Consumes: `zonas.calcular` (Task 1), `estilos.IDS`, `difusion._carpeta_libre`, `difusion._enlazar_o_copiar`.
- Produces: `OpcionesShorts(subtitulos: bool = True, encuadre: str = "cara", editar: bool = False, estilo: str = "divertido")`; `de_datos` lee `"editar"`/`"estilo"` y lanza `ValueError` si el estilo no está en `IDS`. `encolar(carpeta: Path, episodio: str, stems: list[str], tramos: dict[str, list[Palabra]], estilo: str, zonas: dict, idioma: str, dir_edicion: Path = DIR_EDICION) -> list[Path]` (un trabajo por stem con `.mp4` en `carpeta`; escribe en `.<nombre>.tmp` y renombra; nunca lanza: registra el aviso y devuelve lo que pudo).

- [ ] **Step 1: Tests.**
  - `test_opciones_editar_y_estilo`: `de_datos({"editar": True, "estilo": "formal"})`; `{"estilo": "neon"}` → `ValueError`; por defecto `editar is False`.
  - `test_crear_sin_editar_no_encola(ficha_con_base, tmp_path)`: `DIR_EDICION` monkeypatcheado → `pendientes/` vacío o inexistente.
  - `test_crear_con_editar_encola_un_trabajo_por_short`: N trabajos; cada uno con `video.mp4`, `palabras.json` (las de `tramo_palabras` del short, tiempos relativos), `trabajo.json` con `origen`, `destino` (`.editado.mp4`), `origen_tam`, `origen_mtime`, `estilo`, `encuadre` y `zonas`.
  - `test_regenerar_borra_editado_viejo`: crear, escribir `<stem>.editado.mp4` y `<stem>.editado.mp4.tmp` a mano, crear otra vez → ya no existen.
  - `test_encolar_nombre_ocupado`: dos `encolar` con el mismo episodio/stem → segunda carpeta con sufijo `-2`.
  - `test_encolar_que_falla_no_rompe_crear`: `encolar` monkeypatcheado para lanzar → `crear` termina y los shorts existen.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** En `crear`: guardar `tramos[stem] = tramo` en el bucle; en el `for anterior in anteriores` borrar también `<stem>.editado.mp4` y `.editado.mp4.tmp` de los `.mp4`; tras mover los nuevos y reescribir `shorts.json`, si `opciones.editar`: `zonas.calcular(config, opciones.encuadre, resolucion_video(pasada.base), con_titulo=bool(c.titulo_video))` y `encolar(...)` dentro de `try/except Exception` con `log.warning`.
- [ ] **Step 4: Run → PASS** (todo `tests/test_shorts.py`).
- [ ] **Step 5: Commit** `feat: queue created shorts for Claude editing`.

### Task 10: Publicar el editado

**Files:**
- Modify: `videopipeline/shorts.py:470-500` (`Corto`, `listar`), `videopipeline/redes/registro.py:36` (`ruta`), `app/widgets/dialogo_publicar_shorts.py:92`
- Test: `tests/test_shorts.py` (o `tests/test_edicion_publicar.py`), `tests/test_redes_registro.py`, `tests/test_app_publicar_shorts.py`

**Interfaces:**
- Produces: `Corto(mp4: Path, titulo: str, duracion: float, caption: Caption | None, editado: bool = False)`; `listar` usa `<stem>.editado.mp4` si es fichero (nunca el `.tmp`), con `caption` del `.md` del original; `registro.ruta(video)` quita el sufijo `.editado` del stem.

- [ ] **Step 1: Tests.**
  - `test_listar_prefiere_editado`: con `X.editado.mp4` → `mp4.name == "X.editado.mp4"`, `editado is True`, `caption` el de `X.md`.
  - `test_listar_ignora_tmp`: solo `X.editado.mp4.tmp` → `mp4.name == "X.mp4"`, `editado is False`.
  - `test_ruta_del_editado_es_la_del_original`: `ruta(Path("a/X.editado.mp4")) == Path("a/X.publicado.json")`.
  - `test_dialogo_marca_editado(qtbot, carpeta, ajustes)`: con un editado en la fixture `carpeta`, el texto de su casilla termina en `"(editado)"`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run → PASS** (incluye `tests/test_redes_*.py` y `tests/test_app_publicar_shorts.py` completos).
- [ ] **Step 5: Commit** `feat: publish the edited short when it exists`.

### Task 11: Panel y app

**Files:**
- Modify: `app/widgets/panel_opciones.py:431-470` (sección Shorts), `:724-730` (`valores_shorts`), `:799-806` (`cargar`); `app/main.py:280`, `:785-792` (`_datos_shorts`), `:956` (`_al_terminar_cola`); `locale/en/LC_MESSAGES/tsots.po`
- Test: el test de panel existente (buscar `valores_shorts` en `tests/`), `tests/test_app_main.py`

**Interfaces:**
- Consumes: `edicion.claude_disponible`, `edicion.lanzar_agente_edicion`, `estilos.IDS`.
- Produces: `PanelOpciones.check_editar_claude: QCheckBox` (`_("Editar con Claude")`), `combo_estilo_shorts: QComboBox` con `ETIQUETA_ESTILO = {N_("Divertido"): "divertido", N_("Formal"): "formal", N_("Académico"): "academico"}`; `valores_shorts()` añade `"shorts_editar": bool`, `"shorts_estilo": str`; `_datos_shorts` añade `"editar"` y `"estilo"`.

- [ ] **Step 1: Tests.**
  - `test_editar_y_estilo_se_guardan_y_restauran`: marcar, elegir "formal", `valores_shorts()` los devuelve; `cargar({"shorts_editar": "true", "shorts_estilo": "academico"})` los restaura (a diferencia de `shorts_al_procesar`).
  - `test_combo_desactivado_sin_casilla`: casilla desmarcada → `combo_estilo_shorts.isEnabled() is False`.
  - `test_sin_claude_casilla_desactivada`: `claude_disponible` monkeypatcheado a `False` → casilla desactivada y tooltip contiene `"claude"`.
  - `test_datos_shorts_llevan_edicion` (main): `_datos_shorts(id)` contiene `editar` y `estilo` del panel.
  - `test_al_terminar_cola_lanza_agente_de_edicion`: monkeypatch de `lanzar_agente_edicion` → llamado una vez.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Filas nuevas tras el encuadre: `form_shorts.addRow(self.check_editar_claude)` y `addRow(self._etiqueta(_("Estilo:"), "combo_estilo_shorts"), self.combo_estilo_shorts)` con su entrada de ayuda en el dict de l.178. Tooltip sin claude: `_("Necesita Claude Code instalado y con la sesión iniciada (comando claude).")`. `QTimer.singleShot(0, lanzar_agente_edicion)` junto al del blog; `lanzar_agente_edicion()` al final de `_al_terminar_cola`. Traducciones con `lanzador/traducir.sh`.
- [ ] **Step 4: Run → PASS** (suite completa).
- [ ] **Step 5: Commit** `feat: Claude editing option in the shorts panel`.

### Task 12: README, TODO y aceptación

**Files:**
- Modify: `README.md` (sección nueva tras `## Blog and LinkedIn`, l.301; requisito en `## Requirements`, l.23), `README.es.md` (tras `## Blog y LinkedIn`, l.300; `## Requisitos`, l.23), `docs/TODO.md` (seguir al que habla en el zoom; estilo por short)

- [ ] **Step 1: Docs.** Sección "Editar shorts con Claude" / "Edit shorts with Claude": qué hace; casilla y estilo; requiere `claude` instalado **con sesión iniciada con la cuenta de quien lo use** (consume de su plan; TSOTS no guarda credenciales de Claude); carpetas `~/TSOTS/edicion/{pendientes,hechos,errores}` y `agente.log`; cómo reintentar (mover de `errores/` a `pendientes/`); uso desde el chat: `ln -s <repo>/lanzador/edicion ~/.claude/skills/editar-short`. En "If something goes wrong": entrada para un editado que no aparece.
- [ ] **Step 2: Suite completa → PASS.**
- [ ] **Step 3: Aceptación manual** (usuario + implementador): con la app del worktree, crear shorts del Episodio 20 con "Editar con Claude" + Divertido; esperar a `hechos/`; abrir 2 editados; "Publicar shorts…" muestra "(editado)". Repetir un short en Formal y Académico. Anotar tiempos y fallos en la descripción del PR.
- [ ] **Step 4: Commit** `docs: Claude short editing`; push de la rama y PR a `develop` con descripción (qué, por qué, cómo se verificó, riesgos: consumo de plan, calidad de Haiku, zoom centrado).
