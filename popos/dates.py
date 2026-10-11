"""Dates: UTC stamps, how they read, and the month grid."""
import datetime as dt


def stamp():
    # Siempre en UTC: el texto ISO se ordena bien aunque cambie la hora (verano/invierno)
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def display_date(value):
    try:
        return dt.datetime.fromisoformat(value).astimezone().strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return str(value)[:16]


MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def month_grid(day):
    """The Monday-first weeks (lists of 7 dates) that show the month of `day`."""
    first = day.replace(day=1)
    following = dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    monday = first - dt.timedelta(days=first.weekday())
    weeks = []
    while monday < following:
        weeks.append([monday + dt.timedelta(days=i) for i in range(7)])
        monday += dt.timedelta(days=7)
    return weeks
