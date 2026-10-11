"""Sizes, tabs and the key hints at the bottom."""

TABS = ["OVERVIEW", "ACUERDOS", "CALENDARIO", "BITÁCORA", "REVIEW", "POPARIUM"]


# Fallback when no editor is installed: one line per field
FIELDS = [
    ("title", "Nombre del acuerdo (breve)", True),
    ("pinned", "Nota destacada, la que verás en la ficha (opcional)", False),
    ("body", "Texto libre (opcional; en un editor no tiene límite)", False),
]


JOURNAL_LIMIT = 200  # newest entries the BITÁCORA tab shows


# Below SIDEBAR_W columns the sidebar folds into a tab row on top.
# SIDE_W: the sidebar panels (whose inside fits the 25-column name) plus a gap
MIN_W, MIN_H, SIDEBAR_W, SIDE_W = 50, 20, 86, 30


# Wider than this, the app stops stretching and sits centred: its longest
# lines (sidebar + the widest panel text) set the size, not the screen
MAX_W = 120


# The CALENDARIO tab gives the arrows to the days
MENU_HINTS = [
    "↑↓ menú  ENTER entrar  + añadir experiencia (D/P/B/I)  N nuevo acuerdo  ? ayuda",
    "↑↓ menú  ENTER entrar  + experiencia  N nuevo  ? ayuda",
    "↑↓ menú  ENTER entrar  ? ayuda",
]


CALENDAR_INSIDE_HINTS = [
    "←→↑↓ día  [ ] mes  T hoy  ESC menú  D/P/B/I apuntar en este día  ? ayuda",
    "←→↑↓ día  [ ] mes  T hoy  ESC menú",
]


# Longest first; draw() shows the first one that fits the window width
KEY_HINTS = [
    "↑↓ elegir  ENTER leer  ESC menú  + añadir experiencia (D/P/B/I)  E editar  X estado  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  + experiencia  E editar  X estado  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  + experiencia  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  ? ayuda",
    "←→ pestañas  ↑↓ elegir  ENTER leer  N nuevo  E editar  V versiones  D/P/B/I registrar  R retro  ? ayuda",
    "←→ pestañas  ↑↓ elegir  ENTER leer  N nuevo  E editar  D/P/B/I registrar  ? ayuda",
    "ENTER leer  N nuevo  E editar  V versiones  D/P/B/I registrar  ? ayuda",
    "ENTER leer  N nuevo  E editar  ? ayuda",
]
