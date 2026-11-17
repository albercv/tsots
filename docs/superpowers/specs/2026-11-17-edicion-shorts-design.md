# Edición automática de shorts con Claude (TSOTS + skill `editar-short`)

Fecha: 2026-11-17 · Estado: borrador para aprobación

## 1. Intención

TSOTS (The Silence of the Shorts, repo `~/Documents/personalProjects/limpiadorVideo`)
ya genera los shorts de un episodio: vertical 1080x1920, silencios recortados,
subtítulos y título quemados, y un `.md` con caption y hashtags. Lo que falta es
la capa de **edición para engagement**: etiquetas con palabras clave, contadores
en las enumeraciones, emojis como imágenes, transiciones, zooms, efectos de
sonido sincronizados a palabra y música de fondo que baja bajo la voz.

Esa capa ya se ha probado a mano en esta sesión con dos shorts reales del
Episodio 20 (`10 - Software Silence of the Shorts`, `11 - El futuro del código`),
y al usuario le gusta el resultado (`VideoEditor/edit/10/preview.mp4`,
`VideoEditor/edit/11/preview.mp4`). Ahora se quiere que ocurra sola: TSOTS crea
los shorts, Claude los edita en segundo plano en el estilo elegido, y TSOTS
publica la versión editada.

Objetivo final del usuario: decir "edita en estilo divertido / formal /
académico" y que salga hecho, sin pasar por el chat.

## 2. Objetivos, no objetivos, anti-objetivos

**Objetivos**
- En el panel de TSOTS (sección Shorts): casilla **"Editar con Claude"**
  (activable/desactivable) y desplegable **Estilo**: Divertido / Formal /
  Académico. Un ajuste por lote: se aplica a todos los shorts que crea esa
  ejecución, igual que hoy "Subtítulos" y "Encuadre".
- Si está activada, cada short creado se edita en segundo plano con
  `claude -p --model claude-haiku-5-5` y una skill (`editar-short`).
- El resultado queda junto al original como `NN - título.editado.mp4`, y
  "Publicar shorts…" sube esa versión si existe.
- La skill también sirve en interactivo ("edita este vídeo en estilo X") desde
  Claude Code.
- Disponible en cualquier instalación de TSOTS, con la cuenta de Claude de
  quien la use.

**No objetivos (v1)**
- Estilo distinto por short, o que Claude elija el estilo.
- Publicar automáticamente.
- Música de librería, imágenes generadas por IA o logos descargados.
- Pantalla en TSOTS para ver o reintentar los errores de edición.

**Anti-objetivos** (fallaría aunque "funcione")
- Que la edición bloquee o retrase la creación de shorts.
- Que se borre o sobrescriba el short limpio original.
- Que se publique un editado cuyo original ha cambiado (shorts regenerados).
- Que un fallo de edición deje el short sin poder publicarse.
- Que se tape el subtítulo o el título quemados.

## 3. Restricciones

- TSOTS: reglas de `limpiadorVideo/CLAUDE.md`. Rama desde `develop`, PR a
  `develop`, nunca push a `develop`/`main`; commits en inglés **sin
  atribución de IA**; código, comentarios y GUI en español; textos nuevos de
  GUI traducidos con `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po`;
  tests con `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -q`
  antes de cada commit; docs y TODO viajan en la rama de la feature.
- macOS: launchd no puede ejecutar scripts desde `~/Documents` (privacidad);
  por eso el agente lo lanza la app, como el del blog
  (`videopipeline/difusion.py:163`).
- Modelo: `claude-haiku-5-5` (decisión del usuario). Haiku debe tener un
  trabajo acotado: decidir *qué* y *cuándo*; el *cómo* lo hace código
  determinista.
- Coste: un episodio trae ~14 shorts; cada uno es una ejecución de
  `claude -p`. Se procesan de uno en uno.
- Todo local y gratis salvo el uso de Claude: ffmpeg, PIL, SFX y música
  sintetizados, emojis de Apple Color Emoji.
- **Credenciales de Claude:** TSOTS nunca lee, guarda, copia ni pasa
  credenciales de Claude. El agente ejecuta `claude -p` y este usa la
  sesión que el usuario de ese Mac tenga iniciada (en macOS, en el
  Llavero, entrada `Claude Code-credentials`). Cada persona que use TSOTS
  usa su propia cuenta y su propio plan. El script no define
  `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` ni similares, y los logs
  (`claude.log`, `motivo.txt`, `agente.log`) solo guardan la salida de
  `claude`, nunca su entorno. Comprobado el 2026-11-17: ni el repo
  `albercv/tsots` (todas las ramas e historial) ni este diseño contienen
  tokens; las claves de TSOTS (Upload-Post, etc.) ya van al Llavero vía
  `app/credenciales.py`, y `tests/secretos_falsos.py` son valores
  inventados.

## 4. Enfoques considerados

- **A. Cola de carpetas + `claude -p` (ELEGIDO por el usuario).** Copia el
  patrón del agente del blog: TSOTS deja trabajos en
  `~/TSOTS/edicion/pendientes/`, lanza un script suelto que ejecuta
  `claude -p` con Haiku y la skill; el script valida y mueve a `hechos/` o
  `errores/`. A favor: patrón ya probado en la app, usa el plan de Claude sin
  API key, Haiku puede mirar fotogramas para revisar. En contra: depende de
  que el CLI `claude` tenga sesión; hay que mantener la lista de herramientas
  permitidas.
- **B. API directa + paso de TSOTS.** TSOTS pide a Haiku por API un JSON de
  efectos y renderiza como un paso más del pipeline. A favor: determinista,
  testeable con pytest, menos tokens. En contra: API key de pago aparte, sin
  revisión visual, el código de render pasa a vivir en TSOTS. Descartado por
  el usuario.
- **C. Sesión de Claude Code vigilando la carpeta (`/loop`).** Depende de
  tener la app abierta; frágil. Descartado.

## 5. Diseño

### 5.1 Ajustes en TSOTS (panel de opciones)

- `app/widgets/panel_opciones.py`, sección Shorts (junto a
  `check_shorts_subtitulos` / encuadre / `check_shorts_al_procesar`,
  ~líneas 434-470): `QCheckBox(_("Editar con Claude"))` y un `QComboBox` de
  estilo con los ids `divertido`, `formal`, `academico` (textos visibles
  "Divertido", "Formal", "Académico"). El combo se desactiva si la casilla
  está desmarcada. Valores por defecto: casilla desmarcada, estilo divertido.
- Persistencia como el resto del panel (`app/settings.py`, grupo `panel/*`):
  `panel/shorts_editar` (bool) y `panel/shorts_estilo` (str).
- `valores_shorts()` los devuelve; `app/main.py` (~790) los pasa en el JSON
  del runner; `OpcionesShorts` (`videopipeline/shorts.py:441-452`) gana
  `editar: bool = False` y `estilo: str = "divertido"`, con validación del
  estilo como la del encuadre.

### 5.2 Encolado (al final de `shorts.crear`)

Cuando `shorts.crear` (`videopipeline/shorts.py:542-700`) ha movido los
ficheros nuevos a la carpeta del episodio y ha reescrito `shorts.json`, si
`opciones.editar` es verdadero, crea **un trabajo por short creado** en
`~/TSOTS/edicion/pendientes/`:

- Nombre de carpeta: `<nombre del episodio> - <stem del short>`; si existe en
  `pendientes/`, `hechos/` o `errores/`, sufijo libre (como
  `difusion._carpeta_libre`). Se escribe primero como `.<nombre>.tmp` y se
  renombra al final (el script ignora las ocultas).
- Contenido: `video.mp4` (enlace duro o copia del short, como
  `difusion._enlazar_o_copiar`), `subs.srt`, `caption.md` (si existe),
  `palabras.json` y `trabajo.json`.
- `palabras.json`: las palabras con tiempos del short tal como TSOTS ya las
  calcula para quemar los subtítulos (`tramo_palabras(...)`,
  `videopipeline/shorts.py:650`; mlx-whisper corregido con el glosario), en
  el timeline del short: `[{"texto", "inicio", "fin"}]`. Con esto el modo
  en segundo plano no vuelve a transcribir y los anclajes `palabra` casan
  con el subtítulo quemado.
- `trabajo.json`:

```json
{
  "version": 1,
  "origen": "/abs/.../Episodio20/11 - El futuro del código.mp4",
  "destino": "/abs/.../Episodio20/11 - El futuro del código.editado.mp4",
  "origen_tam": 43740507,
  "origen_mtime": 1763375340.12,
  "estilo": "divertido",
  "idioma": "es",
  "resolucion": [1080, 1920],
  "encuadre": "difuminado",
  "zonas": {
    "titulo":     {"y": [0, 640], "hasta": 5.0},
    "contenido":  [0, 656, 1080, 608],
    "subtitulos": [1265, 1460]
  }
}
```

- `zonas` las calcula TSOTS con sus propias funciones, no se adivinan:
  - `contenido`: rectángulo donde está la imagen original según el encuadre
    (`videopipeline/vertical.py:59-91`). Para `difuminado` y `barras`, la
    imagen 16:9 escalada y centrada; para `cara`, la ventana 4:3 a
    ~1080x810 centrada (y≈555–1365) sobre el fondo difuminado; para
    `central`, el frame completo.
  - `subtitulos`: franja vertical que ocupa el texto de los subtítulos, sin
    margen, a partir de `posicion`, `PRESETS[diseno].tamano_rel` y `tamano`
    (`videopipeline/subtitles.py:253-279`, `margen_v = alto*(100-posicion)/100`,
    alineación abajo). El margen de seguridad (1 línea) lo aplica la skill
    solo al colocar gráficos, nunca al decidir los zooms.
  - `titulo`: franja del título quemado y su duración (`titulo.DURACION`, 5.0 s).
- Tras encolar, la app lanza el agente (5.3). Si encolar falla, se registra
  un aviso y los shorts siguen siendo válidos (nunca rompe `shorts.crear`).

### 5.3 Agente: `lanzador/edicion/procesar_pendientes.sh`

Copia del agente del blog (`lanzador/blog/procesar_pendientes.sh`) con la
misma estructura: bloqueo `.bloqueo` (con caducidad), bucle sobre
`pendientes/*/` que ignora ocultas, cada carpeta se procesa una vez,
`hechos/` y `errores/`, log en `~/TSOTS/edicion/agente.log`, límite por
carpeta `TSOTS_EDICION_LIMITE` (por defecto 1200 s).

Por cada trabajo:
1. Ejecuta `claude -p --model claude-haiku-5-5` con:
   - prompt = contenido de `SKILL.md` de la skill + "Trabajo: <ruta>"
     (inline, como el blog con `instrucciones.md`; no depende de que el
     modo `-p` descubra skills);
   - `--allowedTools` limitado a: `Read`, `Write` del `plan.json` del
     trabajo, y `Bash(<.venv-clearvoice/bin/python> -m videopipeline.edicion.<x>:*)`
     para `preparar`, `validar_plan`, `renderizar` y `verificar` (como el
     blog con `videopipeline.blog_subida`);
   - `--disallowedTools` para todo lo demás que pueda escribir fuera del
     trabajo (mismo criterio que el blog: las prohibidas ganan).
2. **El script, no Haiku, decide el éxito.** Comprueba:
   - existe `<trabajo>/salida.mp4`;
   - `ffprobe`: vídeo 1080x1920 y audio presentes, duración = la del
     original ±0.25 s;
   - el original no ha cambiado (`origen_tam` y `origen_mtime`) y sigue
     existiendo.
3. Éxito: copia `salida.mp4` a `<destino>.tmp` en la carpeta del episodio y
   la renombra a `destino` (atómico); borra `video.mp4` y `salida.mp4` del
   trabajo; mueve la carpeta a `hechos/` con `resultado.json`
   (`{destino, estilo, duracion, fecha}`).
4. Fallo: mueve a `errores/` con `motivo.txt` (motivo + final de
   `claude.log`). El short original queda como estaba.

Lanzamiento desde la app: nueva función `lanzar_agente_edicion()` (módulo
nuevo `videopipeline/edicion.py`, gemela de `difusion.lanzar_agente`): se
llama al abrir la app (junto a la del blog, `app/main.py:280`) y cuando
**termina el lote** (la cola de procesamiento queda vacía), no tras cada
vídeo: así la edición (render a 60 fps) no compite con ClearVoice /
mlx-whisper / Ollama mientras el lote procesa. "No retrasar la creación de
shorts" significa que la creación nunca espera a la edición. Si el usuario
lanza otro lote mientras el agente edita, ambos corren a la vez (aceptado
en v1). El sitio exacto del enganche es del constructor. Nunca lanza
excepciones.

### 5.4 Motor de edición y skill `editar-short` (dentro de TSOTS)

Decisión del usuario: todo vive en el repo de TSOTS, para que cualquiera
que instale TSOTS pueda usarlo. Los scripts de `VideoEditor/tools/` y de
`chatcut/tools/` se portan (código y comentarios en español, con tests) y
`VideoEditor` queda solo como banco de pruebas.

```
limpiadorVideo/
  lanzador/edicion/
    procesar_pendientes.sh   agente (5.3)
    SKILL.md                 proceso para Haiku (modo trabajo) y para el
                             chat (modo interactivo); el agente lo mete
                             inline en el prompt, como instrucciones.md
    estilos/divertido.json   reglas y presupuesto de cada estilo
    estilos/formal.json
    estilos/academico.json
  videopipeline/edicion/
    __init__.py              lanzar_agente_edicion(), encolar()
    preparar.py              contexto.md desde palabras.json + zonas
    validar_plan.py          comprueba plan.json, lista de errores
    renderizar.py            plan.json -> specs -> salida.mp4
    verificar.py             hoja de fotogramas en los momentos del plan
    rotulos.py               plantillas de etiquetas, contadores, títulos y
                             transiciones (port de chatcut gen_overlays.py,
                             paleta y fps por estilo)
    sonidos.py               SFX sintetizados (port de gen_sfx.py + golpe y
                             zumbido de extras.py)
    musica.py                música sintetizada por estilo (de extras.py)
    emojis.py                emojis como imagen y viñeta (de extras.py)
    componer.py              zoom por franja, overlays, mezcla (compose.py)
```

- Se ejecuta con `.venv-clearvoice/bin/python -m videopipeline.edicion.<x>`.
- **Sin dependencias nuevas:** `.venv-clearvoice` ya tiene Pillow 12.3,
  numpy 1.26 y scipy 1.17 (comprobado); TSOTS ya exige ffmpeg-full
  (`videopipeline/steps.py:117`); Apple Color Emoji es fuente del sistema
  (solo tamaño 160, se reescala). Nada de `whisper` CLI ni de un entorno
  `uv` aparte: en modo interactivo, si no hay `palabras.json`, se transcribe
  con la transcripción mlx-whisper que TSOTS ya tiene.
- Skill para el chat: `~/.claude/skills/editar-short` es un enlace a
  `lanzador/edicion/`. `SKILL.md` localiza el repo relativo a su propia
  ruta (dos niveles arriba). El enlace lo crea el usuario (o un paso
  opcional del instalador); no es necesario para el modo en segundo plano.
- La casilla "Editar con Claude" solo se habilita si encuentra el comando
  `claude` (mismas rutas que el agente: `PATH`, `~/.local/bin`,
  `/opt/homebrew/bin`); si no, desactivada con un tooltip que explica que
  hace falta Claude Code instalado y con sesión iniciada.
- README (ES y EN): sección nueva "Editar shorts con Claude": qué hace,
  que necesita `claude` con sesión iniciada **con la cuenta del propio
  usuario**, que consume de su plan, dónde están los logs y las carpetas
  `~/TSOTS/edicion/{pendientes,hechos,errores}`, y cómo enlazar la skill
  para usarla desde el chat.

**Flujo en modo trabajo** (lo que hace Haiku, en este orden):
1. `preparar.py <trabajo>` → `contexto.md`: frases con tiempos, lista de
   palabras con `inicio` (de `palabras.json`; solo si falta, Whisper local
   cacheado), caption del `.md`, zonas, reglas y presupuesto del estilo,
   catálogo de tipos de momento y emojis permitidos.
2. Haiku escribe `plan.json` (ver 5.5): **solo momentos**, nada de
   posiciones, sonidos ni duraciones de plantilla.
3. `validar_plan.py` → si hay errores, Haiku corrige y repite (máx. 3).
4. `renderizar.py` → deriva los specs y monta `salida.mp4` a calidad
   completa (CRF 18, fps del original).
5. `verificar.py` → hoja de fotogramas (un fotograma por momento + inicio y
   final). Haiku la mira con `Read`; si ve algo roto (texto cortado, tapa
   subtítulos, emoji ausente), corrige `plan.json` y vuelve a 3 (máx. 1
   vuelta). Si no, termina.

**Modo interactivo:** el mismo flujo, con un vídeo y un `.srt` sueltos y
estilo dicho en el chat; `preparar.py` acepta `--video/--srt/--estilo` y
detecta las zonas si no hay `trabajo.json` (o se las pregunta al usuario).

### 5.5 `plan.json`: lo que decide Haiku

```json
{
  "momentos": [
    {"t": 9.20,  "palabra": "escribir", "tipo": "etiqueta", "texto": ["ESCRIBIR CÓDIGO"]},
    {"t": 12.70, "palabra": "The",      "tipo": "titulo",   "texto": ["THE SILENCE", "OF THE SHORTS"]},
    {"t": 31.76, "palabra": "melón",    "tipo": "emoji",    "emoji": "🍉"},
    {"t": 18.08, "palabra": "Anibal",   "tipo": "golpe"},
    {"t": 53.36, "palabra": "llama",    "tipo": "error"},
    {"t": 56.60, "palabra": "negocio",  "tipo": "contador", "lista": 1, "num": 1, "texto": "NEGOCIO"},
    {"t": 24.30, "tipo": "transicion"},
    {"t0": 15.26, "t1": 19.0, "tipo": "zoom"}
  ],
  "final": {"texto": ["REVISA · PLANIFICA", "REGLAS CLARAS"], "check": true}
}
```

- `palabra`: la palabra del transcript donde cae el momento. El validador
  ajusta `t` al `start` real de esa palabra (±0.4 s); si no la encuentra,
  error. Así Haiku no inventa tiempos.
- `renderizar.py` deriva todo lo demás según el estilo:
  - Posiciones: zona libre de arriba (por encima de `contenido`, o por
    encima de `subtitulos` si `contenido` es el frame completo); nada en la
    zona del título antes de `titulo.hasta`; contadores alternando
    izquierda/derecha; un emoji simultáneo con una etiqueta va al lado.
  - Duraciones por defecto por tipo; un contador dura igual que los demás
    de su lista.
  - Sonido emparejado: etiqueta → tic (alternando timbre); contador →
    pop (lista 1) / pluck (lista 2), tono ascendente por número; transición →
    whoosh rotando variantes, 0.12 s antes; título → subida + golpe;
    golpe → sting + viñeta roja; error → zumbido + ❌; emoji → tap con
    frecuencia variable; final → ding. Entrada: boom en 0.05 s.
  - Transiciones: tipo rotando sin repetir dos seguidas.
  - Zoom: la franja que se amplía es `contenido` recortada por arriba del
    borde superior de `subtitulos` (en los shorts 10 y 11: y 660–1260; en
    `cara`, y 555 hasta el subtítulo). Nunca toca el subtítulo ni el título.
    En v1 el zoom va **centrado** en la franja: en segundo plano Haiku no
    sabe quién habla, y centrado a ≤1.25 se ven las dos personas. Seguir
    al que habla (como en las pruebas manuales) queda para después. Zoom
    lento de entrada (0→2.5 s) y de cierre en los estilos que lo permitan.
  - Música sintetizada según estilo, con ducking bajo la voz; voz
    normalizada a -16 LUFS antes de mezclar; salida -14 LUFS, TP -1.5.

**`validar_plan.py`** rechaza: tiempos fuera de `[0, duración]`; tipos o
emojis no permitidos por el estilo; `palabra` no encontrada; dos elementos
visuales a la vez en la misma zona (salvo emoji lateral + etiqueta); líneas
de texto que no caben a 1080 px con la fuente del estilo; más momentos de
los que permite el presupuesto del estilo; listas de contadores con
números no consecutivos; zoom de más de 1.3 o solapado con otro zoom.

### 5.6 Estilos (valores iniciales, ajustables)

| | Divertido | Formal | Académico |
|---|---|---|---|
| Base | lo probado en 10 y 11 | sobrio | didáctico |
| Densidad máx. | 1 momento / 2.5 s | 1 / 6 s | 1 / 5 s |
| Etiquetas | sí | sí | sí, formato "término" |
| Contadores | sí | sí | sí, prioritarios |
| Emojis | sí | no | no |
| Golpe / error | sí | no | no |
| Transiciones | 7 tipos | barrido, persiana | barrido |
| Zoom golpe | 1.12–1.25 | no | no |
| Zoom lento entrada/cierre | sí | sí (≤1.06) | no |
| SFX | todos, niveles actuales | solo tic suave (-24 dB) y transición | solo en contadores (-24 dB) |
| Música | lo-fi 96–100 bpm, -14 dB | tranquila 80 bpm, -20 dB | sin música (o -24 dB) |
| Paleta | naranja #FF5A00, pastilla negra | blanco/gris, acento naranja fino | blanco/azul oscuro, acento naranja |

Cada estilo es un JSON en `estilos/`; `renderizar.py` y `validar_plan.py`
lo leen. Cambiar un estilo no requiere tocar código.

### 5.7 Publicación

- `shorts.listar` (`videopipeline/shorts.py:479-500`): si existe
  `<stem>.editado.mp4`, `Corto.mp4` apunta a él y `Corto.editado = True`;
  si no, el original. El `.md` es el mismo.
- `DialogoPublicarShorts` muestra "(editado)" junto al título del short
  editado. La subida (`upload_post.py`) no cambia: usa `corto.mp4`.
- `<stem>.publicado.json` sigue siendo uno por short, con la clave del
  **original** aunque se suba el editado (`registro.ruta` hoy derivaría
  `X.editado.publicado.json`; hay que anclarlo al original).

### 5.8 Regenerar shorts

- `shorts.crear`, al borrar los ficheros de `archivos` antes de mover los
  nuevos (`shorts.py:676-695`), borra también `<stem>.editado.mp4` de cada
  uno (y su `.tmp` si quedó).
- Un trabajo pendiente de un short regenerado no publica nada: el script
  detecta que `origen_tam/origen_mtime` no coinciden y lo manda a
  `errores/` con motivo "origen cambiado". Si la casilla sigue activada, la
  regeneración ya encoló trabajos nuevos.

### 5.9 Pruebas

TSOTS (pytest, offscreen):
- Panel: la casilla y el estilo se guardan, se restauran y viajan en el
  JSON del runner; el combo se desactiva con la casilla.
- `OpcionesShorts`: estilo inválido → `ValueError`.
- `shorts.crear` con `editar=True` crea un trabajo por short con
  `trabajo.json` correcto (zonas para `difuminado` y `cara`); con
  `editar=False` no crea nada; un fallo al encolar no rompe la creación.
- `shorts.listar` prefiere `.editado.mp4`; `crear` borra los editados viejos.
- `lanzar_agente_edicion`: no hace nada sin pendientes; no lanza excepciones.
- Script del agente, como `tests/test_blog_agente.py`, con un `claude`
  falso (variable de entorno con la ruta): bloqueo, hechos/errores,
  duración que no cuadra → errores, origen cambiado → errores, éxito →
  `destino` escrito de forma atómica.

Motor `videopipeline/edicion/` (pytest en TSOTS, sin `claude`):
- `validar_plan` con planes buenos y malos (cada regla).
- `renderizar` sobre un clip sintético de 10 s generado en el test →
  `ffprobe` (dimensiones, fps, duración, audio).
- Prueba de humo: el plan equivalente al vídeo 11 renderiza sin errores
  (marcada lenta si hace falta).
- Ningún test usa credenciales reales ni llama a `claude`.

Prueba manual de aceptación: crear shorts del Episodio 20 con la casilla
activada en estilo divertido; los editados aparecen y "Publicar shorts…"
los muestra como "(editado)". Repetir un short en formal y académico.

## 6. Lo que decidió el usuario

- Integrar con TSOTS; los finales vuelven a TSOTS para subirlos.
- Desplegable de estilo; un ajuste por lote de creación de shorts, no por
  vídeo; activable y desactivable.
- Modelo `claude-haiku-5-5`.
- Enfoque A (cola + `claude -p`).
- Estilo divertido como el de las pruebas de los vídeos 10 y 11.
- El motor vive dentro de TSOTS, para cualquier instalación; cada usuario
  usa sus propias credenciales de Claude, que nunca entran en el repo.

## 7. Decisiones mías (revisables)

- Nombre `NN - título.editado.mp4` junto al original, no sobrescribir.
- Casilla desmarcada por defecto; estilo por defecto divertido.
- Haiku solo decide momentos (`plan.json`); posiciones, sonidos y
  duraciones son código. Tiempos anclados a `palabra`.
- El script valida el resultado; no se confía en Haiku para dar el OK.
- SKILL.md inline en el prompt de `claude -p` (como el blog).
- Valores iniciales de los estilos formal y académico (tabla 5.6).
- Límite de 1200 s por short; procesamiento secuencial.
- Tiempos por palabra de TSOTS (`palabras.json`) en segundo plano;
  Whisper solo en modo interactivo.
- Zoom centrado en v1 (sin detección de quién habla).
- La franja de zoom se recorta por encima del subtítulo; el margen de 1
  línea es solo para colocar gráficos.
- El agente arranca al terminar el lote y al abrir la app, no tras cada
  vídeo.
- Rama `feature/edicion-shorts` en un worktree
  `~/Documents/personalProjects/tsots-edicion`, como las otras features.
  Este documento viaja a `docs/superpowers/specs/` de esa rama.
- Casilla deshabilitada si no se encuentra `claude`.
- Interactivo sin `palabras.json`: transcripción mlx-whisper de TSOTS.

## 8. Para el constructor

- Cómo restringir `Write` a un solo fichero en `--allowedTools` y la lista
  exacta de prohibidas.
- Qué fotogramas exactos entran en la hoja de verificación.
- Cálculo fino de `zonas` para `cara` y `central` (frame completo: sin
  zooms, gráficos por encima de los subtítulos).
- Presupuestos y niveles exactos dentro de los márgenes de la tabla 5.6.
- Cómo reparametrizar `gen_overlays.py` (FPS y paleta hoy son constantes)
  sin romper su uso actual.
