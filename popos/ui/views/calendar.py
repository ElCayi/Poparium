"""CALENDARIO: the month, its summary and the chosen day."""
import datetime as dt
from popos.dates import MONTHS, WEEKDAYS, month_grid
from popos.ui.draw import box, put, style, wrap_lines
from popos.vocabulary import DAY_KINDS, EVENT_LABELS


class CalendarView:
    def render_calendar(self, scr, top, bottom, left, width):
        """The month as a grid of days with a dot per kind of thing that happened,
        the month in numbers under it, and what happened on the chosen day beside
        (or under) them."""
        day, today = self.cal_day, dt.date.today()
        weeks = month_grid(day)
        events = self.store.events_between(weeks[0][0], weeks[-1][-1])
        by_day = {}
        for e in events:
            by_day.setdefault(e["day"], []).append(e)
        cell = 7
        grid_w = 7 * cell + 4
        space = bottom - top + 1
        beside = width >= grid_w + 32
        # Days header, the weeks, a blank row and the legend in two rows
        grid_h = min(space, len(weeks) + 6)
        title = f"CALENDARIO · {MONTHS[day.month - 1].capitalize()} {day.year}"
        if self.cal_focus:
            title += " · ESC salir"
        y, x, ih, iw = box(scr, top, left, grid_h, grid_w if beside else width, title,
                           edge=style("a", True) if self.cal_focus else None)
        # A narrow window gets narrower days (down to 5 columns: the number and 2 dots)
        cell = max(5, min(7, iw // 7))
        x += max(0, (iw - 7 * cell) // 2)  # the grid (and its legend) centred in its box
        for i, name in enumerate("LMXJVSD"):
            put(scr, y, x + i * cell + 1, name.rjust(2), style("dim"))
        for row, week in enumerate(weeks):
            for col, date in enumerate(week):
                cx, cy = x + col * cell, y + 1 + row
                if cy > y + ih - 1:
                    break
                number = f"{date.day:>2}"
                if date == day:
                    attr = style("select")
                elif date.month != day.month:
                    attr = style("edge")
                else:
                    attr = style("main", date == today)
                put(scr, cy, cx + 1, number, attr)
                kinds = {e["kind"] for e in by_day.get(date, [])}
                dots = [color for _, members, color in DAY_KINDS if kinds & set(members)][:cell - 3]
                for k, color in enumerate(dots):
                    put(scr, cy, cx + 3 + k, "•", style(color, True))
        legend_y = y + len(weeks) + 2
        for i, (name, _, color) in enumerate(DAY_KINDS):
            ly, lx = legend_y + i // 2, x + 1 + (i % 2) * 22
            if ly <= y + ih - 1:
                put(scr, ly, lx, "• " + name, style(color))
        month = [e for e in events if e["day"].month == day.month and e["kind"] not in ("init", "version")]
        if beside:
            if space - grid_h >= 5:
                self.render_month(scr, top + grid_h, space - grid_h, left, grid_w, day, month)
            self.render_day(scr, top, space, left + grid_w + 1, width - grid_w - 1, by_day.get(day, []))
        elif space - grid_h >= 4:
            self.render_day(scr, top + grid_h, space - grid_h, left, width, by_day.get(day, []))

    def render_month(self, scr, top, height, left, width, day, events):
        """What the month held, in numbers: only what was noted, never what "should" have been."""
        y, x, ih, iw = box(scr, top, left, height, width, f"RESUMEN DE {MONTHS[day.month - 1].upper()}",
                           style("b", True))
        count = lambda *kinds: sum(1 for e in events if e["kind"] in kinds)
        obstacles = count("obstacle")
        repaired = sum(1 for e in events if e["kind"] == "obstacle" and e["repair"])
        rows = [(count("done"), "aplicaciones", "good"), (count("progress"), "avances", "good"),
                (obstacles, "obstáculos" + (f" · {repaired} reparado" + ("s" if repaired != 1 else "")
                                            if repaired else ""), "warm"),
                (count("insight", "review"), "descubrimientos", "b"),
                (len({e["commitment_id"] for e in events}), "acuerdos con experiencias", "a")]
        for i, (n, name, color) in enumerate(rows):
            if i >= ih:
                break
            put(scr, y + i, x, f"{n:02}", style(color, True))
            put(scr, y + i, x + 3, name, style(color), iw - 3)
        if len(rows) < ih:
            put(scr, y + ih - 1, x, "Un mes sin registros no es un mes vacío. ♡" if not events
                else "Toda experiencia cuenta para aprender. ♡", style("dim"), iw)

    def render_day(self, scr, top, height, left, width, events):
        day = self.cal_day
        y, x, ih, iw = box(scr, top, left, height, width,
                           f"{WEEKDAYS[day.weekday()].capitalize()} {day.day} de {MONTHS[day.month - 1]}",
                           style("b", True))
        last = y + ih - 1
        if not events:
            put(scr, y, x, "Un día tranquilo: sin registros.", style("dim"), iw)
            return
        for e in events:
            if y > last:
                break
            label, color = EVENT_LABELS.get(e["kind"], ("LOG", "dim"))
            label = label.capitalize()
            time_of_day = dt.datetime.fromisoformat(e["created_at"]).astimezone().strftime("%H:%M")
            put(scr, y, x, time_of_day, style("dim"), 5)
            put(scr, y, x + 6, label, style(color, True), iw - 6)
            if 6 + len(label) + 3 + len(e["title"]) <= iw:
                put(scr, y, x + 6 + len(label), " · " + e["title"], style("main"), iw - 6 - len(label))
            else:  # a narrow column: the commitment gets its own lines
                for line in wrap_lines(e["title"], iw - 6)[:2]:
                    if y + 1 > last:
                        break
                    y += 1
                    put(scr, y, x + 6, line, style("main"), iw - 6)
            y += 1
            if e["note"] and y <= last:
                put(scr, y, x + 6, "↳ " + e["note"], style("dim"), iw - 6)
                y += 1
            y += 1

    def move_day(self, days=0, months=0):
        day = self.cal_day
        if months:
            month = day.month - 1 + months
            year, month = day.year + month // 12, month % 12 + 1
            following = dt.date(year + (month == 12), month % 12 + 1, 1)
            day = dt.date(year, month, min(day.day, (following - dt.timedelta(days=1)).day))
        self.cal_day = day + dt.timedelta(days=days)
