//! POPARIUM: the meadow where the Popos wander.
use crate::kitty::{KITTY_LOGO_IDS, farm_image_id, kitty_placeholder_row, kitty_upload};
use crate::popo::{BELLY, FARM_POPO, FARM_TICK, STRETCH, growth, logo_frame, popo_look, popo_png, py_round};
use crate::pyrandom::PyRandom;
use crate::pytext::{len, take};
use crate::store::Commitment;
use crate::ui::app::{App, Spot};
use std::collections::{HashMap, HashSet};

/// A Popo's size in the meadow: (cols, rows, belly).
type Size = (usize, usize, usize);

impl App {
    /// The meadow: every commitment's Popo wanders about on its own. Wider
    /// with experiences, taller once integrated; the archived ones (A) sleep.
    pub fn render_farm(&mut self, top: i32, bottom: i32, left: i32, width: i32) {
        let edge = self.focus_edge(self.inside);
        let (y, x, ih, iw) =
            self.panel(top, left, bottom - top + 1, width, "POPARIUM · los Popos andan a su aire", None, edge);
        let items = self.current_items();
        if items.is_empty() {
            let dim = self.style("dim", false);
            self.put(y, x, "El Poparium está vacío. Cada acuerdo nuevo (N) trae su Popo.", dim, Some(iw));
            return;
        }
        let counts = self.store.experience_counts().unwrap_or_default();
        let experiences: HashMap<i64, i64> =
            items.iter().map(|i| (i.id, counts.get(&i.id).map_or(0, |c| c.values().sum()))).collect();
        let field_h = ih - 1; // the last row tells who the chosen Popo is
        let (base_w, base_h) = FARM_POPO;
        let has_logo = self.popo.as_ref().is_some_and(|p| !p.logo.is_empty());
        if !has_logo || field_h < base_h as i32 + 1 || iw < py_round(base_w as f64 * BELLY[4]) as i32 + 2 {
            let warm = self.style("warm", false);
            self.put(y, x, "Agranda la ventana para ver el prado.", warm, Some(iw));
            for (i, item) in items.iter().take(0.max(ih - 2) as usize).enumerate() {
                let chosen = i == self.selected;
                let words = popo_look(item.id, &item.status, experiences[&item.id]).1;
                let attr = if chosen { self.style("select", false) } else { self.style("main", false) };
                let text = format!("{}🐾 {} · {words}", if chosen { "▸ " } else { "  " }, item.title);
                self.put(y + 2 + i as i32, x, &text, attr, Some(iw));
            }
            return;
        }
        // Grass: the same few blades every time, scattered over the meadow
        let mut blades = PyRandom::new((iw as i64 * 1000 + field_h as i64) as u64);
        let good = self.style("good", false);
        for _ in 0..(iw * field_h).div_euclid(45) {
            let by = blades.randrange(field_h as usize) as i32;
            let bx = blades.randrange(iw as usize) as i32;
            let blade = blades.choice(&['\'', ',', '.', '"']);
            self.put(y + by, x + bx, &blade.to_string(), good, None);
        }
        // Each Popo's size, then one step of the herd for every FARM_TICK gone by
        let mut sizes: HashMap<i64, Size> = HashMap::new();
        for item in &items {
            let belly = growth(experiences[&item.id]);
            sizes.insert(item.id, (py_round(base_w as f64 * BELLY[belly]), base_h + (item.status == "integrated") as usize, belly));
        }
        self.walk_herd(&items, &sizes, iw as usize, field_h as usize);
        // Draw the far ones first, so the near ones (lower) overlap them
        let chosen_id = items[self.selected.min(items.len() - 1)].id;
        let now_ms = self.now_ms();
        let mut order: Vec<&Commitment> = items.iter().collect();
        order.sort_by_key(|i| self.herd[&i.id].y);
        for item in order {
            let (spot_x, spot_y) = (self.herd[&item.id].x, self.herd[&item.id].y);
            let (cols, rows, belly) = sizes[&item.id];
            // Out of step with each other: each breathes on its own clock
            let frame =
                if item.status == "archived" { 0 } else { logo_frame(now_ms + (item.id.max(0) as u64) * 1700).0 };
            let (py, px) = (y + spot_y as i32, x + spot_x as i32);
            self.draw_meadow_popo(py, px, cols, rows, belly, item.status == "integrated", frame);
            if item.id == chosen_id && spot_y > 0 {
                let name = take(&item.title, cols + 8);
                let select = self.style("select", false);
                self.put(py - 1, px + 0.max((cols as i32 - len(&name) as i32).div_euclid(2)), &name, select, None);
            }
        }
        let chosen = items.iter().find(|i| i.id == chosen_id).expect("chosen is listed");
        let words = popo_look(chosen.id, &chosen.status, experiences[&chosen_id]).1;
        let dim = self.style("dim", false);
        self.put(y + ih - 1, x, &format!("▸ {} · {words}  ·  ↑↓ elegir  ENTER leer", chosen.title), dim, Some(iw));
    }

    /// Move every Popo one step per FARM_TICK since the last time: walk on,
    /// sometimes stop to breathe, turn round or drift a row. Archived ones sleep.
    fn walk_herd(&mut self, items: &[Commitment], sizes: &HashMap<i64, Size>, field_w: usize, field_h: usize) {
        let alive: HashSet<i64> = items.iter().map(|i| i.id).collect();
        self.herd.retain(|id, _| alive.contains(id));
        for item in items {
            let (cols, rows, _) = sizes[&item.id];
            self.herd.entry(item.id).or_insert_with(|| {
                let mut start = PyRandom::new(item.id.max(0) as u64);
                let x = start.randrange(1.max(field_w as i64 - cols as i64) as usize) as f64;
                let y = start.randrange(1.max(field_h as i64 - rows as i64 + 1) as usize) as i64;
                let dx = start.choice(&[-1, 1]);
                let pause = start.randrange(10) as i64;
                Spot { x, y, dx, pause }
            });
        }
        let now = self.monotonic();
        let steps = 25.min(((now - self.herd_clock) / FARM_TICK) as i64);
        self.herd_clock += steps as f64 * FARM_TICK;
        if steps == 25 {
            self.herd_clock = now;
        }
        for item in items {
            let (cols, rows, _) = sizes[&item.id];
            let spot = self.herd.get_mut(&item.id).expect("every Popo has a spot");
            let walking = if item.status != "archived" { steps } else { 0 };
            for _ in 0..walking {
                if spot.pause > 0 {
                    spot.pause -= 1;
                    continue;
                }
                let roll = self.rng.random();
                if roll < 0.03 {
                    spot.pause = self.rng.randint(5, 25); // stops to breathe a while
                } else if roll < 0.05 {
                    spot.dx = -spot.dx;
                } else if roll < 0.07 {
                    spot.y += self.rng.choice(&[-1, 1]);
                }
                spot.x += spot.dx as f64;
                if spot.x <= 0.0 || spot.x >= field_w as f64 - cols as f64 {
                    spot.dx = if spot.x <= 0.0 { 1 } else { -1 };
                }
            }
            spot.x = spot.x.max(0.0).min(0.max(field_w as i64 - cols as i64) as f64);
            spot.y = spot.y.max(0).min(0.max(field_h as i64 - rows as i64));
        }
    }

    /// A Popo in the meadow: kitty's real image, or half blocks stretched as wide.
    #[allow(clippy::too_many_arguments)]
    fn draw_meadow_popo(&mut self, y: i32, x: i32, cols: usize, rows: usize, belly: usize, integrated: bool, frame: usize) {
        let Some(popo) = &self.popo else { return };
        if self.kitty_logo()
            && let Some(rgba) = &popo.logo_rgba {
                if !self.kitty.borrow().farm.contains(&(belly, integrated)) {
                    let stretch = if integrated { STRETCH } else { 1.0 };
                    let data: String = (0..KITTY_LOGO_IDS.len())
                        .map(|f| {
                            kitty_upload(farm_image_id(belly, integrated, f), &popo_png(rgba, f, BELLY[belly], stretch), cols, rows)
                        })
                        .collect();
                    let _ = self.term.raw(data.as_bytes());
                    self.kitty.borrow_mut().farm.insert((belly, integrated));
                }
                let image = farm_image_id(belly, integrated, frame);
                let attr = self.pair((image & 0xFF) as i16, -1);
                for row in 0..rows {
                    let text = kitty_placeholder_row(row, cols, (image >> 24) as usize);
                    self.term.addstr(self.win, y + row as i32, x, &text, attr, None);
                }
                return;
            }
        let cells_frame = popo.logo[frame].clone();
        let width = cells_frame[0].len();
        for (row, cells) in cells_frame.iter().enumerate() {
            for col in 0..cols {
                if let Some((c, fg, bg)) = &cells[(width - 1).min(col * width / cols)] {
                    let attr = self.pair(*fg, *bg);
                    self.put(y + row as i32, x + col as i32, c, attr, None);
                }
            }
        }
    }
}
