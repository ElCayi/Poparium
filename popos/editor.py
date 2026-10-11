"""The external editor (nvim by default) for a commitment's document."""
import curses
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from popos.document import SUGGESTIONS


def find_editor():
    """$VISUAL, then $EDITOR, then the first editor installed."""
    chosen = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if chosen:
        return shlex.split(chosen)
    found = next((shutil.which(e) for e in ("nvim", "vim", "vi", "nano") if shutil.which(e)), None)
    return [found] if found else None


def vim_escape(path):
    return re.sub(r'([ \\%#|"])', r"\\\1", str(path))


def nvim_helpers(folder):
    """A Lua file for nvim, only for popOS documents: a fixed help bar on top and
    Ctrl+G, a list of suggested sections to insert (buffer-local, so the
    user's own nvim is untouched)."""
    items = ", ".join("{%s, %s}" % (json.dumps(name, ensure_ascii=False), json.dumps(question, ensure_ascii=False))
                      for name, question in SUGGESTIONS)
    lua = f"""vim.opt_local.winbar = " popOS · escribe libre bajo la raya ── · Ctrl+G sección sugerida · ZZ guardar · ZQ salir sin guardar"
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
"""
    path = Path(folder) / "popos-nvim.lua"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(lua)
    return path


def edit_in_editor(screen, path, autosave=None):
    """Hand the terminal to the editor on `path`; True if the file was saved.

    vim and nvim also copy every change to `autosave` as it happens, without
    touching `path` itself, so :q! still means "save nothing".
    """
    editor = find_editor()
    command = [*editor]
    if autosave and Path(editor[0]).name in ("nvim", "vim"):
        # -n: no swap file. The autosave already covers a crash, and nvim's own
        # "ATTENTION: swap file found" prompt would only confuse the recovery
        command += ["-n", "-c", "autocmd TextChanged,TextChangedI,InsertLeave <buffer> silent! keepalt write! "
                    + vim_escape(autosave)]
    if Path(editor[0]).name == "nvim":
        # An auto-save plugin would write even on :q!, and :q! must keep meaning "save nothing"
        command += ["-c", "lua pcall(function() require('auto-save').off() end)",
                    "-c", "luafile " + vim_escape(nvim_helpers(path.parent))]
    before = path.stat().st_mtime_ns
    curses.def_prog_mode()
    curses.endwin()
    try:
        subprocess.call([*command, str(path)])
    except OSError:
        return False
    finally:
        curses.reset_prog_mode()
        screen.refresh()
    return path.stat().st_mtime_ns != before
