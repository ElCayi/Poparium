//! The external editor (nvim by default) for a commitment's document.
use crate::document::SUGGESTIONS;
use crate::ui::term::Term;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

fn which(name: &str) -> Option<PathBuf> {
    if name.contains('/') {
        return Path::new(name).is_file().then(|| PathBuf::from(name));
    }
    std::env::var_os("PATH").and_then(|paths| {
        std::env::split_paths(&paths).map(|dir| dir.join(name)).find(|p| {
            use std::os::unix::fs::PermissionsExt;
            p.metadata().is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        })
    })
}

/// `shlex.split`: words, with quotes and backslashes the way a POSIX shell reads them.
fn shell_words(text: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut word = String::new();
    let mut in_word = false;
    let mut chars = text.chars();
    while let Some(c) = chars.next() {
        match c {
            '\'' => {
                in_word = true;
                for q in chars.by_ref() {
                    if q == '\'' {
                        break;
                    }
                    word.push(q);
                }
            }
            '"' => {
                in_word = true;
                while let Some(q) = chars.next() {
                    match q {
                        '"' => break,
                        '\\' => match chars.next() {
                            Some(e @ ('"' | '\\' | '$' | '`')) => word.push(e),
                            Some(e) => {
                                word.push('\\');
                                word.push(e);
                            }
                            None => word.push('\\'),
                        },
                        _ => word.push(q),
                    }
                }
            }
            '\\' => {
                in_word = true;
                if let Some(e) = chars.next() {
                    word.push(e);
                }
            }
            c if c.is_whitespace() => {
                if in_word {
                    words.push(std::mem::take(&mut word));
                    in_word = false;
                }
            }
            c => {
                in_word = true;
                word.push(c);
            }
        }
    }
    if in_word {
        words.push(word);
    }
    words
}

/// $VISUAL, then $EDITOR, then the first editor installed.
pub fn find_editor() -> Option<Vec<String>> {
    let chosen = std::env::var("VISUAL").ok().filter(|v| !v.is_empty()).or_else(|| std::env::var("EDITOR").ok().filter(|v| !v.is_empty()));
    if let Some(chosen) = chosen {
        let words = shell_words(&chosen);
        return (!words.is_empty()).then_some(words);
    }
    ["nvim", "vim", "vi", "nano"].iter().find_map(|e| which(e)).map(|p| vec![p.to_string_lossy().into_owned()])
}

fn vim_escape(path: &Path) -> String {
    let mut out = String::new();
    for c in path.to_string_lossy().chars() {
        if matches!(c, ' ' | '\\' | '%' | '#' | '|' | '"') {
            out.push('\\');
        }
        out.push(c);
    }
    out
}

/// A Lua string as json.dumps(..., ensure_ascii=False) writes it (Lua reads it the same).
fn lua_string(text: &str) -> String {
    serde_json::to_string(text).expect("a string serializes")
}

/// A Lua file for nvim, only for popOS documents: a fixed help bar on top and
/// Ctrl+G, a list of suggested sections to insert (buffer-local, so the
/// user's own nvim is untouched).
fn nvim_helpers(folder: &Path) -> PathBuf {
    let items: Vec<String> =
        SUGGESTIONS.iter().map(|(name, question)| format!("{{{}, {}}}", lua_string(name), lua_string(question))).collect();
    let lua = format!(
        r###"vim.opt_local.winbar = " popOS · escribe libre bajo la raya ── · Ctrl+G sección sugerida · ZZ guardar · ZQ salir sin guardar"
local items = {{ {items} }}
local function insert(choice)
  if not choice then return end
  local row = vim.api.nvim_win_get_cursor(0)[1]
  vim.api.nvim_buf_set_lines(0, row, row, false, {{"", "## " .. choice[1] .. " · " .. choice[2], "", ""}})
  vim.api.nvim_win_set_cursor(0, {{row + 4, 0}})
  vim.cmd("startinsert")
end
local function pick()
  vim.ui.select(items, {{prompt = "Sección sugerida (ESC: ninguna)",
    format_item = function(i) return i[1] .. " · " .. i[2] end}}, insert)
end
vim.keymap.set("n", "<C-g>", pick, {{buffer = true, desc = "popOS: sección sugerida"}})
vim.keymap.set("i", "<C-g>", function() vim.cmd("stopinsert"); vim.schedule(pick) end, {{buffer = true}})
"###,
        items = items.join(", ")
    );
    let path = folder.join("popos-nvim.lua");
    if let Ok(mut file) = OpenOptions::new().create(true).write(true).truncate(true).mode(0o600).open(&path) {
        let _ = file.write_all(lua.as_bytes());
    }
    path
}

fn modified(path: &Path) -> Option<std::time::SystemTime> {
    path.metadata().ok()?.modified().ok()
}

/// Hand the terminal to the editor on `path`; true if the file was saved.
///
/// vim and nvim also copy every change to `autosave` as it happens, without
/// touching `path` itself, so :q! still means "save nothing".
pub fn edit_in_editor(term: &mut Term, path: &Path, autosave: Option<&Path>) -> bool {
    let Some(editor) = find_editor() else { return false };
    let program = Path::new(&editor[0]).file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let mut command: Vec<String> = editor.clone();
    if let (Some(autosave), true) = (autosave, matches!(program.as_str(), "nvim" | "vim")) {
        // -n: no swap file. The autosave already covers a crash, and nvim's own
        // "ATTENTION: swap file found" prompt would only confuse the recovery
        command.push("-n".into());
        command.push("-c".into());
        command.push(format!(
            "autocmd TextChanged,TextChangedI,InsertLeave <buffer> silent! keepalt write! {}",
            vim_escape(autosave)
        ));
    }
    if program == "nvim" {
        // An auto-save plugin would write even on :q!, and :q! must keep meaning "save nothing"
        let helpers = nvim_helpers(path.parent().unwrap_or(Path::new(".")));
        command.extend([
            "-c".into(),
            "lua pcall(function() require('auto-save').off() end)".into(),
            "-c".into(),
            format!("luafile {}", vim_escape(&helpers)),
        ]);
    }
    let before = modified(path);
    term.suspend();
    let ran = Command::new(&command[0]).args(&command[1..]).arg(path).status();
    term.resume();
    ran.is_ok() && modified(path) != before
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn editor_commands_split_like_a_shell() {
        assert_eq!(shell_words("nvim -u NONE"), ["nvim", "-u", "NONE"]);
        assert_eq!(shell_words(r#"code --wait "a b" 'c d' e\ f"#), ["code", "--wait", "a b", "c d", "e f"]);
        assert_eq!(vim_escape(Path::new("/tmp/a b#c")), "/tmp/a\\ b\\#c");
    }
}
