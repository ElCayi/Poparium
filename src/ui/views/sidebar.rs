//! The sidebar (Popo, the name, NAV, SISTEMA) and its narrow tab row.
use crate::kitty::{KITTY_LOGO_IDS, kitty_placeholder_row};
use crate::popo::{logo_frame, wordmark_cells};
use crate::pytext::len;
use crate::ui::app::App;
use crate::ui::layout::{SIDE_W, TABS};
use crate::{APP, TAGLINE, VERSION};

impl App {
    /// The brand (Popo and the name, the one part with no panel), then two
    /// panels: the tabs, and where the data lives.
    ///
    /// Returns the first column of the main area.
    pub fn render_sidebar(&mut self, h: i32, _w: i32) -> i32 {
        let width = SIDE_W - 1;
        let logo = self.popo.as_ref().map(|p| &p.logo).filter(|l| !l.is_empty());
        let logo_size = logo.map(|l| (l[0].len() as i32, l[0][0].len() as i32));
        let colors = self.term.colors >= 256;
        let wordmark = wordmark_cells();
        let (system_h, nav_min) = (5, TABS.len() as i32 + 2);
        // The biggest brand that still leaves room for the other two panels
        let mut options = Vec::new();
        if let (Some((rows, _)), true) = (logo_size, colors) {
            options.push((rows + 1 + wordmark.len() as i32 + 1, true, true));
        }
        if colors {
            options.push((wordmark.len() as i32 + 1, false, true));
        }
        options.push((2, false, false));
        let (inside, with_logo, with_mark) = options
            .iter()
            .copied()
            .find(|o| o.0 + 2 + nav_min + system_h < h)
            .unwrap_or(*options.last().unwrap());
        // Same inside as a panel, so everything lines up, but no border
        let (mut y, x, iw) = (1, 3, width - 4);
        self.logo_at = None;
        if let (true, Some((rows, cols))) = (with_logo, logo_size) {
            self.logo_at = Some((y, x + (iw - cols) / 2));
            self.draw_logo();
            y += rows + 1;
        }
        if with_mark {
            let cream = self.pair(230, -1);
            let a = self.style("a", true);
            for (row, cells) in wordmark.iter().enumerate() {
                for (col, &(c, color)) in cells.iter().enumerate() {
                    if c != ' ' {
                        self.put(y + row as i32, x + col as i32, &c.to_string(), if color == "cream" { cream } else { a }, None);
                    }
                }
            }
            // The version sits in the empty space beside the p's tails
            let dim = self.style("dim", false);
            self.put(y + wordmark.len() as i32 - 1, x + iw - len(VERSION) as i32, VERSION, dim, None);
            y += wordmark.len() as i32;
        } else {
            let a = self.style("a", true);
            self.put(y, x, &format!("{APP} {VERSION}"), a, Some(iw));
            y += 1;
        }
        let dim = self.style("dim", false);
        self.put(y, x, TAGLINE, dim, Some(iw));
        // NAV is just as tall as its tabs (one blank row around them), its list
        // centred in it; the space it leaves sits above SISTEMA
        let nav_top = inside + 2;
        let room = h - 1 - system_h - nav_top;
        let tabs = TABS.len() as i32;
        let step = if tabs * 2 + 3 <= room { 2 } else { 1 };
        let nav_h = room.min((tabs - 1) * step + 1 + 4);
        let edge = self.focus_edge(!self.inside);
        let (y, x, ih, iw) = self.panel(nav_top, 1, nav_h, width, "NAV", None, edge);
        let labels: Vec<String> = TABS.iter().enumerate().map(|(i, name)| format!("{:02}  {name}", i + 1)).collect();
        let widest = labels.iter().map(|t| len(t) as i32).max().unwrap_or(0);
        let lx = x + 0.max((iw - 2 - widest).div_euclid(2));
        let ly = y + 0.max((ih - (tabs - 1) * step - 1).div_euclid(2));
        for (i, text) in labels.iter().enumerate() {
            let chosen = self.tab == i;
            let attr = if chosen { self.style("a", true) } else { self.style("dim", false) };
            self.put(ly + i as i32 * step, lx, &format!("{}{text}", if chosen { "► " } else { "  " }), attr, Some(iw - (lx - x)));
        }
        let (y, x, _, iw) = self.panel(h - 1 - system_h, 1, system_h, width, "SISTEMA", None, None);
        let (good, dim) = (self.style("good", false), self.style("dim", false));
        self.put(y, x, "offline / personal", good, Some(iw));
        self.put(y + 1, x, "sqlite / sin nube", dim, Some(iw));
        self.put(y + 2, x, "? ayuda   q salir", dim, Some(iw));
        SIDE_W + 1
    }

    /// Popo's current frame: kitty's real image if it has it, half blocks otherwise.
    pub fn draw_logo(&mut self) {
        let Some((top, x)) = self.logo_at else { return };
        let index = logo_frame(self.now_ms()).0;
        let Some(popo) = &self.popo else { return };
        let frame = popo.logo[index].clone();
        if self.kitty_logo() {
            let (rows, cols) = (frame.len(), frame[0].len());
            let attr = self.pair(KITTY_LOGO_IDS[index] as i16, -1);
            for row in 0..rows {
                let text = kitty_placeholder_row(row, cols, 0);
                self.term.addstr(self.win, top + row as i32, x, &text, attr, None);
            }
            return;
        }
        for (row, cells) in frame.iter().enumerate() {
            for (col, cell) in cells.iter().enumerate() {
                let (text, attr) = match cell {
                    Some((c, fg, bg)) => (c.as_str(), self.pair(*fg, *bg)),
                    None => (" ", crate::ui::term::Attr::PLAIN),
                };
                self.put(top + row as i32, x + col as i32, text, attr, None);
            }
        }
    }

    /// Compact layout: the sidebar becomes a single row of tabs.
    pub fn render_tabbar(&mut self, w: i32) {
        let mut names: Vec<String> = TABS.iter().enumerate().map(|(i, name)| format!("{} {name}", i + 1)).collect();
        if names.iter().map(|n| len(n) as i32 + 2).sum::<i32>() > w - 4 {
            // Too narrow for every name: only the current tab keeps its own
            names = names
                .iter()
                .enumerate()
                .map(|(i, n)| if i == self.tab { n.clone() } else { n.split(' ').next().unwrap_or("").to_string() })
                .collect();
        }
        let brand = format!("{APP} {VERSION}  ");
        let mut x = 2;
        if len(&brand) as i32 + names.iter().map(|n| len(n) as i32 + 2).sum::<i32>() <= w - 4 {
            let a = self.style("a", true);
            self.put(0, x, &brand, a, None);
            x += len(&brand) as i32;
        }
        for (i, name) in names.iter().enumerate() {
            let attr = if self.tab == i { self.style("select", false) } else { self.style("dim", false) };
            self.put(0, x, &format!(" {name} "), attr, None);
            x += len(name) as i32 + 3;
        }
    }
}
