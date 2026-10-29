//! Small dialogs: a line of text, a one-key choice, a confirmation.
use super::draw::{panel, put, style};
use super::term::{Key, Term, Win};
use crate::drafts::Drafts;
use crate::history::short_hash;

/// A single line of text; None means cancelled.
///
/// With drafts, every keystroke is kept on disk and comes back the next
/// time this same question is asked, until it's answered or cancelled.
#[allow(clippy::too_many_arguments)]
pub fn ask(
    term: &mut Term,
    win: Win,
    heading: &str,
    prompt: &str,
    default: &str,
    required: bool,
    drafts: Option<&Drafts>,
) -> Option<String> {
    let name = format!("linea-{}", short_hash(&[heading, prompt]));
    let recovered = drafts.and_then(|d| d.recover(&name, ".txt"));
    let mut value: Vec<char> = recovered.as_deref().unwrap_or(default).chars().collect();
    let heading = if recovered.is_some() { format!("{heading} · recuperado") } else { heading.to_string() };
    let mut cursor = value.len();
    let mut scroll = 0usize;
    let answer = loop {
        let (h, w) = (win.h, win.w);
        if h < 12 || w < 45 {
            break None;
        }
        let bw = 78.min(w - 4);
        let bx = (w - bw) / 2;
        let by = 3.max((h - 9) / 2);
        term.erase(win);
        let (main, a, a_bold, main_bold, edge, dim) = (
            style(term, "main", false),
            style(term, "a", false),
            style(term, "a", true),
            style(term, "main", true),
            style(term, "edge", false),
            style(term, "dim", false),
        );
        for y in by..by + 9 {
            put(term, win, y, bx, &" ".repeat((bw - 1) as usize), main, Some(bw - 1));
        }
        put(term, win, by, bx, &format!("╭{}╮", "─".repeat((bw - 3) as usize)), a, None);
        put(term, win, by + 1, bx + 2, &heading.to_uppercase(), a_bold, Some(bw - 4));
        put(term, win, by + 2, bx + 2, prompt, main_bold, Some(bw - 4));
        put(term, win, by + 4, bx + 2, &format!("▸ {}", "·".repeat((bw - 7).max(0) as usize)), edge, Some(bw - 4));
        let visible = (bw - 9).max(1) as usize;
        if cursor < scroll {
            scroll = cursor;
        }
        if cursor >= scroll + visible {
            scroll = cursor + 1 - visible;
        }
        let content: String = value.iter().skip(scroll).take(visible).collect();
        put(term, win, by + 4, bx + 4, &crate::pytext::ljust(&content, visible), main, Some(visible as i32));
        put(term, win, by + 6, bx + 2, "ENTER guardar   ESC cancelar   CTRL+U limpiar", dim, Some(bw - 4));
        put(term, win, by + 8, bx, &format!("╰{}╯", "─".repeat((bw - 3) as usize)), a, None);
        let at_y = win.y + by + 4;
        let at_x = win.x + bx + 4 + (cursor - scroll) as i32;
        term.set_cursor(Some((at_y.max(0) as usize, at_x.max(0) as usize)));
        term.refresh();
        let Some(key) = term.read_key(None) else { continue };
        match key {
            Key::Enter => {
                let output: String = value.iter().collect::<String>().trim().to_string();
                if !output.is_empty() || !required {
                    if let Some(d) = drafts {
                        d.discard(&name, ".txt");
                    }
                    break Some(output);
                }
                term.beep();
            }
            Key::Esc => {
                if let Some(d) = drafts {
                    d.discard(&name, ".txt");
                }
                break None;
            }
            Key::CtrlU => {
                value.clear();
                cursor = 0;
                scroll = 0;
            }
            Key::Backspace => {
                if cursor > 0 {
                    value.remove(cursor - 1);
                    cursor -= 1;
                }
            }
            Key::Delete => {
                if cursor < value.len() {
                    value.remove(cursor);
                }
            }
            Key::Left => cursor = cursor.saturating_sub(1),
            Key::Right => cursor = (cursor + 1).min(value.len()),
            Key::Home => cursor = 0,
            Key::End => cursor = value.len(),
            Key::Char(c) if !c.is_control() && value.len() < 450 => {
                value.insert(cursor, c);
                cursor += 1;
            }
            _ => {}
        }
        if let (Some(d), false) = (drafts, key == Key::Enter) {
            d.write(&name, &value.iter().collect::<String>(), ".txt");
        }
    };
    term.set_cursor(None);
    answer
}

/// A one-key choice in a box: returns the key pressed, or None for ESC.
pub fn choose(term: &mut Term, win: Win, heading: &str, options: &str) -> Option<Key> {
    let (h, w) = (win.h, win.w);
    let bw = 70.min(w - 4);
    let (bx, by) = ((w - bw) / 2, 3.max((h - 6) / 2));
    let main = style(term, "main", false);
    for row in by..by + 5 {
        // an opaque box over whatever is behind it
        put(term, win, row, bx, &" ".repeat(bw.max(0) as usize), main, Some(bw));
    }
    let (y, x, _, iw) = panel(term, win, by, bx, 5, bw, &heading.to_uppercase(), None, None);
    let (bold, dim) = (style(term, "main", true), style(term, "dim", false));
    put(term, win, y, x, &" ".repeat(iw.max(0) as usize), main, Some(iw));
    put(term, win, y + 1, x, options, bold, Some(iw));
    put(term, win, y + 2, x, "una tecla · ESC cancelar", dim, Some(iw));
    term.refresh();
    match term.read_key(None) {
        Some(Key::Esc) | None => None,
        key => key,
    }
}

pub fn confirm(term: &mut Term, win: Win, question: &str) -> bool {
    let reply = ask(term, win, "Confirmación", &format!("{question}  (escribe SI)"), "", false, None);
    reply.is_some_and(|r| matches!(r.trim().to_lowercase().as_str(), "si" | "sí"))
}
