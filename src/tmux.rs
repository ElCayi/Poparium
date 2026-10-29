//! tmux: Popo's face in the status line and the cyan tab while popOS runs.
use std::path::Path;
use std::process::{Command, Stdio};

const TAB_CYAN: &str = "#00d7ff"; // the app's cyan (xterm 45)

fn tmux(args: &[&str]) -> Option<String> {
    let out = Command::new("tmux").args(args).stdin(Stdio::null()).stderr(Stdio::null()).output().ok()?;
    Some(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// Every `bg=#rrggbb` colour in a tmux format, as written.
fn backgrounds(format: &str) -> Vec<String> {
    let mut found = Vec::new();
    let mut rest = format;
    while let Some(at) = rest.find("bg=#") {
        let colour = &rest[at + 3..];
        if colour.len() >= 7 && colour[1..7].chars().all(|c| c.is_ascii_hexdigit()) {
            found.push(colour[..7].to_string());
        }
        rest = &rest[at + 4..];
    }
    found
}

/// Every occurrence of `needle`, in any case, replaced.
fn replace_ignore_case(text: &str, needle: &str, with: &str) -> String {
    let (lower, needle) = (text.to_ascii_lowercase(), needle.to_ascii_lowercase());
    let mut out = String::new();
    let mut last = 0;
    for (at, _) in lower.match_indices(&needle) {
        out.push_str(&text[last..at]);
        out.push_str(with);
        last = at + needle.len();
    }
    out.push_str(&text[last..]);
    out
}

/// While popOS runs, its tmux tab wears the app's cyan instead of the theme's
/// accent. Only that window, and only window-level options: unsetting them
/// (on=false, when the app closes) gives the tab back its usual look.
pub fn tmux_tab(on: bool) {
    let Some(pane) = std::env::var("TMUX_PANE").ok().filter(|p| !p.is_empty()) else { return };
    if std::env::var("TMUX").map_or(true, |t| t.is_empty()) {
        return;
    }
    if !on {
        for option in ["window-status-current-format", "window-status-format"] {
            tmux(&["set", "-wu", "-t", &pane, option]);
        }
        return;
    }
    let Some(current) = tmux(&["show", "-gv", "window-status-current-format"]) else { return };
    let mut current = current.trim_end_matches('\n').to_string();
    let mut other = tmux(&["show", "-gv", "window-status-format"]).unwrap_or_default().trim_end_matches('\n').to_string();
    let base = backgrounds(&tmux(&["show", "-gv", "window-status-style"]).unwrap_or_default()).into_iter().next();
    // The theme's accent: the background the current tab uses that the bar itself doesn't
    let accents: Vec<String> = backgrounds(&current)
        .into_iter()
        .map(|c| c.to_lowercase())
        .filter(|c| base.as_ref().is_none_or(|b| *c != b.to_lowercase()))
        .collect();
    if accents.is_empty() {
        current = current.replacen("#W", &format!("#[fg={TAB_CYAN}]#W"), 1);
    } else {
        let mut best = &accents[0];
        for candidate in &accents {
            if accents.iter().filter(|c| *c == candidate).count() > accents.iter().filter(|c| *c == best).count() {
                best = candidate;
            }
        }
        current = replace_ignore_case(&current, best, TAB_CYAN);
    }
    other = other.replacen("#W", &format!("#[fg={TAB_CYAN}]#W"), 1);
    tmux(&["set", "-w", "-t", &pane, "window-status-current-format", &current]);
    tmux(&["set", "-w", "-t", &pane, "window-status-format", &other]);
}

pub const FACE: &str = "(^ᴗ^)";
/// The tmux option the status line reads with #{@popos-status}. Its default
/// (the bare face) is set by the tmux config, not here.
const STATUS_OPTION: &str = "@popos-status";

/// Popo's face, glad as always, and ✎ while a draft is unsaved. Faces
/// only, never titles: anyone can see the status line.
pub fn status_face(unsaved: bool) -> String {
    if unsaved { format!("{FACE} ✎") } else { FACE.to_string() }
}

/// Whether the notebook at db_path has unsaved drafts. Never creates a
/// notebook that doesn't exist, and never fails: no answer is "no".
pub fn unsaved_drafts(db_path: &Path) -> bool {
    let path = crate::store::expand_user(db_path);
    let stem = path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    crate::drafts::has_documents(&path.with_file_name(format!("{stem}.drafts")))
}

/// One short line for a status bar that polls: `#(popos --tmux-status)`.
pub fn tmux_status(db_path: &Path) -> String {
    status_face(unsaved_drafts(db_path))
}

/// Write the face into the tmux server's @popos-status, so the status line
/// shows it with #{@popos-status} instead of re-running a command every
/// status-interval. With no tmux or no server running, nothing happens: the
/// face is decoration, never a reason to fail.
pub fn push_status(unsaved: bool) {
    tmux(&["set", "-gq", STATUS_OPTION, &status_face(unsaved)]);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accents_are_found_and_replaced() {
        assert_eq!(backgrounds("#[bg=#AABBCC]x#[fg=#000000,bg=#112233]"), ["#AABBCC", "#112233"]);
        assert_eq!(replace_ignore_case("a#AbC b#abc", "#abc", "#00d7ff"), "a#00d7ff b#00d7ff");
    }

    #[test]
    fn the_status_is_only_a_face() {
        let dir = std::env::temp_dir().join(format!("popos-status-{}", std::process::id()));
        let missing = dir.join("nope.db");
        assert_eq!(tmux_status(&missing), "(^ᴗ^)");
        assert!(!missing.exists());
        std::fs::create_dir_all(dir.join("store.drafts")).unwrap();
        std::fs::write(dir.join("store.drafts/nuevo.md"), "a medias").unwrap();
        assert!(tmux_status(&dir.join("store.db")).ends_with('✎'));
        let _ = std::fs::remove_dir_all(dir);
    }
}
