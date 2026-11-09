# Varios perfiles de publicación — diseño

Estado: aprobado para construir (2026-11-09). El usuario pidió trabajo autónomo: las decisiones marcadas «(decisión mía)» las tomó el agente.

## Qué y por qué

El usuario publica en upload-post con un perfil (sus redes personales) y ha creado otro, `sixpodcast`, con otras redes conectadas. Hoy la app guarda un solo perfil por servicio, y todo lo que cuelga de él es global: ubicación, página de Facebook, redes marcadas, modos, X Premium… Publicar en el otro perfil obliga a reescribirlo todo en Redes… y a acordarse de volver.

**Es un éxito si:**
- desde la ventana principal se ve, antes de procesar, para qué perfil se trabaja;
- cambiar de perfil carga los datos de ese perfil, sin reescribir nada;
- al publicar, el diálogo propone el perfil con que se procesó el vídeo, y se puede cambiar ahí si fue un error;
- la app recuerda el último perfil usado.

## Decidido con el usuario

- **Perfiles distintos en el mismo servicio:** una sola API key (la de la cuenta de upload-post) y varios perfiles dentro.
- **Claro desde el principio:** el perfil se elige y se ve antes de procesar.
- **Se puede cambiar al subir:** en el diálogo de publicar, por si se olvidó cambiarlo o se confundió.
- **No solo el nombre:** los datos de publicación, como la ubicación, son de cada perfil y se cargan al elegirlo.
- **Último usado:** cambiar de perfil, en cualquier sitio, lo deja como perfil activo para la próxima vez.
- **Privacidad:** el lugar de TikTok (su id) sigue en el Llavero, nunca en el repo, los ajustes ni los logs. Ya va por perfil (`credenciales.guardar_lugar_tiktok(proveedor, perfil, ciudad, lugar)`); no cambia.

## Diseño

### Ajustes por perfil (`app/settings.py`)

Hoy todo el código lee `ajustes.perfil_redes`, `ajustes.ciudad`, `ajustes.pagina_facebook`, etc. Esas propiedades pasan a leer y escribir en el espacio del **perfil activo**. Así casi ningún diálogo cambia: cambiar el perfil activo cambia lo que todas leen.

- **Perfil activo:** sigue en `redes/perfil/<proveedor>`, la clave de hoy. Las versiones anteriores la siguen leyendo.
- **Lista de perfiles conocidos:** `redes/perfiles/<proveedor>`, una lista JSON de nombres. Métodos:
  - `perfiles_de(proveedor) -> list[str]`;
  - `anadir_perfil(proveedor, perfil)`, que no duplica;
  - `quitar_perfil(proveedor, perfil)`, que borra también sus datos.
- **Datos de cada perfil:** en `redes/perfil_datos/<proveedor>/<huella>/<clave>`.
  - La huella es la misma idea que `credenciales._cuenta_lugar`: los primeros 16 caracteres del sha256 del nombre. Un nombre con barras o espacios no rompe la ruta de QSettings.
  - Pasan a ser por perfil:
    - `ciudad`;
    - `pagina_facebook` (id y nombre);
    - `plataformas_redes`;
    - `tiktok_modo`, `instagram_modo` y `facebook_modo`;
    - `x_premium`;
    - `youtube_categoria`;
    - las cuentas guardadas (`cuentas_guardadas` / `guardar_cuentas`);
    - `contexto_marca`.
  - El contexto de marca entra porque el caption y el texto de LinkedIn se escriben con la voz de la marca, y `sixpodcast` no es la misma marca **(decisión mía)**.
- **Se quedan globales:**
  - `proveedor_redes`;
  - el glosario: términos de transcripción, que suman y no estorban **(decisión mía)**;
  - las programadas locales: sus referencias son únicas;
  - todo lo que no es de redes.
- **Migración, una sola vez, al crear `Ajustes`:** si `redes/perfiles/<proveedor>` no existe y hay perfil activo, la lista queda `[perfil]` y los valores globales de hoy se copian a los datos de ese perfil. Las claves globales viejas no se borran ni se siguen escribiendo, para que una versión anterior siga arrancando. Un perfil nuevo empieza con los valores por defecto de siempre: Madrid, sin página, sin marca…
- **Sin perfil activo** (perfil vacío): las propiedades por perfil leen y escriben las claves globales de siempre, como hoy, y el primer perfil que se añada las hereda. Así quien nunca configuró Redes… no pierde su contexto de marca. Igual que hoy cuando falta el perfil, el diálogo de publicar avisa de que falta.
- El perfil activo pasa a la lista al fijarse: `perfil_redes = x` añade `x` a la lista.

### Lista de perfiles del servicio

- `Proveedor.perfiles() -> list[str]`: los perfiles de la cuenta, a partir de la API key. Lanza `ErrorConsulta`.
- En upload-post es `GET /api/uploadposts/users`. La respuesta trae `profiles`, una lista de objetos. El nombre está en `username`, que es el que usa `GET /uploadposts/users/{username}`. Si falta, se prueba `profile` y `name`. Un objeto sin nombre se ignora.
- Sin verificar contra el servicio real: si la respuesta no trae `profiles`, `ErrorConsulta` («Respuesta inesperada…»). La app sigue funcionando: el perfil se puede escribir a mano, como hoy.
- `app/cuentas.listar_perfiles(llavero, fabrica, nombre, *, clave=None) -> tuple[list[str] | None, str]`, como `buscar_lugares`: para fuera del hilo de la interfaz y nunca lanza.
- Los proveedores falsos de los tests (`tests/redes_falsos.py`) y el test de contrato reciben el método.

### Cada vídeo recuerda su perfil (`videopipeline/ficha.py`)

- `Ficha.perfil: str = ""`: el perfil activo cuando se procesó o se crearon sus shorts.
- `_a_dict` lo escribe y `_de_dict` lo lee con `datos.get("perfil", "")`. Una ficha antigua carga sin él.
- La versión anterior ignora la clave al leer. Si reescribe la ficha, la pierde: es aceptable.
- `procesar` y `_crear_shorts` (`app/main.py`) lo anotan en la ficha y la guardan antes de lanzar el runner.

### Selector de perfil (`app/widgets/selector_perfil.py`, nuevo)

`SelectorPerfil(QComboBox)` con los perfiles conocidos del proveedor activo:
- `recargar(ajustes)` lo rellena y marca el activo;
- la señal `perfil_elegido(str)` salta solo cuando el usuario cambia la elección, no al recargar;
- sin perfiles, una sola entrada deshabilitada: «Sin perfil: añádelo en Redes…».

Se usa en cuatro sitios:

1. **Ventana principal:** en la cabecera, a la derecha, «Perfil:» y el selector, visible siempre **(decisión mía: es lo primero que se ve y está antes de procesar)**. Cambiarlo fija el perfil activo. Se recarga al cerrar Redes…, Publicar, Publicar shorts y Programadas, porque cualquiera de ellos puede haber cambiado el activo.
2. **Publicar** (`DialogoPublicar`): sustituye a la etiqueta «Vía … · perfil «x»», manteniendo el «Vía {servicio}».
   - Recibe `perfil` (el de la ficha). Si existe y no es el activo, lo hace activo al abrir: es el último usado.
   - Al cambiarlo en el diálogo: fija el activo y llama a `refrescar_servicio()`, que ahora también vuelve a leer las plataformas deseadas, los modos y la página de Facebook del perfil.
   - Deshabilitado mientras publica.
   - Al publicar, `main` anota en la ficha el perfil usado, para que la próxima vez proponga ese.
   - El caption no se regenera: se escribió con la marca del perfil de antes, y se puede editar en el propio diálogo.
3. **Publicar shorts** (`DialogoPublicarShorts`): igual que Publicar, con el perfil de la ficha del vídeo largo.
4. **Programadas** (`DialogoProgramadas`): elegir otro perfil fija el activo y vuelve a consultar lo programado de ese perfil.

### Redes… (`DialogoRedes`)

- El campo de texto del perfil pasa a un `QComboBox` editable con los perfiles conocidos. Se puede escribir uno nuevo, como hoy, con el mismo aviso si parece un email.
- «Buscar perfiles»: con la clave guardada o la recién escrita, llama a `cuentas.listar_perfiles` en segundo plano y añade a la lista los que no estaban. Los errores se muestran como los de «Comprobar».
- Al elegir otro perfil de la lista, el diálogo carga sus datos:
  - modos, X Premium, categoría de YouTube y página de Facebook;
  - la ubicación, también el lugar de TikTok del Llavero de ese perfil;
  - las cuentas guardadas.
- «Quitar perfil» (con confirmación): lo quita de la lista y borra sus datos de ajustes. Los lugares de TikTok de ese perfil en el Llavero no se tocan **(decisión mía: borrarlos exige saber todas las ciudades; quedan huérfanos e inofensivos)**.
- «Guardar» escribe los datos en el perfil elegido, lo añade a la lista y lo deja activo.
- El contexto de marca se sigue editando donde está, con el botón de marca del panel. Ahora edita el del perfil activo, y el título del diálogo de marca nombra el perfil.

### Lo que no cambia

- La API key: una por proveedor, en el Llavero.
- El registro de publicaciones, el diario y las programadas locales.
- El pipeline: recibe `contexto_marca` como hoy (el del perfil activo).

## No objetivos

- Varias API keys o varias cuentas de upload-post.
- Regenerar el caption al cambiar de perfil en Publicar.
- Mostrar el perfil en cada fila de la cola.
- Un glosario por perfil.

## Pruebas

- **Ajustes:**
  - la migración: el perfil de hoy hereda los valores globales y uno nuevo empieza con los de por defecto;
  - cambiar el activo cambia lo que leen todas las propiedades por perfil;
  - una versión anterior sigue leyendo `redes/perfil/<proveedor>`;
  - quitar un perfil borra sus datos;
  - un perfil con «/» o espacios funciona.
- **Proveedor:** `perfiles()` con respuesta buena, sin `profiles`, con objetos sin nombre, y error HTTP o de red → `ErrorConsulta` sin la clave.
- **Ficha:** se guarda y se lee `perfil`, y una ficha sin la clave carga.
- **GUI** (offscreen, como los tests que ya hay):
  - el selector de la ventana fija el activo;
  - Publicar abre con el perfil de la ficha y al cambiarlo recarga la ubicación y las cuentas de ese perfil;
  - Redes… carga los datos al elegir otro perfil y «Buscar perfiles» añade los del servicio (proveedor falso).
- **Nunca** pasar los tests `lenta` ni `tests/test_redes_real*.py`: suben de verdad.

## Restricciones

- Código, comentarios y textos de la interfaz en español. Los textos nuevos se traducen en `locale/en/LC_MESSAGES/tsots.po` (`lanzador/traducir.sh`).
- Commits en inglés, sin atribución de IA.
- PR contra `develop`, con la documentación (README, DEVELOPMENT y TODO) en la misma rama.
