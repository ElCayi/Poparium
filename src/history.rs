//! Versions and reviews as commits: short hashes and the git log --graph layout.

/// Seven hex chars, like `git log --oneline`. Same content, same hash.
pub fn short_hash(parts: &[&str]) -> String {
    let digest = sha1_smol::Sha1::from(parts.join("\n")).digest().to_string();
    digest[..7].to_string()
}

pub fn init_hash(id: i64, created_at: &str) -> String {
    short_hash(&["init", &id.to_string(), created_at])
}

pub fn review_hash(id: i64, commitment_id: i64, learned: &str, adjustment: &str, created_at: &str) -> String {
    short_hash(&["review", &id.to_string(), &commitment_id.to_string(), learned, adjustment, created_at])
}

pub fn version_hash(id: i64, commitment_id: i64, note: &str, created_at: &str) -> String {
    short_hash(&["version", &id.to_string(), &commitment_id.to_string(), note, created_at])
}

/// v1.0 is the commitment as first written; each edit adds one.
pub fn version_label(index: usize) -> String {
    format!("v1.{index}")
}

/// One commit of the REVIEW tab: a commitment's creation, an edit or a review.
#[derive(Clone, Debug, PartialEq)]
pub struct Event {
    pub kind: &'static str,
    pub hash: String,
    pub commitment_id: i64,
    pub title: String,
    pub created_at: String,
    pub order: (u8, i64),
    pub message: String,
    pub detail: String,
}

/// (char, commitment id) cells of a graph row; None is an empty lane.
pub type Lanes = Vec<(char, Option<i64>)>;

pub struct GraphRow<'a> {
    pub top: Lanes,
    pub below: Lanes,
    /// The commitment's newest commit, where its lane starts
    pub head: bool,
    pub event: &'a Event,
}

/// Lay out events (newest first) as `git log --graph` lanes, one per commitment.
pub fn commit_graph(events: &[Event]) -> Vec<GraphRow<'_>> {
    let mut oldest = std::collections::HashMap::new();
    for (i, e) in events.iter().enumerate() {
        oldest.insert(e.commitment_id, i);
    }
    let mut columns: Vec<Option<i64>> = Vec::new();
    let mut rows = Vec::new();
    for (i, e) in events.iter().enumerate() {
        let cid = e.commitment_id;
        let head = !columns.contains(&Some(cid));
        if head {
            match columns.iter().position(Option::is_none) {
                Some(free) => columns[free] = Some(cid),
                None => columns.push(Some(cid)),
            }
        }
        let top = columns
            .iter()
            .map(|&c| (if c == Some(cid) { '*' } else if c.is_some() { '│' } else { ' ' }, c))
            .collect();
        if oldest[&cid] == i {
            let at = columns.iter().position(|&c| c == Some(cid)).expect("its lane is there");
            columns[at] = None;
            while columns.last() == Some(&None) {
                columns.pop();
            }
        }
        let below = columns.iter().map(|&c| (if c.is_some() { '│' } else { ' ' }, c)).collect();
        rows.push(GraphRow { top, below, head, event: e });
    }
    rows
}
