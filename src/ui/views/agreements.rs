//! OVERVIEW and ACUERDOS: the list and a commitment's page.
use crate::dates::{MONTHS, parse_local};
use crate::document::glance;
use crate::history::version_label;
use crate::kitty::{KITTY_LOGO_IDS, kitty_placeholder_row, kitty_upload};
use crate::popo::{BELLY, STRETCH, growth, logo_frame, popo_look, popo_png, py_round};
use crate::pytext::{capitalize, len, ljust, take};
use crate::ui::app::App;
use crate::ui::draw::{draw_figures, fit_figures, wrap_lines};
use crate::ui::term::Attr;
use crate::vocabulary::{EXPERIENCES, LABEL_W, event_label, status_name};
use chrono::Datelike;

/// "11 oct": a day and its month, short.
fn day_month(created_at: &str) -> (u32, &'static str, usize) {
    match parse_local(created_at) {
        Some(when) => (when.day(), MONTHS[when.month0() as usize], when.month0() as usize),
        None => (0, MONTHS[0], 0),
    }
}

impl App {
    /// Up to `rows` commitments from y, scrolled so the selected one shows.
    pub fn list_commitments(&mut self, y: i32, x: i32, width: i32, rows: i32) {
        let items = self.current_items();
        if items.is_empty() {
            let dim = self.style("dim", false);
            self.put(y, x, "No hay acuerdos todavía. Pulsa N para crear uno.", dim, Some(width));
            return;
        }
        let top = 0.max(self.selected as i32 - rows + 1) as usize;
        for (pos, item) in items.iter().enumerate().skip(top).take(rows.max(0) as usize) {
            let chosen = pos == self.selected;
            let mut name = format!("{}#{:03} {}", if chosen { "▸ " } else { "  " }, item.id, item.title);
            if item.status != "active" {
                name += &format!("  [{}]", status_name(&item.status));
            }
            let attr = if chosen {
                if self.inside { self.style("select", false) } else { self.style("main", true) }
            } else {
                self.style("main", false)
            };
            self.put(y + (pos - top) as i32, x, &ljust(&name, width.max(0) as usize), attr, Some(width));
        }
    }

    /// The commitment's page, each part in its own panel: its Popo, its
    /// current conclusion, how many experiences it has gathered, and the latest
    /// ones. Everything else is a key away (the line at the bottom).
    pub fn render_ficha(&mut self, top: i32, left: i32, width: i32, height: i32) {
        let Some(item) = self.current() else { return };
        let counts = self.store.experience_counts().unwrap_or_default().remove(&item.id).unwrap_or_default();
        let count = |kind: &str| counts.get(kind).copied().unwrap_or(0);
        let experiences: i64 = counts.values().sum();
        let label = version_label(self.store.version_count(item.id).unwrap_or(1).saturating_sub(1));
        let mut title = format!("#{:03} · {} · {label} · {}", item.id, item.title, status_name(&item.status).to_uppercase());
        if self.drafts.pending().contains(&format!("acuerdo-{}", item.id)) {
            title += " · ✎ borrador: E";
        }
        let b = self.style("b", true);
        let (y, x, ih, iw) = self.panel(top, left, height, width, &title, Some(b), None);
        let last = y + ih - 1;
        let room = ih - 2; // the last two rows: how to add an experience, and the other keys
        self.ficha_popo = None;
        // POPO, on the left: him (wider as he grows, taller once integrated) and his words
        let (belly, integrated) = (growth(experiences), item.status == "integrated");
        let cols = py_round(12.0 * BELLY[belly]) as i32;
        let words = popo_look(item.id, &item.status, experiences).1;
        let column = cols.max(len(&words) as i32);
        let popo_h = 6 + integrated as i32 + 1 + 2;
        let has_logo = self.popo.as_ref().is_some_and(|p| !p.logo.is_empty());
        let with_popo = has_logo && room >= popo_h && iw >= column + 30;
        let pw = if with_popo { column + 4 } else { 0 };
        let (rx, rw) = if with_popo { (x + pw + 1, iw - pw - 1) } else { (x, iw) };
        // CONCLUSIÓN ACTUAL and EXPERIENCIAS, on the right
        let (text, is_note) = glance(&item.pinned, &item.body, 3, (rw - 4).max(0) as usize);
        let text = if text.is_empty() { "Sin nota todavía · E para escribirla".to_string() } else { text };
        let conclusion: Vec<String> = wrap_lines(&text, rw - 4).into_iter().take(3).collect();
        let number_rows = fit_figures(
            &[
                (count("done"), "aplicaciones", "apl", "good"),
                (count("progress"), "avances", "av", "good"),
                (count("obstacle"), "obstáculos", "obs", "warm"),
                (count("insight") + count("review"), "descubrimientos", "desc", "b"),
            ],
            rw - 4,
            &[3, 2],
        );
        let conclusion_h = conclusion.len() as i32 + 2;
        let top_h = (if with_popo { popo_h } else { 0 }).max(conclusion_h + number_rows.len() as i32 + 2);
        let numbers_h = top_h - conclusion_h; // the right column ends where POPO does
        if with_popo {
            let (py, px, _, _) = self.panel(y, x, top_h, pw, "POPO", None, None);
            self.ficha_popo = Some((py, px + (column - cols) / 2, belly, integrated, cols as usize));
            self.draw_ficha_popo();
            let dim = self.style("dim", false);
            self.put(py + 6 + integrated as i32, px + (column - len(&words) as i32) / 2, &words, dim, Some(column));
        }
        let heading = if is_note { "NOTA" } else { "NOTA · aún sin nota, del texto:" };
        let (cy, cx, _, cw) = self.panel(y, rx, conclusion_h, rw, heading, Some(b), None);
        let line_attr = if is_note { self.style("main", true) } else { self.style("dim", false) };
        for (i, line) in conclusion.iter().enumerate() {
            self.put(cy + i as i32, cx, line, line_attr, Some(cw));
        }
        let (ny, nx0, _, _) = self.panel(y + conclusion_h, rx, numbers_h, rw, "EXPERIENCIAS", Some(b), None);
        draw_figures(&mut self.term, self.win, ny, nx0, &number_rows);
        // ÚLTIMAS EXPERIENCIAS, across the bottom
        if room - top_h >= 3 {
            let (ly, lx, lh, lw) = self.panel(y + top_h, x, room - top_h, iw, "ÚLTIMAS EXPERIENCIAS", Some(b), None);
            let recent = self.store.recent(lh as i64, Some(item.id)).unwrap_or_default();
            let (dim, main) = (self.style("dim", false), self.style("main", false));
            if recent.is_empty() {
                let hint = "¿Ha pasado algo con este acuerdo? Pulsa + para añadir una experiencia \
                            (o directamente D, P, B o I). La nota es opcional.";
                for (i, line) in wrap_lines(hint, lw).iter().take(lh.max(0) as usize).enumerate() {
                    self.put(ly + i as i32, lx, line, dim, Some(lw));
                }
            }
            for (i, e) in recent.iter().enumerate() {
                let (name, color) = event_label(&e.kind).unwrap_or(("", "dim"));
                let (day, month, _) = day_month(&e.created_at);
                let row = ly + i as i32;
                self.put(row, lx, &format!("{day:>2} {}", take(month, 3)), dim, Some(7));
                let colour = self.style(color, false);
                self.put(row, lx + 7, &capitalize(name), colour, Some(LABEL_W as i32));
                let note = format!(
                    "{}{}",
                    if e.note.is_empty() { "—" } else { &e.note },
                    if e.repair.is_empty() { "" } else { "  ✓ reparado" }
                );
                self.put(row, lx + 7 + LABEL_W as i32, &note, main, Some(1.max(lw - 7 - LABEL_W as i32)));
            }
        }
        // How to add an experience, always in sight; short names when narrow
        let long_line = 12 + EXPERIENCES.iter().map(|(_, _, name, _, _)| 4 + len(name) as i32).sum::<i32>();
        let mut ex = x;
        let (a_bold, a) = (self.style("a", true), self.style("a", false));
        self.put(last - 1, ex, "+", a_bold, None);
        self.put(last - 1, ex + 2, "añadir ·", a, None);
        ex += 12;
        for (key, _, name, _, color) in EXPERIENCES {
            let label = if long_line <= iw { name.to_lowercase() } else { take(name, 4).to_lowercase() };
            let (bold, plain) = (self.style(color, true), self.style(color, false));
            self.put(last - 1, ex, &key.to_uppercase().to_string(), bold, None);
            self.put(last - 1, ex + 2, &label, plain, None);
            ex += len(&label) as i32 + 4;
        }
        let dim = self.style("dim", false);
        self.put(last, x, "ENTER leer · E editar · V versiones · R revisar · X estado", dim, Some(iw));
    }

    /// The ficha's Popo: kitty's real image (wider as he grows, taller when
    /// integrated) or half blocks stretched the same way.
    pub fn draw_ficha_popo(&mut self) {
        let Some((y, x, belly, integrated, cols)) = self.ficha_popo else { return };
        let index = logo_frame(self.now_ms()).0;
        let rows = 6 + integrated as usize;
        let Some(popo) = &self.popo else { return };
        if self.kitty_logo()
            && let Some(rgba) = &popo.logo_rgba {
                let high = 1 + belly + 5 * integrated as usize;
                if !self.kitty.borrow().popos.contains(&(belly, integrated)) {
                    let stretch = if integrated { STRETCH } else { 1.0 };
                    let data: String = KITTY_LOGO_IDS
                        .iter()
                        .enumerate()
                        .map(|(frame, &color)| {
                            kitty_upload(((high as u32) << 24) | color, &popo_png(rgba, frame, BELLY[belly], stretch), cols, rows)
                        })
                        .collect();
                    let _ = self.term.raw(data.as_bytes());
                    self.kitty.borrow_mut().popos.insert((belly, integrated));
                }
                let attr = self.pair(KITTY_LOGO_IDS[index] as i16, -1);
                for row in 0..rows {
                    let text = kitty_placeholder_row(row, cols, high);
                    self.term.addstr(self.win, y + row as i32, x, &text, attr, None);
                }
                return;
            }
        let frame = popo.logo[index].clone();
        let width = frame[0].len();
        for (row, cells) in frame.iter().enumerate() {
            for col in 0..cols {
                let cell = &cells[(width - 1).min(col * width / cols)];
                let (text, attr) = match cell {
                    Some((c, fg, bg)) => (c.as_str(), self.pair(*fg, *bg)),
                    None => (" ", Attr::PLAIN),
                };
                self.put(y + row as i32, x + col as i32, text, attr, None);
            }
        }
    }

    /// A panel listing the commitments and, if it fits, the SELECTED panel under it.
    #[allow(clippy::too_many_arguments)]
    fn list_and_detail(&mut self, top: i32, bottom: i32, left: i32, width: i32, title: &str, list_rows: i32, note: Option<&str>) {
        let space = bottom - top + 1;
        let extra = note.is_some() as i32;
        let list_h = space.min(list_rows + 2 + extra);
        let edge = self.focus_edge(self.inside);
        let (y, x, ih, iw) = self.panel(top, left, list_h, width, title, None, edge);
        if let Some(note) = note {
            let dim = self.style("dim", false);
            self.put(y, x, note, dim, Some(iw));
        }
        self.list_commitments(y + extra, x, iw, 1.max(ih - extra));
        if space - list_h >= 5 {
            self.render_ficha(top + list_h, left, width, space - list_h);
        }
    }

    /// Totals since the beginning (a commitment doesn't expire), the
    /// commitments, and the latest memories of all of them.
    pub fn render_overview(&mut self, top: i32, bottom: i32, left: i32, width: i32) {
        let living = self.store.active().unwrap_or_default();
        let counts = self.store.experience_counts().unwrap_or_default();
        let experiences: i64 = counts.values().map(|c| c.values().sum::<i64>()).sum();
        let learned: i64 =
            counts.values().map(|c| c.get("insight").copied().unwrap_or(0) + c.get("review").copied().unwrap_or(0)).sum();
        let integrated = living.iter().filter(|c| c.status == "integrated").count() as i64;
        let figures = fit_figures(
            &[
                (living.len() as i64, "ACUERDOS", "ACU", "a"),
                (experiences, "EXPERIENCIAS", "EXP", "good"),
                (learned, "DESCUBRIMIENTOS", "DESC", "b"),
                (integrated, "INTEGRADOS", "INT", "warm"),
            ],
            width - 4,
            &[7, 4, 2],
        );
        let (y, x, _, iw) = self.panel(top, left, 4, width, "OVERVIEW · Memoria persistente entre sesiones 🐾", None, None);
        let shown: Vec<_> = figures.iter().take(2).cloned().collect();
        draw_figures(&mut self.term, self.win, y, x, &shown);
        if figures.len() == 1 {
            // a second row of figures takes the motto's place
            let dim = self.style("dim", false);
            self.put(y + 1, x, "Toda experiencia cuenta para aprender. ♡", dim, Some(iw));
        }
        let space = bottom - (top + 4) + 1;
        let rows = 1.max((self.current_items().len() as i32).min(6));
        let list_h = space.min(rows + 2);
        let edge = self.focus_edge(self.inside);
        let (ly, lx, lh, lw) = self.panel(top + 4, left, list_h, width, "FOCUS · Mis acuerdos", None, edge);
        self.list_commitments(ly, lx, lw, lh);
        if space - list_h < 3 {
            return;
        }
        let b = self.style("b", true);
        let (y, x, ih, iw) = self.panel(top + 4 + list_h, left, space - list_h, width, "ÚLTIMOS RECUERDOS", Some(b), None);
        let recent = self.store.recent(ih as i64, None).unwrap_or_default();
        let (dim, main) = (self.style("dim", false), self.style("main", false));
        if recent.is_empty() {
            let steps = [
                "Aún no hay recuerdos. Para añadir una experiencia:",
                "1. ENTER y elige un acuerdo con ↑↓",
                "2. pulsa + (o directamente D, P, B o I)",
                "3. ENTER: la nota es opcional",
            ];
            for (i, line) in steps.iter().take(ih.max(0) as usize).enumerate() {
                self.put(y + i as i32, x, line, if i > 0 { dim } else { main }, Some(iw));
            }
        }
        for (i, e) in recent.iter().enumerate() {
            let (name, color) = event_label(&e.kind).unwrap_or(("", "dim"));
            let (day, month, _) = day_month(&e.created_at);
            let row = y + i as i32;
            self.put(row, x, &format!("↳ {day:>2} {}", take(month, 3)), dim, Some(9));
            let colour = self.style(color, false);
            self.put(row, x + 10, &capitalize(name), colour, Some(LABEL_W as i32));
            let text = if e.note.is_empty() { e.title.clone() } else { format!("{}: {}", e.title, e.note) };
            self.put(row, x + 10 + LABEL_W as i32, &text, main, Some(1.max(iw - 10 - LABEL_W as i32)));
        }
    }

    pub fn render_agreements(&mut self, top: i32, bottom: i32, left: i32, width: i32) {
        let rows = 1.max((self.current_items().len() as i32).min(3.max(9.min((bottom - top).div_euclid(3)))));
        let note = format!("A  /  {}", if self.archive { "Todos, incluso archivados" } else { "Solo activos" });
        self.list_and_detail(top, bottom, left, width, "ACUERDOS · Contratos conmigo mismo · siempre revisables", rows, Some(&note));
    }
}
