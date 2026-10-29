//! The terminal, the way curses gave it to the app: a grid of cells drawn into
//! freely, then sent with refresh(), which writes only the cells that changed.
use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use std::io::{self, Write};
use std::time::Duration;
use unicode_width::UnicodeWidthChar;

/// Colours and weight of a cell. -1 is the terminal's own colour.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Attr {
    pub fg: i16,
    pub bg: i16,
    pub bold: bool,
}

impl Attr {
    pub const PLAIN: Attr = Attr { fg: -1, bg: -1, bold: false };
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Cell {
    /// One character plus the combining marks riding on it; empty for the
    /// second column of a wide character
    text: String,
    attr: Attr,
}

impl Cell {
    fn blank() -> Cell {
        Cell { text: " ".into(), attr: Attr::PLAIN }
    }
}

/// A rectangle of the screen to draw in (curses' derwin): coordinates inside it
/// are relative to its corner, and nothing is drawn outside it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Win {
    pub y: i32,
    pub x: i32,
    pub h: i32,
    pub w: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Key {
    Char(char),
    Enter,
    Esc,
    Up,
    Down,
    Left,
    Right,
    Tab,
    BackTab,
    PageUp,
    PageDown,
    Home,
    End,
    Delete,
    Backspace,
    CtrlU,
    Resize,
    Other,
}

impl Key {
    pub fn is(self, chars: &str) -> bool {
        matches!(self, Key::Char(c) if chars.contains(c))
    }
}

pub struct Term {
    pub rows: usize,
    pub cols: usize,
    cells: Vec<Cell>,
    shown: Vec<Cell>,
    full: bool,
    /// 0 without colours, 8 or 256: what curses called COLORS
    pub colors: u16,
    cursor: Option<(usize, usize)>,
    cursor_shown: bool,
    out: Vec<u8>,
    active: bool,
    /// What Ctrl+C does before leaving: the app's own cleanup
    pub on_interrupt: Option<Box<dyn Fn()>>,
}

/// How many colours the terminal has, as its terminfo entry would say.
fn color_count() -> u16 {
    let term = std::env::var("TERM").unwrap_or_default();
    if term.is_empty() || term == "dumb" {
        return 0;
    }
    if ["256color", "kitty", "direct", "alacritty", "foot", "wezterm", "ghostty", "truecolor"]
        .iter()
        .any(|t| term.contains(t))
    {
        return 256;
    }
    8
}

fn char_width(c: char) -> usize {
    c.width().unwrap_or(0)
}

impl Term {
    pub fn start() -> io::Result<Term> {
        let (cols, rows) = crossterm::terminal::size().unwrap_or((80, 24));
        let (cols, rows) = (cols as usize, rows as usize);
        let mut term = Term {
            rows,
            cols,
            cells: vec![Cell::blank(); rows * cols],
            shown: vec![Cell::blank(); rows * cols],
            full: true,
            colors: color_count(),
            cursor: None,
            cursor_shown: false,
            out: Vec::with_capacity(64 * 1024),
            active: false,
            on_interrupt: None,
        };
        term.enter()?;
        Ok(term)
    }

    fn enter(&mut self) -> io::Result<()> {
        crossterm::terminal::enable_raw_mode()?;
        // The alternate screen, no cursor, no wrapping at the last column
        self.raw(b"\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[H\x1b[2J")?;
        self.cursor_shown = false;
        self.active = true;
        self.full = true;
        Ok(())
    }

    fn leave(&mut self) {
        if !self.active {
            return;
        }
        let _ = self.raw(b"\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l");
        let _ = crossterm::terminal::disable_raw_mode();
        self.active = false;
    }

    /// Give the terminal to another program (the editor) and take it back.
    pub fn suspend(&mut self) {
        self.leave();
    }

    pub fn resume(&mut self) {
        let _ = self.enter();
        self.check_size();
    }

    /// Write bytes straight to the terminal (kitty's graphics commands).
    pub fn raw(&mut self, bytes: &[u8]) -> io::Result<()> {
        let mut stdout = io::stdout().lock();
        stdout.write_all(bytes)?;
        stdout.flush()
    }

    pub fn beep(&mut self) {
        let _ = self.raw(b"\x07");
    }

    /// Follow the terminal's size; the next refresh repaints everything if it changed.
    pub fn check_size(&mut self) {
        let (cols, rows) = crossterm::terminal::size().map(|(c, r)| (c as usize, r as usize)).unwrap_or((self.cols, self.rows));
        if (cols, rows) != (self.cols, self.rows) {
            self.cols = cols;
            self.rows = rows;
            self.cells = vec![Cell::blank(); rows * cols];
            self.shown = vec![Cell::blank(); rows * cols];
            self.full = true;
        }
    }

    pub fn screen(&self) -> Win {
        Win { y: 0, x: 0, h: self.rows as i32, w: self.cols as i32 }
    }

    /// Blank a window.
    pub fn erase(&mut self, win: Win) {
        for y in win.y.max(0)..(win.y + win.h).min(self.rows as i32) {
            for x in win.x.max(0)..(win.x + win.w).min(self.cols as i32) {
                self.set(y as usize, x as usize, Cell::blank());
            }
        }
        // A wide character cut in half at the window's edge goes too
        if win.x > 0 {
            for y in win.y.max(0)..(win.y + win.h).min(self.rows as i32) {
                let left = y as usize * self.cols + win.x as usize - 1;
                if char_width(self.cells[left].text.chars().next().unwrap_or(' ')) == 2 {
                    self.cells[left] = Cell::blank();
                }
            }
        }
    }

    fn set(&mut self, y: usize, x: usize, cell: Cell) {
        let i = y * self.cols + x;
        // Writing over half of a wide character blanks its other half
        if self.cells[i].text.is_empty() && x > 0 {
            self.cells[i - 1] = Cell::blank();
        }
        if x + 1 < self.cols && self.cells[i + 1].text.is_empty() {
            self.cells[i + 1] = Cell::blank();
        }
        self.cells[i] = cell;
    }

    /// curses' addnstr: at most `limit` characters from (y, x) of the window,
    /// stopping at its right edge. Combining marks join the character before them.
    pub fn addstr(&mut self, win: Win, y: i32, x: i32, text: &str, attr: Attr, limit: Option<usize>) {
        if y < 0 || y >= win.h || x < 0 || x >= win.w {
            return;
        }
        let row = win.y + y;
        if row < 0 || row >= self.rows as i32 {
            return;
        }
        let row = row as usize;
        let right = (win.x + win.w).min(self.cols as i32);
        let mut col = win.x + x;
        let mut last: Option<usize> = None;
        for c in text.chars().take(limit.unwrap_or(usize::MAX)) {
            let width = char_width(c);
            if width == 0 {
                if (c as u32) >= 0x20
                    && let Some(at) = last {
                        self.cells[row * self.cols + at].text.push(c);
                    }
                continue;
            }
            if col + width as i32 > right || col < 0 {
                break;
            }
            let at = col as usize;
            self.set(row, at, Cell { text: c.to_string(), attr });
            if width == 2 {
                if at + 2 < self.cols && self.cells[row * self.cols + at + 2].text.is_empty() {
                    self.cells[row * self.cols + at + 2] = Cell::blank();
                }
                self.cells[row * self.cols + at + 1] = Cell { text: String::new(), attr };
            }
            last = Some(at);
            col += width as i32;
        }
    }

    /// Where the text cursor shows (screen coordinates), or hidden.
    pub fn set_cursor(&mut self, at: Option<(usize, usize)>) {
        self.cursor = at;
    }

    fn sgr(&mut self, attr: Attr) {
        let mut code = String::from("\x1b[0");
        if attr.bold {
            code.push_str(";1");
        }
        let colors = self.colors;
        let mut colour = |n: i16, base: u16| {
            if n < 0 || colors == 0 {
                return;
            }
            if n < 8 {
                code.push_str(&format!(";{}", base + n as u16));
            } else {
                code.push_str(&format!(";{};5;{n}", base + 8));
            }
        };
        colour(attr.fg, 30);
        colour(attr.bg, 40);
        code.push('m');
        self.out.extend_from_slice(code.as_bytes());
    }

    /// Send what changed since the last refresh.
    pub fn refresh(&mut self) {
        self.out.clear();
        if self.full {
            self.out.extend_from_slice(b"\x1b[0m\x1b[H\x1b[2J");
            self.shown = vec![Cell::blank(); self.rows * self.cols];
        }
        let mut at: Option<(usize, usize)> = None;
        let mut attr: Option<Attr> = None;
        for y in 0..self.rows {
            for x in 0..self.cols {
                let i = y * self.cols + x;
                let cell = &self.cells[i];
                if !self.full && *cell == self.shown[i] {
                    continue;
                }
                if cell.text.is_empty() {
                    continue; // drawn with the wide character before it
                }
                if self.full && cell.text == " " && cell.attr == Attr::PLAIN {
                    continue; // the screen was just cleared
                }
                if at != Some((y, x)) {
                    self.out.extend_from_slice(format!("\x1b[{};{}H", y + 1, x + 1).as_bytes());
                }
                if attr != Some(cell.attr) {
                    let a = cell.attr;
                    self.sgr(a);
                    attr = Some(a);
                }
                let cell = &self.cells[i];
                self.out.extend_from_slice(cell.text.as_bytes());
                let first = cell.text.chars().next().unwrap_or(' ');
                let width = char_width(first).max(1);
                // After anything a terminal might measure differently, go to the next cell explicitly
                let plain = cell.text.len() == first.len_utf8() && (first as u32) < 0xF0000;
                at = if plain { Some((y, x + width)) } else { None };
            }
        }
        self.shown.clone_from(&self.cells);
        self.full = false;
        self.out.extend_from_slice(b"\x1b[0m");
        match self.cursor {
            Some((y, x)) => {
                self.out.extend_from_slice(format!("\x1b[{};{}H", y + 1, x + 1).as_bytes());
                if !self.cursor_shown {
                    self.out.extend_from_slice(b"\x1b[?25h");
                    self.cursor_shown = true;
                }
            }
            None if self.cursor_shown => {
                self.out.extend_from_slice(b"\x1b[?25l");
                self.cursor_shown = false;
            }
            None => {}
        }
        let out = std::mem::take(&mut self.out);
        let _ = self.raw(&out);
        self.out = out;
    }

    /// The next key, waiting at most `timeout` (None: as long as it takes).
    pub fn read_key(&mut self, timeout: Option<Duration>) -> Option<Key> {
        let deadline = timeout.map(|t| std::time::Instant::now() + t);
        loop {
            let left = match deadline {
                Some(d) => d.saturating_duration_since(std::time::Instant::now()),
                None => Duration::from_secs(3600),
            };
            if !event::poll(left).unwrap_or(false) {
                if deadline.is_some() {
                    return None;
                }
                continue;
            }
            let Ok(happened) = event::read() else { continue };
            let key = match happened {
                Event::Resize(..) => {
                    self.check_size();
                    Key::Resize
                }
                Event::Key(k) if k.kind != KeyEventKind::Release => {
                    let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
                    match k.code {
                        KeyCode::Char('c') if ctrl => {
                            self.interrupt();
                            continue;
                        }
                        KeyCode::Char('u') if ctrl => Key::CtrlU,
                        KeyCode::Char('j' | 'm') if ctrl => Key::Enter,
                        KeyCode::Char('h') if ctrl => Key::Backspace,
                        KeyCode::Char('i') if ctrl => Key::Tab,
                        KeyCode::Char('[') if ctrl => Key::Esc,
                        KeyCode::Char(_) if ctrl => Key::Other,
                        KeyCode::Char(c) => Key::Char(c),
                        KeyCode::Enter => Key::Enter,
                        KeyCode::Esc => Key::Esc,
                        KeyCode::Up => Key::Up,
                        KeyCode::Down => Key::Down,
                        KeyCode::Left => Key::Left,
                        KeyCode::Right => Key::Right,
                        KeyCode::Tab => Key::Tab,
                        KeyCode::BackTab => Key::BackTab,
                        KeyCode::PageUp => Key::PageUp,
                        KeyCode::PageDown => Key::PageDown,
                        KeyCode::Home => Key::Home,
                        KeyCode::End => Key::End,
                        KeyCode::Delete => Key::Delete,
                        KeyCode::Backspace => Key::Backspace,
                        _ => Key::Other,
                    }
                }
                _ => continue,
            };
            return Some(key);
        }
    }

    /// Ctrl+C: tidy up as on q, and leave.
    fn interrupt(&mut self) {
        if let Some(cleanup) = self.on_interrupt.take() {
            cleanup();
        }
        self.leave();
        std::process::exit(130);
    }
}

impl Drop for Term {
    fn drop(&mut self) {
        self.leave();
    }
}
