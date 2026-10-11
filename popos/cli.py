"""The `popos` command."""
import argparse
import curses
import locale
import os
import sys
from popos import APP, TAGLINE, VERSION
from popos.store import DEFAULT_DB, Store
from popos.tmux import tmux_status
from popos.ui.app import App


def main():
    parser = argparse.ArgumentParser(prog="popos", description=f"{APP} {VERSION} · {TAGLINE} — bitácora local de acuerdos y progreso, diseñada para tmux")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ruta de la base de datos SQLite")
    parser.add_argument("--export", action="store_true", help="Exportar Markdown y salir")
    parser.add_argument("--tmux-status", action="store_true",
                        help="Imprimir la cara de Popo para la barra de estado de tmux y salir")
    args = parser.parse_args()
    if args.tmux_status:
        print(tmux_status(args.db))
        return
    locale.setlocale(locale.LC_ALL, "")
    # Sin esto curses espera 1 s tras ESC antes de cancelar un campo
    os.environ.setdefault("ESCDELAY", "25")
    store = Store(args.db)
    try:
        if args.export:
            print(store.export())
        elif not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("la interfaz necesita una terminal interactiva (dentro de tmux funciona)")
        else:
            store.daily_backup()
            curses.wrapper(App(store).run)
    finally:
        store.close()
