//! Popo: his drawings, how he grows, his animations and the block-letter name.

/// The Popo above the name: (frame, ms). Frames: 0 still, 1-2 breathing, 3
/// eyes closed, 4 opening. He breathes slowly all the time, a movement small
/// enough not to tire; the blink only comes now and then, sometimes double.
const BREATH: [(usize, u64); 4] = [(0, 1400), (1, 450), (2, 700), (1, 450)];

fn logo_timeline() -> &'static [(usize, u64)] {
    static TIMELINE: std::sync::OnceLock<Vec<(usize, u64)>> = std::sync::OnceLock::new();
    TIMELINE.get_or_init(|| {
        let mut t = Vec::new();
        for _ in 0..4 {
            t.extend(BREATH);
        }
        t.extend([(3, 140), (4, 90)]);
        for _ in 0..3 {
            t.extend(BREATH);
        }
        t.extend([(3, 140), (0, 160), (3, 140), (4, 90)]);
        t
    })
}

pub fn logo_cycle() -> u64 {
    logo_timeline().iter().map(|(_, ms)| ms).sum()
}

/// Which frame shows at this moment, and how many ms until the next one.
pub fn logo_frame(now_ms: u64) -> (usize, u64) {
    let mut t = now_ms % logo_cycle();
    for &(frame, ms) in logo_timeline() {
        if t < ms {
            return (frame, ms - t);
        }
        t -= ms;
    }
    (0, 1)
}

/// The name drawn in block letters, 8 px tall: "popa" in Popo's cream, "rium"
/// in the app's cyan. Each letter: (color, 8 rows); "#" is a pixel.
const WORDMARK: [(&str, [&str; 8]); 8] = [
    ("cream", ["...", "...", "##.", "#.#", "#.#", "##.", "#..", "#.."]),
    ("cream", ["...", "...", ".#.", "#.#", "#.#", ".#.", "...", "..."]),
    ("cream", ["...", "...", "##.", "#.#", "#.#", "##.", "#..", "#.."]),
    ("cream", ["...", "...", "##.", ".##", "#.#", ".##", "...", "..."]),
    ("a", ["...", "...", "#.#", "##.", "#..", "#..", "...", "..."]),
    ("a", ["#", ".", "#", "#", "#", "#", ".", "."]),
    ("a", ["...", "...", "#.#", "#.#", "#.#", ".##", "...", "..."]),
    ("a", [".....", ".....", "##.#.", "#.#.#", "#.#.#", "#.#.#", ".....", "....."]),
];

/// The wordmark as 4 rows of (char, color) half-block cells, one column gap between letters.
pub fn wordmark_cells() -> Vec<Vec<(char, &'static str)>> {
    let mut rows = Vec::new();
    for y in (0..8).step_by(2) {
        let mut row = Vec::new();
        for (i, (color, glyph)) in WORDMARK.iter().enumerate() {
            for (top, bottom) in glyph[y].chars().zip(glyph[y + 1].chars()) {
                let c = match (top, bottom) {
                    ('#', '#') => '█',
                    ('#', '.') => '▀',
                    ('.', '#') => '▄',
                    _ => ' ',
                };
                row.push((c, *color));
            }
            if i < WORDMARK.len() - 1 {
                row.push((' ', *color));
            }
        }
        rows.push(row);
    }
    rows
}

/// A half-block cell of the logo: (char, fg, bg) in 256 colours; None where empty.
pub type LogoCell = Option<(String, i16, i16)>;

pub struct Popo {
    /// ms per frame of the meadow
    pub ms: u64,
    /// rows of half-block cells, one grid per frame
    pub logo: Vec<Vec<Vec<LogoCell>>>,
    /// The same frames as raw pixels, to make PNGs for kitty at any width
    pub logo_rgba: Option<Rgba>,
}

pub struct Rgba {
    pub size: (usize, usize),
    pub frames: Vec<Vec<u8>>,
}

/// Popo's art, built in (tools/popo_assets.py writes it).
const POPO_JSON: &str = include_str!("../assets/popo.json");

fn b64_value(c: u8) -> Option<u32> {
    Some(match c {
        b'A'..=b'Z' => c - b'A',
        b'a'..=b'z' => c - b'a' + 26,
        b'0'..=b'9' => c - b'0' + 52,
        b'+' => 62,
        b'/' => 63,
        _ => return None,
    } as u32)
}

pub fn b64_decode(text: &str) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    let (mut buffer, mut bits) = (0u32, 0);
    for &c in text.as_bytes() {
        if c == b'=' {
            break;
        }
        buffer = (buffer << 6) | b64_value(c)?;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((buffer >> bits) as u8);
        }
    }
    Some(out)
}

pub fn b64_encode(data: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let n = (chunk[0] as u32) << 16 | (*chunk.get(1).unwrap_or(&0) as u32) << 8 | *chunk.get(2).unwrap_or(&0) as u32;
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(ALPHABET[(n >> (18 - 6 * i) & 63) as usize] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

fn inflate(data: &[u8]) -> Option<Vec<u8>> {
    miniz_oxide::inflate::decompress_to_vec_zlib(data).ok()
}

/// Popo's frames; None when the art is missing or broken.
pub fn load_popo() -> Option<Popo> {
    parse_popo(POPO_JSON)
}

fn parse_popo(text: &str) -> Option<Popo> {
    let data: serde_json::Value = serde_json::from_str(text).ok()?;
    // The meadow's own sprites ("states") aren't drawn: the logo frames are
    data.get("states")?.as_object()?;
    let ms = data.get("ms")?.as_u64()?;
    let logo = data.get("logo").and_then(|frames| {
        frames
            .as_array()?
            .iter()
            .map(|frame| {
                frame
                    .as_array()?
                    .iter()
                    .map(|row| {
                        row.as_array()?
                            .iter()
                            .map(|cell| match cell {
                                serde_json::Value::Array(parts) => Some(Some((
                                    parts.first()?.as_str()?.to_string(),
                                    parts.get(1)?.as_i64()? as i16,
                                    parts.get(2)?.as_i64()? as i16,
                                ))),
                                _ => Some(None),
                            })
                            .collect::<Option<Vec<LogoCell>>>()
                    })
                    .collect::<Option<Vec<_>>>()
            })
            .collect::<Option<Vec<_>>>()
    });
    let logo_rgba = data.get("logo_rgba").and_then(|rgba| {
        let size = rgba.get("size")?.as_array()?;
        let size = (size.first()?.as_u64()? as usize, size.get(1)?.as_u64()? as usize);
        let frames = rgba
            .get("frames")?
            .as_array()?
            .iter()
            .map(|f| inflate(&b64_decode(f.as_str()?)?))
            .collect::<Option<Vec<_>>>()?;
        Some(Rgba { size, frames })
    });
    Some(Popo { ms, logo: logo.unwrap_or_default(), logo_rgba })
}

/// Python's round(): halves go to the even neighbour.
pub fn py_round(x: f64) -> usize {
    let r = x.round();
    let r = if (x - x.trunc()).abs() == 0.5 && r % 2.0 != 0.0 { r - x.signum() } else { r };
    r.max(0.0) as usize
}

/// One logo frame as a PNG (base64), zoomed and, as he grows, wider or taller.
pub fn popo_png(rgba: &Rgba, frame: usize, belly: f64, stretch: f64) -> String {
    let zoom = 4.0;
    let (w, h) = rgba.size;
    let (out_w, out_h) = (py_round(w as f64 * zoom * belly), py_round(h as f64 * zoom * stretch));
    b64_encode(&png_bytes(out_w, out_h, &scale_rgba(&rgba.frames[frame], w, h, out_w, out_h)))
}

/// Nearest-neighbour resize of raw RGBA: pixel art stays crisp, even stretched.
pub fn scale_rgba(raw: &[u8], w: usize, h: usize, out_w: usize, out_h: usize) -> Vec<Vec<u8>> {
    let cols: Vec<usize> = (0..out_w).map(|x| (w - 1).min(x * w / out_w)).collect();
    (0..out_h)
        .map(|oy| {
            let sy = (h - 1).min(oy * h / out_h);
            let line = &raw[sy * w * 4..(sy + 1) * w * 4];
            cols.iter().flat_map(|&c| line[c * 4..c * 4 + 4].iter().copied()).collect()
        })
        .collect()
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            crc = if crc & 1 != 0 { (crc >> 1) ^ 0xEDB8_8320 } else { crc >> 1 };
        }
    }
    !crc
}

/// A minimal RGBA PNG from rows of raw pixels (no imaging library needed).
pub fn png_bytes(width: usize, height: usize, rows: &[Vec<u8>]) -> Vec<u8> {
    fn chunk(out: &mut Vec<u8>, tag: &[u8], data: &[u8]) {
        out.extend((data.len() as u32).to_be_bytes());
        let mut tagged = tag.to_vec();
        tagged.extend_from_slice(data);
        out.extend(&tagged);
        out.extend(crc32(&tagged).to_be_bytes());
    }
    let mut raw = Vec::with_capacity(rows.iter().map(|r| r.len() + 1).sum());
    for row in rows {
        raw.push(0);
        raw.extend(row);
    }
    let mut header = Vec::new();
    header.extend((width as u32).to_be_bytes());
    header.extend((height as u32).to_be_bytes());
    header.extend([8, 6, 0, 0, 0]);
    let mut out = b"\x89PNG\r\n\x1a\n".to_vec();
    chunk(&mut out, b"IHDR", &header);
    chunk(&mut out, b"IDAT", &miniz_oxide::deflate::compress_to_vec_zlib(&raw, 6));
    chunk(&mut out, b"IEND", b"");
    out
}

// Popo is always glad to be there: what he does never reacts to the last thing
// logged (an obstacle is not a sad Popo, a success is not a prouder one). What
// changes is his belly, which grows with every experience, and the stretch he
// gets when a commitment becomes INTEGRADO.
const PLAYFUL: [&str; 6] = ["idle", "hello", "think", "reading", "coding", "comfort"];

const GROWTH: [i64; 5] = [0, 3, 8, 15, 25]; // experiences for each belly size

pub const BELLY: [f64; 5] = [1.0, 1.08, 1.16, 1.24, 1.32]; // how much wider he gets

pub const STRETCH: f64 = 1.18; // how much taller an INTEGRADO Popo is

// The farm: a meadow where the Popos wander on their own. A first sketch: the
// rules are simple on purpose, to grow from
pub const FARM_TICK: f64 = 0.2; // seconds per step of the herd

pub const FARM_POPO: (usize, usize) = (12, 6); // a Popo's base size in the meadow, in cells

/// Belly size 0-4 for a number of experiences.
pub fn growth(experiences: i64) -> usize {
    GROWTH.iter().rposition(|&need| experiences >= need).unwrap_or(0)
}

/// (animation, words under him) for a commitment's Popo.
pub fn popo_look(id: i64, status: &str, experiences: i64) -> (&'static str, String) {
    match status {
        "archived" => ("sleep", "descansando".into()),
        "integrated" => ("hello", "integrado ♡".into()),
        _ => (
            PLAYFUL[id.rem_euclid(PLAYFUL.len() as i64) as usize],
            format!("{experiences} experiencia{}", if experiences == 1 { "" } else { "s" }),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn popo_art_loads_with_whole_frames() {
        let popo = load_popo().expect("the built-in art");
        assert_eq!(popo.logo.len(), 5);
        assert!(popo.logo.iter().flatten().all(|row| row.len() == 12));
        let rgba = popo.logo_rgba.expect("pixels for kitty");
        assert!(rgba.frames.iter().all(|f| f.len() == rgba.size.0 * rgba.size.1 * 4));
        assert!(parse_popo("{}").is_none());
    }

    #[test]
    fn logo_breathes_and_only_blinks_now_and_then() {
        assert_eq!(logo_frame(0), (0, 1400));
        assert_eq!(logo_frame(1400).0, 1);
        let cycle = logo_cycle();
        let closed = (0..cycle).step_by(10).filter(|&t| matches!(logo_frame(t).0, 3 | 4)).count();
        assert!((closed as f64) / (cycle as f64 / 10.0) < 0.05);
        assert!(cycle > 15000);
    }

    #[test]
    fn popo_is_always_glad_and_grows_with_experiences() {
        assert_eq!(popo_look(1, "active", 3), ("hello", "3 experiencias".to_string()));
        assert_eq!(popo_look(1, "active", 1).1, "1 experiencia");
        assert_eq!([0, 2, 3, 8, 15, 25, 400].map(growth), [0, 0, 1, 2, 3, 4, 4]);
        assert_eq!(popo_look(1, "integrated", 3), ("hello", "integrado ♡".to_string()));
    }

    #[test]
    fn popo_png_is_a_real_png_of_the_right_size() {
        let raw: Vec<u8> = [255, 0, 0, 255].repeat(4); // 2x2 red
        let rows = scale_rgba(&raw, 2, 2, 5, 3);
        assert_eq!((rows.len(), rows[0].len()), (3, 5 * 4));
        let png = png_bytes(5, 3, &rows);
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        assert_eq!(u32::from_be_bytes(png[16..20].try_into().unwrap()), 5);
        assert_eq!(crc32(b"IEND"), 0xAE42_6082);
    }

    #[test]
    fn base64_round_trip() {
        for data in [&b""[..], b"a", b"ab", b"abc", b"abcd\xff\x00"] {
            assert_eq!(b64_decode(&b64_encode(data)).unwrap(), data);
        }
        assert_eq!(b64_encode(b"popo"), "cG9wbw==");
    }

    #[test]
    fn rounds_like_python() {
        assert_eq!([py_round(12.0 * 1.08), py_round(12.0 * 1.24), py_round(2.5), py_round(3.5)], [13, 15, 2, 4]);
    }
}

/// Against real Python: every PNG kitty gets, written out for comparison
/// (`POPARIUM_PNG_DIR=dir cargo test -- --ignored`).
#[cfg(test)]
mod against_python {
    use super::*;

    #[test]
    #[ignore]
    fn write_every_png() {
        let dir = std::path::PathBuf::from(std::env::var("POPARIUM_PNG_DIR").expect("POPARIUM_PNG_DIR"));
        let rgba = load_popo().unwrap().logo_rgba.unwrap();
        for frame in 0..rgba.frames.len() {
            for (belly, factor) in BELLY.iter().enumerate() {
                for integrated in [false, true] {
                    let png = popo_png(&rgba, frame, *factor, if integrated { STRETCH } else { 1.0 });
                    std::fs::write(dir.join(format!("{frame}-{belly}-{}.b64", integrated as u8)), png).unwrap();
                }
            }
        }
    }
}
