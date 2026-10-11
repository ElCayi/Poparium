"""The words of the app: experiences, states, labels and what Popo says."""

STATUS_NAMES = {"active": "activo", "integrated": "integrado", "archived": "archivado"}


# The kinds of experience. A commitment isn't a task that gets done: it stays,
# and experiences pile up on it.
#   done      Aplicación      put it into practice in a real situation
#   progress  Avance          noticed it comes easier than it used to
#   obstacle  Obstáculo       something got in the way (a repair can follow)
#   insight   Descubrimiento  understood something about how I act
#   review    Revisión        reconsidered the strategy (R, a commit)
EVENT_LABELS = {"done": ("APLICACIÓN", "good"), "progress": ("AVANCE", "good"), "obstacle": ("OBSTÁCULO", "warm"),
                "insight": ("DESCUBRIMIENTO", "b"), "review": ("REVISIÓN", "b"), "init": ("NUEVO", "a"),
                "version": ("VERSIÓN", "a")}


LABEL_W = 15


# The calendar's dots: what kind of thing happened that day. Soft colours, and
# a day with no dots is just a quiet day
DAY_KINDS = [
    ("práctica", ("done", "progress"), "good"),
    ("obstáculo", ("obstacle",), "warm"),
    ("descubrimiento", ("insight", "review"), "b"),
    ("cambio", ("init", "version"), "a"),
]


# One key and ENTER: the note is always optional. Writing costs; noting that
# it happened is already worth it
# The four experiences as they are offered (+ or Space): key, kind, name,
# what it means, colour. Also the line at the bottom of a commitment's page
EXPERIENCES = [
    ("d", "done", "Aplicación", "lo he puesto en práctica", "good"),
    ("p", "progress", "Avance", "me cuesta menos que antes", "good"),
    ("b", "obstacle", "Obstáculo", "algo lo dificultó", "warm"),
    ("i", "insight", "Descubrimiento", "he comprendido algo", "b"),
]


LOG_PROMPTS = {
    "done": "Aplicación · ¿qué pasó? (opcional, ENTER y listo)",
    "progress": "Avance · ¿qué notas distinto? (opcional)",
    "obstacle": "Obstáculo · ¿qué ocurrió? (opcional; S en BITÁCORA añade cómo lo reparaste)",
    "insight": "Descubrimiento · ¿qué has comprendido? (opcional)",
}


# What Popo says when something is logged: company, never a verdict
POPO_SAYS = {
    "done": "Popo: «¡Otra experiencia para la barriguita! ♡»",
    "progress": "Popo: «¡Se nota! Lo guardo.»",
    "obstacle": "Popo: «¡Gracias por contármelo! Ahora podemos investigarlo :3»",
    "insight": "Popo: «¡Apuntado! Esto lo guardo con cariño.»",
}
