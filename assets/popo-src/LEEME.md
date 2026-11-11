# POPO.CACHE · Animaciones de Poparium

Siete animaciones reales de Popo, hechas a partir del sprite definitivo y listas para usar como recursos.

| Animación | Uso | Archivo |
|---|---|---|
| idle | Respiración, parpadeo | `popo-idle.gif` |
| hello | Saludo y brincos | `popo-hello.gif` |
| think | Pensar, dudas, explorar | `popo-think.gif` |
| coding | Trabajando en la terminal | `popo-coding.gif` |
| reading | Revisar acuerdos | `popo-reading.gif` |
| sleep | Dormir, reposo | `popo-sleep.gif` |
| comfort | Acompañar con cariño | `popo-comfort.gif` |

**GIF:** demo directo en navegador (fondo oscuro, 256×256); **APNG** `popo-*.png`: transparencia y animación a 64×64; **PNG strip:** fotogramas transparentes de 64×64, alineados horizontalmente. Las animaciones duran 2,4 segundos y se repiten sin fin. `animations.json` describe los estados y formatos.

## Animación real dentro de tmux

`tmux` no reproduce GIFs por sí mismo. Incluyo un reproductor ANSI de Popo (sin paquetes `pip`):

```bash
python3 popo_terminal.py idle
python3 popo_terminal.py hello
python3 popo_terminal.py coding
```

Pulsa `Ctrl+C` para salir. Requiere una terminal UTF-8 que admita ANSI truecolor, de al menos 40 columnas y 22 filas. Usa caracteres de medio bloque `▀` para pintar dos píxeles por fila, sin protocolos gráficos especiales. Para integrarlo en una TUI basada en `curses`, puede adaptarse el bucle de fotogramas, pero no se debe incrustar este reproductor directamente dentro de una sesión `curses` activa: el control de pantalla entraría en conflicto.

**Importante:** La versión 0.1 de Poparium tiene un Popo ASCII 9×9 distinto. Este pack es una propuesta visual para una futura integración de estas animaciones; no cambia la app existente. 

**Filosofía:** Popo se alegra de los progresos y acompaña las dificultades sin enfadarse ni mostrar decepción; no contabiliza rachas negativas.
