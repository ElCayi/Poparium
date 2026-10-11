"""POPARIUM: the meadow where the Popos wander."""
import curses
import os
import random
import sys
import time
from popos.kitty import KITTY_LOGO_IDS, farm_image_id, kitty_placeholder_row, kitty_upload
from popos.popo import BELLY, FARM_POPO, FARM_TICK, STRETCH, growth, logo_frame, popo_look, popo_png
from popos.ui.draw import box, put, style


class PopariumView:
    def render_farm(self, scr, top, bottom, left, width):
        """The meadow: every commitment's Popo wanders about on its own. Wider
        with experiences, taller once integrated; the archived ones (A) sleep."""
        y, x, ih, iw = box(scr, top, left, bottom - top + 1, width, "POPARIUM · los Popos andan a su aire",
                           edge=style("a", True) if self.inside else None)
        items = self.current_items()
        if not items:
            put(scr, y, x, "El Poparium está vacío. Cada acuerdo nuevo (N) trae su Popo.", style("dim"), iw)
            return
        counts = self.store.experience_counts()
        experiences = {item["id"]: sum(counts.get(item["id"], {}).values()) for item in items}
        field_h = ih - 1  # the last row tells who the chosen Popo is
        base_w, base_h = FARM_POPO
        if not (self.popo and self.popo.get("logo")) or field_h < base_h + 1 or iw < round(base_w * BELLY[-1]) + 2:
            put(scr, y, x, "Agranda la ventana para ver el prado.", style("warm"), iw)
            for i, item in enumerate(items[:ih - 2]):
                chosen = i == self.selected
                put(scr, y + 2 + i, x, ("▸ " if chosen else "  ") + f"🐾 {item['title']} · "
                    f"{popo_look(item, experiences[item['id']])[1]}", style("select") if chosen else style("main"), iw)
            return
        # Grass: the same few blades every time, scattered over the meadow
        blades = random.Random(iw * 1000 + field_h)
        for _ in range(iw * field_h // 45):
            put(scr, y + blades.randrange(field_h), x + blades.randrange(iw), blades.choice("',.\""), style("good"))
        # Each Popo's size, then one step of the herd for every FARM_TICK gone by
        sizes = {}
        for item in items:
            belly = growth(experiences[item["id"]])
            sizes[item["id"]] = (round(base_w * BELLY[belly]), base_h + (item["status"] == "integrated"), belly)
        self.walk_herd(items, sizes, iw, field_h)
        # Draw the far ones first, so the near ones (lower) overlap them
        chosen_id = items[min(self.selected, len(items) - 1)]["id"]
        now_ms = int(time.monotonic() * 1000)
        for item in sorted(items, key=lambda i: self.herd[i["id"]]["y"]):
            spot = self.herd[item["id"]]
            cols, rows, belly = sizes[item["id"]]
            # Out of step with each other: each breathes on its own clock
            frame = 0 if item["status"] == "archived" else logo_frame(now_ms + item["id"] * 1700)[0]
            self.draw_meadow_popo(scr, y + spot["y"], x + int(spot["x"]), cols, rows, belly,
                                  item["status"] == "integrated", frame)
            if item["id"] == chosen_id and spot["y"] > 0:
                name = item["title"][:cols + 8]
                put(scr, y + spot["y"] - 1, x + int(spot["x"]) + max(0, (cols - len(name)) // 2), name, style("select"))
        chosen = next(i for i in items if i["id"] == chosen_id)
        put(scr, y + ih - 1, x, f"▸ {chosen['title']} · {popo_look(chosen, experiences[chosen_id])[1]}"
            "  ·  ↑↓ elegir  ENTER leer", style("dim"), iw)

    def walk_herd(self, items, sizes, field_w, field_h):
        """Move every Popo one step per FARM_TICK since the last time: walk on,
        sometimes stop to breathe, turn round or drift a row. Archived ones sleep."""
        alive = {item["id"] for item in items}
        for gone in set(self.herd) - alive:
            del self.herd[gone]
        for item in items:
            cols, rows, _ = sizes[item["id"]]
            if item["id"] not in self.herd:
                start = random.Random(item["id"])
                self.herd[item["id"]] = {"x": float(start.randrange(max(1, field_w - cols))),
                                         "y": start.randrange(max(1, field_h - rows + 1)),
                                         "dx": start.choice((-1, 1)), "pause": start.randrange(10)}
        now = time.monotonic()
        steps = min(25, int((now - self.herd_clock) / FARM_TICK))
        self.herd_clock += steps * FARM_TICK
        if steps == 25:
            self.herd_clock = now
        for item in items:
            spot = self.herd[item["id"]]
            cols, rows, _ = sizes[item["id"]]
            for _ in range(steps if item["status"] != "archived" else 0):
                if spot["pause"]:
                    spot["pause"] -= 1
                    continue
                roll = random.random()
                if roll < 0.03:
                    spot["pause"] = random.randint(5, 25)  # stops to breathe a while
                elif roll < 0.05:
                    spot["dx"] = -spot["dx"]
                elif roll < 0.07:
                    spot["y"] += random.choice((-1, 1))
                spot["x"] += spot["dx"]
                if spot["x"] <= 0 or spot["x"] >= field_w - cols:
                    spot["dx"] = 1 if spot["x"] <= 0 else -1
            spot["x"] = min(max(0.0, spot["x"]), float(max(0, field_w - cols)))
            spot["y"] = min(max(0, spot["y"]), max(0, field_h - rows))

    def draw_meadow_popo(self, scr, y, x, cols, rows, belly, integrated, frame):
        """A Popo in the meadow: kitty's real image, or half blocks stretched as wide."""
        rgba = self.popo.get("logo_rgba")
        if self.kitty_logo and rgba:
            if (belly, integrated) not in self.kitty_farm:
                data = "".join(kitty_upload(farm_image_id(belly, integrated, f),
                                            popo_png(rgba, f, BELLY[belly], STRETCH if integrated else 1.0), cols, rows)
                               for f in range(len(KITTY_LOGO_IDS)))
                os.write(sys.stdout.fileno(), data.encode("ascii"))
                self.kitty_farm.add((belly, integrated))
            image = farm_image_id(belly, integrated, frame)
            attr = self.pair(image & 0xFF, -1)
            for row in range(rows):
                try:
                    scr.addstr(y + row, x, kitty_placeholder_row(row, cols, image >> 24), attr)
                except curses.error:
                    pass
            return
        cells_frame = self.popo["logo"][frame]
        width = len(cells_frame[0])
        for row, cells in enumerate(cells_frame):
            for col in range(cols):
                cell = cells[min(width - 1, col * width // cols)]
                if cell:
                    put(scr, y + row, x + col, cell[0], self.pair(cell[1], cell[2]))

    def draw_sprite(self, scr, y, x, pixels, size, belly=1.0):
        """Two pixels per cell with half blocks: ▀ paints the top one, the cell color the bottom.
        `belly` widens him (nearest neighbour), as he grows."""
        for row in range(0, size, 2):
            for col in range(round(size * belly)):
                src = min(size - 1, int(col / belly))
                top, bottom = pixels[row * size + src], pixels[(row + 1) * size + src]
                if top:
                    put(scr, y + row // 2, x + col, "▀", self.pair(top, bottom or -1))
                elif bottom:
                    put(scr, y + row // 2, x + col, "▄", self.pair(bottom, -1))
