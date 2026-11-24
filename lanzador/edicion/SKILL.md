---
name: editar-short
description: Decide los momentos (etiquetas, emojis, contadores, golpes, zooms, flechas, lupas, B-roll, iconos, datos) de un short ya cortado con subtítulos quemados y deja el plan en plan.json.
---

# Editar un short

## Qué haces

Tienes un short ya cortado, con los subtítulos quemados. Decides **qué
momentos** añadir y **cuándo** (etiquetas, emojis, contadores, golpes, zooms…).
Nunca decides posiciones, sonidos ni duraciones: eso lo añade el código.

## Modo trabajo

Trabajas sin nadie delante: no hagas preguntas. Sigue estos pasos en orden.
`<trabajo>` es la ruta que aparece tras «Trabajo:» al final de este texto, y
ya es tu carpeta actual.

Los comandos se escriben **exactamente así**, copiados tal cual: `./tsots`, el
paso y un punto. Sin `cd`, sin rutas, sin comillas y sin variables delante;
cualquier otra forma pide un permiso que nadie puede dar y el trabajo se pierde.

`./tsots preparar .` y `./tsots renderizar .` pueden tardar varios minutos:
ejecútalos con la herramienta Bash poniendo `timeout` a 600000 y espera a que
terminen. No los lances en segundo plano.

1. Ejecuta `./tsots preparar .` y lee con Read el fichero `<trabajo>/contexto.md`.
2. Escribe con Write el fichero `<trabajo>/plan.json`. Formato abajo.
3. Ejecuta `./tsots validar_plan .`. Si no imprime `OK`, corrige `plan.json`
   según cada línea de error y vuelve a ejecutarlo. Como mucho 3 intentos; si
   sigue fallando, para. Si imprime `OK` seguido de líneas `Sugerencia:`,
   aplica las que tengan sentido y vuelve a validar una vez.
4. Ejecuta `./tsots renderizar .`.
5. Ejecuta `./tsots verificar .` y lee con Read `<trabajo>/verificacion.png`.
   Si en algún fotograma ves texto cortado, un gráfico sobre los subtítulos o
   sobre el título, o falta un elemento, o la flecha o la lupa no señalan el
   texto correcto, o el B-roll no tiene que ver con lo que se dice: corrige `plan.json` y repite los
   pasos 3 a 5 **una sola vez**.
6. Para. No ejecutes nada más ni toques ningún otro fichero.

Si un comando te pide aprobación o se deniega, no busques otra forma: para.

## Formato de plan.json

```json
{
  "momentos": [
    {"t": 9.20,  "palabra": "escribir", "tipo": "etiqueta", "texto": ["ESCRIBIR CÓDIGO"]},
    {"t": 12.70, "palabra": "The",      "tipo": "titulo",   "texto": ["THE SILENCE", "OF THE SHORTS"]},
    {"t": 31.76, "palabra": "melón",    "tipo": "emoji",    "emoji": "🍉"},
    {"t": 18.08, "palabra": "Anibal",   "tipo": "golpe"},
    {"t": 56.60, "palabra": "negocio",  "tipo": "contador", "lista": 1, "num": 1, "texto": "NEGOCIO"},
    {"t": 24.30, "tipo": "transicion"},
    {"t": 40.10, "palabra": "Revisión", "tipo": "senalar", "pantalla": "Revisión", "forma": "flecha"},
    {"t": 44.00, "palabra": "factura", "tipo": "lupa",     "pantalla": "Factura 2024"},
    {"t": 48.50, "palabra": "oficina", "tipo": "broll",    "buscar": "busy open plan office"},
    {"t": 54.66, "palabra": "documentos", "tipo": "icono", "icono": "documento"},
    {"t": 30.20, "palabra": "años",    "tipo": "dato",     "valor": 10, "texto": "AÑOS DE CASOS"},
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
| golpe | El chiste principal, si lo hay. Máximo 2. |
| error | Solo si se habla de un error, un fallo o algo que está mal o no se puede hacer («es un error», «esto está mal», «no se puede hacer», «no funciona»). Una negación normal («no», «nunca», «no es…») **no** es un error. La mayoría de vídeos no lleva ninguno; como mucho 1. |
| transicion | Un cambio de tema claro; si no lo hay, ninguna. Como mucho 4 por vídeo. |
| senalar | Lo dicho sale escrito en pantalla (`## En pantalla`): `pantalla` es ese texto (o un trozo corto) y `forma` es `circulo` (por defecto), `flecha` o `subrayado`. Dura 2 s. |
| lupa | Un texto corto de la pantalla (hasta 4 palabras), o el más importante del tramo: `pantalla` es ese texto o un trozo corto. Dura 2,6 s y ocupa la zona superior como una etiqueta. |
| broll | Algo concreto que se nombra y no se ve: `buscar` son de 2 a 6 palabras en inglés, concretas y visuales. Dura 2,5 s. Solo si `B-roll: disponible`. |
| icono | Un concepto abstracto con icono en `## Iconos`: `icono` es su nombre exacto. Dura 1,6 s. |
| dato | Un número dicho (`## Números dichos`): `valor` numérico, `texto` de 22 caracteres como mucho y `unidad` `"%"` si se dice «por ciento». Dura 2,4 s. |
| zoom | Una frase enfática. Dura de 2 a 5 s (`t1` − `t0`) y nunca se solapa con otro zoom. Sin `palabra`. |

## Elegir el recurso

Para cada momento, elige el primer recurso que encaje, en este orden:

1. Lo dicho sale en pantalla (`## En pantalla`) → `lupa` si es un texto corto
   (hasta 4 palabras) o lo más importante del tramo; si es una línea larga,
   `senalar`.
2. Se dice un número relevante → `dato`.
3. Se nombra algo concreto que no se ve (un objeto, un lugar, una acción) →
   `broll`, con la búsqueda en inglés, concreta y visual.
4. Un concepto abstracto con icono en el catálogo (`## Iconos`) → `icono`.
5. Una frase clave → `etiqueta`; una enumeración → `contador`.
6. Un chiste o una imagen dicha → `emoji` o `golpe`. Se habla de un error o de
   algo que está mal o no se puede hacer → `error` (el validador lo comprueba).

- `senalar` y `lupa` solo con textos de `## En pantalla`, visibles en ese
  segundo, y nunca durante un `zoom`. `pantalla` es el texto exacto que sale
  entre « » en `## En pantalla` o un trozo corto de él (1 a 4 palabras
  seguidas), copiado tal cual. Una línea larga no cabe en la `lupa`: usa un
  trozo corto o `senalar`.
- `dato` solo con números de `## Números dichos`, a menos de 1,5 s de `t`.
- `broll` como mucho 1 cada 15 s de vídeo, y no puede coincidir con ningún
  otro momento visual (sí con una `transicion`). Las búsquedas, en inglés,
  concretas y visuales («hands typing on laptop», no «productividad»).
- Variedad: no pongas 3 momentos seguidos del mismo tipo. Ningún tipo es
  obligatorio: no sigas una receta fija (título, golpe, error, transiciones…);
  pon solo lo que encaje con lo que se dice en este vídeo.
- Si en `## Estilo` pone `B-roll: no disponible` o `lectura de pantalla: no`,
  no uses esos tipos (`broll`; `senalar` y `lupa`).

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
