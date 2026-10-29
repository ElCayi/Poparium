//! BITÁCORA: every entry, newest first.
use crate::dates::display_date;
use crate::ui::app::App;
use crate::ui::layout::JOURNAL_LIMIT;
use crate::vocabulary::{LABEL_W, event_label};

impl App {
    /// ↑↓ choose an entry here (Supr deletes it), not a commitment.
    pub fn render_journal(&mut self, top: i32, bottom: i32, left: i32, width: i32) {
        let edge = self.focus_edge(self.inside);
        let (mut y, x, ih, iw) = self.panel(
            top,
            left,
            bottom - top + 1,
            width,
            "BITÁCORA · Todo el recorrido · S repara un obstáculo · Supr borra",
            None,
            edge,
        );
        let last = y + ih - 1;
        let items = self.store.entries(JOURNAL_LIMIT).unwrap_or_default();
        let dim = self.style("dim", false);
        if items.is_empty() {
            self.put(y, x, "Aún no hay entradas. Desde inicio: D, P, B o I.", dim, Some(iw));
            return;
        }
        self.entry_selected = self.entry_selected.min(items.len() - 1);
        // Entries take up to 3 rows: start early enough for the cursor to be on screen
        let start = 0.max(self.entry_selected as i32 - 1.max(ih.div_euclid(3)) + 1) as usize;
        let label_w = LABEL_W as i32;
        for (index, entry) in items.iter().enumerate().skip(start) {
            if y > last {
                break;
            }
            let chosen = index == self.entry_selected;
            let (label, color) = event_label(&entry.kind).unwrap_or(("LOG", "dim"));
            let date_attr = if chosen {
                if self.inside { self.style("select", false) } else { self.style("main", true) }
            } else {
                dim
            };
            self.put(y, x, &display_date(&entry.created_at), date_attr, Some(12));
            let colour = self.style(color, true);
            self.put(y, x + 13, label, colour, Some(label_w));
            let title_attr = self.style("main", chosen);
            self.put(y, x + 13 + label_w, &entry.title, title_attr, Some(1.max(iw - 13 - label_w)));
            y += 1;
            if !entry.note.is_empty() && y <= last {
                self.put(y, x + 13, &format!("↳ {}", entry.note), dim, Some(iw - 13));
                y += 1;
            }
            if !entry.repair.is_empty() && y <= last {
                let good = self.style("good", false);
                self.put(y, x + 13, &format!("✓ reparado: {}", entry.repair), good, Some(iw - 13));
                y += 1;
            }
            y += 1;
        }
    }
}
