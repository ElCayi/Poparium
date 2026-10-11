"""The notebook: SQLite, its migrations, and its daily backups."""
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from popos import APP
from popos.dates import display_date, stamp
from popos.document import LEGACY_COLUMNS, TEXT_FIELDS, glance, legacy_document
from popos.history import init_hash, review_hash, version_hash, version_label


# The notebook keeps the folder it was born in (the app was called keepstate);
# POPOS_DB, or the older KEEPSTATE_DB, points to another one
DEFAULT_DB = Path(os.environ.get("POPOS_DB") or os.environ.get("KEEPSTATE_DB")
                  or "~/.local/share/keepstate/keepstate.db").expanduser()


# Daily copies of the notebook: every day of the last two weeks, and the first
# copy of each month for a year
KEEP_DAILY, KEEP_MONTHLY = 14, 12


def backups_to_keep(dates, today):
    """Which of these backup dates stay."""
    keep = {d for d in dates if 0 <= (today - d).days < KEEP_DAILY}
    first_of_month = {}
    for d in sorted(dates):
        first_of_month.setdefault((d.year, d.month), d)
    keep |= {first_of_month[m] for m in sorted(first_of_month)[-KEEP_MONTHLY:]}
    return keep


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS commitments (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT '',
                cue TEXT NOT NULL DEFAULT '',
                success TEXT NOT NULL DEFAULT '',
                recovery TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                kind TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                learned TEXT NOT NULL,
                adjustment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_journal_time ON journal(created_at DESC);
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY,
                commitment_id INTEGER NOT NULL REFERENCES commitments(id),
                note TEXT NOT NULL DEFAULT '',
                snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        # Older notebooks: add the columns they lack, empty
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(commitments)")}
        missing = [column for column in TEXT_FIELDS + LEGACY_COLUMNS if column not in have]
        if missing and self.db.execute("SELECT COUNT(*) FROM commitments").fetchone()[0]:
            self.backup("pre-0.2" if "context" in missing else "pre-0.3")
        for column in missing:
            self.db.execute(f"ALTER TABLE commitments ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        # 0.3: the fixed sections become free text, once (user_version marks it done)
        if self.db.execute("PRAGMA user_version").fetchone()[0] < 3:
            for c in self.db.execute("SELECT * FROM commitments WHERE pinned='' AND body=''").fetchall():
                doc = legacy_document(c)
                self.db.execute("UPDATE commitments SET pinned=?, body=? WHERE id=?", (doc["pinned"], doc["body"], c["id"]))
            self.db.execute("PRAGMA user_version = 3")
        # ...and give each older commitment its v1.0
        for c in self.db.execute("""SELECT * FROM commitments WHERE id NOT IN
                (SELECT commitment_id FROM versions)""").fetchall():
            self._snapshot(c["id"], "Acuerdo inicial", c["created_at"])
        # An obstacle can get, later, how it was put right
        journal = {r["name"] for r in self.db.execute("PRAGMA table_info(journal)")}
        for column in ("repair", "repaired_at"):
            if column not in journal:
                self.db.execute(f"ALTER TABLE journal ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        # Every entry and review remembers the version of its commitment in force
        # when it happened, so a change of strategy can be judged by what followed
        for table in ("journal", "reviews"):
            if "version_id" not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN version_id INTEGER REFERENCES versions(id)")
                self.db.execute(f"""UPDATE {table} SET version_id = (SELECT v.id FROM versions v
                    WHERE v.commitment_id = {table}.commitment_id AND v.created_at <= {table}.created_at
                    ORDER BY v.created_at DESC, v.id DESC LIMIT 1)""")
        self.db.commit()

    def backup(self, tag):
        """A private copy of the whole notebook next to it, before changing its format."""
        target = self.path.with_name(f"{self.path.stem}.{tag}.db")
        if not target.exists():
            self._copy_to(target)
        return target

    def _copy_to(self, target):
        """SQLite's online backup: a consistent copy even while the notebook is open. 0600."""
        fd = os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        copy = sqlite3.connect(target)
        try:
            self.db.backup(copy)
        finally:
            copy.close()

    def daily_backup(self, today=None):
        """Once a day, a copy in <notebook>.backups/ (private); old ones are pruned
        (backups_to_keep). An empty notebook has nothing worth copying."""
        if not self.db.execute("SELECT COUNT(*) FROM commitments").fetchone()[0]:
            return None
        today = today or dt.date.today()
        folder = self.path.with_name(self.path.stem + ".backups")
        folder.mkdir(mode=0o700, exist_ok=True)
        folder.chmod(0o700)
        target = folder / f"{self.path.stem}-{today.isoformat()}.db"
        if not target.exists():
            self._copy_to(target)
        dated = {}
        for f in folder.glob(f"{self.path.stem}-*.db"):
            try:
                dated[dt.date.fromisoformat(f.stem[len(self.path.stem) + 1:])] = f
            except ValueError:
                continue
        for d in set(dated) - backups_to_keep(set(dated), today):
            dated[d].unlink()
        return target

    def _snapshot(self, identifier, note, when):
        row = self.db.execute("SELECT * FROM commitments WHERE id=?", (identifier,)).fetchone()
        snapshot = json.dumps({k: row[k] for k in TEXT_FIELDS}, ensure_ascii=False)
        self.db.execute("INSERT INTO versions (commitment_id, note, snapshot, created_at) VALUES (?, ?, ?, ?)",
                        (identifier, note, snapshot, when))

    def create(self, title, pinned="", body="", **legacy):
        """A new commitment. Old-style sections (reason=..., plan=...) still work: they
        become free text, as in a migrated notebook."""
        now = stamp()
        if legacy and not body:
            doc = legacy_document({"title": title, **legacy})
            body, pinned = doc["body"], pinned or doc["pinned"]
        # reason is NOT NULL without a default in notebooks from before 0.3
        values = {"title": title, "pinned": pinned, "body": body, "reason": ""}
        with self.db:
            identifier = self.db.execute(
                f"INSERT INTO commitments ({', '.join(values)}, status, created_at, updated_at) "
                f"VALUES ({', '.join('?' * len(values))}, 'active', ?, ?)",
                (*values.values(), now, now)).lastrowid
            self._snapshot(identifier, "Acuerdo inicial", now)
        return identifier

    def revise(self, identifier, fields, note):
        """Save an edit as a new version; returns its label, or None if nothing changed."""
        current = self.db.execute("SELECT * FROM commitments WHERE id=?", (identifier,)).fetchone()
        changed = {k: fields[k] for k in TEXT_FIELDS if k in fields and fields[k] != current[k]}
        if not changed:
            return None
        now = stamp()
        with self.db:
            self.db.execute("UPDATE commitments SET " + ", ".join(f"{k}=?" for k in changed) + ", updated_at=? WHERE id=?",
                            (*changed.values(), now, identifier))
            self._snapshot(identifier, note, now)
        return version_label(len(self.versions(identifier)) - 1)

    def versions(self, identifier):
        """Oldest first, each with its snapshot decoded; old-style snapshots read as
        the new document, so a diff across 0.3 shows only what really changed."""
        out = []
        for r in self.db.execute("SELECT * FROM versions WHERE commitment_id=? ORDER BY created_at, id", (identifier,)):
            snapshot = json.loads(r["snapshot"])
            if "body" not in snapshot:
                snapshot = legacy_document(snapshot)
            out.append(dict(r, snapshot=snapshot))
        return out

    def update(self, identifier, **fields):
        allowed = (*TEXT_FIELDS, *LEGACY_COLUMNS, "status")
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        fields["updated_at"] = stamp()
        sql = "UPDATE commitments SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?"
        with self.db:
            self.db.execute(sql, (*fields.values(), identifier))

    def active(self):
        """What is still being lived: active and integrated, not archived."""
        return self.db.execute("SELECT * FROM commitments WHERE status != 'archived' ORDER BY id DESC").fetchall()

    def all_commitments(self):
        return self.db.execute("SELECT * FROM commitments ORDER BY id DESC").fetchall()

    def entries(self, limit=100):
        return self.db.execute("""SELECT j.*, c.title FROM journal j
            JOIN commitments c ON c.id = j.commitment_id
            ORDER BY j.created_at DESC, j.id DESC LIMIT ?""", (limit,)).fetchall()

    def delete_entry(self, entry_id):
        """Remove one log entry; returns what restore() needs to put it back."""
        return self._remove([("journal", "id", entry_id)])

    def delete_commitment(self, identifier):
        """Remove a commitment with its log, reviews and versions; returns them for restore()."""
        return self._remove([("journal", "commitment_id", identifier), ("reviews", "commitment_id", identifier),
                             ("versions", "commitment_id", identifier), ("commitments", "id", identifier)])

    def _remove(self, where):
        removed = []
        with self.db:
            # Children before their commitment: foreign keys are on
            for table, column, value in where:
                rows = [dict(r) for r in self.db.execute(f"SELECT * FROM {table} WHERE {column}=?", (value,))]
                self.db.execute(f"DELETE FROM {table} WHERE {column}=?", (value,))
                removed.append((table, rows))
        return removed

    def restore(self, removed):
        """Undo a delete: every row comes back with its own id and dates."""
        with self.db:
            for table, rows in reversed(removed):
                for row in rows:
                    self.db.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                                    tuple(row.values()))

    def version_in_force(self, identifier, when=None):
        """The version of a commitment that was current at `when` (default: now)."""
        row = self.db.execute("""SELECT id FROM versions WHERE commitment_id=? AND created_at <= ?
            ORDER BY created_at DESC, id DESC LIMIT 1""", (identifier, when or stamp())).fetchone()
        if not row:  # logged for a day before the commitment existed: its first version
            row = self.db.execute("SELECT MIN(id) id FROM versions WHERE commitment_id=?", (identifier,)).fetchone()
        return row["id"] if row else None

    def log(self, identifier, kind, note="", when=None):
        """A new entry; `when` (UTC ISO) for something remembered from another day."""
        when = when or stamp()
        with self.db:
            self.db.execute("INSERT INTO journal (commitment_id, kind, note, created_at, version_id) VALUES (?, ?, ?, ?, ?)",
                            (identifier, kind, note, when, self.version_in_force(identifier, when)))

    def repair(self, entry_id, text):
        with self.db:
            self.db.execute("UPDATE journal SET repair=?, repaired_at=? WHERE id=?",
                            (text, stamp() if text else "", entry_id))

    def review(self, identifier, learned, adjustment=""):
        now = stamp()
        with self.db:
            rowid = self.db.execute("INSERT INTO reviews (commitment_id, learned, adjustment, created_at, version_id) "
                                    "VALUES (?, ?, ?, ?, ?)",
                                    (identifier, learned, adjustment, now, self.version_in_force(identifier))).lastrowid
        return review_hash({"id": rowid, "commitment_id": identifier, "learned": learned,
                            "adjustment": adjustment, "created_at": now})

    def latest_reviews(self, limit=100):
        return self.db.execute("""SELECT r.*, c.title FROM reviews r
            JOIN commitments c ON c.id = r.commitment_id
            ORDER BY r.created_at DESC, r.id DESC LIMIT ?""", (limit,)).fetchall()

    def history(self):
        """Each commitment's creation, its edits and its reviews as commits, newest first."""
        events = []
        for c in self.all_commitments():
            events.append({"kind": "init", "hash": init_hash(c), "commitment_id": c["id"],
                           "title": c["title"], "created_at": c["created_at"], "order": (0, c["id"]),
                           "message": "init · " + c["title"], "detail": glance(c)[0]})
        for c in self.all_commitments():
            for index, v in enumerate(self.versions(c["id"])[1:], start=1):
                events.append({"kind": "version", "hash": version_hash(v), "commitment_id": c["id"],
                               "title": c["title"], "created_at": v["created_at"], "order": (2, v["id"]),
                               "message": f"{version_label(index)} · {v['note']}", "detail": ""})
        for r in self.latest_reviews(limit=-1):
            events.append({"kind": "review", "hash": review_hash(r), "commitment_id": r["commitment_id"],
                           "title": r["title"], "created_at": r["created_at"], "order": (1, r["id"]),
                           "message": r["learned"], "detail": r["adjustment"]})
        events.sort(key=lambda e: (e["created_at"], e["order"]), reverse=True)
        return events

    def events_between(self, first_day, last_day):
        """Everything that happened from first_day to last_day (local dates, both included).

        Log entries, reviews, new commitments and their edits, oldest first,
        each with the local date it belongs to.
        """
        start = dt.datetime.combine(first_day, dt.time()).astimezone().astimezone(dt.timezone.utc)
        end = dt.datetime.combine(last_day + dt.timedelta(days=1), dt.time()).astimezone().astimezone(dt.timezone.utc)
        bounds = (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))
        rows = self.db.execute("""
            SELECT j.kind, j.note AS note, j.created_at, c.title, c.id AS commitment_id, j.repair FROM journal j
                JOIN commitments c ON c.id = j.commitment_id WHERE j.created_at >= ? AND j.created_at < ?
            UNION ALL SELECT 'review', r.learned, r.created_at, c.title, c.id, '' FROM reviews r
                JOIN commitments c ON c.id = r.commitment_id WHERE r.created_at >= ? AND r.created_at < ?
            UNION ALL SELECT CASE WHEN v.id = (SELECT MIN(id) FROM versions WHERE commitment_id = v.commitment_id)
                    THEN 'init' ELSE 'version' END, v.note, v.created_at, c.title, c.id, '' FROM versions v
                JOIN commitments c ON c.id = v.commitment_id WHERE v.created_at >= ? AND v.created_at < ?
            ORDER BY 3""", bounds * 3).fetchall()
        return [dict(r, day=dt.datetime.fromisoformat(r["created_at"]).astimezone().date()) for r in rows]

    def last_events(self):
        """{commitment_id: (kind, created_at)} of the newest log entry, review or edit."""
        rows = self.db.execute("""SELECT commitment_id, kind, created_at FROM (
                SELECT commitment_id, kind, created_at, 0 src, id FROM journal
                UNION ALL SELECT commitment_id, 'review', created_at, 1, id FROM reviews
                UNION ALL SELECT commitment_id, 'version', created_at, 2, id FROM versions
                    WHERE id NOT IN (SELECT MIN(id) FROM versions GROUP BY commitment_id))
            ORDER BY created_at, src, id""").fetchall()
        return {r["commitment_id"]: (r["kind"], r["created_at"]) for r in rows}

    def experience_counts(self):
        """{commitment_id: {kind: n}} over all time, reviews included. A commitment
        doesn't expire, so nothing here is a "last 7 days" window."""
        counts = {}
        for r in self.db.execute("""SELECT commitment_id, kind, COUNT(*) n FROM journal GROUP BY commitment_id, kind
                UNION ALL SELECT commitment_id, 'review', COUNT(*) FROM reviews GROUP BY commitment_id"""):
            counts.setdefault(r["commitment_id"], {})[r["kind"]] = r["n"]
        return counts

    def recent(self, limit=8, commitment_id=None):
        """The newest log entries and reviews, all commitments or one."""
        where, args = ("WHERE c.id = ?", (commitment_id, commitment_id)) if commitment_id else ("", ())
        return self.db.execute(f"""SELECT * FROM (
                SELECT j.id, j.kind, j.note, j.repair, j.created_at, c.title, c.id cid FROM journal j
                    JOIN commitments c ON c.id = j.commitment_id {where}
                UNION ALL SELECT r.id, 'review', r.learned, '', r.created_at, c.title, c.id FROM reviews r
                    JOIN commitments c ON c.id = r.commitment_id {where})
            ORDER BY created_at DESC, id DESC LIMIT ?""", (*args, limit)).fetchall()

    def export(self):
        out = self.path.parent / ("popos-export-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".md")
        lines = [f"# {APP} / copia de mi bitácora", "", "Documento personal. Los acuerdos son revisables, no verdades absolutas.", ""]
        for c in self.all_commitments():
            versions = self.versions(c["id"])
            lines.extend([f"## {c['title']}  (#{c['id']}, {version_label(len(versions) - 1)}, {c['status']})", ""])
            if c["pinned"]:
                lines.extend([f"> {line}" for line in c["pinned"].splitlines()] + [""])
            if c["body"]:
                # The free text's own headings, one level down
                lines.extend([("#" + line if line.startswith("#") else line) for line in c["body"].splitlines()] + [""])
            lines.extend(["### Historial del acuerdo", ""])
            for index, v in reversed(list(enumerate(versions))):
                lines.append(f"- `{version_hash(v)}` {version_label(index)} · {display_date(v['created_at'])} · {v['note']}")
            lines.extend(["", "### Avances y obstáculos", ""])
            for j in self.db.execute("SELECT * FROM journal WHERE commitment_id=? ORDER BY id", (c["id"],)):
                lines.append(f"- {display_date(j['created_at'])} · {j['kind']}: {j['note']}")
            lines.extend(["", "### Revisiones", ""])
            for r in self.db.execute("SELECT * FROM reviews WHERE commitment_id=? ORDER BY id", (c["id"],)):
                lines.append(f"- `{review_hash(r)}` {display_date(r['created_at'])} · Aprendí: {r['learned']} · Ajusto: {r['adjustment']}")
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        out.chmod(0o600)
        return out

    def close(self):
        self.db.close()
