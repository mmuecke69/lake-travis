#!/usr/bin/env python3
"""Fetch published Lake Travis readings and update the local dataset.

Sources (public, no invented numbers):
  - LCRA Hydromet current lake levels:
      https://hydromet.lcra.org/media/LakeLevel.csv
  - LCRA Hydromet 7-/30-day comparison snapshot:
      https://hydromet.lcra.org/media/LakeLevelsRR.csv
  - LCRA Hydromet historic 5-minute series, Mansfield Dam (site 3963):
      https://hydromet.lcra.org/api/HistoricData/GetDataBySite/3963/lakelevel/<M-D-YYYY>/<M-D-YYYY>
      (public web API used by hydromet.lcra.org/HistoricalData; ~179-day window)
  - TWDB daily history (Water Data for Texas), Lake Travis:
      https://www.waterdatafortexas.org/reservoirs/individual/travis.csv

Writes (idempotent; safe to rerun daily):
  - readings.csv      daily history (TWDB), upserted by date
  - current.json      latest LCRA Hydromet snapshot and computed changes
  - page_data.json    compact series for the dashboard Page
  - raw/              copies of the fetched source files

Usage:
  python3 /workspace/lake-travis/update.py

After a successful run, refresh the Lake Travis dashboard Page from
current.json and page_data.json (the Page does not read these files by
itself).
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DIR = Path(__file__).resolve().parent
RAW = DIR / "raw"
READINGS_CSV = DIR / "readings.csv"
CURRENT_JSON = DIR / "current.json"
PAGE_DATA_JSON = DIR / "page_data.json"

CT = ZoneInfo("America/Chicago")
UA = "LakeTravisDashboard/1.0 (personal dashboard; +https://hydromet.lcra.org)"

LCRA_LAKELEVEL = "https://hydromet.lcra.org/media/LakeLevel.csv"
LCRA_LAKELEVELS_RR = "https://hydromet.lcra.org/media/LakeLevelsRR.csv"
LCRA_HISTORIC = (
    "https://hydromet.lcra.org/api/HistoricData/GetDataBySite/"
    "3963/lakelevel/{start}/{end}"
)
TWDB_CSV = "https://www.waterdatafortexas.org/reservoirs/individual/travis.csv"

# Official LCRA figures from https://www.lcra.org/water/dams-and-lakes/
# (verified on this page, Nov 10, 2026). USACE also lists conservation
# pool 681 ft and spillway / top of flood 714 ft.
THRESHOLDS = {
    "full_pool_ft_msl": 681.0,
    "full_pool_label": "Conservation / full pool (water supply)",
    "full_pool_source": "https://www.lcra.org/water/dams-and-lakes/",
    "spillway_crest_ft_msl": 714.0,
    "spillway_label": "Overflow spillway crest / top of flood pool",
    "spillway_source": "https://www.lcra.org/water/dams-and-lakes/",
    "usace_source": "https://water.usace.army.mil/overview/swf/locations/msdt2",
    "record_high_ft_msl": 710.44,
    "record_high_date": "1991-12-25",
    "record_high_note": "LCRA historic high, daily 8 a.m. reading",
    "record_low_ft_msl": 614.18,
    "record_low_date": "1951-08-14",
    "record_low_note": "LCRA historic low, daily 8 a.m. reading",
}


class FetchError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise FetchError(f"Failed to fetch {url}: {exc}") from exc


def parse_lcra_local(ts: str) -> datetime:
    """Parse LCRA 'YYYY-MM-DD HH:MM' (no zone) as America/Chicago clock time."""
    ts = ts.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=CT)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized LCRA timestamp: {ts!r}")


def parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def to_ct(ts: str) -> datetime:
    return parse_utc(ts).astimezone(CT)


def fmt_ct(dt: datetime) -> str:
    # e.g. "Nov 10, 2026, 3:55 PM CST"
    dt = dt.astimezone(CT)
    hour = dt.strftime("%I").lstrip("0") or "0"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {hour}:{dt.strftime('%M %p %Z')}"


def nearest(records: list[dict], target_utc: datetime) -> tuple[dict, float]:
    best = None
    best_d = None
    for rec in records:
        d = abs((parse_utc(rec["dateTime"]) - target_utc).total_seconds())
        if best is None or d < best_d:
            best, best_d = rec, d
    if best is None:
        raise FetchError("No historic records to search")
    return best, best_d  # type: ignore[return-value]


def parse_lakelevel_csv(text: str) -> dict:
    """Parse Hydromet LakeLevel.csv and return the Travis (site 3963) row."""
    # First header cell is normal; the last header includes a report date.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise FetchError("LakeLevel.csv was empty")
    header_line = lines[0]
    report_date = None
    if "Report Date:" in header_line:
        report_date = header_line.split("Report Date:", 1)[1].strip().rstrip(",")
        header_line = header_line.split("Lake Level")[0].rstrip(", ")
        # Reconstruct a clean header
        # Original: Site,Lake,Date Time,Current,Percent Full,Current Storage,Midnight,Lake Level (ft) Report Date: ...
        header = [
            "site",
            "lake",
            "date_time",
            "current",
            "percent_full",
            "current_storage",
            "midnight",
        ]
    else:
        header = [h.strip() for h in header_line.split(",")]
    travis = None
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        row = {header[i]: parts[i] if i < len(parts) else "" for i in range(len(header))}
        if row.get("site") == "3963" or row.get("lake") == "Travis":
            travis = row
            break
    if not travis:
        raise FetchError("LakeLevel.csv had no Travis / site 3963 row")
    return {
        "site": travis.get("site", "3963"),
        "lake": travis.get("lake", "Travis"),
        "date_time_local": travis["date_time"],
        "date_time_ct": parse_lcra_local(travis["date_time"]).isoformat(),
        "elevation_ft_msl": float(travis["current"]),
        "percent_full": float(travis["percent_full"]) if travis.get("percent_full") else None,
        "storage_acft": float(travis["current_storage"]) if travis.get("current_storage") else None,
        "midnight_ft_msl": float(travis["midnight"]) if travis.get("midnight") else None,
        "report_date_local": report_date,
        "source": LCRA_LAKELEVEL,
    }


def parse_lakelevels_rr(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise FetchError("LakeLevelsRR.csv was empty")
    reader = csv.reader(io.StringIO("\n".join(lines)))
    rows = list(reader)
    header = rows[0]
    # Find Travis
    for row in rows[1:]:
        rec = {header[i].split(" Report")[0].strip(): row[i] if i < len(row) else "" for i in range(len(header))}
        site = rec.get("Site", "")
        lake = rec.get("Lake (Dam)", rec.get("Lake", ""))
        if site == "3963" or "Travis" in lake:
            return {
                "site": site,
                "lake": lake,
                "date_time_local": rec.get("Date Time", ""),
                "elevation_ft_msl": float(rec["Lake Level"]),
                "seven_days_ago_ft_msl": float(rec["7 Days Ago"]) if rec.get("7 Days Ago") else None,
                "thirty_days_ago_ft_msl": float(rec["30 Days Ago"]) if rec.get("30 Days Ago") else None,
                "note": (
                    "LCRA '7 Days Ago' and '30 Days Ago' in this file match "
                    "midnight (America/Chicago) elevations, not same-time-of-day."
                ),
                "source": LCRA_LAKELEVELS_RR,
            }
    raise FetchError("LakeLevelsRR.csv had no Travis / site 3963 row")


def parse_twdb(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    reader = csv.DictReader(lines)
    out = []
    for row in reader:
        try:
            d = date.fromisoformat(row["date"])
            elev = float(row["water_level"])
        except (KeyError, ValueError):
            continue
        pct = row.get("percent_full") or ""
        stor = row.get("reservoir_storage") or ""
        out.append(
            {
                "date": d.isoformat(),
                "elevation_ft_msl": round(elev, 2),
                "percent_full": round(float(pct), 1) if pct else "",
                "storage_acft": int(round(float(stor))) if stor else "",
                "source": "TWDB (waterdatafortexas.org, LCRA gauge)",
            }
        )
    if not out:
        raise FetchError("TWDB CSV contained no daily rows")
    return out


def upsert_readings(new_rows: list[dict]) -> tuple[list[dict], int, int]:
    existing: dict[str, dict] = {}
    if READINGS_CSV.exists():
        with READINGS_CSV.open(newline="") as f:
            for row in csv.DictReader(f):
                existing[row["date"]] = row
    inserted = 0
    updated = 0
    for row in new_rows:
        key = row["date"]
        if key in existing:
            # Update if any field changed
            prev = existing[key]
            changed = any(str(prev.get(k, "")) != str(row.get(k, "")) for k in row)
            if changed:
                existing[key] = row
                updated += 1
        else:
            existing[key] = row
            inserted += 1
    rows = [existing[k] for k in sorted(existing)]
    with READINGS_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "elevation_ft_msl",
                "percent_full",
                "storage_acft",
                "source",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows, inserted, updated


def lcra_8am_and_latest(records: list[dict]) -> tuple[list[dict], dict]:
    """Daily 8 a.m. CT readings plus the latest 5-minute point."""
    if not records:
        raise FetchError("Historic API returned no records")
    records = sorted(records, key=lambda r: r["dateTime"])
    by_day: dict[date, list[tuple[datetime, float]]] = defaultdict(list)
    for rec in records:
        if rec.get("value1") is None:
            continue
        t = to_ct(rec["dateTime"])
        by_day[t.date()].append((t, float(rec["value1"])))
    daily = []
    for day in sorted(by_day):
        items = by_day[day]
        eight = datetime(day.year, day.month, day.day, 8, 0, tzinfo=CT)
        t, val = min(items, key=lambda iv: abs((iv[0] - eight).total_seconds()))
        daily.append(
            {
                "date": day.isoformat(),
                "elevation_ft_msl": round(val, 2),
                "time_ct": t.isoformat(),
                "source": "LCRA Hydromet 8 a.m. CT (nearest 5-min reading, site 3963)",
            }
        )
    last = records[-1]
    latest = {
        "date_time_utc": last["dateTime"],
        "date_time_ct": to_ct(last["dateTime"]).isoformat(),
        "elevation_ft_msl": float(last["value1"]),
        "tailwater_ft_msl": last.get("value2"),
        "source": "LCRA Hydromet 5-minute, Mansfield Dam (site 3963)",
    }
    return daily, latest


def lookback(records: list[dict], latest: dict, days: int) -> dict:
    now = parse_utc(latest["date_time_utc"])
    rec, off = nearest(records, now - timedelta(days=days))
    then = to_ct(rec["dateTime"])
    now_val = latest["elevation_ft_msl"]
    then_val = float(rec["value1"])
    return {
        "days": days,
        "then_elevation_ft_msl": then_val,
        "then_time_ct": then.isoformat(),
        "then_time_label": fmt_ct(then),
        "offset_minutes": round(off / 60.0, 1),
        "change_ft": round(now_val - then_val, 2),
    }


def month_label(d: date) -> str:
    if d.day == 1 or (d.month == 1 and d.day <= 2):
        return d.strftime("%b %Y") if d.month == 1 else d.strftime("%b")
    return ""


def downsample_monthly(rows: list[dict], start: date | None = None) -> list[dict]:
    """One point per month (last available day), plus first row in range."""
    chosen: dict[tuple[int, int], dict] = {}
    for row in rows:
        d = date.fromisoformat(row["date"])
        if start and d < start:
            continue
        chosen[(d.year, d.month)] = row
    out = [chosen[k] for k in sorted(chosen)]
    return out


def series_from_daily(rows: list[dict], start: date, end: date) -> list[dict]:
    return [
        {
            "label": date.fromisoformat(r["date"]).strftime("%b %-d")
            if date.fromisoformat(r["date"]).day in (1, 15)
            or r["date"] in (start.isoformat(), end.isoformat())
            else "",
            "date": r["date"],
            "value": float(r["elevation_ft_msl"]),
        }
        for r in rows
        if start <= date.fromisoformat(r["date"]) <= end
    ]


def nice_floor_ceil(values: list[float], extras: list[float], pad: float = 0.6) -> tuple[float, float]:
    vals = [v for v in values + extras if v is not None and math.isfinite(v)]
    lo = min(vals) - pad
    hi = max(vals) + pad
    # modest rounding to tenths
    return math.floor(lo * 2) / 2, math.ceil(hi * 2) / 2


def md_key(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def build_page_data(
    twdb_rows: list[dict],
    lcra_daily: list[dict],
    latest: dict,
    official: dict,
    changes: dict,
    midnight_ft: float | None,
) -> dict:
    today = to_ct(latest["date_time_utc"]).date()
    by_date = {r["date"]: r for r in twdb_rows}

    def twdb_range(days: int) -> list[dict]:
        start = today - timedelta(days=days - 1)
        return series_from_daily(twdb_rows, start, today)

    # 30d / 90d: LCRA 8 a.m. CT + today's live point so the current rise shows
    def lcra_window(days: int) -> list[dict]:
        start = today - timedelta(days=days - 1)
        pts = []
        for r in lcra_daily:
            d = date.fromisoformat(r["date"])
            if d < start or d > today:
                continue
            if d == today:
                continue  # replaced by live point
            lab = d.strftime("%b %-d") if d.day in (1, 15) or d == start else ""
            pts.append({"label": lab, "date": r["date"], "value": r["elevation_ft_msl"]})
        live_t = to_ct(latest["date_time_utc"])
        pts.append(
            {
                "label": live_t.strftime("%b %-d %-I:%M %p"),
                "date": today.isoformat(),
                "value": round(latest["elevation_ft_msl"], 2),
            }
        )
        if pts:
            pts[0]["label"] = date.fromisoformat(pts[0]["date"]).strftime("%b %-d")
        return pts

    s30 = lcra_window(30)
    s90 = lcra_window(90)
    s1y = twdb_range(365)
    # Put today's live LCRA point as the last 1y value so the chart ends at "now"
    if s1y:
        s1y[-1] = {
            "label": today.strftime("%b %-d"),
            "date": today.isoformat(),
            "value": round(latest["elevation_ft_msl"], 2),
            "note": "Today's last point is the live LCRA reading, not the TWDB daily average",
        }
        s1y[0]["label"] = date.fromisoformat(s1y[0]["date"]).strftime("%b %-d, %Y")
    s5y = twdb_range(365 * 5 + 1)
    if s5y:
        s5y[-1] = {
            "label": today.strftime("%b %-d, %Y"),
            "date": today.isoformat(),
            "value": round(latest["elevation_ft_msl"], 2),
        }
        s5y[0]["label"] = date.fromisoformat(s5y[0]["date"]).strftime("%b %Y")
        # thin x labels: first of month only
        start5 = date.fromisoformat(s5y[0]["date"])
        for p in s5y:
            d = date.fromisoformat(p["date"])
            if p is s5y[0] or p is s5y[-1]:
                continue
            p["label"] = d.strftime("%b %Y") if d.day == 1 else ""

    # All history: monthly from 1942-01-01 (after initial filling years)
    monthly = downsample_monthly(twdb_rows, start=date(1942, 1, 1))
    sall = []
    for i, r in enumerate(monthly):
        d = date.fromisoformat(r["date"])
        lab = d.strftime("%Y") if d.month == 1 or i == 0 else ""
        sall.append({"label": lab, "date": r["date"], "value": float(r["elevation_ft_msl"])})
    if sall:
        sall[-1] = {
            "label": today.strftime("%b %Y"),
            "date": today.isoformat(),
            "value": round(latest["elevation_ft_msl"], 2),
        }

    def pack(pts: list[dict], extras: list[float]) -> dict:
        values = [p["value"] for p in pts]
        floor, ceiling = nice_floor_ceil(values, extras)
        return {
            "points": pts,
            "floor": floor,
            "ceiling": ceiling,
        }

    full = THRESHOLDS["full_pool_ft_msl"]
    rec_hi = THRESHOLDS["record_high_ft_msl"]
    rec_lo = THRESHOLDS["record_low_ft_msl"]
    spill = THRESHOLDS["spillway_crest_ft_msl"]

    ranges = {
        "30d": {**pack(s30, [full]), "source": "LCRA Hydromet, 8 a.m. CT plus live reading", "ref": ["full"]},
        "90d": {**pack(s90, [full]), "source": "LCRA Hydromet, 8 a.m. CT plus live reading", "ref": ["full"]},
        "1y": {**pack(s1y, [full]), "source": "TWDB daily averages; last point is live LCRA", "ref": ["full"]},
        "5y": {**pack(s5y, [full]), "source": "TWDB daily averages; last point is live LCRA", "ref": ["full"]},
        "all": {
            **pack(sall, [full, rec_hi, rec_lo, spill]),
            "source": "TWDB monthly (from 1942); last point is live LCRA",
            "ref": ["full", "spillway", "record_high", "record_low"],
        },
    }

    # Same calendar date, last 10 years + this year (TWDB daily averages)
    same_date = []
    for y in range(today.year - 10, today.year + 1):
        try:
            d = date(y, today.month, today.day)
        except ValueError:
            continue
        r = by_date.get(d.isoformat())
        if not r:
            continue
        same_date.append(
            {
                "date": d.isoformat(),
                "year": y,
                "elevation_ft_msl": float(r["elevation_ft_msl"]),
                "percent_full": float(r["percent_full"]) if r["percent_full"] != "" else None,
                "storage_acft": int(r["storage_acft"]) if r["storage_acft"] != "" else None,
                "is_this_year": y == today.year,
            }
        )

    # Day-of-year overlay: 2026 vs 10-year (2016-2025) min / median / max
    # Skip Feb 29 so non-leap and leap years align by month-day.
    years_prior = list(range(today.year - 10, today.year))
    by_year_md: dict[int, dict[str, float]] = defaultdict(dict)
    for r in twdb_rows:
        d = date.fromisoformat(r["date"])
        if d.month == 2 and d.day == 29:
            continue
        if d.year in years_prior or d.year == today.year:
            by_year_md[d.year][md_key(d)] = float(r["elevation_ft_msl"])

    # Build 365 month-day keys from a non-leap year
    md_list = []
    cursor = date(2025, 1, 1)
    while cursor.year == 2025:
        md_list.append(md_key(cursor))
        cursor += timedelta(days=1)

    def month_x_label(md: str) -> str:
        m, day = md.split("-")
        if day == "01":
            return date(2025, int(m), 1).strftime("%b")
        return ""

    this_year = []
    mins, medians, maxs = [], [], []
    for md in md_list:
        m, day = (int(x) for x in md.split("-"))
        # this year: only through today; after today leave a gap
        if (m, day) <= (today.month, today.day):
            this_val = by_year_md.get(today.year, {}).get(md)
            # After the last TWDB day, use live LCRA on today's month-day
            if (m, day) == (today.month, today.day):
                this_val = round(latest["elevation_ft_msl"], 2)
        else:
            this_val = None
        prior_vals = sorted(
            v for y in years_prior if (v := by_year_md.get(y, {}).get(md)) is not None
        )
        this_year.append(this_val if this_val is not None else None)
        if prior_vals:
            mins.append(prior_vals[0])
            maxs.append(prior_vals[-1])
            mid = prior_vals[len(prior_vals) // 2]
            medians.append(mid)
        else:
            mins.append(None)
            maxs.append(None)
            medians.append(None)

    overlay = {
        "labels": [month_x_label(md) for md in md_list],
        "month_days": md_list,
        "this_year": this_year,
        "this_year_label": str(today.year),
        "prior_years": f"{years_prior[0]}–{years_prior[-1]}",
        "prior_min": mins,
        "prior_median": medians,
        "prior_max": maxs,
        "source": (
            f"TWDB daily averages for {years_prior[0]}–{years_prior[-1]}; "
            f"{today.year} ends at the live LCRA reading"
        ),
    }
    overlay_vals = [v for v in this_year + mins + medians + maxs if v is not None]
    overlay["floor"], overlay["ceiling"] = nice_floor_ceil(overlay_vals, [full], pad=1.0)

    below_full = round(full - latest["elevation_ft_msl"], 2)
    since_midnight = None
    if midnight_ft is not None:
        since_midnight = {
            "midnight_ft_msl": midnight_ft,
            "change_ft": round(latest["elevation_ft_msl"] - midnight_ft, 2),
        }

    return {
        "generated_at_ct": datetime.now(CT).isoformat(),
        "current": {
            "elevation_ft_msl": round(latest["elevation_ft_msl"], 2),
            "time_ct": latest["date_time_ct"],
            "time_label": fmt_ct(to_ct(latest["date_time_utc"])),
            "percent_full": official.get("percent_full"),
            "percent_full_time_label": (
                fmt_ct(parse_lcra_local(official["date_time_local"]))
                if official.get("date_time_local")
                else None
            ),
            "storage_acft": official.get("storage_acft"),
            "storage_note": (
                "Storage and percent full are from LCRA's official LakeLevel.csv "
                f"snapshot at {official.get('date_time_local')} CT, when the lake "
                f"was {official.get('elevation_ft_msl')} ft."
            ),
            "below_full_ft": below_full,
            "site": "Mansfield Dam (LCRA Hydromet site 3963)",
            "source_live": latest["source"],
            "source_official": official.get("source"),
        },
        "changes": {
            "vs_1d": changes["1d"],
            "vs_7d": changes["7d"],
            "vs_30d": changes["30d"],
            "since_midnight": since_midnight,
            "method": (
                "Same-time-of-day comparison from LCRA Hydromet 5-minute "
                "readings at Mansfield Dam, not the midnight values in LakeLevelsRR.csv."
            ),
        },
        "thresholds": THRESHOLDS,
        "ranges": ranges,
        "same_date": same_date,
        "same_date_note": (
            f"TWDB daily average elevation on {today.strftime('%B %-d')} of each year. "
            f"Today's live LCRA reading is {latest['elevation_ft_msl']:.2f} ft; "
            "the TWDB figure for today is a daily average and may differ."
        ),
        "overlay": overlay,
        "sources": [
            {"name": "LCRA Hydromet LakeLevel.csv", "url": LCRA_LAKELEVEL},
            {"name": "LCRA Hydromet historic API, site 3963", "url": "https://hydromet.lcra.org/HistoricalData"},
            {"name": "LCRA dams and lakes (thresholds and records)", "url": "https://www.lcra.org/water/dams-and-lakes/"},
            {"name": "LCRA flood operations", "url": "https://www.lcra.org/water/flood/"},
            {
                "name": "USACE Lake Travis (Mansfield Dam) water data",
                "url": "https://water.usace.army.mil/overview/swf/locations/msdt2",
            },
            {"name": "TWDB Water Data for Texas, Lake Travis daily", "url": TWDB_CSV},
        ],
    }


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    log("Fetching LCRA and TWDB published data…")

    errors: list[str] = []
    official = None
    rr = None
    twdb_rows = None
    historic = None

    try:
        raw = fetch(LCRA_LAKELEVEL)
        (RAW / "LakeLevel.csv").write_bytes(raw)
        official = parse_lakelevel_csv(raw.decode("utf-8", "replace"))
        log(
            f"  LCRA LakeLevel.csv: Travis {official['elevation_ft_msl']} ft, "
            f"{official['percent_full']}% full at {official['date_time_local']} CT"
        )
    except FetchError as exc:
        errors.append(str(exc))
        log(f"  ERROR: {exc}")

    try:
        raw = fetch(LCRA_LAKELEVELS_RR)
        (RAW / "LakeLevelsRR.csv").write_bytes(raw)
        rr = parse_lakelevels_rr(raw.decode("utf-8", "replace"))
        log(
            f"  LCRA LakeLevelsRR.csv: {rr['elevation_ft_msl']} ft; "
            f"file 7d-ago (midnight) {rr['seven_days_ago_ft_msl']}, "
            f"30d-ago (midnight) {rr['thirty_days_ago_ft_msl']}"
        )
    except FetchError as exc:
        errors.append(str(exc))
        log(f"  ERROR: {exc}")

    try:
        raw = fetch(TWDB_CSV, timeout=90)
        (RAW / "travis_twdb.csv").write_bytes(raw)
        twdb_rows = parse_twdb(raw.decode("utf-8", "replace"))
        log(f"  TWDB daily: {len(twdb_rows)} rows, {twdb_rows[0]['date']} → {twdb_rows[-1]['date']}")
    except FetchError as exc:
        errors.append(str(exc))
        log(f"  ERROR: {exc}")
        if READINGS_CSV.exists():
            log("  Falling back to existing readings.csv")
            with READINGS_CSV.open(newline="") as f:
                twdb_rows = list(csv.DictReader(f))

    # Historic ~179-day window (API limit on the public Historical Data page)
    end = datetime.now(CT).date()
    start = end - timedelta(days=179)
    hist_url = LCRA_HISTORIC.format(
        start=f"{start.month}-{start.day}-{start.year}",
        end=f"{end.month}-{end.day}-{end.year}",
    )
    records: list[dict] = []
    hist_meta: dict = {}
    try:
        raw = fetch(hist_url, timeout=90)
        (RAW / "historic_3963.json").write_bytes(raw)
        hist_meta = json.loads(raw.decode("utf-8"))
        records = hist_meta.get("records") or []
        log(
            f"  LCRA historic API: {len(records)} 5-min points, "
            f"operating range max={hist_meta.get('lakeOperatingRangeMax')}"
        )
    except FetchError as exc:
        errors.append(str(exc))
        log(f"  ERROR: {exc}")

    if twdb_rows:
        rows, inserted, updated = upsert_readings(twdb_rows)
        log(f"  readings.csv: {len(rows)} days (inserted {inserted}, updated {updated})")
    else:
        rows = []

    if not records or not official:
        log("Cannot compute a live snapshot without LCRA current + historic data.")
        CURRENT_JSON.write_text(
            json.dumps(
                {
                    "ok": False,
                    "errors": errors,
                    "official": official,
                    "lakelevels_rr": rr,
                },
                indent=2,
            )
            + "\n"
        )
        return 1

    lcra_daily, latest = lcra_8am_and_latest(records)
    # Prefer the official CSV time if historic last point is older; otherwise
    # use the newest 5-minute value as "current level".
    official_dt = parse_lcra_local(official["date_time_local"])
    latest_dt = to_ct(latest["date_time_utc"])
    if official_dt > latest_dt:
        # Official snapshot is newer than the historic API's last point
        latest = {
            "date_time_utc": official_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "date_time_ct": official_dt.isoformat(),
            "elevation_ft_msl": official["elevation_ft_msl"],
            "tailwater_ft_msl": None,
            "source": official["source"],
        }
        latest_dt = official_dt

    changes = {
        "1d": lookback(records, latest, 1),
        "7d": lookback(records, latest, 7),
        "30d": lookback(records, latest, 30),
    }
    midnight_ft = official.get("midnight_ft_msl")
    # Cross-check midnight from historic if official missing
    if midnight_ft is None:
        mid_target = datetime(
            latest_dt.year, latest_dt.month, latest_dt.day, 0, 0, tzinfo=CT
        ).astimezone(timezone.utc)
        rec, _ = nearest(records, mid_target)
        midnight_ft = float(rec["value1"])

    page = build_page_data(rows, lcra_daily, latest, official, changes, midnight_ft)
    page["errors"] = errors
    page["gaps"] = [
        "waterdata.lcra.org did not complete a TLS handshake from this environment.",
        "LCRA Hydromet historic API is limited to about 179 days of 5-minute data.",
        "Longer daily history uses TWDB daily averages, which can differ slightly from LCRA instantaneous or 8 a.m. readings.",
        "LCRA percent full and storage come from the official LakeLevel.csv snapshot and may lag the latest 5-minute elevation by a few minutes.",
        "TWDB daily values from 1940–1941 include reservoir filling and are lower than LCRA's official 1951 record low; the 'all' chart starts in 1942.",
        "The official LCRA historic high (710.44 ft, 8 a.m. Dec 25, 1991) is a daily 8 a.m. reading; TWDB daily averages around that flood peak at 710.31 ft on Dec 26, 1991.",
    ]

    current = {
        "ok": True,
        "fetched_at_ct": datetime.now(CT).isoformat(),
        "elevation_ft_msl": page["current"]["elevation_ft_msl"],
        "time_ct": page["current"].get("time_ct"),
        "time_label": page["current"]["time_label"],
        "percent_full": page["current"]["percent_full"],
        "storage_acft": page["current"]["storage_acft"],
        "below_full_ft": page["current"]["below_full_ft"],
        "changes": page["changes"],
        "official_snapshot": official,
        "lakelevels_rr": rr,
        "historic_meta": {
            "siteNumber": hist_meta.get("siteNumber"),
            "siteName": hist_meta.get("siteName"),
            "lakeOperatingRangeMax": hist_meta.get("lakeOperatingRangeMax"),
            "n_records": len(records),
        },
        "errors": errors,
        "thresholds": THRESHOLDS,
    }
    CURRENT_JSON.write_text(json.dumps(current, indent=2) + "\n")
    PAGE_DATA_JSON.write_text(json.dumps(page) + "\n")

    log("")
    log("Current (LCRA Hydromet, Mansfield Dam):")
    log(f"  {current['elevation_ft_msl']} ft msl at {current['time_label']}")
    log(f"  {current['percent_full']}% full, storage {current['storage_acft']} ac-ft (official snapshot)")
    log(f"  {current['below_full_ft']} ft below full pool (681 ft)")
    log(f"  vs yesterday: {changes['1d']['change_ft']:+.2f} ft ({changes['1d']['then_elevation_ft_msl']} at {changes['1d']['then_time_label']})")
    log(f"  vs 7 days:    {changes['7d']['change_ft']:+.2f} ft ({changes['7d']['then_elevation_ft_msl']} at {changes['7d']['then_time_label']})")
    log(f"  vs 30 days:   {changes['30d']['change_ft']:+.2f} ft ({changes['30d']['then_elevation_ft_msl']} at {changes['30d']['then_time_label']})")
    if errors:
        log("Completed with errors:")
        for e in errors:
            log(f"  - {e}")
        return 1
    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
