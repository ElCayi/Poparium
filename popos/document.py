"""A commitment as a document: title, pinned note and free Markdown text."""
import difflib
import re


# A commitment is a title (required), a pinned note (optional: what to see at
# a glance in its page) and free Markdown text. No fixed sections: writing
# costs, and a two-line conclusion shouldn't have to cross ten empty headings.
TEXT_FIELDS = ["title", "pinned", "body"]


FIELD_HEADINGS = {"title": "TITLE", "pinned": "NOTA", "body": "TEXTO"}


# Sections offered on demand (Ctrl+G in the editor): plain Markdown once
# inserted, to rename, move or delete. WHY first: the reasons are what keep a
# decision from being argued again from scratch
SUGGESTIONS = [
    ("Por qué me importa", "qué hay en juego para mí"),
    ("Contexto", "qué ocurrió y en qué circunstancias"),
    ("Impacto", "qué consecuencias tuvo y a quién afectó"),
    ("Perspectivas", "argumentos, objeciones y desacuerdos"),
    ("Conclusiones", "qué hemos comprendido o decidido"),
    ("Compromiso", "qué conducta quiero mantener"),
    ("Límites y excepciones", "cuándo se aplica y qué matices tiene"),
    ("Desencadenantes", "qué situaciones lo activan"),
    ("Comprobación", "cómo reconocer que funciona"),
    ("Recuperación", "qué hacer si aparecen dificultades"),
]


# Before 0.3 a commitment had fixed sections. Their columns stay (nothing is
# ever dropped); their text became the free text, each under its heading, and
# COMMITMENT the pinned note
LEGACY_SECTIONS = [("context", "Contexto"), ("reason", "Por qué me importa"), ("reasoning", "Razonamiento"),
                   ("exceptions", "Límites y excepciones"), ("plan", "Próxima acción"), ("cue", "Desencadenantes"),
                   ("success", "Comprobación"), ("recovery", "Recuperación")]


LEGACY_COLUMNS = ["tracking", "agreement"] + [column for column, _ in LEGACY_SECTIONS]


LEGACY_TRACKING = {"periodic": "periódico", "once": "puntual", "reflective": "reflexivo"}


def legacy_document(old):
    """title/pinned/body for a commitment (or a version snapshot) in the old sections."""
    get = lambda key: (old.get(key) if isinstance(old, dict) else old[key] if key in old.keys() else "") or ""
    parts = [f"## {name}\n\n{get(column).strip()}" for column, name in LEGACY_SECTIONS if get(column).strip()]
    if get("tracking") in LEGACY_TRACKING:
        parts.insert(0, f"## Seguimiento\n\n{LEGACY_TRACKING[get('tracking')]}")
    return {"title": get("title"), "pinned": get("agreement").strip(), "body": "\n\n".join(parts)}


TITLE_HEADING = "## TITLE · el nombre del acuerdo (obligatorio)"


NOTE_HEADING = "## NOTA · opcional: lo que verás en la ficha (borra la sección si no la quieres)"


LEGACY_TITLE = re.compile(r"^#(?!#)\s*(.*)$")  # drafts from before TITLE was a section


HEADING = re.compile(r"^##\s+([A-Z][A-Z ]*?)\s*(?:·.*)?$")


def glance(c, lines=3, width=60):
    """What to show of a commitment at a glance: its pinned note, or the first
    lines of its text (without headings) when it has none. (text, is_note)."""
    if c["pinned"]:
        return c["pinned"], True
    plain = [line.strip() for line in (c["body"] or "").splitlines() if line.strip() and not line.startswith("#")]
    return " ".join(plain)[:lines * width], False


def to_markdown(c):
    """The commitment as the document opened in the editor: TITLE, NOTA, a rule,
    and free text under it."""
    return "\n".join([TITLE_HEADING, "", c.get("title") or "", "", NOTE_HEADING, "", c.get("pinned") or "",
                      "", "---", "", c.get("body") or ""]).rstrip() + "\n"


def from_markdown(text):
    """Back from the editor: the first line under TITLE is the title, what is under
    NOTA up to the rule (or the next heading) is the pinned note, the rest is free text.

    Deleting the NOTA section is fine (no note); any other heading is just text.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    title, legacy_title, pinned, body = "", "", [], []
    mode = None  # None (before TITLE), "title", "pinned", "body"
    for line in text.splitlines():
        match = HEADING.match(line)
        key = match.group(1) if match else None
        if key == "TITLE":
            mode = "title"
            continue
        if key in ("NOTA", "NOTE"):
            mode = "pinned"
            continue
        if mode == "title":
            if not title and line.strip():
                title = line.strip().lstrip("#").strip()
                continue
            if not line.strip():
                continue
            mode = "body"
            if line.strip() == "---":
                continue
        elif mode == "pinned":
            if line.strip() == "---":
                mode = "body"
                continue
            if line.startswith("#"):
                mode = "body"
            else:
                pinned.append(line)
                continue
        elif mode is None:
            if line.startswith("> popOS"):  # the help line of older drafts
                continue
            if not legacy_title and LEGACY_TITLE.match(line):
                legacy_title = LEGACY_TITLE.match(line).group(1).strip()
                continue
        body.append(line)
    return {"title": title or legacy_title, "pinned": "\n".join(pinned).strip(), "body": "\n".join(body).strip()}


def version_diff(old, new):
    """What changed between two snapshots, per section, as unified diff lines."""
    out = []
    for column in TEXT_FIELDS:
        before, after = old.get(column) or "", new.get(column) or ""
        if before == after:
            continue
        out.append(f"## {FIELD_HEADINGS[column]}")
        out += [line for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=1)
                if not line.startswith(("---", "+++"))]
    return out
