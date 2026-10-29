//! Dates: UTC stamps, how they read, and the month grid.
use chrono::{DateTime, Datelike, Days, Local, NaiveDate, NaiveDateTime, TimeZone, Utc};

/// UTC as `2026-10-11T12:00:00+00:00`, the way the notebook stores every moment.
pub fn utc_iso(moment: DateTime<Utc>) -> String {
    moment.format("%Y-%m-%dT%H:%M:%S+00:00").to_string()
}

pub fn stamp() -> String {
    // Siempre en UTC: el texto ISO se ordena bien aunque cambie la hora (verano/invierno)
    utc_iso(Utc::now())
}

/// A stored moment in local time. Naive values (no offset) are read as local, like Python's astimezone().
pub fn parse_local(value: &str) -> Option<DateTime<Local>> {
    let value = value.trim();
    if let Ok(moment) = DateTime::parse_from_rfc3339(value) {
        return Some(moment.with_timezone(&Local));
    }
    for format in ["%Y-%m-%dT%H:%M:%S%:z", "%Y-%m-%d %H:%M:%S%:z", "%Y-%m-%dT%H:%M:%S%.f%:z"] {
        if let Ok(moment) = DateTime::parse_from_str(value, format) {
            return Some(moment.with_timezone(&Local));
        }
    }
    for format in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%dT%H:%M"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(value, format) {
            return Local.from_local_datetime(&naive).earliest();
        }
    }
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .ok()
        .and_then(|d| Local.from_local_datetime(&d.and_hms_opt(0, 0, 0)?).earliest())
}

pub fn display_date(value: &str) -> String {
    match parse_local(value) {
        Some(moment) => moment.format("%d/%m %H:%M").to_string(),
        None => value.chars().take(16).collect(),
    }
}

/// The UTC stamp of local midnight starting `day`.
pub fn local_midnight_utc(day: NaiveDate) -> String {
    let naive = day.and_hms_opt(0, 0, 0).expect("midnight exists");
    let local = Local.from_local_datetime(&naive).earliest().unwrap_or_else(|| Local.from_utc_datetime(&naive));
    utc_iso(local.with_timezone(&Utc))
}

/// The UTC stamp of local noon on `day`: where something remembered from another day is noted.
pub fn local_noon_utc(day: NaiveDate) -> String {
    let naive = day.and_hms_opt(12, 0, 0).expect("noon exists");
    let local = Local.from_local_datetime(&naive).earliest().unwrap_or_else(|| Local.from_utc_datetime(&naive));
    utc_iso(local.with_timezone(&Utc))
}

pub fn today() -> NaiveDate {
    Local::now().date_naive()
}

pub const MONTHS: [&str; 12] = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
];

pub const WEEKDAYS: [&str; 7] = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];

/// Monday 0 … Sunday 6, like Python's date.weekday().
pub fn weekday(day: NaiveDate) -> usize {
    day.weekday().num_days_from_monday() as usize
}

pub fn first_of_next_month(day: NaiveDate) -> NaiveDate {
    let (year, month) = if day.month() == 12 { (day.year() + 1, 1) } else { (day.year(), day.month() + 1) };
    NaiveDate::from_ymd_opt(year, month, 1).expect("first of a month exists")
}

/// The Monday-first weeks (lists of 7 dates) that show the month of `day`.
pub fn month_grid(day: NaiveDate) -> Vec<[NaiveDate; 7]> {
    let first = day.with_day(1).expect("first of a month exists");
    let following = first_of_next_month(first);
    let mut monday = first - Days::new(weekday(first) as u64);
    let mut weeks = Vec::new();
    while monday < following {
        weeks.push(std::array::from_fn(|i| monday + Days::new(i as u64)));
        monday = monday + Days::new(7);
    }
    weeks
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timestamps_are_utc_so_text_order_is_time_order() {
        assert!(stamp().ends_with("+00:00"));
    }

    #[test]
    fn weeks_start_on_monday() {
        let weeks = month_grid(NaiveDate::from_ymd_opt(2026, 10, 11).unwrap());
        assert_eq!(weeks[0][0], NaiveDate::from_ymd_opt(2026, 9, 28).unwrap());
        assert_eq!(weeks.last().unwrap()[6], NaiveDate::from_ymd_opt(2026, 11, 1).unwrap());
        assert_eq!(weeks.len(), 5);
        assert!(weeks.iter().all(|w| weekday(w[0]) == 0));
    }

    #[test]
    fn unreadable_dates_show_as_they_are() {
        assert_eq!(display_date("no es una fecha, de verdad"), "no es una fecha,");
    }
}
