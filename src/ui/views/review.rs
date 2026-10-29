//! REVIEW: the commitments and their git log --graph.
use crate::history::{Lanes, commit_graph};
use crate::pytext::len;
use crate::ui::app::App;
use crate::ui::draw::lane_style;

impl App {
    pub fn render_review(&mut self, top: i32, bottom: i32, left: i32, width: i32) {
        let space = bottom - top + 1;
        let rows = 1.max((self.current_items().len() as i32).min(2.max(4.min(space.div_euclid(5)))));
        let list_h = rows + 2;
        let edge = self.focus_edge(self.inside);
        let (y, x, ih, iw) = self.panel(
            top,
            left,
            list_h,
            width,
            "REVIEW · R hace commit de una revisión del acuerdo seleccionado",
            None,
            edge,
        );
        self.list_commitments(y, x, iw, ih);
        let b = self.style("b", true);
        let (mut y, x, ih, iw) = self.panel(top + list_h, left, space - list_h, width, "$ git log --graph", Some(b), None);
        let last = y + ih - 1;
        let events = self.store.history().unwrap_or_default();
        let rows = commit_graph(&events);
        if rows.is_empty() {
            let dim = self.style("dim", false);
            self.put(y, x, "Sin commits todavía. Crea un acuerdo con N: será tu primer commit.", dim, Some(iw));
            return;
        }
        let graph_w = rows.iter().map(|r| r.top.len() as i32).max().unwrap_or(0) * 2;
        let right = x + iw;
        let (warm, main, dim) = (self.style("warm", false), self.style("main", false), self.style("dim", false));
        for (i, row) in rows.iter().enumerate() {
            if y > last {
                break;
            }
            self.draw_lanes(y, x, &row.top);
            let mut cx = x + graph_w + 1;
            let event = row.event;
            self.put(y, cx, &event.hash, warm, Some(right - cx));
            cx += 8;
            if row.head {
                let label = format!("({}{}) ", if i == 0 { "HEAD → " } else { "" }, event.title);
                let attr = lane_style(&self.term, Some(event.commitment_id), true);
                self.put(y, cx, &label, attr, Some(1.max(right - cx)));
                cx += len(&label) as i32;
            }
            // The branch label already names the commitment: a bare "init" is enough
            let message = if row.head && event.kind == "init" { "init" } else { event.message.as_str() };
            self.put(y, cx, message, main, Some(1.max(right - cx)));
            y += 1;
            if !event.detail.is_empty() && y <= last {
                self.draw_lanes(y, x, &row.below);
                let prefix = if event.kind == "review" { "→ " } else { "¿por qué? " };
                self.put(y, x + graph_w + 3, &format!("{prefix}{}", event.detail), dim, Some(1.max(right - x - graph_w - 3)));
                y += 1;
            }
        }
    }

    fn draw_lanes(&mut self, y: i32, x: i32, cells: &Lanes) {
        for (col, &(c, cid)) in cells.iter().enumerate() {
            let attr = lane_style(&self.term, cid, c == '*');
            self.put(y, x + col as i32 * 2, &c.to_string(), attr, None);
        }
    }
}
