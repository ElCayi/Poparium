"""The sidebar (Popo, the name, NAV, SISTEMA) and its narrow tab row."""
import curses
import time
from popos import APP, TAGLINE, VERSION
from popos.kitty import KITTY_LOGO_IDS, kitty_placeholder_row
from popos.popo import logo_frame, wordmark_cells
from popos.ui.draw import box, put, style
from popos.ui.layout import SIDE_W, TABS


class SidebarView:
    def render_sidebar(self, scr, h, w):
        """The brand (Popo and the name, the one part with no panel), then two
        panels: the tabs, and where the data lives.

        Returns the first column of the main area.
        """
        width = SIDE_W - 1
        logo = self.popo and self.popo.get("logo")
        colors = curses.has_colors() and curses.COLORS >= 256
        wordmark = wordmark_cells()
        system_h, nav_min = 5, len(TABS) + 2
        # The biggest brand that still leaves room for the other two panels
        options = []
        if logo and colors:
            options.append((len(logo[0]) + 1 + len(wordmark) + 1, True, True))
        if colors:
            options.append((len(wordmark) + 1, False, True))
        options.append((2, False, False))
        inside, with_logo, with_mark = next(
            (o for o in options if o[0] + 2 + nav_min + system_h <= h - 1), options[-1])
        # Same inside as a panel, so everything lines up, but no border
        y, x, iw = 1, 3, width - 4
        self.logo_at = None
        if with_logo:
            self.logo_at = (y, x + (iw - len(logo[0][0])) // 2)
            self.draw_logo(scr)
            y += len(logo[0]) + 1
        if with_mark:
            cream = self.pair(230, -1)
            for row, cells in enumerate(wordmark):
                for col, (char, color) in enumerate(cells):
                    if char != " ":
                        put(scr, y + row, x + col, char, cream if color == "cream" else style(color, True))
            # The version sits in the empty space beside the p's tails
            put(scr, y + len(wordmark) - 1, x + iw - len(VERSION), VERSION, style("dim"))
            y += len(wordmark)
        else:
            put(scr, y, x, f"{APP} {VERSION}", style("a", True), iw)
            y += 1
        put(scr, y, x, TAGLINE, style("dim"), iw)
        # NAV is just as tall as its tabs (one blank row around them), its list
        # centred in it; the space it leaves sits above SISTEMA
        nav_top = inside + 2
        room = h - 1 - system_h - nav_top
        step = 2 if len(TABS) * 2 + 3 <= room else 1
        nav_h = min(room, (len(TABS) - 1) * step + 1 + 4)
        y, x, ih, iw = box(scr, nav_top, 1, nav_h, width, "NAV",
                           edge=None if self.inside else style("a", True))
        labels = [f"{i + 1:02}  {name}" for i, name in enumerate(TABS)]
        lx = x + max(0, (iw - 2 - max(len(t) for t in labels)) // 2)
        ly = y + max(0, (ih - (len(TABS) - 1) * step - 1) // 2)
        for i, text in enumerate(labels):
            chosen = self.tab == i
            put(scr, ly + i * step, lx, ("► " if chosen else "  ") + text,
                style("a", True) if chosen else style("dim"), iw - (lx - x))
        y, x, _, iw = box(scr, h - 1 - system_h, 1, system_h, width, "SISTEMA")
        put(scr, y, x, "offline / personal", style("good"), iw)
        put(scr, y + 1, x, "sqlite / sin nube", style("dim"), iw)
        put(scr, y + 2, x, "? ayuda   q salir", style("dim"), iw)
        return SIDE_W + 1

    def draw_logo(self, scr):
        """Popo's current frame: kitty's real image if it has it, half blocks otherwise."""
        top, x = self.logo_at
        index = logo_frame(int(time.monotonic() * 1000))[0]
        if self.kitty_logo:
            rows, cols = len(self.popo["logo"][0]), len(self.popo["logo"][0][0])
            attr = self.pair(KITTY_LOGO_IDS[index], -1)
            for row in range(rows):
                try:
                    scr.addstr(top + row, x, kitty_placeholder_row(row, cols), attr)
                except curses.error:
                    pass
            return
        frame = self.popo["logo"][index]
        for row, cells in enumerate(frame):
            for col, cell in enumerate(cells):
                put(scr, top + row, x + col, cell[0] if cell else " ",
                    self.pair(cell[1], cell[2]) if cell else 0)

    def render_tabbar(self, scr, w):
        """Compact layout: the sidebar becomes a single row of tabs."""
        names = [f"{i + 1} {name}" for i, name in enumerate(TABS)]
        if sum(len(n) + 2 for n in names) > w - 4:
            # Too narrow for every name: only the current tab keeps its own
            names = [n if i == self.tab else n.split()[0] for i, n in enumerate(names)]
        brand = f"{APP} {VERSION}  "
        x = 2
        if len(brand) + sum(len(n) + 2 for n in names) <= w - 4:
            put(scr, 0, x, brand, style("a", True))
            x += len(brand)
        for i, name in enumerate(names):
            chosen = self.tab == i
            put(scr, 0, x, f" {name} ", style("select") if chosen else style("dim"))
            x += len(name) + 3
