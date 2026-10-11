"""BITÁCORA: every entry, newest first."""
from popos.dates import display_date
from popos.ui.draw import box, put, style
from popos.ui.layout import JOURNAL_LIMIT
from popos.vocabulary import EVENT_LABELS, LABEL_W


class JournalView:
    def render_journal(self, scr, top, bottom, left, width):
        """↑↓ choose an entry here (Supr deletes it), not a commitment."""
        y, x, ih, iw = box(scr, top, left, bottom - top + 1, width,
                           "BITÁCORA · Todo el recorrido · S repara un obstáculo · Supr borra",
                           edge=style("a", True) if self.inside else None)
        last = y + ih - 1
        items = self.store.entries(limit=JOURNAL_LIMIT)
        if not items:
            put(scr, y, x, "Aún no hay entradas. Desde inicio: D, P, B o I.", style("dim"), iw)
            return
        self.entry_selected = min(self.entry_selected, len(items) - 1)
        # Entries take up to 3 rows: start early enough for the cursor to be on screen
        start = max(0, self.entry_selected - max(1, ih // 3) + 1)
        for index, entry in enumerate(items[start:], start=start):
            if y > last:
                break
            chosen = index == self.entry_selected
            label, color = EVENT_LABELS.get(entry["kind"], ("LOG", "dim"))
            put(scr, y, x, display_date(entry["created_at"]),
                (style("select") if self.inside else style("main", True)) if chosen else style("dim"), 12)
            put(scr, y, x + 13, label, style(color, True), LABEL_W)
            put(scr, y, x + 13 + LABEL_W, entry["title"], style("main", chosen), max(1, iw - 13 - LABEL_W))
            y += 1
            if entry["note"] and y <= last:
                put(scr, y, x + 13, "↳ " + entry["note"], style("dim"), iw - 13)
                y += 1
            if entry["repair"] and y <= last:
                put(scr, y, x + 13, "✓ reparado: " + entry["repair"], style("good"), iw - 13)
                y += 1
            y += 1
