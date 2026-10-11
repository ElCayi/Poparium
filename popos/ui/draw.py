"""Drawing in curses: colours, text, panels and rows of figures."""
import curses
import textwrap


# Colors: cyan, lavender, green, amber, muted, white, selected, border
COLOR = {"a": 1, "b": 2, "good": 3, "warm": 4, "dim": 5, "main": 6, "select": 7, "edge": 8}


def setup_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    palette = [
        (1, 45, -1), (2, 141, -1), (3, 84, -1), (4, 215, -1),
        # Selected text: 233, the grey ramp's near-black. Not 16: base16 themes
        # (Stylix) repaint 16-21 with their extra colours, and 16 becomes orange
        (5, 244, -1), (6, 255, -1), (7, 233, 45), (8, 60, -1),
    ] if curses.COLORS >= 256 else [
        (1, curses.COLOR_CYAN, -1), (2, curses.COLOR_MAGENTA, -1),
        (3, curses.COLOR_GREEN, -1), (4, curses.COLOR_YELLOW, -1),
        (5, curses.COLOR_BLUE, -1), (6, curses.COLOR_WHITE, -1),
        (7, curses.COLOR_BLACK, curses.COLOR_CYAN), (8, curses.COLOR_BLUE, -1),
    ]
    for ident, fg, bg in palette:
        try:
            curses.init_pair(ident, fg, bg)
        except curses.error:
            pass


LANE_COLORS = ("a", "b", "good", "warm")


def lane_style(commitment_id, bold=False):
    """Each commitment keeps the same lane color, like branches in a git GUI."""
    return style(LANE_COLORS[(commitment_id or 0) % len(LANE_COLORS)], bold)


def style(name, bold=False):
    attr = curses.color_pair(COLOR.get(name, 6)) if curses.has_colors() else 0
    # The selection is always bold: dark letters on cyan need the weight
    if bold or name == "select":
        attr |= curses.A_BOLD
    return attr


def put(win, y, x, message, attr=0, maxlen=None):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w or x < 0:
        return
    width = min(w - x - 1, maxlen if maxlen is not None else w)
    if width <= 0:
        return
    text = str(message).replace("\n", " ").replace("\t", "  ")
    try:
        win.addnstr(y, x, text, width, attr)
    except (curses.error, ValueError):
        pass


def rule(win, y, x, width):
    put(win, y, x, "─" * max(0, width), style("edge"), width)


def box(win, y, x, height, width, title="", title_attr=None, edge=None):
    """A rounded panel with its title on the top border.

    Returns the inside as (y, x, height, width), one column of padding on each side.
    """
    if height < 2 or width < 6:
        return y, x, 0, 0
    edge = style("edge") if edge is None else edge
    put(win, y, x, "╭" + "─" * (width - 2) + "╮", edge, width)
    for row in range(y + 1, y + height - 1):
        put(win, row, x, "│", edge)
        put(win, row, x + width - 1, "│", edge)
    put(win, y + height - 1, x, "╰" + "─" * (width - 2) + "╯", edge, width)
    if title:
        put(win, y, x + 2, f" {title} ", style("a", True) if title_attr is None else title_attr, width - 4)
    return y + 1, x + 2, height - 2, width - 4


def fit_figures(figures, width, gaps=(7, 4, 2)):
    """Lay out (n, name, short name, colour) figures so they never break their box.

    Tries the full names with a generous gap, then tighter, then the short
    names (EXP for EXPERIENCIAS...), and only then spreads them over more rows.
    Returns rows of (column, "07", name, colour).
    """
    for use_short in (False, True):
        for gap in gaps:
            cells = [(f"{n:02}", short if use_short else name, color) for n, name, short, color in figures]
            if sum(3 + len(name) for _, name, _ in cells) + gap * (len(cells) - 1) <= width:
                row, col = [], 0
                for number, name, color in cells:
                    row.append((col, number, name, color))
                    col += 3 + len(name) + gap
                return [row]
    rows, row, col = [], [], 0
    for n, _, short, color in figures:
        if row and col + 3 + len(short) > width:
            rows.append(row)
            row, col = [], 0
        row.append((col, f"{n:02}", short, color))
        col += 3 + len(short) + 2
    return rows + [row]


def draw_figures(win, y, x, rows):
    for r, row in enumerate(rows):
        for col, number, name, color in row:
            put(win, y + r, x + col, number, style(color, True))
            put(win, y + r, x + col + 3, name, style(color))


def wrap_lines(text, width):
    out = []
    for paragraph in (str(text or "—").split("\n")):
        out.extend(textwrap.wrap(paragraph, width=max(8, width), break_long_words=True) or [""])
    return out
