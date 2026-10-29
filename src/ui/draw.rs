//! Drawing: colours, text, panels and rows of figures.
use super::term::{Attr, Term, Win};
use crate::pytext::{len, wrap};

/// Colors: cyan, lavender, green, amber, muted, white, selected, border
fn palette(colors: u16, name: &str) -> (i16, i16) {
    if colors >= 256 {
        match name {
            "a" => (45, -1),
            "b" => (141, -1),
            "good" => (84, -1),
            "warm" => (215, -1),
            "dim" => (244, -1),
            // Selected text: 233, the grey ramp's near-black. Not 16: base16 themes
            // (Stylix) repaint 16-21 with their extra colours, and 16 becomes orange
            "select" => (233, 45),
            "edge" => (60, -1),
            _ => (255, -1),
        }
    } else {
        // cyan, magenta, green, yellow, blue, white, black on cyan, blue
        match name {
            "a" => (6, -1),
            "b" => (5, -1),
            "good" => (2, -1),
            "warm" => (3, -1),
            "dim" => (4, -1),
            "select" => (0, 6),
            "edge" => (4, -1),
            _ => (7, -1),
        }
    }
}

pub fn style(term: &Term, name: &str, bold: bool) -> Attr {
    let (fg, bg) = if term.colors > 0 { palette(term.colors, name) } else { (-1, -1) };
    // The selection is always bold: dark letters on cyan need the weight
    Attr { fg, bg, bold: bold || name == "select" }
}

const LANE_COLORS: [&str; 4] = ["a", "b", "good", "warm"];

/// Each commitment keeps the same lane color, like branches in a git GUI.
pub fn lane_style(term: &Term, commitment_id: Option<i64>, bold: bool) -> Attr {
    style(term, LANE_COLORS[commitment_id.unwrap_or(0).rem_euclid(LANE_COLORS.len() as i64) as usize], bold)
}

/// Text at (y, x) of the window, cut to `maxlen` characters and never into its last column.
pub fn put(term: &mut Term, win: Win, y: i32, x: i32, message: &str, attr: Attr, maxlen: Option<i32>) {
    let (h, w) = (win.h, win.w);
    if y < 0 || y >= h || x >= w || x < 0 {
        return;
    }
    let width = (w - x - 1).min(maxlen.unwrap_or(w));
    if width <= 0 {
        return;
    }
    let text = message.replace('\n', " ").replace('\t', "  ");
    term.addstr(win, y, x, &text, attr, Some(width as usize));
}

/// A rounded panel with its title on the top border.
///
/// Returns the inside as (y, x, height, width), one column of padding on each side.
#[allow(clippy::too_many_arguments)]
pub fn panel(
    term: &mut Term,
    win: Win,
    y: i32,
    x: i32,
    height: i32,
    width: i32,
    title: &str,
    title_attr: Option<Attr>,
    edge: Option<Attr>,
) -> (i32, i32, i32, i32) {
    if height < 2 || width < 6 {
        return (y, x, 0, 0);
    }
    let edge = edge.unwrap_or_else(|| style(term, "edge", false));
    let line = "─".repeat((width - 2) as usize);
    put(term, win, y, x, &format!("╭{line}╮"), edge, Some(width));
    for row in y + 1..y + height - 1 {
        put(term, win, row, x, "│", edge, None);
        put(term, win, row, x + width - 1, "│", edge, None);
    }
    put(term, win, y + height - 1, x, &format!("╰{line}╯"), edge, Some(width));
    if !title.is_empty() {
        let attr = title_attr.unwrap_or_else(|| style(term, "a", true));
        put(term, win, y, x + 2, &format!(" {title} "), attr, Some(width - 4));
    }
    (y + 1, x + 2, height - 2, width - 4)
}

/// A figure laid out: (column, "07", name, colour).
pub type Figure = (i32, String, String, &'static str);

/// Lay out (n, name, short name, colour) figures so they never break their box.
///
/// Tries the full names with a generous gap, then tighter, then the short
/// names (EXP for EXPERIENCIAS...), and only then spreads them over more rows.
pub fn fit_figures(figures: &[(i64, &str, &str, &'static str)], width: i32, gaps: &[i32]) -> Vec<Vec<Figure>> {
    for use_short in [false, true] {
        for &gap in gaps {
            let cells: Vec<(String, &str, &'static str)> = figures
                .iter()
                .map(|&(n, name, short, color)| (format!("{n:02}"), if use_short { short } else { name }, color))
                .collect();
            let total: i32 = cells.iter().map(|(_, name, _)| 3 + len(name) as i32).sum::<i32>()
                + gap * (cells.len() as i32 - 1);
            if total <= width {
                let mut row = Vec::new();
                let mut col = 0;
                for (number, name, color) in cells {
                    row.push((col, number, name.to_string(), color));
                    col += 3 + len(name) as i32 + gap;
                }
                return vec![row];
            }
        }
    }
    let mut rows = Vec::new();
    let mut row: Vec<Figure> = Vec::new();
    let mut col = 0;
    for &(n, _, short, color) in figures {
        if !row.is_empty() && col + 3 + len(short) as i32 > width {
            rows.push(std::mem::take(&mut row));
            col = 0;
        }
        row.push((col, format!("{n:02}"), short.to_string(), color));
        col += 3 + len(short) as i32 + 2;
    }
    rows.push(row);
    rows
}

pub fn draw_figures(term: &mut Term, win: Win, y: i32, x: i32, rows: &[Vec<Figure>]) {
    for (r, row) in rows.iter().enumerate() {
        for (col, number, name, color) in row {
            let (bold, plain) = (style(term, color, true), style(term, color, false));
            put(term, win, y + r as i32, x + col, number, bold, None);
            put(term, win, y + r as i32, x + col + 3, name, plain, None);
        }
    }
}

/// Paragraphs wrapped to `width`; an empty text reads as "—".
pub fn wrap_lines(text: &str, width: i32) -> Vec<String> {
    let text = if text.is_empty() { "—" } else { text };
    let mut out = Vec::new();
    for paragraph in text.split('\n') {
        let lines = wrap(paragraph, width.max(8) as usize);
        if lines.is_empty() {
            out.push(String::new());
        } else {
            out.extend(lines);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn figures_shorten_their_names_before_breaking_the_box() {
        let figures = [(1, "ACUERDOS", "ACU", "a"), (0, "EXPERIENCIAS", "EXP", "good"),
                       (0, "DESCUBRIMIENTOS", "DESC", "b"), (0, "INTEGRADOS", "INT", "warm")];
        let gaps = [7, 4, 2];
        for width in 10..120 {
            for row in fit_figures(&figures, width, &gaps) {
                let (col, _, name, _) = row.last().unwrap();
                assert!(col + 3 + len(name) as i32 <= width.max(3 + 4));
            }
        }
        let names = |w| fit_figures(&figures, w, &gaps)[0].iter().map(|c| c.2.clone()).collect::<Vec<_>>();
        assert_eq!(names(90), ["ACUERDOS", "EXPERIENCIAS", "DESCUBRIMIENTOS", "INTEGRADOS"]);
        assert_eq!(names(40), ["ACU", "EXP", "DESC", "INT"]);
        assert_eq!(fit_figures(&figures, 20, &gaps).len(), 2);
    }
}
