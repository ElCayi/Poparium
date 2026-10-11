"""The app: its state, the main loop and the keys; the drawing lives in the views."""
import curses
import datetime as dt
import os
import sys
import time
from popos import APP, VERSION
from popos.drafts import Drafts
from popos.kitty import KITTY_LOGO_IDS, farm_image_id, kitty_escape, kitty_graphics, kitty_upload
from popos.popo import load_popo, logo_frame, popo_png
from popos.tmux import tmux_tab
from popos.ui.draw import box, put, setup_colors, style
from popos.ui.layout import CALENDAR_INSIDE_HINTS, JOURNAL_LIMIT, KEY_HINTS, MAX_W, MENU_HINTS, MIN_H, MIN_W, SIDEBAR_W, TABS
from popos.ui.actions import ActionsMixin
from popos.ui.reader import ReaderMixin
from popos.ui.views.sidebar import SidebarView
from popos.ui.views.agreements import AgreementsView
from popos.ui.views.calendar import CalendarView
from popos.ui.views.journal import JournalView
from popos.ui.views.review import ReviewView
from popos.ui.views.poparium import PopariumView


class App(ActionsMixin, ReaderMixin, SidebarView, AgreementsView, CalendarView, JournalView, ReviewView, PopariumView):
    """popOS in curses. Each tab draws itself from its view (ui/views);
    what the keys do lives in ActionsMixin, reading in ReaderMixin."""

    def __init__(self, store):
        self.store = store
        self.tab = 0
        self.selected = 0
        self.message = "Datos locales y privados. Nadie supervisa tus avances."
        self.archive = False
        self.drafts = Drafts(store.path.with_name(store.path.stem + ".drafts"))
        waiting = self.describe_drafts()
        if waiting:
            self.message = "✎ Borradores sin guardar: " + waiting + ". Se recuperan al abrirlos otra vez."
        self.popo = load_popo()
        self.logo_at = None  # (row, col) of the sidebar Popo while it's on screen
        self.kitty_logo = False  # True once the logo PNGs are in kitty: draw placeholders, not blocks
        self.entry_selected = 0  # cursor in the BITÁCORA tab
        self.cal_day = dt.date.today()  # the day chosen in the CALENDARIO tab
        # Where the arrows go: the menu (NAV, ↑↓ change tab) or, after ENTER, the
        # tab's content (↑↓ choose in it; in the calendar the arrows move the days). ESC: back
        self.inside = False
        self.kitty_popos = set()  # (belly, integrated) sizes of the ficha Popo already sent to kitty
        self.kitty_farm = set()  # (belly, integrated) sizes of the meadow's Popos already sent
        self.herd = {}  # commitment id -> where its Popo is in the meadow and what it's doing
        self.herd_clock = time.monotonic()
        self.ficha_popo = None  # where the ficha's Popo is drawn, for the animation between keys
        self.undo = None  # (removed rows, what they were) of the last delete, until the app closes
        self.pairs = {}  # (fg, bg) -> curses pair id, handed out from 9 on

    def pair(self, fg, bg):
        """Color pair for a sprite cell; the plain text color once pairs run out."""
        key = (fg, bg)
        if key not in self.pairs:
            ident = 9 + len(self.pairs)
            # Attributes only hold 8 bits of pair number
            if ident > min(255, curses.COLOR_PAIRS - 1):
                return style("main")
            try:
                curses.init_pair(ident, fg, bg)
            except curses.error:
                return style("main")
            self.pairs[key] = ident
        return curses.color_pair(self.pairs[key])

    @property
    def cal_focus(self):
        return self.inside and self.tab == TABS.index("CALENDARIO")

    def current(self):
        items = self.store.all_commitments() if self.archive else self.store.active()
        if items:
            self.selected = max(0, min(self.selected, len(items) - 1))
            return items[self.selected]
        self.selected = 0
        return None

    def current_items(self):
        return self.store.all_commitments() if self.archive else self.store.active()

    def frame(self, screen):
        """The window the app draws in: the whole screen up to MAX_W columns,
        centred beyond that. It shares the screen's memory (derwin)."""
        h, w = screen.getmaxyx()
        if getattr(self, "_frame_for", None) != (h, w):
            fw = min(w, MAX_W)
            self._frame = screen.derwin(h, fw, 0, (w - fw) // 2)
            self._frame.keypad(True)
            self._frame_for = (h, w)
        return self._frame

    def draw(self, screen):
        screen.erase()
        scr = self.win = self.frame(screen)
        h, w = scr.getmaxyx()
        if h < MIN_H or w < MIN_W:
            put(scr, 2, 2, f"Ventana pequeña: mínimo {MIN_W}x{MIN_H}", style("warm", True))
            put(scr, 4, 2, f"Ahora: {w}x{h} · agranda el panel", style("dim"))
            put(scr, 6, 2, "q para salir", style("main"))
            screen.refresh()
            return
        self.logo_at = self.ficha_popo = None
        if w >= SIDEBAR_W:
            left, top = self.render_sidebar(scr, h, w), 0
        else:
            self.render_tabbar(scr, w)
            left, top = 1, 1
        width = w - 1 - left
        # Rows top..h-5 for the tab's panels, h-4..h-2 for the status panel, h-1 for the keys
        render = (self.render_overview, self.render_agreements, self.render_calendar, self.render_journal,
                  self.render_review, self.render_farm)[self.tab]
        render(scr, top, h - 5, left, width)
        y, x, _, iw = box(scr, h - 4, left, 3, width)
        put(scr, y, x, self.message, style("dim"), iw)
        hints = CALENDAR_INSIDE_HINTS if self.cal_focus else KEY_HINTS if self.inside else MENU_HINTS
        hint = next((k for k in hints if len(k) <= w - 3), hints[-1])
        put(scr, h - 1, 1, hint, style("a"), w - 2)
        screen.refresh()

    def help(self, scr):
        h, w = scr.getmaxyx()
        lines = [
            f"{APP} {VERSION}  /  MAPA DE TECLAS", "",
            "↑↓     En el menú: cambiar de pestaña (también ←→, TAB o 1-6)",
            "ENTER  Entrar en la pestaña: ↑↓ eligen dentro · ESC vuelve al menú",
            "       Dentro de una lista, ENTER abre el acuerdo entero",
            "N      Nuevo acuerdo, en tu editor", "E      Editar: cada cambio es una versión nueva",
            "V      Versiones: qué cambió y por qué",
            "+      Añadir una experiencia: elige el tipo (también Espacio)",
            "D      Aplicación: lo he puesto en práctica", "P      Avance: me cuesta menos que antes",
            "B      Obstáculo: algo lo dificultó (S en BITÁCORA: cómo lo reparé)",
            "I      Descubrimiento: algo que he comprendido", "R      Revisar la estrategia (un commit)",
            "       (dentro del CALENDARIO, D/P/B/I apuntan en el día elegido)",
            "X      Estado: activo, integrado o archivado", "A      Ver archivados",
            "Supr   Borrar la entrada (BITÁCORA) o el acuerdo seleccionado",
            "U      Deshacer el último borrado",
            "M      Exportar una copia Markdown", "Q      Salir", "",
            "3      CALENDARIO: dentro, ←→↑↓ día, [ ] mes, T hoy",
            "6      POPARIUM: los Popos de tus acuerdos, a su aire", "",
            "Tu herramienta. Tu ritmo. Los acuerdos pueden revisarse.",
            "No es un sistema para que otra persona te supervise.", "",
            "Pulsa cualquier tecla para volver..."
        ]
        scr.erase()
        width = min(76, w - 2)
        height = min(len(lines) + 1, h)
        y, x, _, iw = box(scr, max(0, (h - height) // 2), (w - width) // 2, height, width, lines[0])
        for i, line in enumerate(lines[2:]):
            put(scr, y + i, x, line, style("main"), iw)
        scr.refresh()
        scr.get_wch()

    def send_logo_to_kitty(self):
        rgba = self.popo and self.popo.get("logo_rgba")
        if not rgba or not curses.has_colors() or curses.COLORS < 256 or not kitty_graphics():
            return
        rows, cols = len(self.popo["logo"][0]), len(self.popo["logo"][0][0])
        data = "".join(kitty_upload(image_id, popo_png(rgba, frame), cols, rows)
                       for frame, image_id in enumerate(KITTY_LOGO_IDS))
        os.write(sys.stdout.fileno(), data.encode("ascii"))
        self.kitty_logo = True

    def forget_logo_in_kitty(self):
        if self.kitty_logo:
            ids = list(KITTY_LOGO_IDS) + [((1 + belly + 5 * integrated) << 24) | color
                                          for belly, integrated in self.kitty_popos for color in KITTY_LOGO_IDS]
            ids += [farm_image_id(belly, integrated, frame)
                    for belly, integrated in self.kitty_farm for frame in range(len(KITTY_LOGO_IDS))]
            data = "".join(kitty_escape(f"a=d,d=I,i={i},q=2") for i in ids)
            os.write(sys.stdout.fileno(), data.encode("ascii"))
            self.kitty_logo = False

    def run(self, scr):
        curses.curs_set(0)
        scr.keypad(True)
        setup_colors()
        self.send_logo_to_kitty()
        tmux_tab(True)
        try:
            self.main_loop(scr)
        finally:
            tmux_tab(False)
            self.forget_logo_in_kitty()

    def main_loop(self, scr):
        while True:
            self.draw(scr)
            farm = self.tab == TABS.index("POPARIUM") and self.popo
            key = None
            while key is None:
                # Sleep until the next frame is due, or until a key: the farm
                # redraws everything, the sidebar Popo only redraws himself
                waits = [self.popo["ms"]] if farm else []
                if self.logo_at or self.ficha_popo:
                    waits.append(logo_frame(int(time.monotonic() * 1000))[1] + 5)
                scr.timeout(min(waits) if waits else -1)
                try:
                    key = scr.get_wch()
                except curses.error:
                    if farm:
                        break
                    if self.logo_at:
                        self.draw_logo(self.win)
                    if self.ficha_popo:
                        self.draw_ficha_popo(self.win)
                    # The frame window, not the screen: what is drawn through a
                    # derwin doesn't mark the screen's lines as changed
                    self.win.refresh()
                finally:
                    scr.timeout(-1)
            if key is None:
                continue  # next farm frame
            if key in ("q", "Q"):
                break
            enter = key in ("\n", "\r", curses.KEY_ENTER)
            vertical = key in (curses.KEY_UP, "k", "K", curses.KEY_DOWN, "j", "J")
            up = key in (curses.KEY_UP, "k", "K")
            if self.inside and key == "\x1b":
                self.inside = False  # back to the menu
            elif not self.inside and enter:
                self.inside = True  # into the tab's content
            elif not self.inside and vertical:
                self.tab = max(0, min(len(TABS) - 1, self.tab + (-1 if up else 1)))
            elif self.cal_focus and (vertical or key in (curses.KEY_LEFT, curses.KEY_RIGHT, "h", "l")):
                step = {curses.KEY_LEFT: -1, "h": -1, curses.KEY_RIGHT: 1, "l": 1,
                        curses.KEY_UP: -7, "k": -7, "K": -7, curses.KEY_DOWN: 7, "j": 7, "J": 7}[key]
                self.move_day(days=step)
            elif self.cal_focus and key in ("[", "]", curses.KEY_PPAGE, curses.KEY_NPAGE):
                self.move_day(months=-1 if key in ("[", curses.KEY_PPAGE) else 1)
            elif self.cal_focus and key in ("t", "T"):
                self.cal_day = dt.date.today()
            elif self.cal_focus and enter:
                self.inside = False
            elif isinstance(key, str) and key.isdigit() and 1 <= int(key) <= len(TABS):
                self.tab, self.inside = int(key) - 1, False
            elif key in (curses.KEY_RIGHT, "\t", "l", "L"):
                self.tab, self.inside = (self.tab + 1) % len(TABS), False
            elif key in (curses.KEY_LEFT, curses.KEY_BTAB, "h", "H"):
                self.tab, self.inside = (self.tab - 1) % len(TABS), False
            elif vertical and self.tab == TABS.index("BITÁCORA"):
                count = len(self.store.entries(limit=JOURNAL_LIMIT))
                self.entry_selected = max(0, min(count - 1, self.entry_selected + (-1 if up else 1)))
            elif vertical:
                items = self.current_items()
                if not items:
                    self.message = "Aún no hay acuerdos: pulsa N para crear el primero."
                elif up:
                    self.selected = max(0, self.selected - 1)
                else:
                    self.selected = min(len(items) - 1, self.selected + 1)
            elif enter and self.tab == TABS.index("BITÁCORA"):
                self.message = "En la bitácora: S repara un obstáculo, Supr borra · ESC vuelve al menú."
            elif enter:
                if self.current():
                    self.open_detail(self.win)
                else:
                    self.message = "Aún no hay acuerdos: pulsa N para crear el primero."
            elif key == curses.KEY_DC:
                self.delete(self.win)
            elif key in ("u", "U"):
                self.undo_delete()
            elif key in ("v", "V"):
                self.open_history(self.win)
            elif key in ("n", "N"):
                self.new(self.win)
            elif key in ("e", "E"):
                self.edit(self.win)
            elif key in ("+", " "):
                self.choose_experience(self.win)
            elif key in ("d", "D"):
                self.log(self.win, "done")
            elif key in ("p", "P"):
                self.log(self.win, "progress")
            elif key in ("b", "B"):
                self.log(self.win, "obstacle")
            elif key in ("i", "I"):
                self.log(self.win, "insight")
            elif key in ("r", "R"):
                self.review(self.win)
            elif key in ("x", "X"):
                self.change_status(self.win)
            elif key in ("s", "S"):
                self.add_repair(self.win)
            elif key in ("a", "A"):
                self.archive = not self.archive
                self.selected = 0
                self.message = "Mostrando todos los acuerdos." if self.archive else "Mostrando acuerdos activos."
            elif key in ("m", "M"):
                out = self.store.export()
                self.message = "Markdown guardado: " + str(out)
            elif key == "?":
                self.help(self.win)
