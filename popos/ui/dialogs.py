"""Small dialogs: a line of text, a one-key choice, a confirmation."""
import curses
from popos.history import short_hash
from popos.ui.draw import box, put, style


def ask(screen, heading, prompt, default="", required=False, drafts=None):
    """Return a single-line UTF-8 value; None means cancelled.

    With drafts, every keystroke is kept on disk and comes back the next
    time this same question is asked, until it's answered or cancelled.
    """
    name = "linea-" + short_hash(heading, prompt)
    recovered = drafts.recover(name, ".txt") if drafts else None
    value = list(recovered if recovered is not None else default)
    if recovered is not None:
        heading += " · recuperado"
    cursor = len(value)
    scroll = 0
    curses.curs_set(1)
    try:
        while True:
            h, w = screen.getmaxyx()
            if h < 12 or w < 45:
                curses.curs_set(0)
                return None
            bw = min(78, w - 4)
            bx = (w - bw) // 2
            by = max(3, (h - 9) // 2)
            screen.erase()
            for y in range(by, by + 9):
                put(screen, y, bx, " " * (bw - 1), style("main"), bw - 1)
            put(screen, by, bx, "╭" + "─" * (bw - 3) + "╮", style("a"))
            put(screen, by + 1, bx + 2, heading.upper(), style("a", True), bw - 4)
            put(screen, by + 2, bx + 2, prompt, style("main", True), bw - 4)
            put(screen, by + 4, bx + 2, "▸ " + "·" * (bw - 7), style("edge"), bw - 4)
            visible = bw - 9
            if cursor < scroll:
                scroll = cursor
            if cursor >= scroll + visible:
                scroll = cursor - visible + 1
            content = "".join(value[scroll:scroll + visible])
            put(screen, by + 4, bx + 4, content.ljust(visible), style("main"), visible)
            put(screen, by + 6, bx + 2, "ENTER guardar   ESC cancelar   CTRL+U limpiar", style("dim"), bw - 4)
            put(screen, by + 8, bx, "╰" + "─" * (bw - 3) + "╯", style("a"))
            try:
                screen.move(by + 4, bx + 4 + cursor - scroll)
            except curses.error:
                pass
            screen.refresh()
            key = screen.get_wch()
            if key in ("\n", "\r", curses.KEY_ENTER):
                output = "".join(value).strip()
                if output or not required:
                    if drafts:
                        drafts.discard(name, ".txt")
                    return output
                curses.beep()
            elif key in ("\x1b",):
                if drafts:
                    drafts.discard(name, ".txt")
                return None
            elif key in ("\x15",):
                value, cursor, scroll = [], 0, 0
            elif key in ("\x7f", "\b", curses.KEY_BACKSPACE):
                if cursor:
                    value.pop(cursor - 1)
                    cursor -= 1
            elif key == curses.KEY_DC:
                if cursor < len(value):
                    value.pop(cursor)
            elif key == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif key == curses.KEY_RIGHT:
                cursor = min(len(value), cursor + 1)
            elif key == curses.KEY_HOME:
                cursor = 0
            elif key == curses.KEY_END:
                cursor = len(value)
            elif isinstance(key, str) and key.isprintable() and len(value) < 450:
                value.insert(cursor, key)
                cursor += 1
            if drafts and key not in ("\n", "\r", curses.KEY_ENTER):
                drafts.write(name, "".join(value), ".txt")
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def choose(screen, heading, options):
    """A one-key choice in a box: returns the key pressed, or None for ESC."""
    h, w = screen.getmaxyx()
    bw = min(70, w - 4)
    bx, by = (w - bw) // 2, max(3, (h - 6) // 2)
    for row in range(by, by + 5):  # an opaque box over whatever is behind it
        put(screen, row, bx, " " * bw, style("main"), bw)
    y, x, _, iw = box(screen, by, bx, 5, bw, heading.upper())
    put(screen, y, x, " " * iw, style("main"), iw)
    put(screen, y + 1, x, options, style("main", True), iw)
    put(screen, y + 2, x, "una tecla · ESC cancelar", style("dim"), iw)
    screen.refresh()
    key = screen.get_wch()
    return None if key == "\x1b" else key


def confirm(screen, question):
    reply = ask(screen, "Confirmación", question + "  (escribe SI)")
    return reply is not None and reply.strip().lower() in ("si", "sí")
