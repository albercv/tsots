---
name: editar-short
description: Decide los momentos (etiquetas, emojis, contadores, golpes, zooms) de un short ya cortado con subtítulos quemados y deja el plan en plan.json.
---

# Editar un short

## Qué haces

Tienes un short ya cortado, con los subtítulos quemados. Decides **qué
momentos** añadir y **cuándo** (etiquetas, emojis, contadores, golpes, zooms…).
Nunca decides posiciones, sonidos ni duraciones: eso lo añade el código.

## Modo trabajo

Trabajas sin nadie delante: no hagas preguntas. Sigue estos pasos en orden.
`<trabajo>` es la ruta que aparece tras «Trabajo:» al final de este texto.

1. Ejecuta `@PYTHON@ -m videopipeline.edicion.preparar <trabajo>` y lee con
   Read el fichero `<trabajo>/contexto.md`.
2. Escribe con Write el fichero `plan.json` en la carpeta actual (es la carpeta
   del trabajo; no hagas `cd` a ningún sitio). Formato abajo.
3. Ejecuta `@PYTHON@ -m videopipeline.edicion.validar_plan <trabajo>`. Si no
   imprime `OK`, corrige `plan.json` según cada línea de error y vuelve a
   ejecutarlo. Como mucho 3 intentos.
4. Ejecuta `@PYTHON@ -m videopipeline.edicion.renderizar <trabajo>`.
5. Ejecuta `@PYTHON@ -m videopipeline.edicion.verificar <trabajo>` y lee con
   Read `<trabajo>/verificacion.png`. Si en algún fotograma ves texto cortado,
   un gráfico sobre los subtítulos o sobre el título, o falta un elemento:
   corrige `plan.json` y repite los pasos 3 a 5 **una sola vez**.
6. Para. No ejecutes `entregar` ni toques ningún otro fichero.

## Formato de plan.json

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

`final` es opcional. `etiqueta` y `titulo`: `texto` es una lista de 1 o 2
líneas. `contador`: `texto` es una sola cadena de 22 caracteres como mucho.

| tipo | cuándo usarlo |
|---|---|
| etiqueta | Una frase clave dicha, 2 a 4 palabras. |
| titulo | El nombre propio o la tesis del vídeo. Máximo 1. |
| contador | Cada ítem de una enumeración hablada, en la palabra clave del ítem. `lista` 1 para la primera enumeración y 2 para la segunda; `num` 1, 2, 3… |
| emoji | Un chiste o una imagen concreta dicha («melón» → 🍉, «junior» → 🐣). |
| golpe | El chiste principal. Máximo 2. |
| error | Una negación rotunda («no es…», «nunca»). |
| transicion | Un cambio de tema. Entre 3 y 5 por vídeo. |
| zoom | Una frase enfática. Dura de 2 a 5 s (`t1` − `t0`) y nunca se solapa con otro zoom. Sin `palabra`. |

## Reglas

- `palabra`: la palabra exacta tal como aparece en `## Palabras` del contexto.
  Obligatoria en todos los tipos salvo `transicion` y `zoom`.
- Los textos van en MAYÚSCULAS, con 26 caracteres como mucho por línea.
- Sin emojis ni flechas dentro de los textos.
- No repitas el mismo emoji dos veces seguidas.
- No superes el máximo de momentos que dice el contexto.
- Nada antes del segundo que indica el contexto, salvo `zoom` y `golpe`.
- Densidad: un momento cada 3 a 5 s en estilo divertido; menos en formal y
  académico.
- Pon momentos en los primeros 10 s tras el título para enganchar.

## Modo interactivo

Solo si una persona te lo pide en el chat. Tienes un vídeo suelto (y quizá un
`.srt`). Si no sabes el estilo (divertido, formal, académico → `divertido`,
`formal`, `academico`) o el encuadre (`cara`, `difuminado`, `central`),
pregúntaselo.

Dónde está todo: esta carpeta es `<repo>/lanzador/edicion`, así que el
repositorio `<repo>` está dos niveles por encima de este `SKILL.md` (si lo lees
por el enlace `~/.claude/skills/editar-short`, resuelve el enlace). El Python es
`<repo>/.venv-clearvoice/bin/python` y todos los comandos se ejecutan con
`PYTHONPATH=<repo>`. Abajo, `PY` significa
`PYTHONPATH=<repo> <repo>/.venv-clearvoice/bin/python`.

1. Crea la carpeta de trabajo (junto al vídeo, `<nombre>.edicion/`) y el
   contexto. Imprime la ruta del trabajo, que es `<trabajo>` en adelante:
   `PY -m videopipeline.edicion.preparar --video <vídeo.mp4> --estilo <estilo> --encuadre <encuadre> [--srt <subs.srt>]`
   Si el vídeo no es vertical (1080x1920), dilo: hay que verticalizarlo antes.
2. Lee `<trabajo>/contexto.md`, escribe `<trabajo>/plan.json` y valídalo con
   `PY -m videopipeline.edicion.validar_plan <trabajo>` hasta que imprima `OK`
   (mismas reglas que en el modo trabajo).
3. `PY -m videopipeline.edicion.renderizar <trabajo> --borrador` (720p) y
   `PY -m videopipeline.edicion.verificar <trabajo>`. Enseña a la persona el
   vídeo borrador y `<trabajo>/verificacion.png`.
4. Ajusta `plan.json` con lo que pida y repite el paso 3. Solo cuando la
   persona lo apruebe, renderiza el final (sin `--borrador`).
5. Para entregarlo: `PY -m videopipeline.edicion.entregar <trabajo>`. Deja
   `<nombre>.editado.mp4` junto al vídeo original y no toca el original.
