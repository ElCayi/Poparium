//! A commitment as a document: title, pinned note and free Markdown text.
use crate::pytext::{splitlines, take, unified_diff};

/// A commitment is a title (required), a pinned note (optional: what to see at
/// a glance in its page) and free Markdown text. No fixed sections: writing
/// costs, and a two-line conclusion shouldn't have to cross ten empty headings.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Doc {
    pub title: String,
    pub pinned: String,
    pub body: String,
}

impl Doc {
    pub fn new(title: &str, pinned: &str, body: &str) -> Self {
        Doc { title: title.into(), pinned: pinned.into(), body: body.into() }
    }

    pub fn fields(&self) -> [(&'static str, &str); 3] {
        [("title", &self.title), ("pinned", &self.pinned), ("body", &self.body)]
    }
}

pub const TEXT_FIELDS: [&str; 3] = ["title", "pinned", "body"];

pub fn field_heading(column: &str) -> &'static str {
    match column {
        "title" => "TITLE",
        "pinned" => "NOTA",
        _ => "TEXTO",
    }
}

/// Sections offered on demand (Ctrl+G in the editor): plain Markdown once
/// inserted, to rename, move or delete. WHY first: the reasons are what keep a
/// decision from being argued again from scratch
pub const SUGGESTIONS: [(&str, &str); 10] = [
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
];

/// Before 0.3 a commitment had fixed sections. Their columns stay (nothing is
/// ever dropped); their text became the free text, each under its heading, and
/// COMMITMENT the pinned note
pub const LEGACY_SECTIONS: [(&str, &str); 8] = [
    ("context", "Contexto"),
    ("reason", "Por qué me importa"),
    ("reasoning", "Razonamiento"),
    ("exceptions", "Límites y excepciones"),
    ("plan", "Próxima acción"),
    ("cue", "Desencadenantes"),
    ("success", "Comprobación"),
    ("recovery", "Recuperación"),
];

pub fn legacy_columns() -> Vec<&'static str> {
    let mut columns = vec!["tracking", "agreement"];
    columns.extend(LEGACY_SECTIONS.iter().map(|(column, _)| *column));
    columns
}

fn legacy_tracking(value: &str) -> Option<&'static str> {
    match value {
        "periodic" => Some("periódico"),
        "once" => Some("puntual"),
        "reflective" => Some("reflexivo"),
        _ => None,
    }
}

/// title/pinned/body for a commitment (or a version snapshot) in the old sections.
/// `get` answers "" for what isn't there.
pub fn legacy_document(get: impl Fn(&str) -> String) -> Doc {
    let mut parts: Vec<String> = LEGACY_SECTIONS
        .iter()
        .filter(|(column, _)| !get(column).trim().is_empty())
        .map(|(column, name)| format!("## {name}\n\n{}", get(column).trim()))
        .collect();
    if let Some(tracking) = legacy_tracking(&get("tracking")) {
        parts.insert(0, format!("## Seguimiento\n\n{tracking}"));
    }
    Doc { title: get("title"), pinned: get("agreement").trim().to_string(), body: parts.join("\n\n") }
}

pub const TITLE_HEADING: &str = "## TITLE · el nombre del acuerdo (obligatorio)";

pub const NOTE_HEADING: &str = "## NOTA · opcional: lo que verás en la ficha (borra la sección si no la quieres)";

/// `^##\s+([A-Z][A-Z ]*?)\s*(?:·.*)?$`: a heading of the document template, its key.
fn heading_key(line: &str) -> Option<String> {
    let rest = line.strip_prefix("##")?;
    let trimmed = rest.trim_start();
    if trimmed.len() == rest.len() {
        return None; // \s+ needs at least one
    }
    let before_dot = match trimmed.find('·') {
        Some(at) => &trimmed[..at],
        None => trimmed,
    };
    let key = before_dot.trim_end();
    let mut chars = key.chars();
    if !chars.next().is_some_and(|c| c.is_ascii_uppercase()) {
        return None;
    }
    if !chars.all(|c| c.is_ascii_uppercase() || c == ' ') {
        return None;
    }
    Some(key.trim_end_matches(' ').to_string())
}

/// `^#(?!#)\s*(.*)$`: drafts from before TITLE was a section.
fn legacy_title(line: &str) -> Option<&str> {
    let rest = line.strip_prefix('#')?;
    if rest.starts_with('#') {
        return None;
    }
    Some(rest.trim_start())
}

/// What to show of a commitment at a glance: its pinned note, or the first
/// lines of its text (without headings) when it has none. (text, is_note).
pub fn glance(pinned: &str, body: &str, lines: usize, width: usize) -> (String, bool) {
    if !pinned.is_empty() {
        return (pinned.to_string(), true);
    }
    let plain: Vec<String> = splitlines(body)
        .into_iter()
        .filter(|line| !line.trim().is_empty() && !line.starts_with('#'))
        .map(|line| line.trim().to_string())
        .collect();
    (take(&plain.join(" "), lines * width), false)
}

/// The commitment as the document opened in the editor: TITLE, NOTA, a rule,
/// and free text under it.
pub fn to_markdown(doc: &Doc) -> String {
    let text =
        [TITLE_HEADING, "", &doc.title, "", NOTE_HEADING, "", &doc.pinned, "", "---", "", &doc.body].join("\n");
    format!("{}\n", text.trim_end())
}

fn strip_comments(text: &str) -> String {
    let mut out = String::new();
    let mut rest = text;
    while let Some(start) = rest.find("<!--") {
        match rest[start + 4..].find("-->") {
            Some(end) => {
                out.push_str(&rest[..start]);
                rest = &rest[start + 4 + end + 3..];
            }
            None => break,
        }
    }
    out.push_str(rest);
    out
}

/// Back from the editor: the first line under TITLE is the title, what is under
/// NOTA up to the rule (or the next heading) is the pinned note, the rest is free text.
///
/// Deleting the NOTA section is fine (no note); any other heading is just text.
pub fn from_markdown(text: &str) -> Doc {
    #[derive(PartialEq)]
    enum Mode {
        Before,
        Title,
        Pinned,
        Body,
    }
    let text = strip_comments(text);
    let (mut title, mut old_title) = (String::new(), String::new());
    let (mut pinned, mut body): (Vec<String>, Vec<String>) = (Vec::new(), Vec::new());
    let mut mode = Mode::Before;
    for line in splitlines(&text) {
        let key = heading_key(&line);
        if key.as_deref() == Some("TITLE") {
            mode = Mode::Title;
            continue;
        }
        if matches!(key.as_deref(), Some("NOTA") | Some("NOTE")) {
            mode = Mode::Pinned;
            continue;
        }
        match mode {
            Mode::Title => {
                if title.is_empty() && !line.trim().is_empty() {
                    title = line.trim().trim_start_matches('#').trim().to_string();
                    continue;
                }
                if line.trim().is_empty() {
                    continue;
                }
                mode = Mode::Body;
                if line.trim() == "---" {
                    continue;
                }
            }
            Mode::Pinned => {
                if line.trim() == "---" {
                    mode = Mode::Body;
                    continue;
                }
                if line.starts_with('#') {
                    mode = Mode::Body;
                } else {
                    pinned.push(line);
                    continue;
                }
            }
            Mode::Before => {
                if line.starts_with("> popOS") {
                    continue; // the help line of older drafts
                }
                if old_title.is_empty()
                    && let Some(found) = legacy_title(&line) {
                        old_title = found.trim().to_string();
                        continue;
                    }
            }
            Mode::Body => {}
        }
        body.push(line);
    }
    Doc {
        title: if title.is_empty() { old_title } else { title },
        pinned: pinned.join("\n").trim().to_string(),
        body: body.join("\n").trim().to_string(),
    }
}

/// What changed between two snapshots, per section, as unified diff lines.
pub fn version_diff(old: &Doc, new: &Doc) -> Vec<String> {
    let mut out = Vec::new();
    for ((column, before), (_, after)) in old.fields().into_iter().zip(new.fields()) {
        if before == after {
            continue;
        }
        out.push(format!("## {}", field_heading(column)));
        out.extend(
            unified_diff(&splitlines(before), &splitlines(after), 1)
                .into_iter()
                .filter(|line| !line.starts_with("---") && !line.starts_with("+++")),
        );
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn markdown_round_trip_keeps_long_text_and_own_headings() {
        let doc = Doc::new(
            "Avisar cuando cambien los planes",
            "Si cambia un plan compartido, aviso en cuanto lo sé.",
            "## Por qué me importa · qué hay en juego\n\nNo es pedir permiso.\n\n\
             ### Lo que pensaba yo\n- No siempre se puede anticipar\n\n## CONCLUSIONES\nSin resolver.",
        );
        assert_eq!(from_markdown(&to_markdown(&doc)), doc);
        assert!(to_markdown(&doc).contains("## TITLE"));
        // Deleting the NOTA section leaves no note; text right under the title is free text
        assert_eq!(from_markdown("## TITLE\n\nA\n\nTexto libre\n"), Doc::new("A", "", "Texto libre"));
        assert_eq!(from_markdown("## TITLE\n\nA\n\n---\n\nTexto\n").body, "Texto");
        // Drafts written with older templates still keep their title
        assert_eq!(from_markdown("# Antiguo\n\n## WHY · x\n\nporque").title, "Antiguo");
        assert_eq!(from_markdown("<!-- nada -->## TITLE\nA").title, "A");
    }

    #[test]
    fn headings_match_the_template_only() {
        assert_eq!(heading_key("## TITLE · el nombre").as_deref(), Some("TITLE"));
        assert_eq!(heading_key("##  NOTA").as_deref(), Some("NOTA"));
        assert_eq!(heading_key("## CONCLUSIONES  ").as_deref(), Some("CONCLUSIONES"));
        assert_eq!(heading_key("## Por qué"), None);
        assert_eq!(heading_key("##TITLE"), None);
        assert_eq!(heading_key("### TITLE"), None);
    }

    #[test]
    fn diff_per_section() {
        let old = Doc::new("Avisar", "Coordinarnos", "");
        let new = Doc::new("Avisar", "Coordinarnos, no controlar", "");
        assert_eq!(version_diff(&old, &new), ["## NOTA", "@@ -1 +1 @@", "-Coordinarnos", "+Coordinarnos, no controlar"]);
    }

    #[test]
    fn glance_falls_back_to_the_text() {
        assert_eq!(glance("nota", "texto", 3, 10), ("nota".to_string(), true));
        assert_eq!(glance("", "## Título\n\n uno \ndos", 1, 5), ("uno d".to_string(), false));
    }
}
