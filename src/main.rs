//! Poparium · Memoria entre sesiones: the `poparium` command.
mod dates;
mod document;
mod drafts;
mod editor;
mod history;
mod kitty;
mod popo;
mod pyrandom;
mod pytext;
mod store;
mod tmux;
mod ui;
mod vocabulary;

use std::io::IsTerminal;
use std::path::PathBuf;

pub const APP: &str = "Poparium";
pub const VERSION: &str = "v0.1";
pub const TAGLINE: &str = "Memoria entre sesiones";

const USAGE: &str = "usage: poparium [-h] [--db DB] [--export] [--tmux-status] [--tmux-status-push]";

fn help() -> String {
    format!(
        "{USAGE}\n\n{APP} {VERSION} · {TAGLINE} — bitácora local de acuerdos y progreso, diseñada para tmux\n\n\
         options:\n  \
         -h, --help          show this help message and exit\n  \
         --db DB             Ruta de la base de datos SQLite (por defecto, {})\n  \
         --export            Exportar Markdown y salir\n  \
         --tmux-status       Imprimir la cara de Popo para la barra de estado de tmux y salir\n  \
         --tmux-status-push  Escribir la cara de Popo en la opción @poparium-status de tmux y salir",
        store::default_db().display()
    )
}

fn fail(message: &str) -> ! {
    eprintln!("{USAGE}\npoparium: error: {message}");
    std::process::exit(2);
}

#[derive(Default)]
struct Args {
    db: Option<PathBuf>,
    export: bool,
    tmux_status: bool,
    tmux_status_push: bool,
}

fn parse_args(raw: &[String]) -> Args {
    let mut args = Args::default();
    let mut words = raw.iter();
    while let Some(word) = words.next() {
        match word.as_str() {
            "-h" | "--help" => {
                println!("{}", help());
                std::process::exit(0);
            }
            "--db" => match words.next() {
                Some(path) => args.db = Some(PathBuf::from(path)),
                None => fail("argument --db: expected one argument"),
            },
            "--export" => args.export = true,
            "--tmux-status" => args.tmux_status = true,
            "--tmux-status-push" => args.tmux_status_push = true,
            other => match other.strip_prefix("--db=") {
                Some(path) => args.db = Some(PathBuf::from(path)),
                None => fail(&format!("unrecognized arguments: {other}")),
            },
        }
    }
    args
}

/// Without arguments and outside tmux, Poparium opens in its own tmux session
/// (`poparium`), created or picked up again; inside tmux it opens right there.
fn into_tmux_session() {
    use std::os::unix::process::CommandExt;
    if std::env::var("TMUX").is_ok_and(|t| !t.is_empty()) {
        return;
    }
    let Ok(me) = std::env::current_exe() else { return };
    let found = std::env::var_os("PATH")
        .is_some_and(|paths| std::env::split_paths(&paths).any(|dir| dir.join("tmux").is_file()));
    if !found {
        return;
    }
    // Only returns if tmux couldn't be started: then Poparium opens here
    let _ = std::process::Command::new("tmux").args(["new-session", "-A", "-s", "poparium"]).arg(me).exec();
}

/// With panic = "abort" nothing unwinds: give the terminal back before dying.
fn restore_terminal_on_panic() {
    let default = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let _ = std::io::Write::write_all(&mut std::io::stdout(), b"\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l");
        let _ = crossterm::terminal::disable_raw_mode();
        default(info);
    }));
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    if raw.is_empty() {
        into_tmux_session();
    }
    let args = parse_args(&raw);
    if args.tmux_status {
        // Runs every few seconds: it never moves the old folder, it only reads
        println!("{}", tmux::tmux_status(&args.db.unwrap_or_else(store::default_db)));
        return;
    }
    if args.tmux_status_push {
        // Once when the tmux server starts: the app keeps it current from then on
        tmux::push_status(tmux::unsaved_drafts(&args.db.unwrap_or_else(store::default_db)));
        return;
    }
    let db = args.db.unwrap_or_else(|| {
        if std::env::var_os("POPARIUM_DB").is_some() {
            store::default_db()
        } else {
            store::adopt_legacy_folders()
        }
    });
    let store = match store::Store::open(&db) {
        Ok(store) => store,
        Err(error) => {
            eprintln!("poparium: no se pudo abrir la libreta {}: {error}", db.display());
            std::process::exit(1);
        }
    };
    if args.export {
        match store.export() {
            Ok(out) => println!("{}", out.display()),
            Err(error) => {
                eprintln!("poparium: no se pudo exportar: {error}");
                std::process::exit(1);
            }
        }
        return;
    }
    if !std::io::stdin().is_terminal() || !std::io::stdout().is_terminal() {
        fail("la interfaz necesita una terminal interactiva (dentro de tmux funciona)");
    }
    let _ = store.daily_backup(None);
    restore_terminal_on_panic();
    let term = match ui::term::Term::start() {
        Ok(term) => term,
        Err(error) => {
            eprintln!("poparium: no se pudo preparar la terminal: {error}");
            std::process::exit(1);
        }
    };
    ui::app::App::new(store, term).run();
}
