"""Popo: his drawings, how he grows, his animations and the block-letter name."""
import base64
import json
import struct
import zlib
from pathlib import Path


# The Popo above the name: (frame, ms). Frames: 0 still, 1-2 breathing, 3
# eyes closed, 4 opening. He breathes slowly all the time, a movement small
# enough not to tire; the blink only comes now and then, sometimes double.
BREATH = [(0, 1400), (1, 450), (2, 700), (1, 450)]


LOGO_TIMELINE = (BREATH * 4 + [(3, 140), (4, 90)] + BREATH * 3
                 + [(3, 140), (0, 160), (3, 140), (4, 90)])


LOGO_CYCLE = sum(ms for _, ms in LOGO_TIMELINE)


def popo_png(rgba, frame, belly=1.0, stretch=1.0, zoom=4):
    """One logo frame as a PNG (base64), zoomed and, as he grows, wider or taller."""
    w, h = rgba["size"]
    out_w, out_h = round(w * zoom * belly), round(h * zoom * stretch)
    return base64.b64encode(png_bytes(out_w, out_h, scale_rgba(rgba["frames"][frame], w, h, out_w, out_h))).decode("ascii")


def logo_frame(now_ms):
    """Which frame shows at this moment, and how many ms until the next one."""
    t = now_ms % LOGO_CYCLE
    for frame, ms in LOGO_TIMELINE:
        if t < ms:
            return frame, ms - t
        t -= ms
    return 0, 1


# The name drawn in block letters, 8 px tall: "pop" in Popo's cream, "OS" in
# the app's cyan. Each letter: (color, 8 rows); "#" is a pixel.
WORDMARK = [
    ("cream", ["....", "....", "###.", "#..#", "#..#", "###.", "#...", "#..."]),
    ("cream", ["....", "....", ".##.", "#..#", "#..#", ".##.", "....", "...."]),
    ("cream", ["....", "....", "###.", "#..#", "#..#", "###.", "#...", "#..."]),
    ("a", [".###.", "#...#", "#...#", "#...#", "#...#", ".###.", ".....", "....."]),
    ("a", [".###", "#...", ".##.", "...#", "...#", "###.", "....", "...."]),
]


def wordmark_cells():
    """The wordmark as 4 rows of (char, color) half-block cells, one column gap between letters."""
    rows = []
    for y in range(0, 8, 2):
        row = []
        for i, (color, glyph) in enumerate(WORDMARK):
            for top, bottom in zip(glyph[y], glyph[y + 1]):
                char = {("#", "#"): "█", ("#", "."): "▀", (".", "#"): "▄"}.get((top, bottom), " ")
                row.append((char, color))
            if i < len(WORDMARK) - 1:
                row.append((" ", color))
        rows.append(row)
    return rows


POPO_FILE = Path(__file__).resolve().parent / "assets" / "popo.json"


def load_popo(path=POPO_FILE):
    """Popo's frames from tools/popo_assets.py output; None when the art is missing."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        states = {name: [zlib.decompress(base64.b64decode(f)) for f in frames]
                  for name, frames in data["states"].items()}
    except (OSError, ValueError, KeyError, zlib.error):
        return None
    # logo: rows of [char, fg, bg] half-block cells, None where empty
    # logo_rgba: the same frames as raw pixels, to make PNGs for kitty at any width
    rgba = data.get("logo_rgba")
    if rgba:
        rgba = {"size": tuple(rgba["size"]), "frames": [zlib.decompress(base64.b64decode(f)) for f in rgba["frames"]]}
    return {"size": data["size"], "ms": data["ms"], "states": states, "logo": data.get("logo"), "logo_rgba": rgba}


def scale_rgba(raw, w, h, out_w, out_h):
    """Nearest-neighbour resize of raw RGBA: pixel art stays crisp, even stretched."""
    cols = [min(w - 1, x * w // out_w) for x in range(out_w)]
    lines = {}
    rows = []
    for oy in range(out_h):
        sy = min(h - 1, oy * h // out_h)
        if sy not in lines:
            line = raw[sy * w * 4:(sy + 1) * w * 4]
            lines[sy] = b"".join(line[c * 4:c * 4 + 4] for c in cols)
        rows.append(lines[sy])
    return rows


def png_bytes(width, height, rows):
    """A minimal RGBA PNG from rows of raw pixels (no imaging library needed)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# Popo is always glad to be there: what he does never reacts to the last thing
# logged (an obstacle is not a sad Popo, a success is not a prouder one). What
# changes is his belly, which grows with every experience, and the stretch he
# gets when a commitment becomes INTEGRADO.
PLAYFUL = ["idle", "hello", "think", "reading", "coding", "comfort"]


GROWTH = [0, 3, 8, 15, 25]  # experiences for each belly size


BELLY = [1.0, 1.08, 1.16, 1.24, 1.32]  # how much wider he gets


STRETCH = 1.18  # how much taller an INTEGRADO Popo is


# The farm: a meadow where the Popos wander on their own. A first sketch: the
# rules are simple on purpose, to grow from
FARM_TICK = 0.2  # seconds per step of the herd


FARM_POPO = (12, 6)  # a Popo's base size in the meadow, in cells


def growth(experiences):
    """Belly size 0-4 for a number of experiences."""
    return max(i for i, need in enumerate(GROWTH) if experiences >= need)


def popo_look(commitment, experiences):
    """(animation, words under him) for a commitment's Popo."""
    if commitment["status"] == "archived":
        return "sleep", "descansando"
    if commitment["status"] == "integrated":
        return "hello", "integrado ♡"
    words = f"{experiences} experiencia" + ("" if experiences == 1 else "s")
    return PLAYFUL[commitment["id"] % len(PLAYFUL)], words
