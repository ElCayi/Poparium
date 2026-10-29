//! Reading a commitment in full, and its history of versions.
use super::app::App;
use super::draw::wrap_lines;
use super::term::{Attr, Key};
use crate::APP;
use crate::dates::display_date;
use crate::document::version_diff;
use crate::history::{version_hash, version_label};
use crate::pytext::{capitalize, splitlines};
use crate::store::Commitment;
use crate::vocabulary::status_name;

/// Lines to read: (text, attr).
type Lines = Vec<(String, Attr)>;

impl App {
    /// Full-screen reading view. build(app, width) -> lines.
    ///
    /// Returns the key in `keys` that closed it, or None for ESC/q/←.
    fn pager(&mut self, title: &str, build: &dyn Fn(&App, i32) -> Lines, hint: &str, keys: &str) -> Option<char> {
        let mut top: i64 = 0;
        loop {
            let (h, w) = (self.win.h, self.win.w);
            self.term.erase(self.win);
            let (y, x, body, iw) = self.panel(0, 1, h - 1, w - 2, title, None, None);
            let lines = build(self, 20.max(iw));
            let body = 1.max(body) as i64;
            top = top.min(lines.len() as i64 - body).max(0);
            for (i, (text, attr)) in lines.iter().skip(top as usize).take(body as usize).enumerate() {
                self.put(y + i as i32, x, text, *attr, Some(iw));
            }
            let total = lines.len() as i64;
            let place = if total > body { format!("  {}-{}/{}", top + 1, total.min(top + body), total) } else { String::new() };
            let a = self.style("a", false);
            self.put(h - 1, 1, &format!("{hint}{place}"), a, Some(w - 2));
            self.term.refresh();
            let Some(key) = self.term.read_key(None) else { continue };
            match key {
                Key::Up | Key::Char('k') => top -= 1,
                Key::Down | Key::Char('j') => top += 1,
                Key::PageUp | Key::Char('b') => top -= body - 1,
                Key::PageDown | Key::Char(' ') => top += body - 1,
                Key::Home | Key::Char('g') => top = 0,
                Key::End | Key::Char('G') => top = total,
                Key::Esc | Key::Char('q' | 'Q') | Key::Left => return None,
                Key::Char(c) => {
                    let lower = c.to_lowercase().next().unwrap_or(c);
                    if keys.contains(lower) {
                        return Some(lower);
                    }
                }
                _ => {}
            }
        }
    }

    /// Reading level: the title, the pinned note, and the free text, its
    /// headings set apart (a suggested one's question, after ·, dimmer).
    fn detail_lines(&self, item: &Commitment, width: i32) -> Lines {
        let versions = self.store.version_count(item.id).unwrap_or(1);
        let status = capitalize(status_name(&item.status));
        let (dim, main, plain) = (self.style("dim", false), self.style("main", false), Attr::PLAIN);
        let mut lines: Lines = vec![
            (format!("◇ AGREEMENT #{:03} · {} · {status}", item.id, version_label(versions.saturating_sub(1))), dim),
            (String::new(), plain),
            (item.title.clone(), self.style("main", true)),
            (String::new(), plain),
        ];
        if !item.pinned.is_empty() {
            let b = self.style("b", true);
            for line in wrap_lines(&item.pinned, width - 2) {
                lines.push((format!("▌ {line}"), b));
            }
            lines.push((String::new(), plain));
        }
        if item.body.is_empty() {
            lines.push(("Sin texto todavía · E para escribir (Ctrl+G sugiere secciones)".into(), dim));
            return lines;
        }
        let a = self.style("a", true);
        for paragraph in item.body.split('\n') {
            if paragraph.trim().is_empty() {
                lines.push((String::new(), plain));
            } else if paragraph.starts_with('#') {
                let heading = paragraph.trim_start_matches('#').trim();
                let (name, question) = heading.split_once(" · ").unwrap_or((heading, ""));
                let name = if paragraph.starts_with("## ") { name.to_uppercase() } else { name.to_string() };
                lines.push((name, a));
                if !question.is_empty() {
                    lines.extend(wrap_lines(question, width).into_iter().map(|l| (l, dim)));
                }
            } else if paragraph.trim_start().starts_with('>') {
                lines.extend(wrap_lines(paragraph, width).into_iter().map(|l| (l, dim)));
            } else {
                lines.extend(wrap_lines(paragraph, width).into_iter().map(|l| (l, main)));
            }
        }
        lines
    }

    /// Each version, newest first, with what it changed from the one before.
    fn history_lines(&self, item: &Commitment, width: i32) -> Lines {
        let versions = self.store.versions(item.id).unwrap_or_default();
        let mut lines: Lines = Vec::new();
        let (good_bold, dim) = (self.style("good", true), self.style("dim", false));
        for index in (0..versions.len()).rev() {
            let v = &versions[index];
            lines.push((format!("{} · {}", version_label(index), v.note), good_bold));
            lines.push((
                format!("{} · {}", version_hash(v.id, v.commitment_id, &v.note, &v.created_at), display_date(&v.created_at)),
                dim,
            ));
            let diff = if index > 0 {
                version_diff(&versions[index - 1].snapshot, &v.snapshot)
            } else {
                let pinned = if v.snapshot.pinned.is_empty() { "—" } else { &v.snapshot.pinned };
                let mut diff = vec!["## NOTA".to_string()];
                diff.extend(splitlines(pinned).into_iter().map(|line| format!("  {line}")));
                diff
            };
            for line in diff {
                let attr = if line.starts_with("## ") {
                    self.style("b", true)
                } else if line.starts_with('+') {
                    self.style("good", false)
                } else if line.starts_with('-') {
                    self.style("warm", false)
                } else {
                    dim
                };
                lines.extend(wrap_lines(&line, width).into_iter().map(|part| (part, attr)));
            }
            lines.push((String::new(), Attr::PLAIN));
        }
        lines
    }

    pub fn open_detail(&mut self) {
        while let Some(item) = self.current() {
            let title = format!("◇ {APP} / {}", item.title);
            let shown = item.clone();
            let key = self.pager(
                &title,
                &move |app: &App, width| app.detail_lines(&shown, width),
                "↑↓ leer  E editar en el editor  V versiones  ESC volver",
                "ev",
            );
            match key {
                Some('e') => self.edit(),
                Some('v') => self.open_history(),
                _ => return,
            }
        }
    }

    pub fn open_history(&mut self) {
        let Some(item) = self.current() else {
            self.message = "Primero selecciona un acuerdo.".into();
            return;
        };
        let title = format!("◇ AGREEMENT HISTORY / {}", item.title);
        self.pager(
            &title,
            &move |app: &App, width| app.history_lines(&item, width),
            "↑↓ leer  ESC volver   + añadido  - quitado",
            "",
        );
    }
}
