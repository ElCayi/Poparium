"""Versions and reviews as commits: short hashes and the git log --graph layout."""
import hashlib


def short_hash(*parts):
    """Seven hex chars, like `git log --oneline`. Same content, same hash."""
    return hashlib.sha1("\n".join(map(str, parts)).encode("utf-8")).hexdigest()[:7]


def init_hash(c):
    return short_hash("init", c["id"], c["created_at"])


def review_hash(r):
    return short_hash("review", r["id"], r["commitment_id"], r["learned"], r["adjustment"], r["created_at"])


def version_hash(v):
    return short_hash("version", v["id"], v["commitment_id"], v["note"], v["created_at"])


def version_label(index):
    """v1.0 is the commitment as first written; each edit adds one."""
    return f"v1.{index}"


def commit_graph(events):
    """Lay out events (newest first) as `git log --graph` lanes, one per commitment.

    Returns (top, below, head, event) per event: top/below are lists of
    (char, commitment_id) cells for the commit row and the row under it;
    head marks the commitment's newest commit, where its lane starts.
    """
    oldest = {}
    for i, e in enumerate(events):
        oldest[e["commitment_id"]] = i
    columns, rows = [], []
    for i, e in enumerate(events):
        cid = e["commitment_id"]
        head = cid not in columns
        if head:
            if None in columns:
                columns[columns.index(None)] = cid
            else:
                columns.append(cid)
        top = [("*" if c == cid else "│" if c is not None else " ", c) for c in columns]
        if i == oldest[cid]:
            columns[columns.index(cid)] = None
            while columns and columns[-1] is None:
                columns.pop()
        below = [("│" if c is not None else " ", c) for c in columns]
        rows.append((top, below, head, e))
    return rows
