"""What the keys do to the notebook: write, log, repair, change, delete."""
import datetime as dt
from popos.dates import MONTHS
from popos.document import TEXT_FIELDS, from_markdown, to_markdown
from popos.editor import edit_in_editor, find_editor
from popos.history import version_label
from popos.ui.dialogs import ask, choose, confirm
from popos.ui.draw import box, put, style
from popos.ui.layout import FIELDS, JOURNAL_LIMIT, TABS
from popos.vocabulary import EXPERIENCES, LOG_PROMPTS, POPO_SAYS


class ActionsMixin:
    def ask(self, scr, heading, prompt, default="", required=False):
        return ask(scr, heading, prompt, default, required, drafts=self.drafts)

    def describe_drafts(self):
        names = []
        titles = {c["id"]: c["title"] for c in self.store.all_commitments()}
        for name in self.drafts.pending():
            if name == "nuevo":
                names.append("un acuerdo nuevo (N)")
            elif name.startswith("acuerdo-") and name[8:].isdigit() and int(name[8:]) in titles:
                names.append(f"«{titles[int(name[8:])]}» (E)")
        return ", ".join(names)

    def write_document(self, scr, name, initial):
        """Edit a document as the draft `name`; returns the text to save, or None.

        The draft stays on disk until the caller has saved it and calls
        self.drafts.discard(name).
        """
        recovered = self.drafts.recover(name)
        path = self.drafts.write(name, recovered if recovered is not None else initial)
        saved = edit_in_editor(scr, path, self.drafts.autosave_path(name))
        # The editor came back on its own: its autosave isn't needed any more
        self.drafts.drop_autosave(name)
        text = path.read_text(encoding="utf-8")
        if saved:
            return text
        if recovered is not None and confirm(scr, "Era un borrador recuperado. ¿Lo guardo en el acuerdo?"):
            return text
        self.drafts.discard(name)
        return None

    def new(self, scr):
        if not find_editor():
            return self.new_by_lines(scr)
        text = self.write_document(scr, "nuevo", to_markdown({}))
        if text is None:
            self.message = "Creación cancelada: no se guardó nada."
            return
        fields = from_markdown(text)
        if not fields["title"]:
            # Never throw away what was written just for a missing title
            fields["title"] = self.ask(scr, "Nuevo acuerdo", "Falta el título (la sección TITLE)", required=True) or "Sin título"
        self.store.create(**fields)
        self.drafts.discard("nuevo")
        self.selected = 0
        self.tab = 1
        self.message = "Acuerdo creado · v1.0. ENTER para leerlo entero."

    def new_by_lines(self, scr):
        data = {}
        for key, title, required in FIELDS:
            entry = self.ask(scr, "Nuevo acuerdo · " + str(len(data) + 1) + f"/{len(FIELDS)}", title, required=required)
            if entry is None:
                self.message = "Creación cancelada: no se guardó nada."
                return
            data[key] = entry
        self.store.create(**data)
        self.selected = 0
        self.tab = 1
        self.message = "Acuerdo creado. Sin editor instalado, las secciones largas no están disponibles."

    def edit(self, scr):
        item = self.current()
        if not item:
            self.message = "Primero crea un acuerdo con N."
            return
        name = f"acuerdo-{item['id']}"
        if find_editor():
            text = self.write_document(scr, name, to_markdown(dict(item)))
            if text is None:
                self.message = "Edición cancelada: no se guardaron cambios."
                return
            fields = from_markdown(text)
            fields["title"] = fields["title"] or item["title"]
        else:
            fields = {}
            for key, title, required in FIELDS:
                entry = self.ask(scr, "Editar acuerdo #" + str(item["id"]), title, default=item[key], required=required)
                if entry is None:
                    self.message = "Edición cancelada: no se guardaron cambios."
                    return
                fields[key] = entry
        if all(fields.get(k, item[k]) == item[k] for k in TEXT_FIELDS):
            self.drafts.discard(name)
            self.message = "Sin cambios: el acuerdo sigue igual."
            return
        next_label = version_label(len(self.store.versions(item["id"])))
        # ESC here still keeps the edit: the note is optional, the text is not.
        # Until revise() returns, the edit only lives in the draft
        note = self.ask(scr, f"Versión nueva · {next_label}", "¿Qué cambió y por qué?") or "Actualizado"
        label = self.store.revise(item["id"], fields, note)
        self.drafts.discard(name)
        self.message = f"{label} · {note}"

    def log(self, scr, kind):
        item = self.current()
        if not item:
            self.message = "Elige un acuerdo antes de registrar una experiencia."
            return
        # Inside the calendar, what's logged goes to the chosen day: the way to
        # add what was not noted at the time
        when, on = None, ""
        if self.tab == TABS.index("CALENDARIO") and self.cal_focus and self.cal_day != dt.date.today():
            noon = dt.datetime.combine(self.cal_day, dt.time(12)).astimezone()
            when = noon.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
            on = f" · apuntado el {self.cal_day.day} de {MONTHS[self.cal_day.month - 1]}"
        note = self.ask(scr, f"{item['title']}{on}", LOG_PROMPTS[kind])
        if note is None:
            self.message = "Registro cancelado."
            return
        self.store.log(item["id"], kind, note, when)
        self.message = POPO_SAYS[kind] + on

    def choose_experience(self, scr):
        """+ or Space: the four kinds of experience, explained, one key to pick."""
        item = self.current()
        if not item:
            self.message = "Aún no hay acuerdos: pulsa N para crear el primero."
            return
        h, w = scr.getmaxyx()
        bw = min(64, w - 4)
        bx, by = (w - bw) // 2, max(2, (h - 8) // 2)
        for row in range(by, by + 8):  # opaque over what is behind
            put(scr, row, bx, " " * bw, style("main"), bw)
        y, x, _, iw = box(scr, by, bx, 8, bw, f"AÑADIR EXPERIENCIA · {item['title']}", style("a", True))
        for i, (key, _, name, meaning, color) in enumerate(EXPERIENCES):
            put(scr, y + i, x, key.upper(), style(color, True))
            put(scr, y + i, x + 3, name, style(color, True), iw - 3)
            put(scr, y + i, x + 20, meaning, style("main"), iw - 20)
        put(scr, y + 5, x, "una tecla · luego ENTER (la nota es opcional) · ESC cancelar", style("dim"), iw)
        scr.refresh()
        key = scr.get_wch()
        kind = next((kind for k, kind, *_ in EXPERIENCES if isinstance(key, str) and key.lower() == k), None)
        if kind:
            self.log(scr, kind)

    def add_repair(self, scr):
        """S on an obstacle in BITÁCORA: how it was put right (or what will be done)."""
        entries = self.store.entries(limit=JOURNAL_LIMIT)
        if self.tab != TABS.index("BITÁCORA") or not entries:
            self.message = "S añade una reparación a un obstáculo: elígelo en BITÁCORA."
            return
        entry = entries[min(self.entry_selected, len(entries) - 1)]
        if entry["kind"] != "obstacle":
            self.message = "S es para obstáculos: este registro no lo es."
            return
        text = self.ask(scr, f"Reparación · {entry['title']}", "¿Cómo lo reparé, o qué haré? (vacío lo quita)",
                        default=entry["repair"])
        if text is None:
            return
        self.store.repair(entry["id"], text)
        self.message = "Popo: «Reparar también es avanzar.»" if text else "Reparación quitada."

    def review(self, scr):
        item = self.current()
        if not item:
            self.message = "Primero selecciona un acuerdo."
            return
        learned = self.ask(scr, "Retrospectiva", "¿Qué aprendí del experimento?", required=True)
        if learned is None:
            return
        adjustment = self.ask(scr, "Retrospectiva", "¿Qué voy a cambiar para la próxima vez?")
        if adjustment is None:
            return
        commit = self.store.review(item["id"], learned, adjustment)
        self.tab = TABS.index("REVIEW")
        self.message = f"commit {commit} · {learned}"

    def change_status(self, scr):
        """X: active, integrated or archived, with one key. Nothing is lost either way."""
        item = self.current()
        if not item:
            return
        options = [("1", "active", "activo"), ("2", "integrated", "integrado"), ("3", "archived", "archivado")]
        key = choose(scr, f"Estado · {item['title']}", "  ".join(f"{k} {name}" for k, _, name in options))
        status = next((value for k, value, _ in options if key == k), None)
        if not status or status == item["status"]:
            return
        self.store.update(item["id"], status=status)
        self.message = {"active": "Activo de nuevo.",
                        "integrated": "¡Integrado! Ya forma parte de ti. Popo pega un estirón 🐾",
                        "archived": "Archivado: guardado con toda su historia (A para verlo)."}[status]

    def delete(self, scr):
        """Supr: the selected entry in BITÁCORA, the selected commitment in OVERVIEW/ACUERDOS."""
        if self.tab == TABS.index("BITÁCORA"):
            entries = self.store.entries(limit=JOURNAL_LIMIT)
            if not entries:
                self.message = "No hay entradas que borrar."
                return
            self.entry_selected = min(self.entry_selected, len(entries) - 1)
            self.undo = (self.store.delete_entry(entries[self.entry_selected]["id"]), "La entrada")
            self.entry_selected = max(0, min(self.entry_selected, len(entries) - 2))
            self.message = "Entrada borrada. U para deshacer."
        elif self.tab in (TABS.index("OVERVIEW"), TABS.index("ACUERDOS")):
            item = self.current()
            if not item:
                self.message = "No hay acuerdos que borrar."
                return
            title = item["title"] if len(item["title"]) <= 28 else item["title"][:27] + "…"
            if not confirm(scr, f"¿Borrar «{title}» y todo su historial?"):
                self.message = "No se ha borrado nada."
                return
            self.undo = (self.store.delete_commitment(item["id"]), f"«{item['title']}»")
            self.selected = 0
            self.message = "Acuerdo borrado. U para deshacer mientras no cierres la app; X archiva sin borrar."
        else:
            self.message = "Supr borra entradas en BITÁCORA (3) y acuerdos en OVERVIEW o ACUERDOS (1-2)."

    def undo_delete(self):
        if not self.undo:
            self.message = "No hay nada que deshacer."
            return
        removed, what = self.undo
        self.store.restore(removed)
        self.undo = None
        self.message = f"{what} ha vuelto."
