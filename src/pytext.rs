//! Python's text behaviour, where the app shows it: `str.splitlines`,
//! `str.capitalize`, `textwrap.wrap` and `difflib.unified_diff`. Ported rather
//! than approximated, so wrapped lines and version diffs read exactly as before.

/// Lengths are counted in characters, as Python's `len` does.
pub fn len(text: &str) -> usize {
    text.chars().count()
}

/// The first `n` characters.
pub fn take(text: &str, n: usize) -> String {
    text.chars().take(n).collect()
}

/// `text.ljust(width)`.
pub fn ljust(text: &str, width: usize) -> String {
    let n = len(text);
    if n >= width { text.to_string() } else { format!("{text}{}", " ".repeat(width - n)) }
}

/// `str.splitlines()`: every line boundary Python knows, no trailing empty line.
pub fn splitlines(text: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut current = String::new();
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\r' => {
                if chars.peek() == Some(&'\n') {
                    chars.next();
                }
                lines.push(std::mem::take(&mut current));
            }
            '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}' => {
                lines.push(std::mem::take(&mut current))
            }
            _ => current.push(c),
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

/// `str.capitalize()`: the first character upper case, the rest lower.
pub fn capitalize(text: &str) -> String {
    let mut chars = text.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars.flat_map(char::to_lowercase)).collect(),
        None => String::new(),
    }
}

// ---------------------------------------------------------------- textwrap

const ASCII_WS: [char; 6] = [' ', '\t', '\n', '\x0b', '\x0c', '\r'];

fn is_ws(c: char) -> bool {
    ASCII_WS.contains(&c)
}

/// `\w` in a Python str pattern.
fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// `[^\d\W]`: a word character that isn't a digit.
fn is_letter(c: char) -> bool {
    is_word(c) && !c.is_numeric()
}

/// `[\w!"'&.,?]`
fn is_word_punct(c: char) -> bool {
    is_word(c) || matches!(c, '!' | '"' | '\'' | '&' | '.' | ',' | '?')
}

fn expand_tabs(text: &str) -> String {
    let mut out = String::new();
    let mut column = 0;
    for c in text.chars() {
        match c {
            '\t' => {
                let spaces = 8 - column % 8;
                out.extend(std::iter::repeat_n(' ', spaces));
                column += spaces;
            }
            '\n' | '\r' => {
                out.push(c);
                column = 0;
            }
            _ => {
                out.push(c);
                column += 1;
            }
        }
    }
    out
}

/// TextWrapper.wordsep_re with break_on_hyphens: whitespace runs, em-dashes
/// between words, and words split after their hyphens.
fn split_chunks(text: &[char]) -> Vec<Vec<char>> {
    let at = |i: isize| -> Option<char> { if i < 0 { None } else { text.get(i as usize).copied() } };
    let letter = |i: isize| at(i).is_some_and(is_letter);
    let mut chunks = Vec::new();
    let mut p = 0usize;
    while p < text.len() {
        if is_ws(text[p]) {
            let start = p;
            while p < text.len() && is_ws(text[p]) {
                p += 1;
            }
            chunks.push(text[start..p].to_vec());
            continue;
        }
        // An em-dash between words: (?<=wp) -{2,} (?=\w)
        if p > 0 && is_word_punct(text[p - 1]) && text[p] == '-' && at(p as isize + 1) == Some('-') {
            let mut q = p;
            while q < text.len() && text[q] == '-' {
                q += 1;
            }
            if at(q as isize).is_some_and(is_word) {
                chunks.push(text[p..q].to_vec());
                p = q;
                continue;
            }
        }
        // A word, as short as one of its endings allows
        let mut q = p + 1;
        loop {
            let qi = q as isize;
            // A hyphenated word: the hyphen stays with the first part
            if at(qi) == Some('-')
                && ((letter(qi - 2) && letter(qi - 1)) || (letter(qi - 3) && at(qi - 2) == Some('-') && letter(qi - 1)))
                && letter(qi + 1)
                && (letter(qi + 2) || (at(qi + 2) == Some('-') && letter(qi + 3)))
            {
                q += 1;
                break;
            }
            // The end of the word
            if q >= text.len() || is_ws(text[q]) {
                break;
            }
            // Before an em-dash
            if is_word_punct(text[q - 1]) && text[q] == '-' && at(qi + 1) == Some('-') {
                let mut r = q;
                while r < text.len() && text[r] == '-' {
                    r += 1;
                }
                if at(r as isize).is_some_and(is_word) {
                    break;
                }
            }
            q += 1;
        }
        chunks.push(text[p..q].to_vec());
        p = q;
    }
    chunks
}

fn blank(chunk: &[char]) -> bool {
    chunk.iter().all(|c| c.is_whitespace())
}

/// `textwrap.wrap(text, width, break_long_words=True)`.
pub fn wrap(text: &str, width: usize) -> Vec<String> {
    let munged: Vec<char> = expand_tabs(text).chars().map(|c| if is_ws(c) { ' ' } else { c }).collect();
    let mut chunks = split_chunks(&munged);
    chunks.reverse();
    let mut lines: Vec<String> = Vec::new();
    while !chunks.is_empty() {
        let mut line: Vec<Vec<char>> = Vec::new();
        let mut used = 0;
        if !lines.is_empty() && blank(chunks.last().expect("not empty")) {
            chunks.pop();
        }
        while let Some(chunk) = chunks.last() {
            if used + chunk.len() <= width {
                used += chunk.len();
                line.push(chunks.pop().expect("not empty"));
            } else {
                break;
            }
        }
        // A word longer than any line: cut what fits, after a hyphen when there is one
        let space_left = if width < 1 { 1 } else { width - used };
        if space_left > 0
            && let Some(chunk) = chunks.pop_if(|c| c.len() > width)
        {
            let mut end = space_left;
            if chunk.len() > space_left
                && let Some(hyphen) = chunk[..space_left].iter().rposition(|&c| c == '-')
                && hyphen > 0
                && chunk[..hyphen].iter().any(|&c| c != '-')
            {
                end = hyphen + 1;
            }
            line.push(chunk[..end].to_vec());
            chunks.push(chunk[end..].to_vec());
        } else if line.is_empty()
            && let Some(chunk) = chunks.pop_if(|c| c.len() > width)
        {
            line.push(chunk);
        }
        if line.last().is_some_and(|c| blank(c)) {
            line.pop();
        }
        if !line.is_empty() {
            lines.push(line.concat().into_iter().collect());
        }
        // An empty rest of a cut word fits anywhere and adds nothing
        if chunks.last().is_some_and(|c| c.is_empty()) {
            chunks.pop();
        }
    }
    lines
}

// ---------------------------------------------------------------- difflib

/// difflib.SequenceMatcher(None, a, b) with autojunk, enough for unified_diff.
struct Matcher<'a> {
    a: &'a [String],
    b: &'a [String],
    b2j: std::collections::HashMap<&'a str, Vec<usize>>,
}

type Opcode = (&'static str, usize, usize, usize, usize);

impl<'a> Matcher<'a> {
    fn new(a: &'a [String], b: &'a [String]) -> Self {
        let mut b2j: std::collections::HashMap<&str, Vec<usize>> = std::collections::HashMap::new();
        for (i, line) in b.iter().enumerate() {
            b2j.entry(line.as_str()).or_default().push(i);
        }
        if b.len() >= 200 {
            let ntest = b.len() / 100 + 1;
            b2j.retain(|_, indices| indices.len() <= ntest);
        }
        Matcher { a, b, b2j }
    }

    fn find_longest_match(&self, alo: usize, ahi: usize, blo: usize, bhi: usize) -> (usize, usize, usize) {
        let (mut besti, mut bestj, mut bestsize) = (alo, blo, 0);
        let mut j2len: std::collections::HashMap<usize, usize> = std::collections::HashMap::new();
        for i in alo..ahi {
            let mut next: std::collections::HashMap<usize, usize> = std::collections::HashMap::new();
            if let Some(indices) = self.b2j.get(self.a[i].as_str()) {
                for &j in indices {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = j.checked_sub(1).and_then(|p| j2len.get(&p)).copied().unwrap_or(0) + 1;
                    next.insert(j, k);
                    if k > bestsize {
                        besti = i + 1 - k;
                        bestj = j + 1 - k;
                        bestsize = k;
                    }
                }
            }
            j2len = next;
        }
        // No junk: popular lines still extend a match at its ends
        while besti > alo && bestj > blo && self.a[besti - 1] == self.b[bestj - 1] {
            besti -= 1;
            bestj -= 1;
            bestsize += 1;
        }
        while besti + bestsize < ahi && bestj + bestsize < bhi && self.a[besti + bestsize] == self.b[bestj + bestsize] {
            bestsize += 1;
        }
        (besti, bestj, bestsize)
    }

    fn matching_blocks(&self) -> Vec<(usize, usize, usize)> {
        let (la, lb) = (self.a.len(), self.b.len());
        let mut queue = vec![(0, la, 0, lb)];
        let mut blocks = Vec::new();
        while let Some((alo, ahi, blo, bhi)) = queue.pop() {
            let (i, j, k) = self.find_longest_match(alo, ahi, blo, bhi);
            if k > 0 {
                blocks.push((i, j, k));
                if alo < i && blo < j {
                    queue.push((alo, i, blo, j));
                }
                if i + k < ahi && j + k < bhi {
                    queue.push((i + k, ahi, j + k, bhi));
                }
            }
        }
        blocks.sort();
        let (mut i1, mut j1, mut k1) = (0, 0, 0);
        let mut joined = Vec::new();
        for (i2, j2, k2) in blocks {
            if i1 + k1 == i2 && j1 + k1 == j2 {
                k1 += k2;
            } else {
                if k1 > 0 {
                    joined.push((i1, j1, k1));
                }
                (i1, j1, k1) = (i2, j2, k2);
            }
        }
        if k1 > 0 {
            joined.push((i1, j1, k1));
        }
        joined.push((la, lb, 0));
        joined
    }

    fn opcodes(&self) -> Vec<Opcode> {
        let (mut i, mut j) = (0, 0);
        let mut answer = Vec::new();
        for (ai, bj, size) in self.matching_blocks() {
            let tag = if i < ai && j < bj {
                "replace"
            } else if i < ai {
                "delete"
            } else if j < bj {
                "insert"
            } else {
                ""
            };
            if !tag.is_empty() {
                answer.push((tag, i, ai, j, bj));
            }
            (i, j) = (ai + size, bj + size);
            if size > 0 {
                answer.push(("equal", ai, i, bj, j));
            }
        }
        answer
    }

    fn grouped_opcodes(&self, n: usize) -> Vec<Vec<Opcode>> {
        let mut codes = self.opcodes();
        if codes.is_empty() {
            codes = vec![("equal", 0, 1, 0, 1)];
        }
        if codes[0].0 == "equal" {
            let (tag, i1, i2, j1, j2) = codes[0];
            codes[0] = (tag, i1.max(i2.saturating_sub(n)), i2, j1.max(j2.saturating_sub(n)), j2);
        }
        let last = codes.len() - 1;
        if codes[last].0 == "equal" {
            let (tag, i1, i2, j1, j2) = codes[last];
            codes[last] = (tag, i1, i2.min(i1 + n), j1, j2.min(j1 + n));
        }
        let nn = n + n;
        let mut groups = Vec::new();
        let mut group = Vec::new();
        for (tag, mut i1, i2, mut j1, j2) in codes {
            if tag == "equal" && i2 - i1 > nn {
                group.push((tag, i1, i2.min(i1 + n), j1, j2.min(j1 + n)));
                groups.push(std::mem::take(&mut group));
                i1 = i1.max(i2.saturating_sub(n));
                j1 = j1.max(j2.saturating_sub(n));
            }
            group.push((tag, i1, i2, j1, j2));
        }
        if !group.is_empty() && !(group.len() == 1 && group[0].0 == "equal") {
            groups.push(group);
        }
        groups
    }
}

fn format_range(start: usize, stop: usize) -> String {
    let mut beginning = start + 1;
    let length = stop - start;
    if length == 1 {
        return beginning.to_string();
    }
    if length == 0 {
        beginning -= 1;
    }
    format!("{beginning},{length}")
}

/// `difflib.unified_diff(a, b, lineterm="", n=n)`, file header lines included.
pub fn unified_diff(a: &[String], b: &[String], n: usize) -> Vec<String> {
    let matcher = Matcher::new(a, b);
    let mut out = Vec::new();
    for (index, group) in matcher.grouped_opcodes(n).into_iter().enumerate() {
        if index == 0 {
            out.push("--- ".to_string());
            out.push("+++ ".to_string());
        }
        let (first, last) = (group[0], group[group.len() - 1]);
        out.push(format!("@@ -{} +{} @@", format_range(first.1, last.2), format_range(first.3, last.4)));
        for (tag, i1, i2, j1, j2) in group {
            if tag == "equal" {
                out.extend(a[i1..i2].iter().map(|line| format!(" {line}")));
                continue;
            }
            if tag == "replace" || tag == "delete" {
                out.extend(a[i1..i2].iter().map(|line| format!("-{line}")));
            }
            if tag == "replace" || tag == "insert" {
                out.extend(b[j1..j2].iter().map(|line| format!("+{line}")));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(text: &str) -> Vec<String> {
        splitlines(text)
    }

    #[test]
    fn wrap_like_textwrap() {
        assert_eq!(wrap("hola que tal estas", 8), ["hola que", "tal", "estas"]);
        assert_eq!(wrap("", 8), Vec::<String>::new());
        assert_eq!(wrap("   ", 8), Vec::<String>::new());
        assert_eq!(wrap("abcdefghijkl", 5), ["abcde", "fghij", "kl"]);
        assert_eq!(wrap("bien-estar y auto-cuidado diario", 12), ["bien-estar y", "auto-cuidado", "diario"]);
        assert_eq!(wrap("un ejemplo-largo-con-guiones", 14), ["un ejemplo-", "largo-con-", "guiones"]);
        assert_eq!(wrap("  sangría inicial", 10), ["  sangría", "inicial"]);
        assert_eq!(wrap("palabra--otra", 9), ["palabra--", "otra"]);
    }

    #[test]
    fn diffs_like_difflib() {
        assert_eq!(unified_diff(&lines("a"), &lines("b"), 1), ["--- ", "+++ ", "@@ -1 +1 @@", "-a", "+b"]);
        assert_eq!(
            unified_diff(&lines("1\n2\n3\n4\n5\n6\n7"), &lines("1\n2\nX\n4\n5\n6\nY"), 1),
            ["--- ", "+++ ", "@@ -2,3 +2,3 @@", " 2", "-3", "+X", " 4", "@@ -6,2 +6,2 @@", " 6", "-7", "+Y"]
        );
        assert_eq!(unified_diff(&[], &lines("nuevo"), 1), ["--- ", "+++ ", "@@ -0,0 +1 @@", "+nuevo"]);
        assert!(unified_diff(&lines("igual"), &lines("igual"), 1).is_empty());
    }

    #[test]
    fn splitlines_like_python() {
        assert_eq!(splitlines("a\r\nb\rc\n"), ["a", "b", "c"]);
        assert_eq!(splitlines("\n\nx"), ["", "", "x"]);
        assert!(splitlines("").is_empty());
    }

    #[test]
    fn capitalize_like_python() {
        assert_eq!(capitalize("APLICACIÓN"), "Aplicación");
        assert_eq!(capitalize("lunes"), "Lunes");
    }
}

/// Against real Python: `python3 tests/python_cases.py > cases.json`, then
/// `POPOS_PYCASES=cases.json cargo test -- --ignored`.
#[cfg(test)]
mod against_python {
    use super::*;

    fn cases() -> serde_json::Value {
        let path = std::env::var("POPOS_PYCASES").expect("POPOS_PYCASES: the cases Python wrote");
        serde_json::from_str(&std::fs::read_to_string(path).expect("readable cases")).expect("json cases")
    }

    fn strings(value: &serde_json::Value) -> Vec<String> {
        value.as_array().unwrap().iter().map(|s| s.as_str().unwrap().to_string()).collect()
    }

    #[test]
    #[ignore]
    fn wrap_matches_textwrap() {
        let cases = cases();
        let mut failures = 0;
        for case in cases["wrap"].as_array().unwrap() {
            let (text, width) = (case["text"].as_str().unwrap(), case["width"].as_u64().unwrap() as usize);
            let got = wrap(text, width);
            if got != strings(&case["out"]) {
                failures += 1;
                if failures < 10 {
                    eprintln!("wrap({text:?}, {width}): python {:?} rust {got:?}", strings(&case["out"]));
                }
            }
        }
        assert_eq!(failures, 0);
    }

    #[test]
    #[ignore]
    fn diff_matches_difflib() {
        let cases = cases();
        let mut failures = 0;
        for case in cases["diff"].as_array().unwrap() {
            let (a, b) = (strings(&case["a"]), strings(&case["b"]));
            let got = unified_diff(&a, &b, 1);
            if got != strings(&case["out"]) {
                failures += 1;
                if failures < 10 {
                    eprintln!("diff({a:?}, {b:?}): python {:?} rust {got:?}", strings(&case["out"]));
                }
            }
        }
        assert_eq!(failures, 0);
    }

    #[test]
    #[ignore]
    fn random_matches_python() {
        for case in cases()["random"].as_array().unwrap() {
            let mut r = crate::pyrandom::PyRandom::new(case["seed"].as_u64().unwrap());
            let mut got = vec![r.randrange(1) as i64, r.randrange(97) as i64, r.randrange(1_000_000) as i64, r.choice(&[-1, 1]), r.randrange(10) as i64];
            got.extend((1..300).map(|n| r.randrange(n) as i64));
            got.push(r.randint(5, 25));
            let want: Vec<i64> = case["out"].as_array().unwrap().iter().map(|v| v.as_i64().unwrap()).collect();
            assert_eq!(got, want, "seed {}", case["seed"]);
        }
    }
}
