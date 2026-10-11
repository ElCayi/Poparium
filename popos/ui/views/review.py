"""REVIEW: the commitments and their git log --graph."""
from popos.history import commit_graph
from popos.ui.draw import box, lane_style, put, style


class ReviewView:
    def render_review(self, scr, top, bottom, left, width):
        space = bottom - top + 1
        rows = max(1, min(len(self.current_items()), max(2, min(4, space // 5))))
        list_h = rows + 2
        y, x, ih, iw = box(scr, top, left, list_h, width, "REVIEW · R hace commit de una revisión del acuerdo seleccionado",
                           edge=style("a", True) if self.inside else None)
        self.list_commitments(scr, y, x, iw, ih)
        y, x, ih, iw = box(scr, top + list_h, left, space - list_h, width, "$ git log --graph", style("b", True))
        last = y + ih - 1
        rows = commit_graph(self.store.history())
        if not rows:
            put(scr, y, x, "Sin commits todavía. Crea un acuerdo con N: será tu primer commit.", style("dim"), iw)
            return
        graph_w = max(len(cells) for cells, _, _, _ in rows) * 2
        right = x + iw
        for i, (cells, below, head, event) in enumerate(rows):
            if y > last:
                break
            self.draw_lanes(scr, y, x, cells)
            cx = x + graph_w + 1
            put(scr, y, cx, event["hash"], style("warm"), right - cx)
            cx += 8
            if head:
                label = "(" + ("HEAD → " if i == 0 else "") + event["title"] + ") "
                put(scr, y, cx, label, lane_style(event["commitment_id"], True), max(1, right - cx))
                cx += len(label)
            # The branch label already names the commitment: a bare "init" is enough
            message = "init" if head and event["kind"] == "init" else event["message"]
            put(scr, y, cx, message, style("main"), max(1, right - cx))
            y += 1
            if event["detail"] and y <= last:
                self.draw_lanes(scr, y, x, below)
                prefix = "→ " if event["kind"] == "review" else "¿por qué? "
                put(scr, y, x + graph_w + 3, prefix + event["detail"], style("dim"), max(1, right - x - graph_w - 3))
                y += 1

    def draw_lanes(self, scr, y, x, cells):
        for col, (char, cid) in enumerate(cells):
            put(scr, y, x + col * 2, char, lane_style(cid, char == "*"))
