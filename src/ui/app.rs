//! The app: its state, the main loop and the keys; the drawing lives in the views.
use super::draw::{panel, put, style};
use super::layout::*;
use super::term::{Attr, Key, Term, Win};
use crate::dates::today;
use crate::drafts::Drafts;
use crate::kitty::{KITTY_LOGO_IDS, farm_image_id, kitty_escape, kitty_graphics, kitty_upload};
use crate::popo::{Popo, load_popo, logo_frame, popo_png};
use crate::pyrandom::PyRandom;
use crate::store::{Commitment, Removed, Store};
use crate::tmux::{push_status, tmux_tab};
use crate::{APP, VERSION};
use chrono::NaiveDate;
use std::cell::RefCell;
use std::collections::{BTreeSet, HashMap};
use std::rc::Rc;
use std::time::{Duration, Instant};

/// What kitty already holds: the logo, and the sizes of the ficha's and the meadow's Popos.
#[derive(Default)]
pub struct KittySent {
    pub logo: bool,
    pub popos: BTreeSet<(usize, bool)>,
    pub farm: BTreeSet<(usize, bool)>,
}

impl KittySent {
    /// The commands that make kitty forget every image the app sent.
    fn forget(&mut self) -> String {
        if !self.logo {
            return String::new();
        }
        let mut ids: Vec<u32> = KITTY_LOGO_IDS.to_vec();
        for &(belly, integrated) in &self.popos {
            ids.extend(KITTY_LOGO_IDS.iter().map(|color| ((1 + belly as u32 + 5 * integrated as u32) << 24) | color));
        }
        for &(belly, integrated) in &self.farm {
            ids.extend((0..KITTY_LOGO_IDS.len()).map(|frame| farm_image_id(belly, integrated, frame)));
        }
        self.logo = false;
        ids.iter().map(|i| kitty_escape(&format!("a=d,d=I,i={i},q=2"), "")).collect()
    }
}

/// Where a Popo is in the meadow and what it's doing.
pub struct Spot {
    pub x: f64,
    pub y: i64,
    pub dx: i64,
    pub pause: i64,
}

/// The ficha's Popo on screen: (y, x, belly, integrated, cols).
pub type FichaPopo = (i32, i32, usize, bool, usize);

/// popOS in the terminal. Each tab draws itself from its view (ui/views);
/// what the keys do lives in actions.rs, reading in reader.rs.
pub struct App {
    pub term: Term,
    pub win: Win,
    pub store: Store,
    pub tab: usize,
    pub selected: usize,
    pub message: String,
    pub archive: bool,
    pub drafts: Drafts,
    pub popo: Option<Popo>,
    /// (row, col) of the sidebar Popo while it's on screen
    pub logo_at: Option<(i32, i32)>,
    pub kitty: Rc<RefCell<KittySent>>,
    /// cursor in the BITÁCORA tab
    pub entry_selected: usize,
    /// the day chosen in the CALENDARIO tab
    pub cal_day: NaiveDate,
    /// Where the arrows go: the menu (NAV, ↑↓ change tab) or, after ENTER, the
    /// tab's content (↑↓ choose in it; in the calendar the arrows move the days). ESC: back
    pub inside: bool,
    /// commitment id -> where its Popo is in the meadow and what it's doing
    pub herd: HashMap<i64, Spot>,
    pub herd_clock: f64,
    /// where the ficha's Popo is drawn, for the animation between keys
    pub ficha_popo: Option<FichaPopo>,
    /// (removed rows, what they were) of the last delete, until the app closes
    pub undo: Option<(Removed, String)>,
    pub rng: PyRandom,
    clock: Instant,
}

impl App {
    pub fn new(store: Store, term: Term) -> App {
        let stem = store.path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
        // Popo's ✎ in tmux follows the drafts; run() sets it once at the start, off the first screen's path
        let mut drafts = Drafts::new(store.path.with_file_name(format!("{stem}.drafts")), None);
        drafts.on_change = Some(Box::new(push_status));
        let mut app = App {
            win: term.screen(),
            term,
            store,
            tab: 0,
            selected: 0,
            message: "Datos locales y privados. Nadie supervisa tus avances.".into(),
            archive: false,
            drafts,
            popo: load_popo(),
            logo_at: None,
            kitty: Rc::new(RefCell::new(KittySent::default())),
            entry_selected: 0,
            cal_day: today(),
            inside: false,
            herd: HashMap::new(),
            herd_clock: 0.0,
            ficha_popo: None,
            undo: None,
            rng: PyRandom::from_time(),
            clock: Instant::now(),
        };
        app.herd_clock = app.monotonic();
        let waiting = app.describe_drafts();
        if !waiting.is_empty() {
            app.message = format!("✎ Borradores sin guardar: {waiting}. Se recuperan al abrirlos otra vez.");
        }
        app
    }

    /// Seconds on a steady clock.
    pub fn monotonic(&self) -> f64 {
        self.clock.elapsed().as_secs_f64()
    }

    pub fn now_ms(&self) -> u64 {
        self.clock.elapsed().as_millis() as u64
    }

    // Drawing in the app's window, the way the views do it

    pub fn style(&self, name: &str, bold: bool) -> Attr {
        style(&self.term, name, bold)
    }

    pub fn put(&mut self, y: i32, x: i32, text: &str, attr: Attr, maxlen: Option<i32>) {
        put(&mut self.term, self.win, y, x, text, attr, maxlen);
    }

    #[allow(clippy::too_many_arguments)]
    pub fn panel(&mut self, y: i32, x: i32, h: i32, w: i32, title: &str, title_attr: Option<Attr>, edge: Option<Attr>) -> (i32, i32, i32, i32) {
        panel(&mut self.term, self.win, y, x, h, w, title, title_attr, edge)
    }

    /// The edge of a panel the arrows are in: cyan.
    pub fn focus_edge(&self, focused: bool) -> Option<Attr> {
        focused.then(|| self.style("a", true))
    }

    /// Color pair for a sprite cell; the plain text color without 256 colours.
    pub fn pair(&self, fg: i16, bg: i16) -> Attr {
        if self.term.colors < 256 {
            return self.style("main", false);
        }
        Attr { fg, bg, bold: false }
    }

    pub fn cal_focus(&self) -> bool {
        self.inside && self.tab == CALENDARIO
    }

    pub fn current_items(&self) -> Vec<Commitment> {
        let items = if self.archive { self.store.all_commitments() } else { self.store.active() };
        items.unwrap_or_default()
    }

    pub fn current(&mut self) -> Option<Commitment> {
        let items = self.current_items();
        if items.is_empty() {
            self.selected = 0;
            return None;
        }
        self.selected = self.selected.min(items.len() - 1);
        Some(items[self.selected].clone())
    }

    /// The window the app draws in: the whole screen up to MAX_W columns,
    /// centred beyond that.
    fn frame(&mut self) -> Win {
        let (h, w) = (self.term.rows as i32, self.term.cols as i32);
        let fw = w.min(MAX_W);
        Win { y: 0, x: (w - fw) / 2, h, w: fw }
    }

    pub fn draw(&mut self) {
        self.term.check_size();
        let screen = self.term.screen();
        self.term.erase(screen);
        self.win = self.frame();
        let (h, w) = (self.win.h, self.win.w);
        if h < MIN_H || w < MIN_W {
            let (warm, dim, main) = (self.style("warm", true), self.style("dim", false), self.style("main", false));
            self.put(2, 2, &format!("Ventana pequeña: mínimo {MIN_W}x{MIN_H}"), warm, None);
            self.put(4, 2, &format!("Ahora: {w}x{h} · agranda el panel"), dim, None);
            self.put(6, 2, "q para salir", main, None);
            self.term.refresh();
            return;
        }
        self.logo_at = None;
        self.ficha_popo = None;
        let (left, top) = if w >= SIDEBAR_W {
            (self.render_sidebar(h, w), 0)
        } else {
            self.render_tabbar(w);
            (1, 1)
        };
        let width = w - 1 - left;
        // Rows top..h-5 for the tab's panels, h-4..h-2 for the status panel, h-1 for the keys
        match self.tab {
            OVERVIEW => self.render_overview(top, h - 5, left, width),
            ACUERDOS => self.render_agreements(top, h - 5, left, width),
            CALENDARIO => self.render_calendar(top, h - 5, left, width),
            BITACORA => self.render_journal(top, h - 5, left, width),
            REVIEW => self.render_review(top, h - 5, left, width),
            _ => self.render_farm(top, h - 5, left, width),
        }
        let (y, x, _, iw) = self.panel(h - 4, left, 3, width, "", None, None);
        let (message, dim) = (self.message.clone(), self.style("dim", false));
        self.put(y, x, &message, dim, Some(iw));
        let hints: &[&str] = if self.cal_focus() {
            &CALENDAR_INSIDE_HINTS
        } else if self.inside {
            &KEY_HINTS
        } else {
            &MENU_HINTS
        };
        let hint = hints.iter().find(|k| crate::pytext::len(k) as i32 <= w - 3).unwrap_or(hints.last().unwrap());
        let a = self.style("a", false);
        self.put(h - 1, 1, hint, a, Some(w - 2));
        self.term.refresh();
    }

    fn help(&mut self) {
        let (h, w) = (self.win.h, self.win.w);
        let title = format!("{APP} {VERSION}  /  MAPA DE TECLAS");
        let lines = [
            "↑↓     En el menú: cambiar de pestaña (también ←→, TAB o 1-6)",
            "ENTER  Entrar en la pestaña: ↑↓ eligen dentro · ESC vuelve al menú",
            "       Dentro de una lista, ENTER abre el acuerdo entero",
            "N      Nuevo acuerdo, en tu editor",
            "E      Editar: cada cambio es una versión nueva",
            "V      Versiones: qué cambió y por qué",
            "+      Añadir una experiencia: elige el tipo (también Espacio)",
            "D      Aplicación: lo he puesto en práctica",
            "P      Avance: me cuesta menos que antes",
            "B      Obstáculo: algo lo dificultó (S en BITÁCORA: cómo lo reparé)",
            "I      Descubrimiento: algo que he comprendido",
            "R      Revisar la estrategia (un commit)",
            "       (dentro del CALENDARIO, D/P/B/I apuntan en el día elegido)",
            "X      Estado: activo, integrado o archivado",
            "A      Ver archivados",
            "Supr   Borrar la entrada (BITÁCORA) o el acuerdo seleccionado",
            "U      Deshacer el último borrado",
            "M      Exportar una copia Markdown",
            "Q      Salir",
            "",
            "3      CALENDARIO: dentro, ←→↑↓ día, [ ] mes, T hoy",
            "6      POPARIUM: los Popos de tus acuerdos, a su aire",
            "",
            "Tu herramienta. Tu ritmo. Los acuerdos pueden revisarse.",
            "No es un sistema para que otra persona te supervise.",
            "",
            "Pulsa cualquier tecla para volver...",
        ];
        self.term.erase(self.win);
        let width = 76.min(w - 2);
        let height = (lines.len() as i32 + 3).min(h);
        let (y, x, _, iw) = self.panel(0.max((h - height) / 2), (w - width) / 2, height, width, &title, None, None);
        let main = self.style("main", false);
        for (i, line) in lines.iter().enumerate() {
            self.put(y + i as i32, x, line, main, Some(iw));
        }
        self.term.refresh();
        self.term.read_key(None);
    }

    fn send_logo_to_kitty(&mut self) {
        let Some(popo) = &self.popo else { return };
        let Some(rgba) = &popo.logo_rgba else { return };
        if popo.logo.is_empty() || self.term.colors < 256 || !kitty_graphics() {
            return;
        }
        let (rows, cols) = (popo.logo[0].len(), popo.logo[0][0].len());
        let data: String = KITTY_LOGO_IDS
            .iter()
            .enumerate()
            .map(|(frame, &image_id)| kitty_upload(image_id, &popo_png(rgba, frame, 1.0, 1.0), cols, rows))
            .collect();
        let _ = self.term.raw(data.as_bytes());
        self.kitty.borrow_mut().logo = true;
    }

    fn forget_logo_in_kitty(&mut self) {
        let data = self.kitty.borrow_mut().forget();
        if !data.is_empty() {
            let _ = self.term.raw(data.as_bytes());
        }
    }

    pub fn kitty_logo(&self) -> bool {
        self.kitty.borrow().logo
    }

    pub fn run(&mut self) {
        self.send_logo_to_kitty();
        // Popo's face and the tab's colour are decoration: they never hold up the first screen
        let folder = self.drafts.folder.clone();
        let tab = std::thread::spawn(move || {
            push_status(crate::drafts::has_documents(&folder));
            tmux_tab(true);
        });
        // Ctrl+C tidies up like q does
        let kitty = self.kitty.clone();
        self.term.on_interrupt = Some(Box::new(move || {
            tmux_tab(false);
            let data = kitty.borrow_mut().forget();
            let mut stdout = std::io::stdout().lock();
            let _ = std::io::Write::write_all(&mut stdout, data.as_bytes());
            let _ = std::io::Write::flush(&mut stdout);
        }));
        self.main_loop();
        let _ = tab.join();
        tmux_tab(false);
        self.forget_logo_in_kitty();
    }

    fn main_loop(&mut self) {
        loop {
            self.draw();
            let farm = self.tab == POPARIUM && self.popo.is_some();
            let mut key = None;
            while key.is_none() {
                // Sleep until the next frame is due, or until a key: the farm
                // redraws everything, the sidebar Popo only redraws himself
                let mut waits = Vec::new();
                if farm {
                    waits.push(self.popo.as_ref().map_or(150, |p| p.ms));
                }
                if self.logo_at.is_some() || self.ficha_popo.is_some() {
                    waits.push(logo_frame(self.now_ms()).1 + 5);
                }
                let timeout = waits.into_iter().min().map(Duration::from_millis);
                match self.term.read_key(timeout) {
                    Some(k) => key = Some(k),
                    None => {
                        if farm {
                            break;
                        }
                        if self.logo_at.is_some() {
                            self.draw_logo();
                        }
                        if self.ficha_popo.is_some() {
                            self.draw_ficha_popo();
                        }
                        self.term.refresh();
                    }
                }
            }
            let Some(key) = key else { continue }; // next farm frame
            if key.is("qQ") {
                break;
            }
            self.handle(key);
        }
    }

    fn handle(&mut self, key: Key) {
        let enter = key == Key::Enter;
        let vertical = matches!(key, Key::Up | Key::Down) || key.is("kKjJ");
        let up = key == Key::Up || key.is("kK");
        if self.inside && key == Key::Esc {
            self.inside = false; // back to the menu
        } else if !self.inside && enter {
            self.inside = true; // into the tab's content
        } else if !self.inside && vertical {
            self.tab = if up { self.tab.saturating_sub(1) } else { (self.tab + 1).min(TABS.len() - 1) };
        } else if self.cal_focus() && (vertical || matches!(key, Key::Left | Key::Right) || key.is("hl")) {
            let step = match key {
                Key::Left | Key::Char('h') => -1,
                Key::Right | Key::Char('l') => 1,
                Key::Up | Key::Char('k' | 'K') => -7,
                _ => 7,
            };
            self.move_day(step, 0);
        } else if self.cal_focus() && (key.is("[]") || matches!(key, Key::PageUp | Key::PageDown)) {
            self.move_day(0, if key == Key::Char('[') || key == Key::PageUp { -1 } else { 1 });
        } else if self.cal_focus() && key.is("tT") {
            self.cal_day = today();
        } else if self.cal_focus() && enter {
            self.inside = false;
        } else if let Key::Char(c @ '1'..='6') = key {
            self.tab = c as usize - '1' as usize;
            self.inside = false;
        } else if matches!(key, Key::Right | Key::Tab) || key.is("lL") {
            self.tab = (self.tab + 1) % TABS.len();
            self.inside = false;
        } else if matches!(key, Key::Left | Key::BackTab) || key.is("hH") {
            self.tab = (self.tab + TABS.len() - 1) % TABS.len();
            self.inside = false;
        } else if vertical && self.tab == BITACORA {
            let count = self.store.entries(JOURNAL_LIMIT).map(|e| e.len()).unwrap_or(0);
            let moved = if up { self.entry_selected as i64 - 1 } else { self.entry_selected as i64 + 1 };
            self.entry_selected = moved.min(count as i64 - 1).max(0) as usize;
        } else if vertical {
            let items = self.current_items();
            if items.is_empty() {
                self.message = "Aún no hay acuerdos: pulsa N para crear el primero.".into();
            } else if up {
                self.selected = self.selected.saturating_sub(1);
            } else {
                self.selected = (self.selected + 1).min(items.len() - 1);
            }
        } else if enter && self.tab == BITACORA {
            self.message = "En la bitácora: S repara un obstáculo, Supr borra · ESC vuelve al menú.".into();
        } else if enter {
            if self.current().is_some() {
                self.open_detail();
            } else {
                self.message = "Aún no hay acuerdos: pulsa N para crear el primero.".into();
            }
        } else if key == Key::Delete {
            self.delete();
        } else if key.is("uU") {
            self.undo_delete();
        } else if key.is("vV") {
            self.open_history();
        } else if key.is("nN") {
            self.new_commitment();
        } else if key.is("eE") {
            self.edit();
        } else if key.is("+ ") {
            self.choose_experience();
        } else if key.is("dD") {
            self.log("done");
        } else if key.is("pP") {
            self.log("progress");
        } else if key.is("bB") {
            self.log("obstacle");
        } else if key.is("iI") {
            self.log("insight");
        } else if key.is("rR") {
            self.review();
        } else if key.is("xX") {
            self.change_status();
        } else if key.is("sS") {
            self.add_repair();
        } else if key.is("aA") {
            self.archive = !self.archive;
            self.selected = 0;
            self.message =
                if self.archive { "Mostrando todos los acuerdos." } else { "Mostrando acuerdos activos." }.into();
        } else if key.is("mM") {
            self.message = match self.store.export() {
                Ok(out) => format!("Markdown guardado: {}", out.display()),
                Err(error) => format!("No se pudo exportar: {error}"),
            };
        } else if key == Key::Char('?') {
            self.help();
        }
    }
}
