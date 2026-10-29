# popOS v0.1 · Personal Operating System

Una **bitácora de acuerdos, aprendizajes y progreso** de estética terminal, para usar dentro de **tmux**. Sin cuenta, sin nube y sin nadie más mirando.

## Iniciar

Es un único binario sin dependencias en tiempo de ejecución (SQLite va dentro) y necesita un terminal UTF-8 de **al menos 50 columnas × 20 filas**; con menos de 86 columnas la barra lateral se pliega en una fila de pestañas.

Con Nix, se instala como el comando `popos` y se abre escribiéndolo:

```bash
nix profile add ~/Projects/popos   # una vez; para actualizar: nix profile upgrade popos
popos
```

Sin instalar nada, desde la carpeta del proyecto: `./run.sh` (lo compila con `cargo` la primera vez; luego, `target/release/popos`).

- Si ya estás dentro de una sesión tmux, la app se abre en el panel actual.
- Si tmux está instalado pero no estás dentro, crea (o recupera) la sesión `popos`.
- Si no tienes tmux, se abre en tu terminal habitual.
- En NixOS, si falta `cargo`, `./run.sh` lo trae con nix al compilar; si falta tmux: `nix shell nixpkgs#tmux`.

## Pestañas y teclas

| Tecla | Acción |
|---|---|
| `←` `→`, `TAB` o `1` a `6` | Cambiar de pestaña: inicio, acuerdos, calendario, bitácora, retrospectivas, poparium |
| `↑` `↓` | Elegir un acuerdo de la lista; en BITÁCORA, una entrada |
| `ENTER` | Leer el acuerdo entero |
| `n` | Nuevo acuerdo, en tu editor |
| `e` | Editar acuerdo: cada cambio guardado es una versión nueva |
| `v` | Versiones: qué cambió en cada una y por qué |
| `d` | Registrar una **aplicación** |
| `p` | Registrar un **avance** |
| `b` | Registrar un **obstáculo** |
| `i` | Guardar un **descubrimiento** |
| `r` | Registrar una revisión (qué aprendí y qué ajustaré) |
| `s` | En BITÁCORA, sobre un obstáculo: cómo lo reparé |
| `x` | Estado: activo, integrado o archivado (una tecla) |
| `Supr` | Borrar: en BITÁCORA la entrada seleccionada; en OVERVIEW o ACUERDOS el acuerdo seleccionado con todo su historial (pide escribir SI) |
| `u` | Deshacer el último borrado, mientras no cierres la app |
| `a` | Mostrar/ocultar archivados |
| `m` | Exportar Markdown |
| `?` | Ayuda |
| `q` | Salir |

En los campos de una línea, `ENTER` confirma, `ESC` cancela sin guardar y `CTRL+U` vacía el campo.

## Acuerdos con su razonamiento

Un acuerdo guarda la decisión **y los motivos que la sostienen**. Así, si días después vuelve a ponerse en duda, se puede recuperar el razonamiento entero, no solo leer «habíamos quedado en esto».

`N` y `E` abren el acuerdo en tu editor (`$VISUAL`, `$EDITOR` o, si no hay ninguno, `nvim`) como un documento casi vacío. **Solo el título es obligatorio**:

```markdown
## TITLE · el nombre del acuerdo (obligatorio)

No hacer pasar hambre a Cayi

## NOTA · opcional: lo que verás en la ficha (borra la sección si no la quieres)

Si acepto preparar la comida, la priorizo o aviso si me retraso.

---

(texto libre: lo que haga falta, con la forma que quieras)
```

- La **nota** es lo que se ve de un vistazo en la ficha. La escribe él; la app nunca la genera. Si se borra la sección, el acuerdo no tiene nota y la ficha muestra en gris el principio del texto.
- Bajo la raya, **texto libre** en Markdown: dos líneas o cinco páginas.
- En nvim, **`Ctrl+G`** ofrece **secciones sugeridas** para cuando ayuda tener una pregunta delante: *Por qué me importa* (la primera, porque los motivos son lo que evita volver a discutir lo decidido), *Contexto*, *Impacto*, *Perspectivas*, *Conclusiones*, *Compromiso*, *Límites y excepciones*, *Desencadenantes*, *Comprobación* y *Recuperación*. Una vez insertada, es Markdown normal: se puede renombrar, mover o borrar. Arriba, una barra fija recuerda las teclas (`ZZ` guardar, `ZQ` salir sin guardar). El atajo solo existe en los documentos de popOS; tu nvim normal no cambia.

Al guardar y salir (`:wq` o `ZZ`) vuelves a popOS; si sales sin guardar (`:q!` o `ZQ`), no cambia nada.

Hay **dos niveles de lectura**:

- **La ficha**, en ACUERDOS: la nota, las experiencias y Popo.
- **El acuerdo entero**, con `ENTER`: el título, la nota destacada y el texto, con scroll.

Las libretas de antes de la 0.3 tenían secciones fijas (WHY, CONTEXT, COMMITMENT…). Al abrirlas, COMMITMENT pasa a ser la nota y las demás pasan al texto libre, cada una bajo su título; las columnas antiguas se conservan y antes se guarda una copia (`popos.pre-0.3.db`).

### Historial de versiones

Cada edición guardada es una versión nueva (`v1.0`, `v1.1`…) con una nota de qué cambió y por qué. `V` muestra todas las versiones, cada una con un diff de lo que cambió respecto a la anterior. Las versiones aparecen también como commits en la pestaña REVIEW. Las conclusiones anteriores siguen pudiéndose consultar, pero nunca dejan de poder revisarse.

Al abrir una libreta creada con una versión anterior de la app, la app añade las secciones nuevas (vacías) y guarda antes una copia de seguridad, `popos.pre-0.2.db`, junto a la base de datos.

## Revisiones como commits

La pestaña **04 REVIEW** muestra el historial como un `git log --graph`. Cada acuerdo es una rama con su color. Su primer commit (`init`) es el momento en que se creó, y cada revisión hecha con `R` es un commit más:

```text
*      82308df (HEAD → Revisar mi libreta) He aprendido a revisar mis acuerdos sin recordatorios ajenos
│        → Revisar los domingos
│ *    40592cd (Mantener rutina) Cenar pronto ayuda a todo lo demás
* │    76f782e El disparador de la mañana funciona
│ │      → Añadir uno por la tarde
│ *    8aa666e init · Mantener rutina
*      c5e0006 init · Revisar mi libreta
```

El hash son 7 caracteres de un SHA-1 del contenido de la revisión. No cambia nunca, y aparece también en la exportación Markdown. El historial cuenta lo que se aprendió y lo que se ajustó.

## Calendario

La pestaña **03 CALENDARIO** muestra el mes como una cuadrícula. Cada día lleva un punto por cada tipo de cosa que pasó: **logro** (D, P), **obstáculo** (B), **aprendizaje** (I, R) y **cambio** (un acuerdo nuevo o una versión). Al lado, o debajo si la ventana es estrecha, está todo lo del día elegido.

En la pestaña, `←` `→` siguen cambiando de pestaña como en todas. **`ENTER` entra en el calendario** (su borde se ilumina): entonces `←` `→` `↑` `↓` se mueven por los días, `[` y `]` cambian de mes y `T` vuelve a hoy. **`ESC`** (o `ENTER` otra vez, o cambiar de pestaña) sale. Un día sin puntos es un día tranquilo, nunca un día en rojo: popOS es una memoria, no una agenda, y no avisa ni reclama nada.

## La versión de cada experiencia

Cada entrada de la bitácora y cada revisión guardan además la **versión del acuerdo que estaba en vigor** cuando ocurrieron, para poder ver más adelante qué pasó después de cada cambio de estrategia. Las de libretas antiguas se completan solas con la versión que había en su fecha.

## Si la app se cierra de golpe

Todo lo que ya se ha guardado (acuerdos, avances, revisiones, versiones) se escribe en la base de datos en el mismo momento, así que cerrar la app, el panel de tmux o la terminal no lo pierde.

Lo que está **a medio escribir** se guarda como borrador en una carpeta privada junto a la libreta (`popos.drafts/`, solo legible por tu usuario). Cada borrador se borra solo cuando su contenido ya está en la libreta:

- **En el editor:** mientras escribes en nvim o vim, cada cambio se copia aparte sin tocar tu archivo, así que `:q!` sigue sin guardar nada. Si todo se cierra de golpe, al volver a pulsar `N` (o `E` en ese acuerdo) se abre lo que estabas escribiendo.
- **Entre el editor y la libreta:** una edición ya guardada en el editor pero sin nota de versión sigue en su borrador hasta que la versión existe.
- **Campos de una línea:** lo tecleado en un avance, una revisión o una nota vuelve a aparecer, marcado como *recuperado*, la próxima vez que se abre esa misma pregunta.

Al arrancar, la app avisa si hay borradores pendientes, y el acuerdo con un borrador lo muestra en su resumen. Si al recuperar uno sales del editor sin guardar, la app pregunta si lo guardas en el acuerdo o lo descarta.

## La ficha del acuerdo y sus experiencias

Un acuerdo no es una tarea que se termina: es una decisión que se queda, y sobre ella se van acumulando **experiencias**. Cada una es una tecla y ENTER; la nota siempre es opcional.

| Tecla | Experiencia | Qué significa |
|---|---|---|
| `D` | **Aplicación** | Lo he puesto en práctica en una situación real |
| `P` | **Avance** | Noto que me cuesta menos que antes |
| `B` | **Obstáculo** | Algo lo dificultó o lo impidió |
| `I` | **Descubrimiento** | He comprendido algo sobre cómo actúo |
| `R` | **Revisión** | He reconsiderado la estrategia (un commit) |

Los obstáculos se registran sin disimularlos y sin restar nada: con `S` sobre uno, en la BITÁCORA, se añade después **cómo se reparó** (o qué se hará). Lo que no se apuntó a tiempo se apunta desde el CALENDARIO: dentro de él (ENTER), D/P/B/I van al día elegido.

En **02 ACUERDOS**, debajo de la lista, está la **ficha** del acuerdo elegido: su Popo, la conclusión actual (COMMITMENT, o el WHY si no hay), cuántas aplicaciones, avances, obstáculos y descubrimientos lleva **desde siempre**, y sus últimas experiencias. Las cifras son solo lo que se ha apuntado: la app no puntúa ni calcula porcentajes de cumplimiento.

Con `X` se cambia el **estado** con una sola tecla: **activo**, **integrado** (ya forma parte de su manera de actuar; sigue en la lista, con su historia) o **archivado**.

La portada (**01 OVERVIEW**) muestra los totales desde el principio (un compromiso no caduca) y los **últimos recuerdos** de todos los acuerdos.

## Popo

Hay un Popo por acuerdo: en su ficha y en la pestaña **06 POPARIUM**, donde andan a su aire. Popo **siempre está contento** de acompañar: lo que hace no reacciona al último registro (tres obstáculos seguidos no lo ponen triste, un logro no lo hace más orgulloso). Lo que cambia es su **barriguita**, que crece con las experiencias (3, 8, 15 y 25), y el **estirón** que pega cuando el acuerdo pasa a integrado. Los archivados duermen.

En kitty, el Popo de la ficha es el dibujo real, que la app ensancha o estira según crece; en otras terminales, su versión de bloques. Las animaciones solo se mueven mientras están en pantalla y apenas gastan CPU.

Necesita una terminal de 256 colores (tmux lo es) y unas 36×24 celdas por Popo; con menos espacio aparece una lista. Con más Popos de los que caben, `↑` `↓` pasan de página.

Los dibujos originales están en `assets/popo-src/`. Si cambian, se regenera `assets/popo.json` con:

```bash
nix shell nixpkgs#imagemagick nixpkgs#python3 -c python3 tools/popo_assets.py
```

## Filosofía

Una tarea dice qué hacer; el razonamiento guardado permite recuperar qué se había comprendido y por qué parecía importante. Por eso el **WHY** es el centro de cada acuerdo.

1. **Por qué:** su significado, para no perderlo cuando pase la emoción.
2. **Qué:** un compromiso concreto, formulado por la persona que lo utilizará.
3. **Próxima acción:** algo realmente realizable.
4. **Disparador:** cuándo o con qué señal visible consultarlo.
5. **Éxito:** una señal observable, no un juicio sobre la persona.
6. **Plan B:** qué hacer cuando aparezca un obstáculo.

La bitácora conserva **aciertos, avances, obstáculos y aprendizajes**. Una retrospectiva registra cómo cambiar el método. Los compromisos son **revisables**, no verdades absolutas.

### Recordar que existe

Un cuaderno no puede resolver por sí solo el problema de acordarse de abrirlo. Asociarlo a un disparador externo (alarma del móvil, inicio de una sesión tmux o después de una rutina ya consolidada) puede ayudar. La clave es que sea un hábito autónomo, no una obligación de otra persona recordárselo.

Por ejemplo, un atajo en `~/.tmux.conf` que abra popOS flotando encima de lo que se esté haciendo:

```tmux
bind-key K display-popup -E -w 80% -h 85% "popos"
```

Recarga con `tmux source-file ~/.tmux.conf` y abre la app con **Prefijo + K**. Para ver a Popo en la barra de estado de tmux (solo su cara, nunca títulos):

```tmux
set -g @popos-status "(^ᴗ^)"
set -ga status-right "#{@popos-status}"
run-shell -b "popos --tmux-status-push >/dev/null 2>&1 || true"
```

popOS escribe la opción `@popos-status` cada vez que cambian los borradores (con `✎` mientras quede alguno sin guardar), así que tmux no tiene que ejecutar nada cada pocos segundos. El `run-shell` la pone al día una vez al arrancar el servidor, por si quedaban borradores de antes. Si prefieres que tmux pregunte, `#(popos --tmux-status)` sigue funcionando.

## Datos y privacidad

La base de datos se guarda en:

```text
~/.local/share/popos/popos.db
```

(Cuando la app se llamaba keepstate, la libreta vivía en `~/.local/share/keepstate/keepstate.db`. La primera vez que se abre popOS, la carpeta entera se mueve a la nueva ruta y sus archivos pasan a llamarse `popos.*`, copias incluidas. Con `POPOS_DB` o `--db` se puede usar otra libreta.)

Se crea con permisos de archivo `0600`.

**Copias de seguridad:** cada día que se abre la app se guarda una copia (la copia en caliente de SQLite, consistente aunque la libreta esté abierta) en `~/.local/share/popos/popos.backups/`, solo legible por tu usuario. Se conservan las de las **últimas dos semanas** y **la primera de cada mes durante un año**. Para recuperar una, con la app cerrada, se copia encima de `popos.db`. Los datos **no se envían por red**. En ordenadores compartidos, la privacidad efectiva depende también de la cuenta de usuario y los permisos del directorio.

Exportar desde la app con `m` o desde la terminal:

```bash
popos --export
```

También puedes elegir otra base de datos con `--db /ruta/privada.db` o mediante la variable `POPOS_DB`.

## Cómo está hecho

Rust, con un binario pequeño que arranca en unos milisegundos: `rusqlite` (SQLite incluido), `crossterm` para el terminal y poco más. El código, en `src/`:

| Módulo | Qué contiene |
|---|---|
| `main.rs` | El comando `popos`: sus opciones y la sesión tmux propia |
| `store.rs` | La libreta: SQLite, sus migraciones y las copias diarias |
| `document.rs` | Un acuerdo como documento: título, nota y texto libre; los diffs entre versiones |
| `history.rs` | Versiones y revisiones como commits: hashes y el grafo |
| `vocabulary.rs` | Las palabras de la app: experiencias, estados, lo que dice Popo |
| `dates.rs` | Fechas en UTC, cómo se leen, la cuadrícula del mes |
| `popo.rs`, `kitty.rs` | Popo (dibujos, crecimiento, animación) y el protocolo gráfico de kitty |
| `tmux.rs` | La cara de Popo en la barra de estado y la pestaña cian |
| `drafts.rs`, `editor.rs` | Los borradores y el editor externo (nvim) |
| `pytext.rs`, `pyrandom.rs` | Lo que la app heredó de Python y conserva igual: cómo se parten las líneas, los diffs, el azar del prado |
| `ui/term.rs` | El terminal: una cuadrícula de celdas que solo envía lo que cambia |
| `ui/app.rs` | La app: estado, bucle principal y teclas |
| `ui/actions.rs`, `ui/reader.rs` | Lo que hacen las teclas, y la lectura de un acuerdo y su historial |
| `ui/draw.rs`, `ui/dialogs.rs`, `ui/layout.rs` | Colores, cajas, diálogos, tamaños y barras de teclas |
| `ui/views/` | Una vista por pestaña: barra lateral, acuerdos, calendario, bitácora, review, poparium |

Los dibujos de Popo están en `assets/popo-src/`; `tools/popo_assets.py` los convierte en `assets/popo.json`, que va dentro del binario. Los tests: `cargo test`. Los que comparan con Python (`textwrap`, `difflib`, `random`) se lanzan aparte: `python3 tests/python_cases.py > cases.json` y `POPOS_PYCASES=cases.json cargo test -- --ignored`.

La versión anterior, en Python, vive en el historial de git: la libreta es la misma y las dos la leen igual.

## Qué no es

No es una aplicación de terapia, evaluación clínica o vigilancia de pareja. Para que ayude de verdad, quien use la libreta debe **elegir participar, revisar sus acuerdos y ser dueño de los datos**. Si los problemas de memoria son generalizados y repercuten en la vida diaria, conviene valorarlos con un profesional además de usar herramientas externas.

**Idea de arranque:** empezar con un solo acuerdo sencillo y revisarlo una vez por semana. Mejor un método sostenible que un sistema perfecto que nadie abre.
