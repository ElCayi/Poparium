//! Unfinished writing, kept on disk until it reaches the notebook.
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

/// Unfinished writing, kept next to the notebook until it reaches it.
///
/// A draft is only deleted once its content is saved in the database (or
/// deliberately thrown away), so closing the app, the tmux pane or the
/// whole session at any moment loses nothing that was typed.
pub struct Drafts {
    pub folder: PathBuf,
    /// Told after every change to the unsaved documents (see new())
    pub on_change: Option<Box<dyn Fn(bool)>>,
}

/// Whether a folder holds an unsaved document (a .md draft; a field's .txt doesn't count).
pub fn has_documents(folder: &Path) -> bool {
    fs::read_dir(folder)
        .map(|entries| entries.filter_map(Result::ok).any(|e| e.file_name().to_string_lossy().ends_with(".md")))
        .unwrap_or(false)
}

impl Drafts {
    /// on_change(unsaved) is called now and after every change to the
    /// unsaved documents, with whether any remain: how Popo's ✎ in tmux follows them.
    pub fn new(folder: PathBuf, on_change: Option<Box<dyn Fn(bool)>>) -> Drafts {
        let _ = fs::create_dir_all(&folder);
        let _ = fs::set_permissions(&folder, fs::Permissions::from_mode(0o700));
        let drafts = Drafts { folder, on_change };
        drafts.changed();
        drafts
    }

    pub fn unsaved(&self) -> bool {
        has_documents(&self.folder)
    }

    fn changed(&self) {
        // No memory of the last value: another Poparium (the popup and the poparium
        // session at once) may have changed the folder meanwhile
        if let Some(on_change) = &self.on_change {
            on_change(self.unsaved());
        }
    }

    pub fn path(&self, name: &str, suffix: &str) -> PathBuf {
        self.folder.join(format!("{name}{suffix}"))
    }

    /// Where the editor copies every change, separate from the real file.
    pub fn autosave_path(&self, name: &str) -> PathBuf {
        self.path(name, ".autosave.md")
    }

    pub fn write(&self, name: &str, text: &str, suffix: &str) -> PathBuf {
        let path = self.path(name, suffix);
        if let Ok(mut file) = OpenOptions::new().create(true).write(true).truncate(true).mode(0o600).open(&path) {
            let _ = file.write_all(text.as_bytes());
        }
        if suffix == ".md" {
            self.changed();
        }
        path
    }

    /// The newest unsaved text: the editor's autosave beats the last :w.
    pub fn recover(&self, name: &str, suffix: &str) -> Option<String> {
        let mut candidates = Vec::new();
        if suffix == ".md" {
            candidates.push(self.autosave_path(name));
        }
        candidates.push(self.path(name, suffix));
        candidates.into_iter().find(|p| p.exists()).and_then(|p| fs::read_to_string(p).ok())
    }

    pub fn drop_autosave(&self, name: &str) {
        let _ = fs::remove_file(self.autosave_path(name));
        self.changed();
    }

    pub fn discard(&self, name: &str, suffix: &str) {
        let _ = fs::remove_file(self.path(name, suffix));
        if suffix == ".md" {
            self.drop_autosave(name); // which calls changed()
        }
    }

    /// Names of unsaved documents ("nuevo", "acuerdo-7"), oldest first.
    pub fn pending(&self) -> Vec<String> {
        let mut files: Vec<(std::time::SystemTime, String)> = fs::read_dir(&self.folder)
            .map(|entries| {
                entries
                    .filter_map(Result::ok)
                    .filter_map(|e| {
                        let name = e.file_name().to_string_lossy().into_owned();
                        let modified = e.metadata().ok()?.modified().ok()?;
                        name.ends_with(".md").then_some((modified, name))
                    })
                    .collect()
            })
            .unwrap_or_default();
        files.sort_by_key(|(modified, _)| *modified);
        let mut names: Vec<String> = Vec::new();
        for (_, file) in files {
            let name = file.split('.').next().unwrap_or_default().to_string();
            if !names.contains(&name) {
                names.push(name);
            }
        }
        names
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    fn folder() -> PathBuf {
        let dir = std::env::temp_dir().join(format!("poparium-drafts-{}-{:?}", std::process::id(), std::thread::current().id()));
        let _ = fs::remove_dir_all(&dir);
        dir.join("store.drafts")
    }

    #[test]
    fn drafts_are_private_and_the_autosave_wins() {
        let drafts = Drafts::new(folder(), None);
        assert_eq!(fs::metadata(&drafts.folder).unwrap().permissions().mode() & 0o777, 0o700);
        assert_eq!(drafts.recover("nuevo", ".md"), None);
        let path = drafts.write("nuevo", "# Último :w", ".md");
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        assert_eq!(drafts.recover("nuevo", ".md").as_deref(), Some("# Último :w"));
        // The editor died after more typing: that typing is what comes back
        fs::write(drafts.autosave_path("nuevo"), "# Último :w y algo más").unwrap();
        assert_eq!(drafts.recover("nuevo", ".md").as_deref(), Some("# Último :w y algo más"));
        assert_eq!(drafts.pending(), ["nuevo"]);
        drafts.discard("nuevo", ".md");
        assert_eq!((drafts.recover("nuevo", ".md"), drafts.pending()), (None, vec![]));
        drafts.write("linea-abc", "a medias", ".txt");
        assert_eq!(drafts.recover("linea-abc", ".txt").as_deref(), Some("a medias"));
        assert!(drafts.pending().is_empty());
        let _ = fs::remove_dir_all(drafts.folder.parent().unwrap());
    }

    #[test]
    fn drafts_report_only_unsaved_documents() {
        let seen = Rc::new(RefCell::new(Vec::new()));
        let log = seen.clone();
        let mut dir = folder();
        dir.set_file_name("report.drafts");
        let drafts = Drafts::new(dir, Some(Box::new(move |unsaved| log.borrow_mut().push(unsaved))));
        drafts.write("campo", "a medias", ".txt");
        drafts.write("nuevo", "a medias", ".md");
        fs::write(drafts.autosave_path("nuevo"), "más").unwrap();
        drafts.drop_autosave("nuevo");
        drafts.discard("nuevo", ".md");
        drafts.discard("campo", ".txt");
        assert_eq!(*seen.borrow(), [false, true, true, false]);
        let _ = fs::remove_dir_all(drafts.folder.parent().unwrap());
    }
}
