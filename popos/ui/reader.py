"""Reading a commitment in full, and its history of versions."""
import curses
from popos import APP
from popos.dates import display_date
from popos.document import version_diff
from popos.history import version_hash, version_label
from popos.ui.draw import box, put, style, wrap_lines
from popos.vocabulary import STATUS_NAMES


class ReaderMixin:
    def pager(self, scr, title, build, hint, keys=()):
        """Full-screen reading view. build(width) -> [(text, attr)].

        Returns the key in `keys` that closed it, or None for ESC/q/←.
        """
        top = 0
        while True:
            h, w = scr.getmaxyx()
            scr.erase()
            y, x, body, iw = box(scr, 0, 1, h - 1, w - 2, title)
            lines = build(max(20, iw))
            body = max(1, body)
            top = max(0, min(top, len(lines) - body))
            for i, (text, attr) in enumerate(lines[top:top + body]):
                put(scr, y + i, x, text, attr, iw)
            where = f"  {top + 1}-{min(len(lines), top + body)}/{len(lines)}" if len(lines) > body else ""
            put(scr, h - 1, 1, hint + where, style("a"), w - 2)
            scr.refresh()
            key = scr.get_wch()
            if key in (curses.KEY_UP, "k"):
                top -= 1
            elif key in (curses.KEY_DOWN, "j"):
                top += 1
            elif key in (curses.KEY_PPAGE, "b"):
                top -= body - 1
            elif key in (curses.KEY_NPAGE, " "):
                top += body - 1
            elif key in (curses.KEY_HOME, "g"):
                top = 0
            elif key in (curses.KEY_END, "G"):
                top = len(lines)
            elif key in ("\x1b", "q", "Q", curses.KEY_LEFT):
                return None
            elif isinstance(key, str) and key.lower() in keys:
                return key.lower()

    def detail_lines(self, item, width):
        """Reading level: the title, the pinned note, and the free text, its
        headings set apart (a suggested one's question, after ·, dimmer)."""
        versions = self.store.versions(item["id"])
        status = STATUS_NAMES[item["status"]].capitalize()
        lines = [(f"◇ AGREEMENT #{item['id']:03} · {version_label(len(versions) - 1)} · {status}", style("dim")),
                 ("", 0), (item["title"], style("main", True)), ("", 0)]
        if item["pinned"]:
            for line in wrap_lines(item["pinned"], width - 2):
                lines.append(("▌ " + line, style("b", True)))
            lines.append(("", 0))
        if not item["body"]:
            lines.append(("Sin texto todavía · E para escribir (Ctrl+G sugiere secciones)", style("dim")))
            return lines
        for paragraph in item["body"].split("\n"):
            if not paragraph.strip():
                lines.append(("", 0))
            elif paragraph.startswith("#"):
                name, _, question = paragraph.lstrip("#").strip().partition(" · ")
                lines.append((name.upper() if paragraph.startswith("## ") else name, style("a", True)))
                if question:
                    lines += [(line, style("dim")) for line in wrap_lines(question, width)]
            elif paragraph.lstrip().startswith(">"):
                lines += [(line, style("dim")) for line in wrap_lines(paragraph, width)]
            else:
                lines += [(line, style("main")) for line in wrap_lines(paragraph, width)]
        return lines

    def history_lines(self, item, width):
        """Each version, newest first, with what it changed from the one before."""
        versions = self.store.versions(item["id"])
        lines = []
        for index in range(len(versions) - 1, -1, -1):
            v = versions[index]
            lines.append((f"{version_label(index)} · {v['note']}", style("good", True)))
            lines.append((f"{version_hash(v)} · {display_date(v['created_at'])}", style("dim")))
            if index:
                diff = version_diff(versions[index - 1]["snapshot"], v["snapshot"])
            else:
                diff = ["## NOTA"] + ["  " + line for line in (v["snapshot"].get("pinned") or "—").splitlines()]
            for line in diff:
                attr = (style("b", True) if line.startswith("## ") else style("good") if line.startswith("+")
                        else style("warm") if line.startswith("-") else style("dim"))
                lines += [(part, attr) for part in wrap_lines(line, width)]
            lines.append(("", 0))
        return lines

    def open_detail(self, scr):
        while self.current():
            item = self.current()
            key = self.pager(scr, f"◇ {APP} / {item['title']}", lambda width: self.detail_lines(item, width),
                             "↑↓ leer  E editar en el editor  V versiones  ESC volver", ("e", "v"))
            if key == "e":
                self.edit(scr)
            elif key == "v":
                self.open_history(scr)
            else:
                return

    def open_history(self, scr):
        item = self.current()
        if not item:
            self.message = "Primero selecciona un acuerdo."
            return
        self.pager(scr, f"◇ AGREEMENT HISTORY / {item['title']}", lambda width: self.history_lines(item, width),
                   "↑↓ leer  ESC volver   + añadido  - quitado")
