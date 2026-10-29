//! CALENDARIO: the month, its summary and the chosen day.
use crate::dates::{MONTHS, WEEKDAYS, first_of_next_month, month_grid, parse_local, today, weekday};
use crate::pytext::{capitalize, len};
use crate::store::DayEvent;
use crate::ui::app::App;
use crate::ui::draw::wrap_lines;
use crate::vocabulary::{DAY_KINDS, event_label};
use chrono::{Datelike, Days, NaiveDate};
use std::collections::{BTreeSet, HashMap};

impl App {
    /// The month as a grid of days with a dot per kind of thing that happened,
    /// the month in numbers under it, and what happened on the chosen day beside
    /// (or under) them.
    pub fn render_calendar(&mut self, top: i32, bottom: i32, left: i32, width: i32) {
        let (day, today) = (self.cal_day, today());
        let weeks = month_grid(day);
        let events = self.store.events_between(weeks[0][0], weeks[weeks.len() - 1][6]).unwrap_or_default();
        let mut by_day: HashMap<NaiveDate, Vec<DayEvent>> = HashMap::new();
        for e in &events {
            by_day.entry(e.day).or_default().push(e.clone());
        }
        let cell = 7;
        let grid_w = 7 * cell + 4;
        let space = bottom - top + 1;
        let beside = width >= grid_w + 32;
        // Days header, the weeks, a blank row and the legend in two rows
        let grid_h = space.min(weeks.len() as i32 + 6);
        let mut title = format!("CALENDARIO · {} {}", capitalize(MONTHS[day.month0() as usize]), day.year());
        if self.cal_focus() {
            title += " · ESC salir";
        }
        let edge = self.focus_edge(self.cal_focus());
        let (y, mut x, ih, iw) = self.panel(top, left, grid_h, if beside { grid_w } else { width }, &title, None, edge);
        // A narrow window gets narrower days (down to 5 columns: the number and 2 dots)
        let cell = 5.max(7.min(iw.div_euclid(7)));
        x += 0.max((iw - 7 * cell).div_euclid(2)); // the grid (and its legend) centred in its box
        let dim = self.style("dim", false);
        for (i, name) in "LMXJVSD".chars().enumerate() {
            self.put(y, x + i as i32 * cell + 1, &format!("{name:>2}"), dim, None);
        }
        for (row, week) in weeks.iter().enumerate() {
            for (col, date) in week.iter().enumerate() {
                let (cx, cy) = (x + col as i32 * cell, y + 1 + row as i32);
                if cy > y + ih - 1 {
                    break;
                }
                let number = format!("{:>2}", date.day());
                let attr = if *date == day {
                    self.style("select", false)
                } else if date.month() != day.month() {
                    self.style("edge", false)
                } else {
                    self.style("main", *date == today)
                };
                self.put(cy, cx + 1, &number, attr, None);
                let kinds: BTreeSet<&str> = by_day.get(date).map(|es| es.iter().map(|e| e.kind.as_str()).collect()).unwrap_or_default();
                let dots: Vec<&str> = DAY_KINDS
                    .iter()
                    .filter(|(_, members, _)| members.iter().any(|m| kinds.contains(m)))
                    .map(|(_, _, color)| *color)
                    .take(0.max(cell - 3) as usize)
                    .collect();
                for (k, color) in dots.iter().enumerate() {
                    let attr = self.style(color, true);
                    self.put(cy, cx + 3 + k as i32, "•", attr, None);
                }
            }
        }
        let legend_y = y + weeks.len() as i32 + 2;
        for (i, (name, _, color)) in DAY_KINDS.iter().enumerate() {
            let (ly, lx) = (legend_y + i as i32 / 2, x + 1 + (i as i32 % 2) * 22);
            if ly < y + ih {
                let attr = self.style(color, false);
                self.put(ly, lx, &format!("• {name}"), attr, None);
            }
        }
        let month: Vec<DayEvent> = events
            .iter()
            .filter(|e| e.day.month() == day.month() && e.kind != "init" && e.kind != "version")
            .cloned()
            .collect();
        let chosen = by_day.get(&day).cloned().unwrap_or_default();
        if beside {
            if space - grid_h >= 5 {
                self.render_month(top + grid_h, space - grid_h, left, grid_w, day, &month);
            }
            self.render_day(top, space, left + grid_w + 1, width - grid_w - 1, &chosen);
        } else if space - grid_h >= 4 {
            self.render_day(top + grid_h, space - grid_h, left, width, &chosen);
        }
    }

    /// What the month held, in numbers: only what was noted, never what "should" have been.
    #[allow(clippy::too_many_arguments)]
    fn render_month(&mut self, top: i32, height: i32, left: i32, width: i32, day: NaiveDate, events: &[DayEvent]) {
        let b = self.style("b", true);
        let title = format!("RESUMEN DE {}", MONTHS[day.month0() as usize].to_uppercase());
        let (y, x, ih, iw) = self.panel(top, left, height, width, &title, Some(b), None);
        let count = |kinds: &[&str]| events.iter().filter(|e| kinds.contains(&e.kind.as_str())).count();
        let obstacles = count(&["obstacle"]);
        let repaired = events.iter().filter(|e| e.kind == "obstacle" && !e.repair.is_empty()).count();
        let obstacle_name = if repaired > 0 {
            format!("obstáculos · {repaired} reparado{}", if repaired != 1 { "s" } else { "" })
        } else {
            "obstáculos".into()
        };
        let commitments: BTreeSet<i64> = events.iter().map(|e| e.commitment_id).collect();
        let rows = [
            (count(&["done"]), "aplicaciones".to_string(), "good"),
            (count(&["progress"]), "avances".to_string(), "good"),
            (obstacles, obstacle_name, "warm"),
            (count(&["insight", "review"]), "descubrimientos".to_string(), "b"),
            (commitments.len(), "acuerdos con experiencias".to_string(), "a"),
        ];
        for (i, (n, name, color)) in rows.iter().enumerate() {
            if i as i32 >= ih {
                break;
            }
            let (bold, plain) = (self.style(color, true), self.style(color, false));
            self.put(y + i as i32, x, &format!("{n:02}"), bold, None);
            self.put(y + i as i32, x + 3, name, plain, Some(iw - 3));
        }
        if (rows.len() as i32) < ih {
            let motto = if events.is_empty() {
                "Un mes sin registros no es un mes vacío. ♡"
            } else {
                "Toda experiencia cuenta para aprender. ♡"
            };
            let dim = self.style("dim", false);
            self.put(y + ih - 1, x, motto, dim, Some(iw));
        }
    }

    fn render_day(&mut self, top: i32, height: i32, left: i32, width: i32, events: &[DayEvent]) {
        let day = self.cal_day;
        let b = self.style("b", true);
        let title = format!("{} {} de {}", capitalize(WEEKDAYS[weekday(day)]), day.day(), MONTHS[day.month0() as usize]);
        let (mut y, x, ih, iw) = self.panel(top, left, height, width, &title, Some(b), None);
        let last = y + ih - 1;
        let (dim, main) = (self.style("dim", false), self.style("main", false));
        if events.is_empty() {
            self.put(y, x, "Un día tranquilo: sin registros.", dim, Some(iw));
            return;
        }
        for e in events {
            if y > last {
                break;
            }
            let (label, color) = event_label(&e.kind).unwrap_or(("LOG", "dim"));
            let label = capitalize(label);
            let time_of_day = parse_local(&e.created_at).map(|t| t.format("%H:%M").to_string()).unwrap_or_default();
            self.put(y, x, &time_of_day, dim, Some(5));
            let colour = self.style(color, true);
            self.put(y, x + 6, &label, colour, Some(iw - 6));
            let label_w = len(&label) as i32;
            if 6 + label_w + 3 + len(&e.title) as i32 <= iw {
                self.put(y, x + 6 + label_w, &format!(" · {}", e.title), main, Some(iw - 6 - label_w));
            } else {
                // a narrow column: the commitment gets its own lines
                for line in wrap_lines(&e.title, iw - 6).iter().take(2) {
                    if y + 1 > last {
                        break;
                    }
                    y += 1;
                    self.put(y, x + 6, line, main, Some(iw - 6));
                }
            }
            y += 1;
            if !e.note.is_empty() && y <= last {
                self.put(y, x + 6, &format!("↳ {}", e.note), dim, Some(iw - 6));
                y += 1;
            }
            y += 1;
        }
    }

    pub fn move_day(&mut self, days: i64, months: i32) {
        let mut day = self.cal_day;
        if months != 0 {
            let month = day.month0() as i32 + months;
            let (year, month) = (day.year() + month.div_euclid(12), month.rem_euclid(12) as u32 + 1);
            let first = NaiveDate::from_ymd_opt(year, month, 1).expect("first of a month exists");
            let length = (first_of_next_month(first) - Days::new(1)).day();
            day = NaiveDate::from_ymd_opt(year, month, day.day().min(length)).expect("a day of the month");
        }
        self.cal_day = if days >= 0 { day + Days::new(days as u64) } else { day - Days::new((-days) as u64) };
    }
}
