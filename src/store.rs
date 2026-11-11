//! The notebook: SQLite, its migrations, and its daily backups.
use crate::dates::{display_date, local_midnight_utc, parse_local, stamp};
use crate::document::{Doc, TEXT_FIELDS, glance, legacy_columns, legacy_document};
use crate::history::{Event, init_hash, review_hash, version_hash, version_label};
use crate::APP;
use chrono::{Datelike, Local, NaiveDate};
use rusqlite::types::Value;
use rusqlite::{Connection, OptionalExtension, Row, params};
use std::collections::{BTreeSet, HashMap};
use std::fs::{self, OpenOptions};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

pub type Result<T> = rusqlite::Result<T>;

fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}

/// `~` at the start of a path, as Python's expanduser.
pub fn expand_user(path: &Path) -> PathBuf {
    match path.to_str() {
        Some("~") => home(),
        Some(text) if text.starts_with("~/") => home().join(&text[2..]),
        _ => path.to_path_buf(),
    }
}

pub fn data_dir() -> PathBuf {
    home().join(".local/share/poparium")
}

/// POPARIUM_DB points to another notebook
pub fn default_db() -> PathBuf {
    match std::env::var_os("POPARIUM_DB").filter(|v| !v.is_empty()) {
        Some(path) => expand_user(Path::new(&path)),
        None => data_dir().join("poparium.db"),
    }
}

/// The app's earlier names, newest first: its notebook lived in
/// ~/.local/share/<name>/<name>.db
const LEGACY_NAMES: [&str; 2] = ["popos", "keepstate"];

fn names_in(folder: &Path) -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(folder)
        .map(|entries| entries.filter_map(|e| e.ok()?.file_name().into_string().ok()).collect())
        .unwrap_or_default();
    names.sort();
    names
}

/// Brings the notebook of any earlier name into the data folder (see
/// adopt_legacy_folder). Returns the notebook to open.
pub fn adopt_legacy_folders() -> PathBuf {
    let new = data_dir();
    for stem in LEGACY_NAMES {
        let db = adopt_legacy_folder(&new, &home().join(".local/share").join(stem), stem);
        if !db.starts_with(&new) {
            return db;
        }
    }
    new.join("poparium.db")
}

/// Moves the folder of an earlier name (popos/, keepstate/) to poparium/ and
/// renames what's inside (<stem>.db, .backups, .drafts, .pre-0.x.db) to poparium.*.
///
/// The folder moves in one rename, and the renames inside are repeated on
/// every start until none is left, so an interruption at any point loses
/// nothing. Left alone while the old notebook is mid-write (a -journal or
/// -wal next to it): the app then opens it where it is, untouched.
pub fn adopt_legacy_folder(new: &Path, old: &Path, stem: &str) -> PathBuf {
    if !new.exists() && old.is_dir() {
        if names_in(old).iter().any(|n| n.starts_with(&format!("{stem}.db-"))) {
            return old.join(format!("{stem}.db"));
        }
        let _ = fs::rename(old, new);
    }
    if !new.is_dir() {
        return new.join("poparium.db");
    }
    for name in names_in(new) {
        if let Some(rest) = name.strip_prefix(&format!("{stem}.")) {
            let target = new.join(format!("poparium.{rest}"));
            if !target.exists() {
                let _ = fs::rename(new.join(&name), target);
            }
        }
    }
    let backups = new.join("poparium.backups");
    if backups.is_dir() {
        for name in names_in(&backups) {
            if name.starts_with(&format!("{stem}-")) && name.ends_with(".db") {
                let target = backups.join(format!("poparium{}", &name[stem.len()..]));
                if !target.exists() {
                    let _ = fs::rename(backups.join(&name), target);
                }
            }
        }
    }
    new.join("poparium.db")
}

// Daily copies of the notebook: every day of the last two weeks, and the first
// copy of each month for a year
const KEEP_DAILY: i64 = 14;
const KEEP_MONTHLY: usize = 12;

/// Which of these backup dates stay.
pub fn backups_to_keep(dates: &BTreeSet<NaiveDate>, today: NaiveDate) -> BTreeSet<NaiveDate> {
    let mut keep: BTreeSet<NaiveDate> =
        dates.iter().copied().filter(|d| (0..KEEP_DAILY).contains(&(today - *d).num_days())).collect();
    let mut first_of_month: std::collections::BTreeMap<(i32, u32), NaiveDate> = Default::default();
    for d in dates {
        first_of_month.entry((d.year(), d.month())).or_insert(*d);
    }
    let firsts: Vec<NaiveDate> = first_of_month.values().copied().collect();
    keep.extend(firsts.iter().skip(firsts.len().saturating_sub(KEEP_MONTHLY)));
    keep
}

/// A file created private (0600) if it doesn't exist yet.
fn touch_private(path: &Path) -> std::io::Result<()> {
    OpenOptions::new().create(true).append(true).mode(0o600).open(path).map(|_| ())
}

#[derive(Clone, Debug, PartialEq)]
pub struct Commitment {
    pub id: i64,
    pub title: String,
    pub pinned: String,
    pub body: String,
    pub status: String,
    pub created_at: String,
}

impl Commitment {
    fn from_row(row: &Row) -> Result<Self> {
        Ok(Commitment {
            id: row.get("id")?,
            title: row.get("title")?,
            pinned: row.get("pinned")?,
            body: row.get("body")?,
            status: row.get("status")?,
            created_at: row.get("created_at")?,
        })
    }

    pub fn doc(&self) -> Doc {
        Doc::new(&self.title, &self.pinned, &self.body)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Version {
    pub id: i64,
    pub commitment_id: i64,
    pub note: String,
    pub snapshot: Doc,
    pub created_at: String,
}

/// A log entry with its commitment's title (the BITÁCORA tab).
#[derive(Clone, Debug, PartialEq)]
pub struct Entry {
    pub id: i64,
    pub commitment_id: i64,
    pub kind: String,
    pub note: String,
    pub repair: String,
    pub created_at: String,
    pub title: String,
}

/// A log entry or a review, newest first (a commitment's page, OVERVIEW).
#[derive(Clone, Debug, PartialEq)]
pub struct Recent {
    pub id: i64,
    pub kind: String,
    pub note: String,
    pub repair: String,
    pub created_at: String,
    pub title: String,
    pub cid: i64,
}

/// Something that happened, for the calendar, with the local day it belongs to.
#[derive(Clone, Debug, PartialEq)]
pub struct DayEvent {
    pub kind: String,
    pub note: String,
    pub created_at: String,
    pub title: String,
    pub commitment_id: i64,
    pub repair: String,
    pub day: NaiveDate,
}

/// Rows taken out by a delete, table by table, for restore().
pub type Removed = Vec<(String, Vec<Vec<(String, Value)>>)>;

pub struct Store {
    pub path: PathBuf,
    pub db: Connection,
}

/// A snapshot as Python's json.dumps(..., ensure_ascii=False) wrote it, byte for byte.
fn snapshot_json(doc: &Doc) -> String {
    let field = |key: &str, value: &str| {
        let mut out = format!("\"{key}\": \"");
        for c in value.chars() {
            match c {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                '\x08' => out.push_str("\\b"),
                '\x0c' => out.push_str("\\f"),
                c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
                c => out.push(c),
            }
        }
        out.push('"');
        out
    };
    format!(
        "{{{}, {}, {}}}",
        field("title", &doc.title),
        field("pinned", &doc.pinned),
        field("body", &doc.body)
    )
}

fn text_of(value: Option<&serde_json::Value>) -> String {
    match value {
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(serde_json::Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    }
}

/// A stored snapshot as a document; old-style ones read as the new document, so
/// a diff across 0.3 shows only what really changed.
fn read_snapshot(text: &str) -> Doc {
    let map = match serde_json::from_str::<serde_json::Value>(text) {
        Ok(serde_json::Value::Object(map)) => map,
        _ => return Doc::default(),
    };
    if !map.contains_key("body") {
        return legacy_document(|key| text_of(map.get(key)));
    }
    Doc { title: text_of(map.get("title")), pinned: text_of(map.get("pinned")), body: text_of(map.get("body")) }
}

impl Store {
    pub fn open(path: &Path) -> Result<Store> {
        let path = expand_user(path);
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if !path.exists() {
            let _ = touch_private(&path);
        }
        let db = Connection::open(&path)?;
        let store = Store { path, db };
        store.migrate()?;
        Ok(store)
    }

    fn columns(&self, table: &str) -> Result<Vec<String>> {
        let mut statement = self.db.prepare(&format!("PRAGMA table_info({table})"))?;
        let names = statement.query_map([], |row| row.get::<_, String>("name"))?;
        names.collect()
    }

    fn count_commitments(&self) -> Result<i64> {
        self.db.query_row("SELECT COUNT(*) FROM commitments", [], |r| r.get(0))
    }

    fn migrate(&self) -> Result<()> {
        self.db.execute_batch("PRAGMA foreign_keys=ON")?;
        self.db.execute_batch(
            "CREATE TABLE IF NOT EXISTS commitments (
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
            );",
        )?;
        // Older notebooks: add the columns they lack, empty
        let have = self.columns("commitments")?;
        let mut wanted: Vec<&str> = TEXT_FIELDS.to_vec();
        wanted.extend(legacy_columns());
        let missing: Vec<&str> = wanted.into_iter().filter(|c| !have.iter().any(|h| h == c)).collect();
        if !missing.is_empty() && self.count_commitments()? > 0 {
            self.backup(if missing.contains(&"context") { "pre-0.2" } else { "pre-0.3" })?;
        }
        let tx = self.db.unchecked_transaction()?;
        for column in &missing {
            tx.execute_batch(&format!("ALTER TABLE commitments ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"))?;
        }
        // 0.3: the fixed sections become free text, once (user_version marks it done)
        let user_version: i64 = tx.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        if user_version < 3 {
            let old = {
                let mut statement = tx.prepare("SELECT * FROM commitments WHERE pinned='' AND body=''")?;
                let names: Vec<String> = statement.column_names().map(String::from).collect();
                let rows = statement.query_map([], |row| {
                    let mut values = HashMap::new();
                    for (i, name) in names.iter().enumerate() {
                        let text = match row.get::<_, Value>(i)? {
                            Value::Text(t) => t,
                            Value::Integer(n) => n.to_string(),
                            Value::Real(f) => f.to_string(),
                            _ => String::new(),
                        };
                        values.insert(name.clone(), text);
                    }
                    Ok(values)
                })?;
                rows.collect::<Result<Vec<_>>>()?
            };
            for values in old {
                let doc = legacy_document(|key| values.get(key).cloned().unwrap_or_default());
                tx.execute(
                    "UPDATE commitments SET pinned=?, body=? WHERE id=?",
                    params![doc.pinned, doc.body, values["id"].parse::<i64>().unwrap_or_default()],
                )?;
            }
            tx.execute_batch("PRAGMA user_version = 3")?;
        }
        // ...and give each older commitment its v1.0
        let unversioned: Vec<(i64, String)> = {
            let mut statement = tx.prepare(
                "SELECT id, created_at FROM commitments WHERE id NOT IN (SELECT commitment_id FROM versions)",
            )?;
            let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?;
            rows.collect::<Result<_>>()?
        };
        for (id, created_at) in unversioned {
            snapshot(&tx, id, "Acuerdo inicial", &created_at)?;
        }
        // An obstacle can get, later, how it was put right
        let journal = self.columns("journal")?;
        for column in ["repair", "repaired_at"] {
            if !journal.iter().any(|c| c == column) {
                tx.execute_batch(&format!("ALTER TABLE journal ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"))?;
            }
        }
        // Every entry and review remembers the version of its commitment in force
        // when it happened, so a change of strategy can be judged by what followed
        for table in ["journal", "reviews"] {
            if !self.columns(table)?.iter().any(|c| c == "version_id") {
                tx.execute_batch(&format!(
                    "ALTER TABLE {table} ADD COLUMN version_id INTEGER REFERENCES versions(id);
                     UPDATE {table} SET version_id = (SELECT v.id FROM versions v
                        WHERE v.commitment_id = {table}.commitment_id AND v.created_at <= {table}.created_at
                        ORDER BY v.created_at DESC, v.id DESC LIMIT 1);"
                ))?;
            }
        }
        tx.commit()
    }

    /// A private copy of the whole notebook next to it, before changing its format.
    pub fn backup(&self, tag: &str) -> Result<PathBuf> {
        let stem = self.stem();
        let target = self.path.with_file_name(format!("{stem}.{tag}.db"));
        if !target.exists() {
            self.copy_to(&target)?;
        }
        Ok(target)
    }

    fn stem(&self) -> String {
        self.path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
    }

    /// SQLite's online backup: a consistent copy even while the notebook is open. 0600.
    fn copy_to(&self, target: &Path) -> Result<()> {
        let _ = touch_private(target);
        let copied = Connection::open(target).and_then(|mut copy| {
            let backup = rusqlite::backup::Backup::new(&self.db, &mut copy)?;
            backup.run_to_completion(i32::MAX, std::time::Duration::from_millis(50), None)
        });
        // A copy that didn't finish isn't a copy: it would stop the next try (backup() skips what exists)
        if copied.is_err() {
            let _ = fs::remove_file(target);
        }
        copied
    }

    /// Once a day, a copy in <notebook>.backups/ (private); old ones are pruned
    /// (backups_to_keep). An empty notebook has nothing worth copying.
    pub fn daily_backup(&self, today: Option<NaiveDate>) -> Result<Option<PathBuf>> {
        if self.count_commitments()? == 0 {
            return Ok(None);
        }
        let today = today.unwrap_or_else(|| Local::now().date_naive());
        let stem = self.stem();
        let folder = self.path.with_file_name(format!("{stem}.backups"));
        let _ = fs::create_dir(&folder);
        let _ = fs::set_permissions(&folder, fs::Permissions::from_mode(0o700));
        let target = folder.join(format!("{stem}-{}.db", today.format("%Y-%m-%d")));
        if !target.exists() {
            self.copy_to(&target)?;
        }
        let mut dated = HashMap::new();
        for name in names_in(&folder) {
            let Some(date) = name
                .strip_prefix(&format!("{stem}-"))
                .and_then(|rest| rest.strip_suffix(".db"))
                .and_then(|d| NaiveDate::parse_from_str(d, "%Y-%m-%d").ok())
            else {
                continue;
            };
            dated.insert(date, folder.join(name));
        }
        let dates: BTreeSet<NaiveDate> = dated.keys().copied().collect();
        let keep = backups_to_keep(&dates, today);
        for date in dates.difference(&keep) {
            let _ = fs::remove_file(&dated[date]);
        }
        Ok(Some(target))
    }

    /// A new commitment, with its v1.0.
    pub fn create(&self, doc: &Doc) -> Result<i64> {
        let now = stamp();
        let tx = self.db.unchecked_transaction()?;
        // reason is NOT NULL without a default in notebooks from before 0.3
        tx.execute(
            "INSERT INTO commitments (title, pinned, body, reason, status, created_at, updated_at) \
             VALUES (?, ?, ?, ?, 'active', ?, ?)",
            params![doc.title, doc.pinned, doc.body, "", now, now],
        )?;
        let identifier = tx.last_insert_rowid();
        snapshot(&tx, identifier, "Acuerdo inicial", &now)?;
        tx.commit()?;
        Ok(identifier)
    }

    pub fn commitment(&self, identifier: i64) -> Result<Option<Commitment>> {
        self.db.query_row("SELECT * FROM commitments WHERE id=?", [identifier], Commitment::from_row).optional()
    }

    /// Save an edit as a new version; returns its label, or None if nothing changed.
    pub fn revise(&self, identifier: i64, fields: &Doc, note: &str) -> Result<Option<String>> {
        let Some(current) = self.commitment(identifier)? else { return Ok(None) };
        let changed: Vec<(&str, &str)> = fields
            .fields()
            .into_iter()
            .zip(current.doc().fields())
            .filter(|((_, new), (_, old))| new != old)
            .map(|(new, _)| new)
            .collect();
        if changed.is_empty() {
            return Ok(None);
        }
        let now = stamp();
        let tx = self.db.unchecked_transaction()?;
        let sets: Vec<String> = changed.iter().map(|(k, _)| format!("{k}=?")).collect();
        let mut values: Vec<Value> = changed.iter().map(|(_, v)| Value::Text(v.to_string())).collect();
        values.push(Value::Text(now.clone()));
        values.push(Value::Integer(identifier));
        tx.execute(
            &format!("UPDATE commitments SET {}, updated_at=? WHERE id=?", sets.join(", ")),
            rusqlite::params_from_iter(values),
        )?;
        snapshot(&tx, identifier, note, &now)?;
        tx.commit()?;
        Ok(Some(version_label(self.versions(identifier)?.len() - 1)))
    }

    /// Oldest first, each with its snapshot decoded.
    pub fn versions(&self, identifier: i64) -> Result<Vec<Version>> {
        let mut statement = self.db.prepare_cached(
            "SELECT id, commitment_id, note, snapshot, created_at FROM versions WHERE commitment_id=? ORDER BY created_at, id",
        )?;
        let rows = statement.query_map([identifier], |r| {
            Ok(Version {
                id: r.get(0)?,
                commitment_id: r.get(1)?,
                note: r.get(2)?,
                snapshot: read_snapshot(&r.get::<_, String>(3)?),
                created_at: r.get(4)?,
            })
        })?;
        rows.collect()
    }

    pub fn version_count(&self, identifier: i64) -> Result<usize> {
        self.db.query_row("SELECT COUNT(*) FROM versions WHERE commitment_id=?", [identifier], |r| {
            r.get::<_, i64>(0).map(|n| n as usize)
        })
    }

    pub fn update_status(&self, identifier: i64, status: &str) -> Result<()> {
        self.db.execute("UPDATE commitments SET status=?, updated_at=? WHERE id=?", params![status, stamp(), identifier])?;
        Ok(())
    }

    fn commitments(&self, sql: &str) -> Result<Vec<Commitment>> {
        let mut statement = self.db.prepare_cached(sql)?;
        let rows = statement.query_map([], Commitment::from_row)?;
        rows.collect()
    }

    /// What is still being lived: active and integrated, not archived.
    pub fn active(&self) -> Result<Vec<Commitment>> {
        self.commitments("SELECT * FROM commitments WHERE status != 'archived' ORDER BY id DESC")
    }

    pub fn all_commitments(&self) -> Result<Vec<Commitment>> {
        self.commitments("SELECT * FROM commitments ORDER BY id DESC")
    }

    pub fn entries(&self, limit: i64) -> Result<Vec<Entry>> {
        let mut statement = self.db.prepare_cached(
            "SELECT j.id, j.commitment_id, j.kind, j.note, j.repair, j.created_at, c.title FROM journal j
                JOIN commitments c ON c.id = j.commitment_id
                ORDER BY j.created_at DESC, j.id DESC LIMIT ?",
        )?;
        let rows = statement.query_map([limit], |r| {
            Ok(Entry {
                id: r.get(0)?,
                commitment_id: r.get(1)?,
                kind: r.get(2)?,
                note: r.get(3)?,
                repair: r.get(4)?,
                created_at: r.get(5)?,
                title: r.get(6)?,
            })
        })?;
        rows.collect()
    }

    /// Remove one log entry; returns what restore() needs to put it back.
    pub fn delete_entry(&self, entry_id: i64) -> Result<Removed> {
        self.remove(&[("journal", "id", entry_id)])
    }

    /// Remove a commitment with its log, reviews and versions; returns them for restore().
    pub fn delete_commitment(&self, identifier: i64) -> Result<Removed> {
        self.remove(&[
            ("journal", "commitment_id", identifier),
            ("reviews", "commitment_id", identifier),
            ("versions", "commitment_id", identifier),
            ("commitments", "id", identifier),
        ])
    }

    fn remove(&self, places: &[(&str, &str, i64)]) -> Result<Removed> {
        let mut removed = Vec::new();
        let tx = self.db.unchecked_transaction()?;
        // Children before their commitment: foreign keys are on
        for (table, column, value) in places {
            let rows = {
                let mut statement = tx.prepare(&format!("SELECT * FROM {table} WHERE {column}=?"))?;
                let names: Vec<String> = statement.column_names().map(String::from).collect();
                let rows = statement.query_map([value], |row| {
                    names.iter().enumerate().map(|(i, name)| Ok((name.clone(), row.get::<_, Value>(i)?))).collect()
                })?;
                rows.collect::<Result<Vec<Vec<(String, Value)>>>>()?
            };
            tx.execute(&format!("DELETE FROM {table} WHERE {column}=?"), [value])?;
            removed.push((table.to_string(), rows));
        }
        tx.commit()?;
        Ok(removed)
    }

    /// Undo a delete: every row comes back with its own id and dates.
    pub fn restore(&self, removed: &Removed) -> Result<()> {
        let tx = self.db.unchecked_transaction()?;
        for (table, rows) in removed.iter().rev() {
            for row in rows {
                let names: Vec<&str> = row.iter().map(|(n, _)| n.as_str()).collect();
                let marks = vec!["?"; row.len()].join(", ");
                tx.execute(
                    &format!("INSERT INTO {table} ({}) VALUES ({marks})", names.join(", ")),
                    rusqlite::params_from_iter(row.iter().map(|(_, v)| v)),
                )?;
            }
        }
        tx.commit()
    }

    /// The version of a commitment that was current at `when` (default: now).
    pub fn version_in_force(&self, identifier: i64, when: Option<&str>) -> Result<Option<i64>> {
        version_in_force(&self.db, identifier, when)
    }

    /// A new entry; `when` (UTC ISO) for something remembered from another day.
    pub fn log(&self, identifier: i64, kind: &str, note: &str, when: Option<&str>) -> Result<()> {
        let when = when.map(str::to_string).unwrap_or_else(stamp);
        let version = self.version_in_force(identifier, Some(&when))?;
        self.db.execute(
            "INSERT INTO journal (commitment_id, kind, note, created_at, version_id) VALUES (?, ?, ?, ?, ?)",
            params![identifier, kind, note, when, version],
        )?;
        Ok(())
    }

    pub fn repair(&self, entry_id: i64, text: &str) -> Result<()> {
        let when = if text.is_empty() { String::new() } else { stamp() };
        self.db.execute("UPDATE journal SET repair=?, repaired_at=? WHERE id=?", params![text, when, entry_id])?;
        Ok(())
    }

    /// A review, as a commit; returns its hash.
    pub fn review(&self, identifier: i64, learned: &str, adjustment: &str) -> Result<String> {
        let now = stamp();
        let version = self.version_in_force(identifier, None)?;
        self.db.execute(
            "INSERT INTO reviews (commitment_id, learned, adjustment, created_at, version_id) VALUES (?, ?, ?, ?, ?)",
            params![identifier, learned, adjustment, now, version],
        )?;
        let rowid = self.db.last_insert_rowid();
        Ok(review_hash(rowid, identifier, learned, adjustment, &now))
    }

    /// Each commitment's creation, its edits and its reviews as commits, newest first.
    pub fn history(&self) -> Result<Vec<Event>> {
        let mut events = Vec::new();
        let commitments = self.all_commitments()?;
        for c in &commitments {
            events.push(Event {
                kind: "init",
                hash: init_hash(c.id, &c.created_at),
                commitment_id: c.id,
                title: c.title.clone(),
                created_at: c.created_at.clone(),
                order: (0, c.id),
                message: format!("init · {}", c.title),
                detail: glance(&c.pinned, &c.body, 3, 60).0,
            });
        }
        for c in &commitments {
            for (index, v) in self.versions(c.id)?.into_iter().enumerate().skip(1) {
                events.push(Event {
                    kind: "version",
                    hash: version_hash(v.id, v.commitment_id, &v.note, &v.created_at),
                    commitment_id: c.id,
                    title: c.title.clone(),
                    created_at: v.created_at,
                    order: (2, v.id),
                    message: format!("{} · {}", version_label(index), v.note),
                    detail: String::new(),
                });
            }
        }
        let mut statement = self.db.prepare_cached(
            "SELECT r.id, r.commitment_id, r.learned, r.adjustment, r.created_at, c.title FROM reviews r
                JOIN commitments c ON c.id = r.commitment_id
                ORDER BY r.created_at DESC, r.id DESC",
        )?;
        let reviews = statement.query_map([], |r| {
            let (id, cid, learned, adjustment, created_at, title): (i64, i64, String, String, String, String) =
                (r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?);
            Ok(Event {
                kind: "review",
                hash: review_hash(id, cid, &learned, &adjustment, &created_at),
                commitment_id: cid,
                title,
                created_at,
                order: (1, id),
                message: learned,
                detail: adjustment,
            })
        })?;
        for review in reviews {
            events.push(review?);
        }
        events.sort_by(|a, b| (&b.created_at, b.order).cmp(&(&a.created_at, a.order)));
        Ok(events)
    }

    /// Everything that happened from first_day to last_day (local dates, both included).
    ///
    /// Log entries, reviews, new commitments and their edits, oldest first,
    /// each with the local date it belongs to.
    pub fn events_between(&self, first_day: NaiveDate, last_day: NaiveDate) -> Result<Vec<DayEvent>> {
        let start = local_midnight_utc(first_day);
        let end = local_midnight_utc(last_day + chrono::Days::new(1));
        let mut statement = self.db.prepare_cached(
            "SELECT j.kind, j.note AS note, j.created_at, c.title, c.id AS commitment_id, j.repair FROM journal j
                JOIN commitments c ON c.id = j.commitment_id WHERE j.created_at >= ?1 AND j.created_at < ?2
            UNION ALL SELECT 'review', r.learned, r.created_at, c.title, c.id, '' FROM reviews r
                JOIN commitments c ON c.id = r.commitment_id WHERE r.created_at >= ?1 AND r.created_at < ?2
            UNION ALL SELECT CASE WHEN v.id = (SELECT MIN(id) FROM versions WHERE commitment_id = v.commitment_id)
                    THEN 'init' ELSE 'version' END, v.note, v.created_at, c.title, c.id, '' FROM versions v
                JOIN commitments c ON c.id = v.commitment_id WHERE v.created_at >= ?1 AND v.created_at < ?2
            ORDER BY 3",
        )?;
        let rows = statement.query_map([&start, &end], |r| {
            let created_at: String = r.get(2)?;
            let day = parse_local(&created_at).map(|d| d.date_naive()).unwrap_or(first_day);
            Ok(DayEvent {
                kind: r.get(0)?,
                note: r.get(1)?,
                created_at,
                title: r.get(3)?,
                commitment_id: r.get(4)?,
                repair: r.get(5)?,
                day,
            })
        })?;
        rows.collect()
    }

    /// {commitment_id: {kind: n}} over all time, reviews included. A commitment
    /// doesn't expire, so nothing here is a "last 7 days" window.
    pub fn experience_counts(&self) -> Result<HashMap<i64, HashMap<String, i64>>> {
        let mut counts: HashMap<i64, HashMap<String, i64>> = HashMap::new();
        let mut statement = self.db.prepare_cached(
            "SELECT commitment_id, kind, COUNT(*) n FROM journal GROUP BY commitment_id, kind
                UNION ALL SELECT commitment_id, 'review', COUNT(*) FROM reviews GROUP BY commitment_id",
        )?;
        let rows = statement.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, i64>(2)?)))?;
        for row in rows {
            let (cid, kind, n) = row?;
            counts.entry(cid).or_default().insert(kind, n);
        }
        Ok(counts)
    }

    /// The newest log entries and reviews, all commitments or one.
    pub fn recent(&self, limit: i64, commitment_id: Option<i64>) -> Result<Vec<Recent>> {
        let filter = if commitment_id.is_some() { "WHERE c.id = ?1" } else { "WHERE ?1 IS NULL" };
        let mut statement = self.db.prepare_cached(&format!(
            "SELECT * FROM (
                SELECT j.id, j.kind, j.note, j.repair, j.created_at, c.title, c.id cid FROM journal j
                    JOIN commitments c ON c.id = j.commitment_id {filter}
                UNION ALL SELECT r.id, 'review', r.learned, '', r.created_at, c.title, c.id FROM reviews r
                    JOIN commitments c ON c.id = r.commitment_id {filter})
            ORDER BY created_at DESC, id DESC LIMIT ?2"
        ))?;
        let rows = statement.query_map(params![commitment_id, limit], |r| {
            Ok(Recent {
                id: r.get(0)?,
                kind: r.get(1)?,
                note: r.get(2)?,
                repair: r.get(3)?,
                created_at: r.get(4)?,
                title: r.get(5)?,
                cid: r.get(6)?,
            })
        })?;
        rows.collect()
    }

    /// A Markdown copy next to the notebook; returns where it went.
    pub fn export(&self) -> std::io::Result<PathBuf> {
        let folder = self.path.parent().map(Path::to_path_buf).unwrap_or_default();
        let out = folder.join(format!("poparium-export-{}.md", Local::now().format("%Y%m%d-%H%M%S")));
        let lines = self.export_lines().map_err(std::io::Error::other)?;
        let mut file = OpenOptions::new().create(true).write(true).truncate(true).mode(0o600).open(&out)?;
        std::io::Write::write_all(&mut file, lines.join("\n").as_bytes())?;
        fs::set_permissions(&out, fs::Permissions::from_mode(0o600))?;
        Ok(out)
    }

    fn export_lines(&self) -> Result<Vec<String>> {
        let mut lines: Vec<String> = vec![
            format!("# {APP} / copia de mi bitácora"),
            String::new(),
            "Documento personal. Los acuerdos son revisables, no verdades absolutas.".into(),
            String::new(),
        ];
        for c in self.all_commitments()? {
            let versions = self.versions(c.id)?;
            lines.push(format!("## {}  (#{}, {}, {})", c.title, c.id, version_label(versions.len() - 1), c.status));
            lines.push(String::new());
            if !c.pinned.is_empty() {
                lines.extend(crate::pytext::splitlines(&c.pinned).iter().map(|l| format!("> {l}")));
                lines.push(String::new());
            }
            if !c.body.is_empty() {
                // The free text's own headings, one level down
                lines.extend(
                    crate::pytext::splitlines(&c.body)
                        .into_iter()
                        .map(|l| if l.starts_with('#') { format!("#{l}") } else { l }),
                );
                lines.push(String::new());
            }
            lines.extend(["### Historial del acuerdo".to_string(), String::new()]);
            for (index, v) in versions.iter().enumerate().rev() {
                lines.push(format!(
                    "- `{}` {} · {} · {}",
                    version_hash(v.id, v.commitment_id, &v.note, &v.created_at),
                    version_label(index),
                    display_date(&v.created_at),
                    v.note
                ));
            }
            lines.extend([String::new(), "### Avances y obstáculos".to_string(), String::new()]);
            let mut statement = self.db.prepare_cached(
                "SELECT created_at, kind, note FROM journal WHERE commitment_id=? ORDER BY id",
            )?;
            let journal = statement.query_map([c.id], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
            })?;
            for row in journal {
                let (created_at, kind, note) = row?;
                lines.push(format!("- {} · {kind}: {note}", display_date(&created_at)));
            }
            lines.extend([String::new(), "### Revisiones".to_string(), String::new()]);
            let mut statement = self.db.prepare_cached(
                "SELECT id, commitment_id, learned, adjustment, created_at FROM reviews WHERE commitment_id=? ORDER BY id",
            )?;
            let reviews = statement.query_map([c.id], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?, r.get::<_, String>(4)?))
            })?;
            for row in reviews {
                let (id, cid, learned, adjustment, created_at) = row?;
                lines.push(format!(
                    "- `{}` {} · Aprendí: {learned} · Ajusto: {adjustment}",
                    review_hash(id, cid, &learned, &adjustment, &created_at),
                    display_date(&created_at)
                ));
            }
            lines.push(String::new());
        }
        Ok(lines)
    }
}

fn version_in_force(db: &Connection, identifier: i64, when: Option<&str>) -> Result<Option<i64>> {
    let when = when.map(str::to_string).unwrap_or_else(stamp);
    let found: Option<i64> = db
        .query_row(
            "SELECT id FROM versions WHERE commitment_id=? AND created_at <= ? ORDER BY created_at DESC, id DESC LIMIT 1",
            params![identifier, when],
            |r| r.get(0),
        )
        .optional()?;
    if found.is_some() {
        return Ok(found);
    }
    // Logged for a day before the commitment existed: its first version
    db.query_row("SELECT MIN(id) FROM versions WHERE commitment_id=?", [identifier], |r| r.get(0))
}

fn snapshot(db: &Connection, identifier: i64, note: &str, when: &str) -> Result<()> {
    let doc = db.query_row("SELECT title, pinned, body FROM commitments WHERE id=?", [identifier], |r| {
        Ok(Doc { title: r.get(0)?, pinned: r.get(1)?, body: r.get(2)? })
    })?;
    db.execute(
        "INSERT INTO versions (commitment_id, note, snapshot, created_at) VALUES (?, ?, ?, ?)",
        params![identifier, note, snapshot_json(&doc), when],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::document::version_diff;
    use crate::history::commit_graph;

    /// A private folder per test, removed when it ends.
    struct Folder(PathBuf);

    impl Folder {
        fn new(name: &str) -> Folder {
            let path = std::env::temp_dir().join(format!("poparium-test-{}-{name}", std::process::id()));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).unwrap();
            Folder(path)
        }
    }

    impl Drop for Folder {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn mode(path: &Path) -> u32 {
        fs::metadata(path).unwrap().permissions().mode() & 0o777
    }

    fn doc(title: &str, pinned: &str) -> Doc {
        Doc::new(title, pinned, "")
    }

    fn old_notebook(path: &Path, sql: &str) {
        Connection::open(path).unwrap().execute_batch(sql).unwrap();
    }

    const V01: &str = "CREATE TABLE commitments (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        reason TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', cue TEXT NOT NULL DEFAULT '',
        success TEXT NOT NULL DEFAULT '', recovery TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO commitments (title, reason, created_at, updated_at)
        VALUES ('Antiguo', 'Porque sí', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00');";

    #[test]
    fn full_lifecycle() {
        let folder = Folder::new("lifecycle");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let id = store.create(&Doc::new("Revisar cuaderno", "Quiero ser autónomo", "Abrirlo tres minutos")).unwrap();
        assert_eq!(store.active().unwrap().len(), 1);
        store.log(id, "done", "Mi primer día", None).unwrap();
        store.log(id, "progress", "Me acordé sin ayuda", None).unwrap();
        store.log(id, "obstacle", "Sin disparador visible", None).unwrap();
        assert_eq!(store.entries(100).unwrap().len(), 3);
        assert_eq!(store.experience_counts().unwrap()[&id]["done"], 1);
        store.review(id, "Necesito un hábito existente", "Poner atajo fijo").unwrap();
        store.update_status(id, "archived").unwrap();
        assert!(store.active().unwrap().is_empty());
        assert_eq!(store.all_commitments().unwrap().len(), 1);
        let exported = store.export().unwrap();
        let content = fs::read_to_string(&exported).unwrap();
        for text in ["Mi primer día", "Poner atajo fijo", "Revisar cuaderno"] {
            assert!(content.contains(text), "{text}");
        }
        // The notebook and its export are private files
        assert_eq!(mode(&store.path), 0o600);
        assert_eq!(mode(&exported), 0o600);
    }

    #[test]
    fn review_returns_the_hash_shown_in_history() {
        let folder = Folder::new("review");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let id = store.create(&doc("Revisar cuaderno", "Quiero ser autónomo")).unwrap();
        let commit = store.review(id, "Aprendí algo", "Ajusto algo").unwrap();
        assert!(commit.len() == 7 && commit.chars().all(|c| c.is_ascii_hexdigit()));
        let history = store.history().unwrap();
        assert_eq!(history.iter().map(|e| e.kind).collect::<Vec<_>>(), ["review", "init"]);
        assert_eq!(history[0].hash, commit);
        assert!(fs::read_to_string(store.export().unwrap()).unwrap().contains(&commit));
    }

    #[test]
    fn graph_gives_each_commitment_its_own_lane() {
        let folder = Folder::new("graph");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("A", "porque A")).unwrap();
        let b = store.create(&doc("B", "porque B")).unwrap();
        store.review(a, "aprendí A", "").unwrap();
        store.review(b, "aprendí B", "").unwrap();
        // Everything was created in the same second: spread it over days, oldest first
        for (row, day) in [(a, 1), (b, 2)] {
            store.db.execute("UPDATE commitments SET created_at=? WHERE id=?", params![format!("2026-10-0{day}T00:00:00+00:00"), row]).unwrap();
        }
        store.db.execute("UPDATE reviews SET created_at='2026-10-03T00:00:00+00:00' WHERE commitment_id=?", [a]).unwrap();
        store.db.execute("UPDATE reviews SET created_at='2026-10-04T00:00:00+00:00' WHERE commitment_id=?", [b]).unwrap();
        let events = store.history().unwrap();
        let rows = commit_graph(&events);
        let drawn: Vec<String> =
            rows.iter().map(|r| format!("{} {}", r.top.iter().map(|(c, _)| c).collect::<String>(), r.event.message)).collect();
        assert_eq!(drawn, ["* aprendí B", "│* aprendí A", "*│ init · B", " * init · A"]);
        assert_eq!(rows.iter().map(|r| r.head).collect::<Vec<_>>(), [true, true, false, false]);
    }

    #[test]
    fn old_notebook_gains_sections_and_a_first_version() {
        let folder = Folder::new("old");
        let old = folder.0.join("old.db");
        old_notebook(&old, V01);
        let store = Store::open(&old).unwrap();
        let reasons: (String, String, String) = store
            .db
            .query_row("SELECT title, reason, reasoning FROM commitments", [], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap();
        assert_eq!(reasons, ("Antiguo".into(), "Porque sí".into(), String::new()));
        let item = &store.all_commitments().unwrap()[0];
        assert_eq!(store.versions(item.id).unwrap().iter().map(|v| v.note.as_str()).collect::<Vec<_>>(), ["Acuerdo inicial"]);
        let backup = folder.0.join("old.pre-0.2.db");
        assert_eq!(mode(&backup), 0o600);
        let title: String = Connection::open(&backup).unwrap().query_row("SELECT title FROM commitments", [], |r| r.get(0)).unwrap();
        assert_eq!(title, "Antiguo");
    }

    #[test]
    fn each_edit_is_a_version_with_its_diff() {
        let folder = Folder::new("versions");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let id = store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        assert_eq!(store.revise(id, &doc("Avisar", "Coordinarnos"), "nada").unwrap(), None);
        assert_eq!(store.revise(id, &doc("Avisar", "Coordinarnos, no controlar"), "Aclarado el motivo").unwrap().as_deref(), Some("v1.1"));
        let versions = store.versions(id).unwrap();
        assert_eq!(
            version_diff(&versions[0].snapshot, &versions[1].snapshot),
            ["## NOTA", "@@ -1 +1 @@", "-Coordinarnos", "+Coordinarnos, no controlar"]
        );
        let messages: Vec<String> = store.history().unwrap().into_iter().map(|e| e.message).collect();
        assert_eq!(messages, ["v1.1 · Aclarado el motivo", "init · Avisar"]);
        assert!(fs::read_to_string(store.export().unwrap()).unwrap().contains("v1.1 · "));
    }

    #[test]
    fn deleted_entries_and_commitments_can_come_back() {
        let folder = Folder::new("undo");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        store.log(a, "done", "Avisé a tiempo", None).unwrap();
        store.log(a, "obstacle", "Lo olvidé", None).unwrap();
        store.review(a, "Aprendí", "Ajusto").unwrap();
        store.revise(a, &doc("Avisar", "Coordinarnos mejor"), "Aclarado").unwrap();
        let entry = store.entries(100).unwrap()[0].clone();
        let removed = store.delete_entry(entry.id).unwrap();
        assert_eq!(store.entries(100).unwrap().iter().map(|e| e.note.as_str()).collect::<Vec<_>>(), ["Avisé a tiempo"]);
        store.restore(&removed).unwrap();
        assert_eq!(store.entries(100).unwrap()[0].id, entry.id);
        let before = (store.history().unwrap(), store.entries(100).unwrap());
        let removed = store.delete_commitment(a).unwrap();
        assert!(store.all_commitments().unwrap().is_empty() && store.entries(100).unwrap().is_empty());
        assert!(store.history().unwrap().is_empty());
        store.restore(&removed).unwrap();
        assert_eq!((store.history().unwrap(), store.entries(100).unwrap()), before);
    }

    #[test]
    fn old_sections_become_free_text_once() {
        let folder = Folder::new("sections");
        let old = folder.0.join("old.db");
        old_notebook(&old, "CREATE TABLE commitments (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            reason TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', cue TEXT NOT NULL DEFAULT '',
            success TEXT NOT NULL DEFAULT '', recovery TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '', reasoning TEXT NOT NULL DEFAULT '', agreement TEXT NOT NULL DEFAULT '',
            exceptions TEXT NOT NULL DEFAULT '', tracking TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO commitments (title, reason, agreement, cue, tracking, created_at, updated_at)
            VALUES ('Comida', 'Nos sienta bien', 'Aviso si me retraso', 'Al mediodía', 'periodic',
                    '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00');");
        {
            let store = Store::open(&old).unwrap();
            let item = store.all_commitments().unwrap()[0].clone();
            assert_eq!(item.pinned, "Aviso si me retraso");
            assert!(item.body.contains("## Por qué me importa\n\nNos sienta bien"));
            assert!(item.body.contains("## Desencadenantes\n\nAl mediodía"));
            assert!(item.body.contains("periódico"));
            let reason: String = store.db.query_row("SELECT reason FROM commitments", [], |r| r.get(0)).unwrap();
            assert_eq!(reason, "Nos sienta bien"); // the old column is kept
            assert!(folder.0.join("old.pre-0.3.db").exists());
            // The old v1.0 reads as the new document: an edit diffs only what changed
            store.revise(1, &Doc::new("Comida", "Aviso si me retraso, siempre", &item.body), "Matiz").unwrap();
            let versions = store.versions(1).unwrap();
            let diff = version_diff(&versions[0].snapshot, &versions[1].snapshot);
            assert_eq!(diff[0], "## NOTA");
            assert_eq!(diff.iter().filter(|l| l.starts_with("## ")).count(), 1);
            // Once only: emptying the text later doesn't bring the old sections back
            store.revise(1, &Doc::new("Comida", "Aviso si me retraso, siempre", ""), "Limpio").unwrap();
        }
        assert_eq!(Store::open(&old).unwrap().all_commitments().unwrap()[0].body, "");
    }

    #[test]
    fn entries_remember_the_version_in_force() {
        let folder = Folder::new("in-force");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        store.log(a, "done", "antes", None).unwrap();
        store.revise(a, &doc("Avisar", "Coordinarnos mejor"), "Aclarado").unwrap();
        store.log(a, "done", "después", None).unwrap();
        store.review(a, "Aprendí", "").unwrap();
        let ids: Vec<i64> = store.versions(a).unwrap().iter().map(|v| v.id).collect();
        let rows: Vec<(String, i64)> = store
            .db
            .prepare("SELECT note, version_id FROM journal ORDER BY id")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap()
            .collect::<Result<_>>()
            .unwrap();
        assert_eq!(rows, [("antes".to_string(), ids[0]), ("después".to_string(), ids[1])]);
        let review: i64 = store.db.query_row("SELECT version_id FROM reviews", [], |r| r.get(0)).unwrap();
        assert_eq!(review, ids[1]);
    }

    #[test]
    fn old_entries_get_the_version_that_was_in_force_then() {
        let folder = Folder::new("old-entries");
        let old = folder.0.join("old.db");
        old_notebook(&old, &format!("{V01}
            CREATE TABLE journal (id INTEGER PRIMARY KEY, commitment_id INTEGER NOT NULL, kind TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
            INSERT INTO journal (commitment_id, kind, note, created_at) VALUES (1, 'done', 'hecho', '2026-10-02T00:00:00+00:00');"));
        let store = Store::open(&old).unwrap();
        let v0 = store.versions(1).unwrap()[0].id;
        let version: i64 = store.db.query_row("SELECT version_id FROM journal", [], |r| r.get(0)).unwrap();
        assert_eq!(version, v0);
    }

    #[test]
    fn calendar_groups_by_local_day() {
        let folder = Folder::new("calendar");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        store.log(a, "obstacle", "hoy", None).unwrap();
        let today = crate::dates::today();
        let mut seen: Vec<(String, NaiveDate)> =
            store.events_between(today, today).unwrap().into_iter().map(|e| (e.kind, e.day)).collect();
        seen.sort();
        assert_eq!(seen, [("init".to_string(), today), ("obstacle".to_string(), today)]);
        assert!(store.events_between(today + chrono::Days::new(1), today + chrono::Days::new(2)).unwrap().is_empty());
    }

    #[test]
    fn obstacles_can_be_repaired_later() {
        let folder = Folder::new("repair");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        store.log(a, "obstacle", "", None).unwrap(); // an empty note is fine: it happened
        let entry = store.entries(100).unwrap()[0].clone();
        store.repair(entry.id, "Pedí perdón y avisé").unwrap();
        assert_eq!(store.entries(100).unwrap()[0].repair, "Pedí perdón y avisé");
        assert_eq!(store.recent(8, Some(a)).unwrap()[0].repair, "Pedí perdón y avisé");
    }

    #[test]
    fn logging_another_day_keeps_the_version_of_that_day() {
        let folder = Folder::new("another-day");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        store.db.execute("UPDATE versions SET created_at='2026-10-01T00:00:00+00:00'", []).unwrap();
        store.revise(a, &doc("Avisar", "Coordinarnos mejor"), "Aclarado").unwrap();
        let ids: Vec<i64> = store.versions(a).unwrap().iter().map(|v| v.id).collect();
        store.log(a, "done", "me acordé tarde", Some("2026-10-03T12:00:00+00:00")).unwrap();
        store.log(a, "done", "hoy", None).unwrap();
        let rows: Vec<(String, i64, String)> = store
            .db
            .prepare("SELECT note, version_id, created_at FROM journal ORDER BY id")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap()
            .collect::<Result<_>>()
            .unwrap();
        assert_eq!((rows[0].1, rows[1].1), (ids[0], ids[1]));
        assert!(rows[0].2.starts_with("2026-10-03"));
    }

    #[test]
    fn integrated_commitments_stay_in_the_list() {
        let folder = Folder::new("integrated");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        let a = store.create(&doc("A", "x")).unwrap();
        let b = store.create(&doc("B", "y")).unwrap();
        store.update_status(a, "integrated").unwrap();
        store.update_status(b, "archived").unwrap();
        assert_eq!(store.active().unwrap().iter().map(|c| c.title.as_str()).collect::<Vec<_>>(), ["A"]);
    }

    #[test]
    fn daily_backups_are_private_and_pruned() {
        let folder = Folder::new("backups");
        let store = Store::open(&folder.0.join("store.db")).unwrap();
        assert_eq!(store.daily_backup(None).unwrap(), None); // nothing to copy yet
        store.create(&doc("Avisar", "Coordinarnos")).unwrap();
        let today = NaiveDate::from_ymd_opt(2026, 10, 11).unwrap();
        let first = store.daily_backup(Some(today)).unwrap().unwrap();
        assert_eq!(mode(&first), 0o600);
        assert_eq!(mode(first.parent().unwrap()), 0o700);
        let title: String = Connection::open(&first).unwrap().query_row("SELECT title FROM commitments", [], |r| r.get(0)).unwrap();
        assert_eq!(title, "Avisar");
        assert_eq!(store.daily_backup(Some(today)).unwrap().unwrap(), first); // once a day
        for days in 1..400 {
            store.daily_backup(Some(today + chrono::Days::new(days))).unwrap();
        }
        let kept = names_in(first.parent().unwrap());
        assert!(kept.len() <= 14 + 12);
        assert!(kept.iter().any(|f| f.contains("2027-11-14"))); // the newest
    }

    #[test]
    fn backups_keep_two_weeks_and_a_year_of_months() {
        let today = NaiveDate::from_ymd_opt(2026, 10, 11).unwrap();
        let dates: BTreeSet<NaiveDate> = (0..500).map(|n| today - chrono::Days::new(n)).collect();
        let keep = backups_to_keep(&dates, today);
        assert!((0..14).all(|n| keep.contains(&(today - chrono::Days::new(n)))));
        assert!(!keep.contains(&(today - chrono::Days::new(20))));
        let months: BTreeSet<(i32, u32)> = keep.iter().map(|d| (d.year(), d.month())).collect();
        assert_eq!(months.len(), 12);
    }

    #[test]
    fn popos_folder_becomes_poparium() {
        let folder = Folder::new("popos");
        let (old, new) = (folder.0.join("popos"), folder.0.join("poparium"));
        fs::create_dir_all(old.join("popos.backups")).unwrap();
        fs::create_dir_all(old.join("popos.drafts")).unwrap();
        for name in ["popos.db", "popos.pre-0.3.db", "popos.backups/popos-2026-10-11.db", "popos.drafts/nuevo.md"] {
            fs::write(old.join(name), name).unwrap();
        }
        assert_eq!(adopt_legacy_folder(&new, &old, "popos"), new.join("poparium.db"));
        assert!(!old.exists());
        assert_eq!(fs::read_to_string(new.join("poparium.db")).unwrap(), "popos.db");
        assert!(new.join("poparium.pre-0.3.db").exists());
        assert!(new.join("poparium.backups/poparium-2026-10-11.db").exists());
        assert!(new.join("poparium.drafts/nuevo.md").exists());
        assert_eq!(adopt_legacy_folder(&new, &old, "popos"), new.join("poparium.db")); // nothing left to do
    }

    #[test]
    fn half_renamed_keepstate_files_finish_as_poparium() {
        let folder = Folder::new("keepstate");
        let new = folder.0.join("poparium");
        fs::create_dir_all(new.join("poparium.backups")).unwrap();
        for name in ["poparium.db", "keepstate.pre-0.2.db", "poparium.backups/keepstate-2026-10-01.db"] {
            fs::write(new.join(name), name).unwrap();
        }
        assert_eq!(adopt_legacy_folder(&new, &folder.0.join("keepstate"), "keepstate"), new.join("poparium.db"));
        assert_eq!(fs::read_to_string(new.join("poparium.db")).unwrap(), "poparium.db");
        assert!(new.join("poparium.pre-0.2.db").exists());
        assert!(new.join("poparium.backups/poparium-2026-10-01.db").exists());
    }

    #[test]
    fn legacy_folder_mid_write_stays_put() {
        let folder = Folder::new("mid-write");
        let (old, new) = (folder.0.join("popos"), folder.0.join("poparium"));
        fs::create_dir_all(&old).unwrap();
        fs::write(old.join("popos.db"), "db").unwrap();
        fs::write(old.join("popos.db-journal"), "journal").unwrap();
        assert_eq!(adopt_legacy_folder(&new, &old, "popos"), old.join("popos.db"));
        assert!(!new.exists());
    }

    #[test]
    fn snapshots_are_written_as_python_wrote_them() {
        let doc = Doc::new("Tí\"tulo", "a\\b\nc\td\u{1}", "ñ 🐾");
        assert_eq!(
            snapshot_json(&doc),
            r#"{"title": "Tí\"tulo", "pinned": "a\\b\nc\td\u0001", "body": "ñ 🐾"}"#
        );
        assert_eq!(read_snapshot(&snapshot_json(&doc)), doc);
    }
}
