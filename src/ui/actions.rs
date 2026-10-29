//! What the keys do to the notebook: write, log, repair, change, delete.
use super::app::App;
use super::dialogs::{ask, choose, confirm};
use super::layout::*;
use super::term::Key;
use crate::dates::{MONTHS, local_noon_utc, today};
use crate::document::{Doc, from_markdown, to_markdown};
use crate::editor::{edit_in_editor, find_editor};
use crate::history::version_label;
use crate::pytext::{len, take};
use crate::vocabulary::{EXPERIENCES, log_prompt, popo_says};
use chrono::Datelike;

impl App {
    /// A line of text, its keystrokes kept as a draft until it is answered.
    pub fn ask(&mut self, heading: &str, prompt: &str, default: &str, required: bool) -> Option<String> {
        ask(&mut self.term, self.win, heading, prompt, default, required, Some(&self.drafts))
    }

    pub fn confirm(&mut self, question: &str) -> bool {
        confirm(&mut self.term, self.win, question)
    }

    pub fn describe_drafts(&self) -> String {
        let titles: std::collections::HashMap<i64, String> =
            self.store.all_commitments().unwrap_or_default().into_iter().map(|c| (c.id, c.title)).collect();
        let mut names = Vec::new();
        for name in self.drafts.pending() {
            if name == "nuevo" {
                names.push("un acuerdo nuevo (N)".to_string());
            } else if let Some(title) = name
                .strip_prefix("acuerdo-")
                .filter(|n| !n.is_empty() && n.chars().all(|c| c.is_ascii_digit()))
                .and_then(|n| n.parse::<i64>().ok())
                .and_then(|n| titles.get(&n))
            {
                names.push(format!("«{title}» (E)"));
            }
        }
        names.join(", ")
    }

    /// Edit a document as the draft `name`; returns the text to save, or None.
    ///
    /// The draft stays on disk until the caller has saved it and calls
    /// self.drafts.discard(name).
    fn write_document(&mut self, name: &str, initial: &str) -> Option<String> {
        let recovered = self.drafts.recover(name, ".md");
        let path = self.drafts.write(name, recovered.as_deref().unwrap_or(initial), ".md");
        let autosave = self.drafts.autosave_path(name);
        let saved = edit_in_editor(&mut self.term, &path, Some(&autosave));
        // The editor came back on its own: its autosave isn't needed any more
        self.drafts.drop_autosave(name);
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        if saved {
            return Some(text);
        }
        if recovered.is_some() && self.confirm("Era un borrador recuperado. ¿Lo guardo en el acuerdo?") {
            return Some(text);
        }
        self.drafts.discard(name, ".md");
        None
    }

    pub fn new_commitment(&mut self) {
        if find_editor().is_none() {
            return self.new_by_lines();
        }
        let Some(text) = self.write_document("nuevo", &to_markdown(&Doc::default())) else {
            self.message = "Creación cancelada: no se guardó nada.".into();
            return;
        };
        let mut fields = from_markdown(&text);
        if fields.title.is_empty() {
            // Never throw away what was written just for a missing title
            fields.title = self
                .ask("Nuevo acuerdo", "Falta el título (la sección TITLE)", "", true)
                .filter(|t| !t.is_empty())
                .unwrap_or_else(|| "Sin título".into());
        }
        if let Err(error) = self.store.create(&fields) {
            self.message = format!("No se pudo guardar: {error}. El borrador sigue a salvo.");
            return;
        }
        self.drafts.discard("nuevo", ".md");
        self.selected = 0;
        self.tab = 1;
        self.message = "Acuerdo creado · v1.0. ENTER para leerlo entero.".into();
    }

    fn new_by_lines(&mut self) {
        let mut values = Vec::new();
        for (_, title, required) in FIELDS {
            let heading = format!("Nuevo acuerdo · {}/{}", values.len() + 1, FIELDS.len());
            let Some(entry) = self.ask(&heading, title, "", required) else {
                self.message = "Creación cancelada: no se guardó nada.".into();
                return;
            };
            values.push(entry);
        }
        let _ = self.store.create(&Doc { title: values[0].clone(), pinned: values[1].clone(), body: values[2].clone() });
        self.selected = 0;
        self.tab = 1;
        self.message = "Acuerdo creado. Sin editor instalado, las secciones largas no están disponibles.".into();
    }

    pub fn edit(&mut self) {
        let Some(item) = self.current() else {
            self.message = "Primero crea un acuerdo con N.".into();
            return;
        };
        let name = format!("acuerdo-{}", item.id);
        let fields = if find_editor().is_some() {
            let Some(text) = self.write_document(&name, &to_markdown(&item.doc())) else {
                self.message = "Edición cancelada: no se guardaron cambios.".into();
                return;
            };
            let mut fields = from_markdown(&text);
            if fields.title.is_empty() {
                fields.title = item.title.clone();
            }
            fields
        } else {
            let mut values = Vec::new();
            for ((_, title, required), default) in FIELDS.iter().zip([&item.title, &item.pinned, &item.body]) {
                let Some(entry) = self.ask(&format!("Editar acuerdo #{}", item.id), title, default, *required) else {
                    self.message = "Edición cancelada: no se guardaron cambios.".into();
                    return;
                };
                values.push(entry);
            }
            Doc { title: values[0].clone(), pinned: values[1].clone(), body: values[2].clone() }
        };
        if fields == item.doc() {
            self.drafts.discard(&name, ".md");
            self.message = "Sin cambios: el acuerdo sigue igual.".into();
            return;
        }
        let next_label = version_label(self.store.version_count(item.id).unwrap_or(1));
        // ESC here still keeps the edit: the note is optional, the text is not.
        // Until revise() returns, the edit only lives in the draft
        let note = self
            .ask(&format!("Versión nueva · {next_label}"), "¿Qué cambió y por qué?", "", false)
            .filter(|n| !n.is_empty())
            .unwrap_or_else(|| "Actualizado".into());
        match self.store.revise(item.id, &fields, &note) {
            Ok(label) => {
                self.drafts.discard(&name, ".md");
                self.message = format!("{} · {note}", label.unwrap_or_else(|| "None".into()));
            }
            Err(error) => self.message = format!("No se pudo guardar: {error}. El borrador sigue a salvo."),
        }
    }

    pub fn log(&mut self, kind: &str) {
        let Some(item) = self.current() else {
            self.message = "Elige un acuerdo antes de registrar una experiencia.".into();
            return;
        };
        // Inside the calendar, what's logged goes to the chosen day: the way to
        // add what was not noted at the time
        let (mut when, mut on) = (None, String::new());
        if self.tab == CALENDARIO && self.cal_focus() && self.cal_day != today() {
            when = Some(local_noon_utc(self.cal_day));
            on = format!(" · apuntado el {} de {}", self.cal_day.day(), MONTHS[self.cal_day.month0() as usize]);
        }
        let Some(note) = self.ask(&format!("{}{on}", item.title), log_prompt(kind), "", false) else {
            self.message = "Registro cancelado.".into();
            return;
        };
        self.message = match self.store.log(item.id, kind, &note, when.as_deref()) {
            Ok(()) => format!("{}{on}", popo_says(kind)),
            Err(error) => format!("No se pudo guardar: {error}"),
        };
    }

    /// + or Space: the four kinds of experience, explained, one key to pick.
    pub fn choose_experience(&mut self) {
        let Some(item) = self.current() else {
            self.message = "Aún no hay acuerdos: pulsa N para crear el primero.".into();
            return;
        };
        let (h, w) = (self.win.h, self.win.w);
        let bw = 64.min(w - 4);
        let (bx, by) = ((w - bw) / 2, 2.max((h - 8) / 2));
        let main = self.style("main", false);
        for row in by..by + 8 {
            // opaque over what is behind
            self.put(row, bx, &" ".repeat(bw.max(0) as usize), main, Some(bw));
        }
        let a = self.style("a", true);
        let (y, x, _, iw) = self.panel(by, bx, 8, bw, &format!("AÑADIR EXPERIENCIA · {}", item.title), Some(a), None);
        for (i, (key, _, name, meaning, color)) in EXPERIENCES.iter().enumerate() {
            let bold = self.style(color, true);
            self.put(y + i as i32, x, &key.to_uppercase().to_string(), bold, None);
            self.put(y + i as i32, x + 3, name, bold, Some(iw - 3));
            self.put(y + i as i32, x + 20, meaning, main, Some(iw - 20));
        }
        let dim = self.style("dim", false);
        self.put(y + 5, x, "una tecla · luego ENTER (la nota es opcional) · ESC cancelar", dim, Some(iw));
        self.term.refresh();
        let key = self.term.read_key(None);
        let kind = EXPERIENCES.iter().find(|(k, ..)| matches!(key, Some(Key::Char(c)) if c.to_lowercase().eq(k.to_lowercase()))).map(|e| e.1);
        if let Some(kind) = kind {
            self.log(kind);
        }
    }

    /// S on an obstacle in BITÁCORA: how it was put right (or what will be done).
    pub fn add_repair(&mut self) {
        let entries = self.store.entries(JOURNAL_LIMIT).unwrap_or_default();
        if self.tab != BITACORA || entries.is_empty() {
            self.message = "S añade una reparación a un obstáculo: elígelo en BITÁCORA.".into();
            return;
        }
        let entry = entries[self.entry_selected.min(entries.len() - 1)].clone();
        if entry.kind != "obstacle" {
            self.message = "S es para obstáculos: este registro no lo es.".into();
            return;
        }
        let Some(text) = self.ask(
            &format!("Reparación · {}", entry.title),
            "¿Cómo lo reparé, o qué haré? (vacío lo quita)",
            &entry.repair,
            false,
        ) else {
            return;
        };
        let _ = self.store.repair(entry.id, &text);
        self.message = if text.is_empty() { "Reparación quitada." } else { "Popo: «Reparar también es avanzar.»" }.into();
    }

    pub fn review(&mut self) {
        let Some(item) = self.current() else {
            self.message = "Primero selecciona un acuerdo.".into();
            return;
        };
        let Some(learned) = self.ask("Retrospectiva", "¿Qué aprendí del experimento?", "", true) else { return };
        let Some(adjustment) = self.ask("Retrospectiva", "¿Qué voy a cambiar para la próxima vez?", "", false) else {
            return;
        };
        match self.store.review(item.id, &learned, &adjustment) {
            Ok(commit) => {
                self.tab = REVIEW;
                self.message = format!("commit {commit} · {learned}");
            }
            Err(error) => self.message = format!("No se pudo guardar: {error}"),
        }
    }

    /// X: active, integrated or archived, with one key. Nothing is lost either way.
    pub fn change_status(&mut self) {
        let Some(item) = self.current() else { return };
        let options = [('1', "active", "activo"), ('2', "integrated", "integrado"), ('3', "archived", "archivado")];
        let listed: Vec<String> = options.iter().map(|(k, _, name)| format!("{k} {name}")).collect();
        let key = choose(&mut self.term, self.win, &format!("Estado · {}", item.title), &listed.join("  "));
        let Some(status) = options.iter().find(|(k, ..)| key == Some(Key::Char(*k))).map(|o| o.1) else { return };
        if status == item.status {
            return;
        }
        let _ = self.store.update_status(item.id, status);
        self.message = match status {
            "active" => "Activo de nuevo.",
            "integrated" => "¡Integrado! Ya forma parte de ti. Popo pega un estirón 🐾",
            _ => "Archivado: guardado con toda su historia (A para verlo).",
        }
        .into();
    }

    /// Supr: the selected entry in BITÁCORA, the selected commitment in OVERVIEW/ACUERDOS.
    pub fn delete(&mut self) {
        if self.tab == BITACORA {
            let entries = self.store.entries(JOURNAL_LIMIT).unwrap_or_default();
            if entries.is_empty() {
                self.message = "No hay entradas que borrar.".into();
                return;
            }
            self.entry_selected = self.entry_selected.min(entries.len() - 1);
            if let Ok(removed) = self.store.delete_entry(entries[self.entry_selected].id) {
                self.undo = Some((removed, "La entrada".into()));
            }
            self.entry_selected = (self.entry_selected as i64).min(entries.len() as i64 - 2).max(0) as usize;
            self.message = "Entrada borrada. U para deshacer.".into();
        } else if self.tab == OVERVIEW || self.tab == ACUERDOS {
            let Some(item) = self.current() else {
                self.message = "No hay acuerdos que borrar.".into();
                return;
            };
            let title = if len(&item.title) <= 28 { item.title.clone() } else { format!("{}…", take(&item.title, 27)) };
            if !self.confirm(&format!("¿Borrar «{title}» y todo su historial?")) {
                self.message = "No se ha borrado nada.".into();
                return;
            }
            if let Ok(removed) = self.store.delete_commitment(item.id) {
                self.undo = Some((removed, format!("«{}»", item.title)));
            }
            self.selected = 0;
            self.message = "Acuerdo borrado. U para deshacer mientras no cierres la app; X archiva sin borrar.".into();
        } else {
            self.message = "Supr borra entradas en BITÁCORA (3) y acuerdos en OVERVIEW o ACUERDOS (1-2).".into();
        }
    }

    pub fn undo_delete(&mut self) {
        let Some((removed, what)) = self.undo.take() else {
            self.message = "No hay nada que deshacer.".into();
            return;
        };
        match self.store.restore(&removed) {
            Ok(()) => self.message = format!("{what} ha vuelto."),
            Err(error) => {
                self.message = format!("No se pudo deshacer: {error}");
                self.undo = Some((removed, what));
            }
        }
    }
}
