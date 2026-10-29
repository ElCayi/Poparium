//! kitty's graphics protocol, the Unicode placeholder way (it works inside tmux).
use std::process::{Command, Stdio};

// kitty's graphics protocol, Unicode placeholder method: the image is sent once,
// then each cell of its area holds U+10EEEE plus two combining marks (row,
// column), coloured with the image id. It is plain text to the screen and tmux, so
// it survives redraws and tmux places it right; kitty paints the image there.
const KITTY_PLACEHOLDER: char = '\u{10EEEE}';

/// First entries of kitty's rowcolumn-diacritics.txt: mark n means row/column n
const KITTY_DIACRITICS: [u32; 16] = [
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F, 0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351,
    0x0352, 0x0357,
];

/// Ids under 256 can be given as a 256-colour foreground index
pub const KITTY_LOGO_IDS: [u32; 5] = [241, 242, 243, 244, 245];

fn inside_tmux() -> bool {
    std::env::var("TMUX").is_ok_and(|t| !t.is_empty())
}

/// Whether the terminal at the far end is kitty, and tmux (if any) lets its escapes through.
///
/// POPOS_GRAPHICS=0/1 overrides the guess.
pub fn kitty_graphics() -> bool {
    match std::env::var("POPOS_GRAPHICS").as_deref() {
        Ok("0") => return false,
        Ok("1") => return true,
        _ => {}
    }
    if inside_tmux() {
        let Ok(out) = Command::new("tmux")
            .args(["display", "-p", "#{client_termname} #{allow-passthrough}"])
            .stdin(Stdio::null())
            .stderr(Stdio::null())
            .output()
        else {
            return false;
        };
        let text = String::from_utf8_lossy(&out.stdout);
        let words: Vec<&str> = text.split_whitespace().collect();
        return words.len() == 2 && words[0].contains("kitty") && matches!(words[1], "on" | "all");
    }
    std::env::var("TERM").unwrap_or_default().contains("kitty")
        || std::env::var("KITTY_WINDOW_ID").is_ok_and(|v| !v.is_empty())
}

/// One graphics command, wrapped for tmux's passthrough when inside tmux.
pub fn kitty_escape(keys: &str, payload: &str) -> String {
    let command =
        if payload.is_empty() { format!("\x1b_G{keys}\x1b\\") } else { format!("\x1b_G{keys};{payload}\x1b\\") };
    if inside_tmux() { format!("\x1bPtmux;{}\x1b\\", command.replace('\x1b', "\x1b\x1b")) } else { command }
}

/// Send a PNG and give it a virtual placement of cols x rows cells, in 4 KB chunks.
pub fn kitty_upload(image_id: u32, png_base64: &str, cols: usize, rows: usize) -> String {
    let bytes = png_base64.as_bytes();
    let chunks: Vec<&str> = if bytes.is_empty() {
        vec![""]
    } else {
        bytes.chunks(4096).map(|c| std::str::from_utf8(c).expect("base64 is ascii")).collect()
    };
    let mut out = String::new();
    for (n, chunk) in chunks.iter().enumerate() {
        let more = u8::from(n < chunks.len() - 1);
        let keys = if n == 0 {
            format!("a=T,U=1,f=100,i={image_id},c={cols},r={rows},C=1,q=2,m={more}")
        } else {
            format!("m={more}")
        };
        out.push_str(&kitty_escape(&keys, chunk));
    }
    out
}

fn diacritic(n: usize) -> char {
    char::from_u32(KITTY_DIACRITICS[n.min(KITTY_DIACRITICS.len() - 1)]).expect("a combining mark")
}

/// One row of placeholders. `high`, the image id's top byte, rides as a third mark.
pub fn kitty_placeholder_row(row: usize, cols: usize, high: usize) -> String {
    let mut out = String::new();
    for col in 0..cols {
        out.push(KITTY_PLACEHOLDER);
        out.push(diacritic(row));
        out.push(diacritic(col));
        if high > 0 {
            out.push(diacritic(high));
        }
    }
    out
}

/// kitty image id of a meadow Popo: top byte 11-15 by belly, low byte by frame.
pub fn farm_image_id(belly: usize, integrated: bool, frame: usize) -> u32 {
    ((11 + belly as u32) << 24) | (100 + frame as u32 + 5 * integrated as u32)
}
