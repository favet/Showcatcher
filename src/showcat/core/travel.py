"""Venue travel-time lookup from the Valhalla/H3 SQLite matrix.

Shared by the score stage (distance signal) and web adapter (display).
"""
import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

SQLITE_DB_PATH = os.environ.get("SQLITE_DB_PATH", r"C:\Users\Justin\Documents\PDX Shows\data\pdx.sqlite")
# The origin cell ETAs are measured from. Env-configurable so the owner's home
# isn't hardcoded; a future per-user "enter your address" feature will resolve an
# address to its grid cell and look up that cell instead.
HOME_CELL_ID = os.environ.get("HOME_CELL_ID", "8828f0003dfffff")

# Estimated travel minutes for venues not yet in the Valhalla matrix.
_FALLBACK_TRAVEL_MINUTES: dict[str, int] = {
    "blue diamond":       4,
    "laurelthirst":       5,
    "kenton club":        7,
    "no fun bar":        10,
    "starday tavern":    10,
    "spare room":         6,
    "alberta street pub": 7,
    "artichoke music":    9,
    "kelly's olympian":   9,
    "goodfoot":          10,
    "mississippi pizza":  3,
    # Venues absent from the Valhalla matrix — estimates from 5123 N Williams.
    "jack london revue": 12,   # downtown basement
    "nova pdx":          10,   # Central Eastside (ex-Bossanova)
    "show bar":          12,   # Revolution Hall complex, Buckman
    "blackberry hall":   12,
    "newmark theatre":   13,   # downtown
    "literary arts":     13,   # downtown
}


def normalize_venue_name(name: str) -> str:
    """Normalize a venue name for fuzzy matching against the travel-time dict."""
    name = name.lower()
    for word in [
        "music venue", "theater", "theatre", "- portland",
        "mcmenamins historic", "manor", "and hotel",
        "at the crystal", "saloon",
    ]:
        name = name.replace(word, "")
    name = name.replace("'", "")
    return name.strip()


def get_travel_times() -> dict[str, dict[str, Any]]:
    """Return {normalized_venue_name: {minutes, miles}} from the SQLite matrix + fallbacks."""
    times: dict[str, dict[str, Any]] = {}
    if os.path.exists(SQLITE_DB_PATH):
        try:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            conn.row_factory = sqlite3.Row
            venues = conn.execute("SELECT venue_id, name FROM venues").fetchall()
            for v in venues:
                bm = conn.execute(
                    "SELECT base_seconds, base_meters FROM base_matrix WHERE cell_id = ? AND venue_id = ?",
                    (HOME_CELL_ID, v["venue_id"]),
                ).fetchone()
                if bm:
                    times[normalize_venue_name(v["name"])] = {
                        "minutes": round(bm["base_seconds"] / 60),
                        "miles": round(bm["base_meters"] / 1609.34, 1),
                    }
            conn.close()
        except Exception as e:
            logger.error("Error querying SQLite travel matrix: %s", e)
    for name, mins in _FALLBACK_TRAVEL_MINUTES.items():
        norm_name = normalize_venue_name(name)
        if norm_name not in times:
            times[norm_name] = {"minutes": mins, "miles": round(mins * 0.35, 1)}
    return times


_BUCKETS = ("pm_peak", "evening", "late_night", "weekend_day", "off_peak")


def departure_bucket(event_date: Any, show_time: Any) -> str:
    """Map a show's local date/time to a traffic bucket (mirrors pdx_travel).

    Untimed shows assume a typical 8pm start. Buckets:
      late_night  23:00–06:00 any day
      weekend_day Sat/Sun 10:00–19:00
      pm_peak     Mon–Fri 15:00–19:00
      evening     Mon–Fri 19:00–23:00
      off_peak    everything else
    """
    hour = show_time.hour if show_time is not None else 20
    wd = event_date.weekday()  # 0=Mon
    if hour >= 23 or hour < 6:
        return "late_night"
    if wd >= 5 and 10 <= hour < 19:
        return "weekend_day"
    if wd < 5 and 15 <= hour < 19:
        return "pm_peak"
    if wd < 5 and 19 <= hour < 23:
        return "evening"
    return "off_peak"


def get_eta_travel_times() -> dict[str, dict[str, dict[str, Any]]]:
    """Return {bucket_slug: {normalized_venue: {minutes, miles}}} from eta_matrix.

    Time-of-day drive times from the home cell, one map per bucket. Falls back to
    the base (free-flow) times for any venue/bucket the eta_matrix doesn't cover,
    so callers always get a value. Empty if eta_matrix isn't populated.
    """
    base = get_travel_times()
    by_bucket: dict[str, dict[str, dict[str, Any]]] = {b: dict(base) for b in _BUCKETS}
    if not os.path.exists(SQLITE_DB_PATH):
        return by_bucket
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT v.name AS name, b.label AS bucket, e.eta_seconds AS secs "
            "FROM eta_matrix e "
            "JOIN venues v ON v.venue_id = e.venue_id "
            "JOIN buckets b ON b.bucket_id = e.bucket_id "
            "WHERE e.cell_id = ?",
            (HOME_CELL_ID,),
        ).fetchall()
        conn.close()
        for r in rows:
            if r["bucket"] not in by_bucket:
                continue
            by_bucket[r["bucket"]][normalize_venue_name(r["name"])] = {
                "minutes": round(r["secs"] / 60),
                "miles": None,
            }
    except Exception as e:
        logger.error("Error querying eta_matrix: %s", e)
    return by_bucket


def lookup_travel(venue_name: str, travel_times: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Find the travel-time entry for a venue name using substring matching."""
    norm = normalize_venue_name(venue_name)
    for k, v in travel_times.items():
        if norm == k or norm in k or k in norm:
            return v
    return None


def distance_signal(travel_minutes: int | None) -> float:
    """Convert travel minutes to a [0, 1] distance signal.

    close (≤10 min) → 1.0 · near (≤30 min) → 0.5 · far / unknown → 0.0
    Venues close to home get a discovery boost; distant venues are neutral.
    """
    if travel_minutes is None:
        return 0.0
    if travel_minutes <= 10:
        return 1.0
    if travel_minutes <= 30:
        return 0.5
    return 0.0
