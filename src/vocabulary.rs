//! The words of the app: experiences, states, labels and what Popo says.

pub fn status_name(status: &str) -> &'static str {
    match status {
        "active" => "activo",
        "integrated" => "integrado",
        "archived" => "archivado",
        _ => "",
    }
}

// The kinds of experience. A commitment isn't a task that gets done: it stays,
// and experiences pile up on it.
//   done      Aplicación      put it into practice in a real situation
//   progress  Avance          noticed it comes easier than it used to
//   obstacle  Obstáculo       something got in the way (a repair can follow)
//   insight   Descubrimiento  understood something about how I act
//   review    Revisión        reconsidered the strategy (R, a commit)
pub fn event_label(kind: &str) -> Option<(&'static str, &'static str)> {
    Some(match kind {
        "done" => ("APLICACIÓN", "good"),
        "progress" => ("AVANCE", "good"),
        "obstacle" => ("OBSTÁCULO", "warm"),
        "insight" => ("DESCUBRIMIENTO", "b"),
        "review" => ("REVISIÓN", "b"),
        "init" => ("NUEVO", "a"),
        "version" => ("VERSIÓN", "a"),
        _ => return None,
    })
}

pub const LABEL_W: usize = 15;

/// The calendar's dots: what kind of thing happened that day. Soft colours, and
/// a day with no dots is just a quiet day
pub const DAY_KINDS: [(&str, &[&str], &str); 4] = [
    ("práctica", &["done", "progress"], "good"),
    ("obstáculo", &["obstacle"], "warm"),
    ("descubrimiento", &["insight", "review"], "b"),
    ("cambio", &["init", "version"], "a"),
];

/// One key and ENTER: the note is always optional. Writing costs; noting that
/// it happened is already worth it.
/// The four experiences as they are offered (+ or Space): key, kind, name,
/// what it means, colour. Also the line at the bottom of a commitment's page
pub const EXPERIENCES: [(char, &str, &str, &str, &str); 4] = [
    ('d', "done", "Aplicación", "lo he puesto en práctica", "good"),
    ('p', "progress", "Avance", "me cuesta menos que antes", "good"),
    ('b', "obstacle", "Obstáculo", "algo lo dificultó", "warm"),
    ('i', "insight", "Descubrimiento", "he comprendido algo", "b"),
];

pub fn log_prompt(kind: &str) -> &'static str {
    match kind {
        "done" => "Aplicación · ¿qué pasó? (opcional, ENTER y listo)",
        "progress" => "Avance · ¿qué notas distinto? (opcional)",
        "obstacle" => "Obstáculo · ¿qué ocurrió? (opcional; S en BITÁCORA añade cómo lo reparaste)",
        _ => "Descubrimiento · ¿qué has comprendido? (opcional)",
    }
}

/// What Popo says when something is logged: company, never a verdict
pub fn popo_says(kind: &str) -> &'static str {
    match kind {
        "done" => "Popo: «¡Otra experiencia para la barriguita! ♡»",
        "progress" => "Popo: «¡Se nota! Lo guardo.»",
        "obstacle" => "Popo: «¡Gracias por contármelo! Ahora podemos investigarlo :3»",
        _ => "Popo: «¡Apuntado! Esto lo guardo con cariño.»",
    }
}
