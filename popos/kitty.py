"""kitty's graphics protocol, the Unicode placeholder way (it works inside tmux)."""
import os
import subprocess


# kitty's graphics protocol, Unicode placeholder method: the image is sent once,
# then each cell of its area holds U+10EEEE plus two combining marks (row,
# column), coloured with the image id. It is plain text to curses and tmux, so
# it survives redraws and tmux places it right; kitty paints the image there.
KITTY_PLACEHOLDER = "\U0010EEEE"


# First entries of kitty's rowcolumn-diacritics.txt: mark n means row/column n
KITTY_DIACRITICS = [0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
                    0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357]


# Ids under 256 can be given as a 256-colour foreground index
KITTY_LOGO_IDS = range(241, 246)


def kitty_graphics():
    """Whether the terminal at the far end is kitty, and tmux (if any) lets its escapes through.

    POPOS_GRAPHICS=0/1 overrides the guess.
    """
    forced = os.environ.get("POPOS_GRAPHICS")
    if forced in ("0", "1"):
        return forced == "1"
    if os.environ.get("TMUX"):
        try:
            out = subprocess.run(["tmux", "display", "-p", "#{client_termname} #{allow-passthrough}"],
                                 capture_output=True, text=True, timeout=2).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return False
        return len(out) == 2 and "kitty" in out[0] and out[1] in ("on", "all")
    return "kitty" in os.environ.get("TERM", "") or bool(os.environ.get("KITTY_WINDOW_ID"))


def kitty_escape(keys, payload=""):
    """One graphics command, wrapped for tmux's passthrough when inside tmux."""
    command = f"\x1b_G{keys};{payload}\x1b\\" if payload else f"\x1b_G{keys}\x1b\\"
    if os.environ.get("TMUX"):
        command = "\x1bPtmux;" + command.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return command


def kitty_upload(image_id, png_base64, cols, rows):
    """Send a PNG and give it a virtual placement of cols x rows cells, in 4 KB chunks."""
    chunks = [png_base64[i:i + 4096] for i in range(0, len(png_base64), 4096)] or [""]
    out = []
    for n, chunk in enumerate(chunks):
        more = int(n < len(chunks) - 1)
        keys = f"a=T,U=1,f=100,i={image_id},c={cols},r={rows},C=1,q=2,m={more}" if n == 0 else f"m={more}"
        out.append(kitty_escape(keys, chunk))
    return "".join(out)


def kitty_placeholder_row(row, cols, high=0):
    """One row of placeholders. `high`, the image id's top byte, rides as a third mark."""
    mark = chr(KITTY_DIACRITICS[row])
    third = chr(KITTY_DIACRITICS[high]) if high else ""
    return "".join(KITTY_PLACEHOLDER + mark + chr(KITTY_DIACRITICS[col]) + third for col in range(cols))


def farm_image_id(belly, integrated, frame):
    """kitty image id of a meadow Popo: top byte 11-15 by belly, low byte by frame."""
    return ((11 + belly) << 24) | (100 + frame + 5 * integrated)
