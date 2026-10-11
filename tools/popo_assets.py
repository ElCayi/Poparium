#!/usr/bin/env python3
"""Turn the Popo sprite strips into assets/popo.json for the POPARIUM tab and the logo.

Run once after changing the art (needs ImageMagick's `magick`):

    nix shell nixpkgs#imagemagick nixpkgs#python3 -c python3 tools/popo_assets.py

Each 64x64 frame is shrunk to SIZE px and every pixel is mapped to the
xterm-256 palette, the most curses can draw inside tmux. Then similar colors
are merged until the sprites need at most MAX_PAIRS color pairs: curses
only has ~240 to give out, and each (top, bottom) pixel combination of a
half block needs one.
Pixel 0 means transparent; any other value is that xterm color (only
16-255 are ever produced, so 0 is free).
"""
import base64
import json
import math
from pathlib import Path
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "popo-src"
OUT = ROOT / "popos" / "assets" / "popo.json"
SIZE = 32
# The small Popo above the name: the original idle frames shrunk to exactly
# 1/4 (each pixel is a whole 4x4 block of the original), so it stays crisp.
# 12x6 half-block cells is close to a square on terminal fonts (cells ~1:2.2)
LOGO_SCALE = 4
LOGO_BOX = (48, 48, 8, 11)  # width, height, x, y inside the 64x64 frame: Popo plus headroom
LOGO_FRAMES = [0, 3, 6, 9, 10]  # idle: still, breathing in, breathing out, eyes closed, opening
# In kitty, Popo is the drawing itself (kitty's graphics protocol). The app
# gets these frames' pixels and makes the PNGs, at whatever width he has grown to
CREAM = (253, 240, 223)
# Popo's near-black (outline, eyes, mouth, and the dark edges of what he holds)
# becomes the app's cyan, xterm 45. The original keeps a few dark steps; they
# stay as darker cyans. Coloured darks (the blanket, the book) are above DARK.
CYAN = (0x00, 0xD7, 0xFF)
DARK = 100  # r + g + b below this is "black"
FRAME = 64
FREE_PAIRS = 247  # pairs 1-8 are the app's own, 9-255 are free (curses attrs hold 8 bits)
RESIZE = ["-filter", "Box", "-resize"]  # 64 -> 32 is exactly 2x2 px per pixel

CUBE = (0, 95, 135, 175, 215, 255)


def distance(c1, c2):
    """'Redmean' color distance: closer to how the eye judges it than plain RGB."""
    rm = (c1[0] + c2[0]) / 2
    dr, dg, db = (a - b for a, b in zip(c1, c2))
    return (2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db


# base16 themes (Stylix) repaint 16-21 with their extra colours: never use them
THEMED = range(16, 22)


def xterm256(r, g, b):
    """Nearest xterm-256 color (6x6x6 cube or grey ramp), never one of THEMED."""
    color = _xterm256(r, g, b)
    if color in THEMED:
        allowed = [c for c in range(22, 256)]
        color = min(allowed, key=lambda c: distance(rgb(c), (r, g, b)))
    return color


def _xterm256(r, g, b):
    def nearest(v):
        return min(range(6), key=lambda i: abs(CUBE[i] - v))
    ri, gi, bi = nearest(r), nearest(g), nearest(b)
    cube = (16 + 36 * ri + 6 * gi + bi, (CUBE[ri], CUBE[gi], CUBE[bi]))
    level = min(23, max(0, round((((r + g + b) / 3) - 8) / 10)))
    grey = (232 + level, (8 + 10 * level,) * 3)
    return min((cube, grey), key=lambda c: distance(c[1], (r, g, b)))[0]


def rgb(color):
    if color >= 232:
        return (8 + 10 * (color - 232),) * 3
    c = color - 16
    return CUBE[c // 36], CUBE[c // 6 % 6], CUBE[c % 6]


def pair_count(states, target):
    pairs = set()
    for px in (px for frs in states.values() for px in frs):
        size = math.isqrt(len(px))
        for y in range(0, size, 2):
            for x in range(size):
                pairs.add((target[px[y * size + x]], target[px[(y + 1) * size + x]]))
    return len(pairs)


def reduce_palette(counts, states, max_pairs):
    """Merge the two closest colors until the pairs fit; returns old -> new.

    Merging by distance, not dropping the least used, keeps small but
    distinct details (blush, sparkles, the zzz) in their own color.
    """
    colors = dict(counts)
    target = {c: c for c in colors}
    target[0] = 0
    while pair_count(states, target) > max_pairs:
        a, b = min(((a, b) for a in colors for b in colors if a < b),
                   key=lambda ab: distance(rgb(ab[0]), rgb(ab[1])))
        big, small = (a, b) if colors[a] >= colors[b] else (b, a)
        colors[big] += colors.pop(small)
        for old, new in target.items():
            if new == small:
                target[old] = big
    return target


def frame_rgba(strip, index):
    """One original 64x64 frame as raw RGBA, its blacks turned cyan."""
    raw = bytearray(subprocess.check_output(["magick", strip, "-crop", f"{FRAME}x{FRAME}+{index * FRAME}+0",
                                             "+repage", "-depth", "8", "rgba:-"]))
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i:i + 4]
        if a >= 128 and r + g + b < DARK:
            k = 0.75 + 0.25 * (r + g + b) / DARK
            raw[i:i + 3] = bytes(min(255, int(c * k)) for c in CYAN)
    return bytes(raw)


def frames(strip, size=SIZE, count=None):
    count = count or int(subprocess.check_output(["magick", "identify", "-format", "%w", strip])) // FRAME
    for i in range(count):
        raw = subprocess.run(["magick", "-size", f"{FRAME}x{FRAME}", "-depth", "8", "rgba:-",
                              *RESIZE, f"{size}x{size}", "-depth", "8", "rgba:-"],
                             input=frame_rgba(strip, i), capture_output=True, check=True).stdout
        pixels = bytearray()
        for p in range(0, len(raw), 4):
            r, g, b, a = raw[p:p + 4]
            pixels.append(0 if a < 128 else xterm256(r, g, b))
        yield pixels


def dominant_downscale(pixels, size, w, h):
    """Each new pixel takes the dominant color of its block instead of a blend.

    Dark pixels (eyes, mouth, outline) win when they are a real part of the
    block, or the face would vanish at this size.
    """
    out = []
    for ty in range(h):
        for tx in range(w):
            ys = range(ty * size // h, max(ty * size // h + 1, (ty + 1) * size // h))
            xs = range(tx * size // w, max(tx * size // w + 1, (tx + 1) * size // w))
            block = [pixels[y * size + x] for y in ys for x in xs]
            opaque = [c for c in block if c]
            if len(opaque) * 2 < len(block):
                out.append(None)
                continue
            dark = [c for c in opaque if sum(c) < 250]
            pick = dark if dark and len(dark) * 4 >= len(opaque) else opaque
            out.append(max(set(pick), key=pick.count))
    return out


def logo_rgba(strip, index):
    """One idle frame cut to LOGO_BOX, as raw RGBA, with only Popo's body.

    Some idle frames carry a lone sparkle pixel well away from him; at logo
    size it reads as a stray dot, so anything not joined to the body goes.
    """
    bw, bh, bx, by = LOGO_BOX
    frame = frame_rgba(strip, index)
    raw = bytearray(b"".join(frame[4 * ((by + y) * FRAME + bx):4 * ((by + y) * FRAME + bx + bw)] for y in range(bh)))
    opaque = {i // 4 for i in range(0, len(raw), 4) if raw[i + 3] >= 128}
    groups, seen = [], set()
    for start in opaque:
        if start in seen:
            continue
        seen.add(start)
        stack, group = [start], []
        while stack:
            p = stack.pop()
            group.append(p)
            y, x = divmod(p, bw)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (y + dy) * bw + x + dx
                    if 0 <= y + dy < bh and 0 <= x + dx < bw and n in opaque and n not in seen:
                        seen.add(n)
                        stack.append(n)
        groups.append(group)
    body = set(max(groups, key=len)) if groups else set()
    for p in opaque - body:
        raw[4 * p:4 * p + 4] = b"\0\0\0\0"
    return bytes(raw)


def logo_cells(strip, index):
    """One frame as rows of [char, fg, bg] half-block cells (or None).

    Near-cream shading turns into plain cream so the body isn't speckled.
    """
    bw, bh, _, _ = LOGO_BOX
    w, h = bw // LOGO_SCALE, bh // LOGO_SCALE
    raw = logo_rgba(strip, index)
    source = [None if raw[p + 3] < 128 else tuple(raw[p:p + 3]) for p in range(0, len(raw), 4)]
    px = [None if c is None else xterm256(*(CREAM if distance(c, CREAM) < 3000 else c))
          for c in dominant_downscale(source, bw, w, h)]
    rows = []
    for row in range(0, h, 2):
        cells = []
        for col in range(w):
            top, bottom = px[row * w + col], px[(row + 1) * w + col]
            if top is None and bottom is None:
                cells.append(None)
            elif top is None:
                cells.append(["▄", bottom, -1])
            else:
                cells.append(["▀", top, -1 if bottom is None else bottom])
        rows.append(cells)
    return rows


def main():
    meta = json.loads((SRC / "animations.json").read_text(encoding="utf-8"))
    states = {name: list(frames(SRC / info["sprite_strip"])) for name, info in meta["states"].items()}
    idle = SRC / meta["states"]["idle"]["sprite_strip"]
    logo = [logo_cells(idle, index) for index in LOGO_FRAMES]
    logo_rgba_frames = [base64.b64encode(zlib.compress(logo_rgba(idle, index), 9)).decode("ascii")
                        for index in LOGO_FRAMES]
    logo_pairs = {(c[1], c[2]) for frame in logo for row in frame for c in row if c}
    counts = {}
    for pixels in (px for frs in states.values() for px in frs):
        for v in pixels:
            if v:
                counts[v] = counts.get(v, 0) + 1
    # The logo's pairs come first; the animations share what is left
    target = reduce_palette(counts, states, FREE_PAIRS - len(logo_pairs))
    states = {name: [base64.b64encode(zlib.compress(bytes(target[v] for v in px), 9)).decode("ascii")
                     for px in frs] for name, frs in states.items()}
    OUT.write_text(json.dumps({"size": SIZE, "ms": meta["frame_duration_ms"], "states": states, "logo": logo,
                               "logo_rgba": {"size": LOGO_BOX[:2], "frames": logo_rgba_frames}},
                              separators=(",", ":")), encoding="utf-8")
    print(f"{OUT}: {len(states)} estados + logo, {OUT.stat().st_size} bytes, logo {len(logo_pairs)} pares de color")


if __name__ == "__main__":
    main()
