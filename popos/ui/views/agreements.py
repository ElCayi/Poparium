"""OVERVIEW and ACUERDOS: the list and a commitment's page."""
import curses
import datetime as dt
import os
import sys
import time
from popos.dates import MONTHS
from popos.document import glance
from popos.history import version_label
from popos.kitty import KITTY_LOGO_IDS, kitty_placeholder_row, kitty_upload
from popos.popo import BELLY, STRETCH, growth, logo_frame, popo_look, popo_png
from popos.ui.draw import box, draw_figures, fit_figures, put, style, wrap_lines
from popos.vocabulary import EVENT_LABELS, EXPERIENCES, LABEL_W, STATUS_NAMES


class AgreementsView:
    def list_commitments(self, scr, y, x, width, rows):
        """Up to `rows` commitments from y, scrolled so the selected one shows."""
        items = self.current_items()
        if not items:
            put(scr, y, x, "No hay acuerdos todavía. Pulsa N para crear uno.", style("dim"), width)
            return
        top = max(0, self.selected - rows + 1)
        for pos, item in enumerate(items[top:top + rows], start=top):
            chosen = pos == self.selected
            name = ("▸ " if chosen else "  ") + f"#{item['id']:03} " + item["title"]
            if item["status"] != "active":
                name += f"  [{STATUS_NAMES[item['status']]}]"
            attr = (style("select") if self.inside else style("main", True)) if chosen else style("main")
            put(scr, y + pos - top, x, name.ljust(width), attr, width)

    def render_ficha(self, scr, top, left, width, height):
        """The commitment's page, each part in its own panel: its Popo, its
        current conclusion, how many experiences it has gathered, and the latest
        ones. Everything else is a key away (the line at the bottom)."""
        item = self.current()
        if not item:
            return
        counts = self.store.experience_counts().get(item["id"], {})
        experiences = sum(counts.values())
        label = version_label(len(self.store.versions(item["id"])) - 1)
        title = f"#{item['id']:03} · {item['title']} · {label} · {STATUS_NAMES[item['status']].upper()}"
        if f"acuerdo-{item['id']}" in self.drafts.pending():
            title += " · ✎ borrador: E"
        y, x, ih, iw = box(scr, top, left, height, width, title, style("b", True))
        last = y + ih - 1
        room = ih - 2  # the last two rows: how to add an experience, and the other keys
        self.ficha_popo = None
        # POPO, on the left: him (wider as he grows, taller once integrated) and his words
        belly, integrated = growth(experiences), item["status"] == "integrated"
        cols = round(12 * BELLY[belly])
        words = popo_look(item, experiences)[1]
        column = max(cols, len(words))
        popo_h = 6 + integrated + 1 + 2
        with_popo = bool(self.popo and self.popo.get("logo")) and room >= popo_h and iw >= column + 30
        pw = column + 4 if with_popo else 0
        rx, rw = (x + pw + 1, iw - pw - 1) if with_popo else (x, iw)
        # CONCLUSIÓN ACTUAL and EXPERIENCIAS, on the right
        text, is_note = glance(item, 3, rw - 4)
        conclusion = wrap_lines(text or "Sin nota todavía · E para escribirla", rw - 4)[:3]
        number_rows = fit_figures([(counts.get("done", 0), "aplicaciones", "apl", "good"),
                                   (counts.get("progress", 0), "avances", "av", "good"),
                                   (counts.get("obstacle", 0), "obstáculos", "obs", "warm"),
                                   (counts.get("insight", 0) + counts.get("review", 0), "descubrimientos", "desc", "b")],
                                  rw - 4, gaps=(3, 2))
        conclusion_h, numbers_h = len(conclusion) + 2, len(number_rows) + 2
        top_h = max(popo_h if with_popo else 0, conclusion_h + numbers_h)
        numbers_h = top_h - conclusion_h  # the right column ends where POPO does
        if with_popo:
            py, px, _, _ = box(scr, y, x, top_h, pw, "POPO")
            self.ficha_popo = (py, px + (column - cols) // 2, belly, integrated, cols)
            self.draw_ficha_popo(scr)
            put(scr, py + 6 + integrated, px + (column - len(words)) // 2, words, style("dim"), column)
        cy, cx, _, cw = box(scr, y, rx, conclusion_h, rw, "NOTA" if is_note else "NOTA · aún sin nota, del texto:",
                            style("b", True))
        for i, line in enumerate(conclusion):
            put(scr, cy + i, cx, line, style("main", True) if is_note else style("dim"), cw)
        ny, nx0, _, _ = box(scr, y + conclusion_h, rx, numbers_h, rw, "EXPERIENCIAS", style("b", True))
        draw_figures(scr, ny, nx0, number_rows)
        # ÚLTIMAS EXPERIENCIAS, across the bottom
        if room - top_h >= 3:
            ly, lx, lh, lw = box(scr, y + top_h, x, room - top_h, iw, "ÚLTIMAS EXPERIENCIAS", style("b", True))
            recent = self.store.recent(limit=lh, commitment_id=item["id"])
            if not recent:
                hint = ("¿Ha pasado algo con este acuerdo? Pulsa + para añadir una experiencia "
                        "(o directamente D, P, B o I). La nota es opcional.")
                for i, line in enumerate(wrap_lines(hint, lw)[:lh]):
                    put(scr, ly + i, lx, line, style("dim"), lw)
            for i, e in enumerate(recent):
                name, color = EVENT_LABELS.get(e["kind"], ("", "dim"))
                when = dt.datetime.fromisoformat(e["created_at"]).astimezone()
                put(scr, ly + i, lx, f"{when.day:>2} {MONTHS[when.month - 1][:3]}", style("dim"), 7)
                put(scr, ly + i, lx + 7, name.capitalize(), style(color), LABEL_W)
                note = (e["note"] or "—") + ("  ✓ reparado" if e["repair"] else "")
                put(scr, ly + i, lx + 7 + LABEL_W, note, style("main"), max(1, lw - 7 - LABEL_W))
        # How to add an experience, always in sight; short names when narrow
        long_line = 12 + sum(4 + len(name) for _, _, name, _, _ in EXPERIENCES)
        ex = x
        put(scr, last - 1, ex, "+", style("a", True))
        put(scr, last - 1, ex + 2, "añadir ·", style("a"))
        ex += 12
        for key, _, name, _, color in EXPERIENCES:
            label = name.lower() if long_line <= iw else name[:4].lower()
            put(scr, last - 1, ex, key.upper(), style(color, True))
            put(scr, last - 1, ex + 2, label, style(color))
            ex += len(label) + 4
        put(scr, last, x, "ENTER leer · E editar · V versiones · R revisar · X estado", style("dim"), iw)

    def draw_ficha_popo(self, scr):
        """The ficha's Popo: kitty's real image (wider as he grows, taller when
        integrated) or half blocks stretched the same way."""
        y, x, belly, integrated, cols = self.ficha_popo
        index = logo_frame(int(time.monotonic() * 1000))[0]
        rows = 6 + integrated
        if self.kitty_logo and self.popo.get("logo_rgba"):
            high = 1 + belly + 5 * integrated
            if (belly, integrated) not in self.kitty_popos:
                data = "".join(kitty_upload((high << 24) | color,
                                            popo_png(self.popo["logo_rgba"], frame, BELLY[belly],
                                                     STRETCH if integrated else 1.0), cols, rows)
                               for frame, color in enumerate(KITTY_LOGO_IDS))
                os.write(sys.stdout.fileno(), data.encode("ascii"))
                self.kitty_popos.add((belly, integrated))
            attr = self.pair(KITTY_LOGO_IDS[index], -1)
            for row in range(rows):
                try:
                    scr.addstr(y + row, x, kitty_placeholder_row(row, cols, high), attr)
                except curses.error:
                    pass
            return
        frame = self.popo["logo"][index]
        width = len(frame[0])
        for row, cells in enumerate(frame):
            for col in range(cols):
                cell = cells[min(width - 1, col * width // cols)]
                put(scr, y + row, x + col, cell[0] if cell else " ", self.pair(cell[1], cell[2]) if cell else 0)

    def list_and_detail(self, scr, top, bottom, left, width, title, list_rows, note=None):
        """A panel listing the commitments and, if it fits, the SELECTED panel under it."""
        space = bottom - top + 1
        extra = 1 if note else 0
        list_h = min(space, list_rows + 2 + extra)
        y, x, ih, iw = box(scr, top, left, list_h, width, title, edge=style("a", True) if self.inside else None)
        if note:
            put(scr, y, x, note, style("dim"), iw)
        self.list_commitments(scr, y + extra, x, iw, max(1, ih - extra))
        if space - list_h >= 5:
            self.render_ficha(scr, top + list_h, left, width, space - list_h)

    def render_overview(self, scr, top, bottom, left, width):
        """Totals since the beginning (a commitment doesn't expire), the
        commitments, and the latest memories of all of them."""
        living = self.store.active()
        counts = self.store.experience_counts()
        experiences = sum(sum(c.values()) for c in counts.values())
        learned = sum(c.get("insight", 0) + c.get("review", 0) for c in counts.values())
        integrated = sum(1 for c in living if c["status"] == "integrated")
        figures = fit_figures([(len(living), "ACUERDOS", "ACU", "a"), (experiences, "EXPERIENCIAS", "EXP", "good"),
                               (learned, "DESCUBRIMIENTOS", "DESC", "b"), (integrated, "INTEGRADOS", "INT", "warm")],
                              width - 4)
        y, x, _, iw = box(scr, top, left, 4, width, "OVERVIEW · Memoria persistente entre sesiones 🐾")
        draw_figures(scr, y, x, figures[:2])
        if len(figures) == 1:  # a second row of figures takes the motto's place
            put(scr, y + 1, x, "Toda experiencia cuenta para aprender. ♡", style("dim"), iw)
        space = bottom - (top + 4) + 1
        rows = max(1, min(len(self.current_items()), 6))
        list_h = min(space, rows + 2)
        ly, lx, lh, lw = box(scr, top + 4, left, list_h, width, "FOCUS · Mis acuerdos",
                             edge=style("a", True) if self.inside else None)
        self.list_commitments(scr, ly, lx, lw, lh)
        if space - list_h < 3:
            return
        y, x, ih, iw = box(scr, top + 4 + list_h, left, space - list_h, width, "ÚLTIMOS RECUERDOS", style("b", True))
        recent = self.store.recent(limit=ih)
        if not recent:
            steps = ["Aún no hay recuerdos. Para añadir una experiencia:",
                     "1. ENTER y elige un acuerdo con ↑↓",
                     "2. pulsa + (o directamente D, P, B o I)",
                     "3. ENTER: la nota es opcional"]
            for i, line in enumerate(steps[:ih]):
                put(scr, y + i, x, line, style("dim") if i else style("main"), iw)
        for i, e in enumerate(recent):
            name, color = EVENT_LABELS.get(e["kind"], ("", "dim"))
            when = dt.datetime.fromisoformat(e["created_at"]).astimezone()
            put(scr, y + i, x, f"↳ {when.day:>2} {MONTHS[when.month - 1][:3]}", style("dim"), 9)
            put(scr, y + i, x + 10, name.capitalize(), style(color), LABEL_W)
            text = e["title"] + (f": {e['note']}" if e["note"] else "")
            put(scr, y + i, x + 10 + LABEL_W, text, style("main"), max(1, iw - 10 - LABEL_W))

    def render_agreements(self, scr, top, bottom, left, width):
        rows = max(1, min(len(self.current_items()), max(3, min(9, (bottom - top) // 3))))
        note = "A  /  " + ("Todos, incluso archivados" if self.archive else "Solo activos")
        self.list_and_detail(scr, top, bottom, left, width, "ACUERDOS · Contratos conmigo mismo · siempre revisables",
                             rows, note)
