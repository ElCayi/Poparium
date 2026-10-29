//! Sizes, tabs and the key hints at the bottom.

pub const TABS: [&str; 6] = ["OVERVIEW", "ACUERDOS", "CALENDARIO", "BITÁCORA", "REVIEW", "POPARIUM"];

pub const OVERVIEW: usize = 0;
pub const ACUERDOS: usize = 1;
pub const CALENDARIO: usize = 2;
pub const BITACORA: usize = 3;
pub const REVIEW: usize = 4;
pub const POPARIUM: usize = 5;

/// Fallback when no editor is installed: one line per field
pub const FIELDS: [(&str, &str, bool); 3] = [
    ("title", "Nombre del acuerdo (breve)", true),
    ("pinned", "Nota destacada, la que verás en la ficha (opcional)", false),
    ("body", "Texto libre (opcional; en un editor no tiene límite)", false),
];

pub const JOURNAL_LIMIT: i64 = 200; // newest entries the BITÁCORA tab shows

// Below SIDEBAR_W columns the sidebar folds into a tab row on top.
// SIDE_W: the sidebar panels (whose inside fits the 25-column name) plus a gap
pub const MIN_W: i32 = 50;
pub const MIN_H: i32 = 20;
pub const SIDEBAR_W: i32 = 86;
pub const SIDE_W: i32 = 30;

/// Wider than this, the app stops stretching and sits centred: its longest
/// lines (sidebar + the widest panel text) set the size, not the screen
pub const MAX_W: i32 = 120;

pub const MENU_HINTS: [&str; 3] = [
    "↑↓ menú  ENTER entrar  + añadir experiencia (D/P/B/I)  N nuevo acuerdo  ? ayuda",
    "↑↓ menú  ENTER entrar  + experiencia  N nuevo  ? ayuda",
    "↑↓ menú  ENTER entrar  ? ayuda",
];

/// The CALENDARIO tab gives the arrows to the days
pub const CALENDAR_INSIDE_HINTS: [&str; 2] = [
    "←→↑↓ día  [ ] mes  T hoy  ESC menú  D/P/B/I apuntar en este día  ? ayuda",
    "←→↑↓ día  [ ] mes  T hoy  ESC menú",
];

/// Longest first; draw() shows the first one that fits the window width
pub const KEY_HINTS: [&str; 8] = [
    "↑↓ elegir  ENTER leer  ESC menú  + añadir experiencia (D/P/B/I)  E editar  X estado  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  + experiencia  E editar  X estado  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  + experiencia  ? ayuda",
    "↑↓ elegir  ENTER leer  ESC menú  ? ayuda",
    "←→ pestañas  ↑↓ elegir  ENTER leer  N nuevo  E editar  V versiones  D/P/B/I registrar  R retro  ? ayuda",
    "←→ pestañas  ↑↓ elegir  ENTER leer  N nuevo  E editar  D/P/B/I registrar  ? ayuda",
    "ENTER leer  N nuevo  E editar  V versiones  D/P/B/I registrar  ? ayuda",
    "ENTER leer  N nuevo  E editar  ? ayuda",
];
