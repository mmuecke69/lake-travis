#!/usr/bin/env python3
"""Build a self-contained, no-login static dashboard from local Lake Travis data."""

from __future__ import annotations

import csv
import os
import json
import math
import re
import statistics
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
CT = ZoneInfo("America/Chicago")
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Continuous daily TWDB record starts in 1943. 1940–41 are filling years
# (values fall below LCRA's official 1951 record low). 1942 is mostly
# sparse month-end snapshots (101 days with large gaps).
CLIM_START = date(1943, 1, 1)

# Attribution is cited, not invented. Numbers are computed from the data.
RISE_SPECS = [
    {
        "id": "july",
        "title": "July 16–19, 2026",
        "sort": "2026-07-16",
        "window_start": "2026-07-16T00:00:00",
        "window_end": "2026-07-19T12:00:00",
        "ongoing": False,
        "kind": "rain",
        "lead": "The year's largest rise. The lake climbed into its flood pool, and LCRA opened floodgates at Mansfield Dam for the first time since 2019.",
        "attribution": (
            "Hill Country rain event — not attributed to a named tropical storm. "
            "LCRA reported that storms over the preceding days brought 1–4 inches "
            "of rain to much of the region, with some areas near Junction and "
            "Fredericksburg receiving as much as a foot, sending runoff toward "
            "Lake Travis. Axios, using LCRA data, reported the lake climbed roughly "
            "13 feet between July 16 and July 19. Tropical Storm Bertha did not form "
            "until July 20, after this rise had crested."
        ),
        "sources": [
            {"name": "LCRA, July 17, 2026: floodgate operations at Mansfield Dam",
             "url": "https://www.lcra.org/news/news-releases/lcra-to-begin-floodgate-operations-at-mansfield-dam/"},
            {"name": "Axios Austin, July 20, 2026: Charted: Lake Travis rises",
             "url": "https://www.axios.com/local/austin/2026/07/20/charted-lake-travis-rises"},
        ],
    },
    {
        "id": "may",
        "title": "May 21–28, 2026",
        "sort": "2026-05-21",
        "window_start": "2026-05-21T00:00:00",
        "window_end": "2026-05-28T18:30:00",
        "ongoing": False,
        "kind": "rain",
        "lead": "A late-May rise in two pulses, steepest overnight May 26–27 when LCRA opened a floodgate at Starcke Dam.",
        "attribution": (
            "Rain event (severe thunderstorms) — not attributed to a named tropical storm. "
            "LCRA warned on May 26 of a line of strong to severe storms and widespread "
            "soaking rain (1–3 inches, isolated pockets up to 5 inches) under an NWS Flood Watch. "
            "The Daily Trib reported that storms that evening washed out roads in the Highland "
            "Lakes area and that LCRA opened a Starcke Dam floodgate overnight to pass runoff "
            "into Lake Travis. The lake had already begun rising on May 20–23 and continued a "
            "slow creep to 670.00 ft early on June 1."
        ),
        "sources": [
            {"name": "LCRA, May 26, 2026: severe storms forecast",
             "url": "https://www.lcra.org/a-line-of-strong-to-severe-storms-will-spread-over-the-area-tuesday-night/"},
            {"name": "Daily Trib, May 27, 2026: severe rainfall in the Highland Lakes",
             "url": "https://www.dailytrib.com/2026/05/27/severe-rainfall-washes-through-highland-lakes/"},
        ],
    },
    {
        "id": "june",
        "title": "June 14–16, 2026",
        "sort": "2026-06-14",
        "window_start": "2026-06-14T21:00:00",
        "window_end": "2026-06-16T21:00:00",
        "ongoing": False,
        "kind": "rain",
        "lead": "A short, sharp bump during a night of flash flooding in the Austin area.",
        "attribution": (
            "Rain event — not attributed to a named tropical storm. "
            "KUT reported flash flooding, water rescues, and 3–4 inches of rain in parts of "
            "Travis County from midnight to early afternoon on June 15, with NWS flash flood "
            "warnings for Travis, Hays, and Williamson counties. LCRA opened a floodgate at "
            "Tom Miller Dam that morning. Tropical Storm Arthur formed on June 17 near the "
            "Texas coast, after this rise; no source reviewed here ties the Lake Travis rise "
            "to Arthur, so it is not named as the cause."
        ),
        "sources": [
            {"name": "KUT, June 15, 2026: Austin flash flooding",
             "url": "https://www.kut.org/austin/2026-06-15/austin-texas-flash-flood-warning"},
        ],
    },
    {
        "id": "october",
        "title": "October 1–7, 2026",
        "sort": "2026-10-01",
        "window_start": "2026-10-01T06:00:00",
        "window_end": "2026-10-07T23:30:00",
        "ongoing": False,
        "kind": "tropical",
        "lead": "Most of this rise happened in the first three days; the lake then crept to a crest on October 7.",
        "attribution": (
            "Remnants of Hurricane Polo interacting with a cold front. "
            "Texas Public Radio, on October 1, reported that the National Weather Service "
            "issued flash flood warnings for portions of Bandera, Gillespie, Kerr, and Real "
            "counties as Polo's remnants interacted with a cold front, and that a flood warning "
            "was in effect for the Llano River at Llano. The next morning, KUT reported that "
            "LCRA had opened floodgates at Wirtz and Starcke dams to pass Llano River floodwaters "
            "downstream into Lake Travis."
        ),
        "sources": [
            {"name": "Texas Public Radio, October 1, 2026: Polo remnants and a cold front",
             "url": "https://www.tpr.org/environment/2026-10-01/polo-cold-front-sputters-on-approach-to-san-antonio-flooding-out-west"},
            {"name": "KUT, October 2, 2026: Wirtz and Starcke floodgates, water into Lake Travis",
             "url": "https://www.kut.org/energy-environment/2026-10-02/austin-tx-dams-floodgates-rain-weather-flood"},
        ],
    },
    {
        "id": "november",
        "title": "November 9–10, 2026 (still rising)",
        "sort": "2026-11-09",
        "window_start": "2026-11-09T16:20:00",
        "window_end": None,  # through latest 5-minute reading
        "ongoing": True,
        "kind": "rain",
        "lead": "A rise still in progress as LCRA moves Llano River floodwaters into Lake Travis.",
        "attribution": (
            "Rain event — not attributed to a named tropical storm. "
            "LCRA's flood page and CBS Austin reported heavy rain west of the Highland Lakes "
            "and high flows on the Llano River. LCRA opened floodgates at Wirtz and Starcke dams "
            "to pass that water downstream into Lake Travis, and projected the lake would rise "
            "to 680–681 ft over the next 24–48 hours. No floodgate operations were expected at "
            "Mansfield Dam."
        ),
        "sources": [
            {"name": "LCRA flood operations page",
             "url": "https://www.lcra.org/water/flood/"},
            {"name": "CBS Austin, November 10, 2026: Wirtz and Starcke gates, Llano floodwaters",
             "url": "https://cbsaustin.com/news/local/lcra-to-open-floodgates-as-llano-floodwaters-head-for-lake-travis"},
        ],
    },
]

HIST_SPECS = [
    {
        "id": "jul2025",
        "title": "July 2025 Hill Country flood",
        "start": "2025-07-04",
        "end": "2025-07-17",
        "note": (
            "LCRA reported that from 7 a.m. Friday, July 4, through July 17, 2025, "
            "Lake Travis rose more than 36 feet. TWDB daily averages show 637.78 ft "
            "on July 4 and 673.70 ft on July 17. A second pulse followed mid-month. "
            "This was a Hill Country rain/flood event, not used here as a named-storm attribution."
        ),
        "source": {"name": "LCRA, July 17, 2025",
                   "url": "https://www.lcra.org/news/news-releases/use-extra-caution-on-the-highland-lakes-after-recent-floods/"},
    },
    {
        "id": "oct2018",
        "title": "October 2018",
        "start": "2018-10-07",
        "end": "2018-10-20",
        "note": (
            "The largest well-documented rise in the modern daily record used here: "
            "TWDB daily averages show the lake going from 658.77 ft on October 7 to "
            "704.28 ft on October 20, including a 19.58 ft jump from October 16 to 17."
        ),
        "source": {"name": "TWDB daily history for Lake Travis",
                   "url": "https://www.waterdatafortexas.org/reservoirs/individual/travis.csv"},
    },
    {
        "id": "dec1991",
        "title": "December 1991 (official record high)",
        "start": "1991-12-10",
        "end": "1991-12-26",
        "note": (
            "LCRA's official historic high is 710.44 ft msl on December 25, 1991, "
            "from a daily 8 a.m. reading. TWDB daily averages peak at 710.31 ft on "
            "December 26 (710.16 ft on December 25). The two sources use different methods; "
            "the official record is LCRA's."
        ),
        "source": {"name": "LCRA dams and lakes (official record high)",
                   "url": "https://www.lcra.org/water/dams-and-lakes/"},
    },
]


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100.0
    i = int(math.floor(k))
    j = min(i + 1, len(xs) - 1)
    f = k - i
    return xs[i] * (1 - f) + xs[j] * f


def parse_ct(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CT)
    return dt.astimezone(CT)


def fmt_ct(dt: datetime) -> str:
    dt = dt.astimezone(CT)
    # %-I is POSIX; Windows wouldn't apply, but this box is Linux.
    return dt.strftime("%b %-d, %Y, %-I:%M %p %Z")


def load_readings():
    rows = []
    with (ROOT / "readings.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            d = date.fromisoformat(r["date"])
            rows.append({
                "date": d,
                "elev": float(r["elevation_ft_msl"]),
                "pct": float(r["percent_full"]) if r.get("percent_full") else None,
                "storage": float(r["storage_acft"]) if r.get("storage_acft") else None,
                "source": r.get("source") or "",
            })
    rows.sort(key=lambda x: x["date"])
    return rows


def load_historic():
    path = ROOT / "raw" / "historic_3963.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    pts = []
    for r in data.get("records", []):
        if r.get("value1") is None:
            continue
        dt = datetime.fromisoformat(r["dateTime"].replace("Z", "+00:00")).astimezone(CT)
        pts.append((dt, float(r["value1"])))
    pts.sort()
    return pts


def compute_climatology(readings):
    op = [r for r in readings if r["date"] >= CLIM_START]
    by_ym = defaultdict(list)
    for r in op:
        by_ym[(r["date"].year, r["date"].month)].append(r["elev"])
    month_year_means = defaultdict(list)
    for (y, m), vals in by_ym.items():
        month_year_means[m].append((y, sum(vals) / len(vals), len(vals)))

    monthly = []
    for m in range(1, 13):
        pairs = month_year_means[m]
        means = [x[1] for x in pairs]
        mn = min(pairs, key=lambda x: x[1])
        mx = max(pairs, key=lambda x: x[1])
        monthly.append({
            "month": m,
            "name": MONTHS[m - 1],
            "short": MONTHS_SHORT[m - 1],
            "n_years": len(means),
            "mean": round(sum(means) / len(means), 2),
            "median": round(statistics.median(means), 2),
            "p10": round(pct(means, 10), 2),
            "p90": round(pct(means, 90), 2),
            "min": round(mn[1], 2),
            "min_year": mn[0],
            "max": round(mx[1], 2),
            "max_year": mx[0],
        })

    # 2026 monthly means (partial months included)
    y2026 = {}
    for m in range(1, 13):
        vals = by_ym.get((2026, m))
        if not vals:
            continue
        y2026[m] = {"mean": round(sum(vals) / len(vals), 2), "n": len(vals)}

    # Day-of-year climatology (skip Feb 29)
    by_md = defaultdict(list)
    for r in op:
        d = r["date"]
        if d.month == 2 and d.day == 29:
            continue
        by_md[(d.month, d.day)].append(r["elev"])
    doy = []
    cursor = date(2025, 1, 1)  # non-leap template
    while cursor.year == 2025:
        xs = by_md[(cursor.month, cursor.day)]
        doy.append({
            "md": f"{cursor.month:02d}-{cursor.day:02d}",
            "n": len(xs),
            "mean": round(sum(xs) / len(xs), 2) if xs else None,
            "median": round(statistics.median(xs), 2) if xs else None,
            "p10": round(pct(xs, 10), 2) if xs else None,
            "p90": round(pct(xs, 90), 2) if xs else None,
        })
        cursor += timedelta(days=1)

    highest = max(monthly, key=lambda x: x["mean"])
    lowest = min(monthly, key=lambda x: x["mean"])
    last = readings[-1]["date"]
    return {
        "start": CLIM_START.isoformat(),
        "end": last.isoformat(),
        "note": (
            f"Typical seasonal levels use TWDB daily averages from {CLIM_START.isoformat()} "
            f"through {last.isoformat()}. 1940–1941 filling years are excluded because the "
            "reservoir was still coming into service and TWDB values fall below LCRA's official "
            "1951 record low (614.18 ft). 1942 is also set aside: that year has only 101 sparse "
            "month-end values, not a continuous daily record. Each calendar month's mean, median, "
            "and 10th/90th percentiles are computed from that month's yearly mean elevation, so "
            "each year counts equally."
        ),
        "monthly": monthly,
        "year_2026": y2026,
        "doy": doy,
        "highest_month": highest["name"],
        "highest_mean": highest["mean"],
        "lowest_month": lowest["name"],
        "lowest_mean": lowest["mean"],
    }


def peak_24h(pts, start, end):
    w = [(t, v) for t, v in pts if start <= t <= end]
    if not w:
        return None
    j = 0
    best = (0.0, w[0], w[0])
    for i, (t0, v0) in enumerate(w):
        limit = t0 + timedelta(hours=24)
        while j + 1 < len(w) and w[j + 1][0] <= limit:
            j += 1
        rise = w[j][1] - v0
        if rise > best[0]:
            best = (rise, (t0, v0), w[j])
    return {
        "ft": round(best[0], 2),
        "start_time": best[1][0].isoformat(),
        "start_label": fmt_ct(best[1][0]),
        "start_ft": round(best[1][1], 2),
        "end_time": best[2][0].isoformat(),
        "end_label": fmt_ct(best[2][0]),
        "end_ft": round(best[2][1], 2),
    }


def analyze_rise(spec, historic, latest_pt):
    start = parse_ct(spec["window_start"])
    end = latest_pt[0] if spec["window_end"] is None else parse_ct(spec["window_end"])
    w = [(t, v) for t, v in historic if start <= t <= end]
    if not w:
        return None
    start_t, start_v = w[0]
    if spec["ongoing"]:
        end_t, end_v = w[-1]
    else:
        end_t, end_v = max(w, key=lambda x: x[1])
    rise = end_v - start_v
    seconds = (end_t - start_t).total_seconds()
    days = seconds / 86400.0
    p24 = peak_24h(historic, start, end)
    return {
        "id": spec["id"],
        "title": spec["title"],
        "sort": spec["sort"],
        "ongoing": spec["ongoing"],
        "kind": spec["kind"],
        "lead": spec["lead"],
        "attribution": spec["attribution"],
        "sources": spec["sources"],
        "start_time": start_t.isoformat(),
        "start_label": fmt_ct(start_t),
        "start_ft": round(start_v, 2),
        "end_time": end_t.isoformat(),
        "end_label": fmt_ct(end_t),
        "end_ft": round(end_v, 2),
        "rise_ft": round(rise, 2),
        "days": round(days, 2),
        "rate_ft_per_day": round(rise / days, 2) if days > 0 else None,
        "peak_24h": p24,
        "series_source": "LCRA Hydromet 5-minute readings at Mansfield Dam (site 3963)",
    }


def twdb_event(readings, start_s, end_s):
    s = date.fromisoformat(start_s)
    e = date.fromisoformat(end_s)
    by = {r["date"]: r["elev"] for r in readings}
    if s not in by or e not in by:
        return None
    rise = by[e] - by[s]
    days = (e - s).days
    peak = 0.0
    peak_day = None
    peak_from = None
    cursor = s + timedelta(days=1)
    prev_d, prev_v = s, by[s]
    while cursor <= e:
        if cursor in by and (cursor - prev_d).days == 1:
            r = by[cursor] - prev_v
            if r > peak:
                peak = r
                peak_day = cursor
                peak_from = (prev_d, prev_v, cursor, by[cursor])
        if cursor in by:
            prev_d, prev_v = cursor, by[cursor]
        cursor += timedelta(days=1)
    return {
        "start": s.isoformat(),
        "end": e.isoformat(),
        "start_ft": round(by[s], 2),
        "end_ft": round(by[e], 2),
        "rise_ft": round(rise, 2),
        "days": days,
        "rate_ft_per_day": round(rise / days, 2) if days else None,
        "peak_24h_ft": round(peak, 2),
        "peak_24h_date": peak_day.isoformat() if peak_day else None,
        "peak_24h_from_ft": round(peak_from[1], 2) if peak_from else None,
        "peak_24h_to_ft": round(peak_from[3], 2) if peak_from else None,
        "source": "TWDB daily average elevation",
    }


def series_daily(readings, start: date):
    out = []
    for r in readings:
        if r["date"] >= start:
            out.append({"d": r["date"].isoformat(), "e": round(r["elev"], 2)})
    return out


def series_monthly(readings, start: date):
    buckets = defaultdict(list)
    for r in readings:
        if r["date"] < start:
            continue
        key = date(r["date"].year, r["date"].month, 1)
        buckets[key].append(r["elev"])
    return [{"d": k.isoformat(), "e": round(sum(v) / len(v), 2)} for k, v in sorted(buckets.items())]


def same_date_table(readings, target: date, years=10):
    rows = []
    by = {r["date"]: r for r in readings}
    # this year uses the matching calendar date; if we want "same date" for Nov 10
    for y in range(target.year - years, target.year + 1):
        try:
            d = date(y, target.month, target.day)
        except ValueError:
            continue
        r = by.get(d)
        if not r:
            continue
        rows.append({
            "date": d.isoformat(),
            "year": y,
            "elevation_ft_msl": round(r["elev"], 2),
            "percent_full": r["pct"],
            "is_this_year": y == target.year,
        })
    return rows


def overlay_years(readings, this_year: int, back=10):
    by_year = defaultdict(dict)
    for r in readings:
        if r["date"].year < this_year - back:
            continue
        if r["date"].month == 2 and r["date"].day == 29:
            continue
        md = f"{r['date'].month:02d}-{r['date'].day:02d}"
        by_year[r["date"].year][md] = round(r["elev"], 2)
    # labels in a non-leap year
    labels = []
    cursor = date(2025, 1, 1)
    while cursor.year == 2025:
        labels.append(f"{cursor.month:02d}-{cursor.day:02d}")
        cursor += timedelta(days=1)
    prior = {}
    for y in range(this_year - back, this_year):
        if y in by_year:
            prior[str(y)] = [by_year[y].get(md) for md in labels]
    this = [by_year.get(this_year, {}).get(md) for md in labels]
    return {"labels": labels, "this_year": this, "this_year_label": str(this_year), "prior_years": prior}


def _plain_html(fragment: str) -> str:
    """Strip tags from an LCRA HTML snippet and return the published text."""
    from html import unescape
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n\n", text, flags=re.I)
    text = re.sub(r"</p>|<p[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_lcra_note() -> dict:
    """Scrape the current LCRA flood-operations note. Never invents text.

    LakeLevel.csv has no note or message field. hydromet.lcra.org has no
    public notices/messages API (those paths 404). The Hydromet flood-status
    report is a JavaScript app. The published, scrapeable current note is
    on https://www.lcra.org/water/flood/ (situation box, floodgate table,
    and Travis forecast), which is server-rendered in the HTML.
    """
    url = "https://www.lcra.org/water/flood/"
    note = {
        "ok": False,
        "source": url,
        "source_label": "lcra.org/water/flood",
        "fetched_at_ct": datetime.now(CT).isoformat(),
    }
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LakeTravisDashboard/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        note["error"] = f"Could not fetch {url}: {exc}"
        return note

    ts = re.search(r'<div class="flood-status-timestamp">(.*?)</div>', html, re.S)
    level = re.search(r'<p class="flood-status-level">(.*?)</p>', html, re.S)
    stext = re.search(r'<div class="flood-status-text">(.*?)</div>', html, re.S)
    table = re.search(
        r'<table class="lcra-lake-table">(.*?)</table>', html, re.S | re.I
    )
    gates = []
    if table:
        for dam, status, as_of in re.findall(
            r"<tr>\s*<td>\s*([^<]+?)\s*</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
            table.group(1),
            re.S | re.I,
        ):
            gates.append({
                "dam": _plain_html(dam),
                "status": _plain_html(status),
                "as_of": _plain_html(as_of),
            })
    mansfield = next((g for g in gates if "Mansfield" in g["dam"] and "Travis" in g["dam"]), None)
    forecast = re.search(
        r'<h3 class="lcra-lake-name">\s*Travis Forecast\s*</h3>\s*'
        r'<div class="lcra-last-updated">\s*<small>(.*?)</small>\s*</div>.*?'
        r'<div class="lcra-forecast">(.*?)</div>',
        html,
        re.S | re.I,
    )

    if not (ts or level or stext or mansfield or forecast):
        note["error"] = (
            "The LCRA flood operations page did not contain a recognizable "
            "current situation, gate-status, or Travis forecast note."
        )
        return note

    note["ok"] = True
    if ts:
        note["situation_as_of"] = _plain_html(ts.group(1))
    if level:
        note["situation_level"] = _plain_html(level.group(1))
    if stext:
        note["situation_text"] = _plain_html(stext.group(1))
    if forecast:
        note["travis_forecast_as_of"] = _plain_html(forecast.group(1))
        note["travis_forecast"] = _plain_html(forecast.group(2))
    if mansfield:
        note["mansfield_gates"] = mansfield["status"]
        note["mansfield_gates_as_of"] = mansfield["as_of"]
    if gates:
        note["gates"] = gates
    return note


def forecast_from_note(note: dict) -> dict:
    """Keep the existing forecast payload shape, filled only from a live scrape."""
    return {
        "as_of_label": note.get("travis_forecast_as_of") or note.get("situation_as_of") or "",
        "text": note.get("travis_forecast") or "",
        "situation": note.get("situation_text") or "",
        "situation_level": note.get("situation_level") or "",
        "situation_as_of": note.get("situation_as_of") or "",
        "gates": note.get("gates") or (
            [{"dam": "Mansfield Dam / Lake Travis", "status": note["mansfield_gates"],
              "as_of": note.get("mansfield_gates_as_of") or ""}]
            if note.get("mansfield_gates") else []
        ),
        "source": note.get("source") or "https://www.lcra.org/water/flood/",
        "fetched": bool(note.get("ok")),
        "error": note.get("error"),
    }


def build_payload():
    current = json.loads((ROOT / "current.json").read_text())
    page = json.loads((ROOT / "page_data.json").read_text()) if (ROOT / "page_data.json").exists() else {}
    readings = load_readings()
    historic = load_historic()
    latest_pt = historic[-1] if historic else None
    today = readings[-1]["date"]
    clim = compute_climatology(readings)

    rises = []
    for spec in RISE_SPECS:
        ev = analyze_rise(spec, historic, latest_pt)
        if ev:
            rises.append(ev)
    rises.sort(key=lambda x: x["sort"], reverse=True)

    hist = []
    for spec in HIST_SPECS:
        ev = twdb_event(readings, spec["start"], spec["end"])
        if not ev:
            continue
        ev.update({
            "id": spec["id"],
            "title": spec["title"],
            "note": spec["note"],
            "source": spec["source"],
        })
        hist.append(ev)

    # Chart series
    last = readings[-1]["date"]
    series = {
        "30d": series_daily(readings, last - timedelta(days=29)),
        "90d": series_daily(readings, last - timedelta(days=89)),
        "1y": series_daily(readings, last - timedelta(days=364)),
        "5y": series_daily(readings, last - timedelta(days=365 * 5)),
        "all": series_monthly(readings, date(1942, 1, 1)),
    }

    lcra_note = fetch_lcra_note()
    forecast = forecast_from_note(lcra_note)
    thresholds = current.get("thresholds") or page.get("thresholds") or {}

    payload = {
        "generated_at_ct": current.get("fetched_at_ct"),
        "current": {
            "elevation_ft_msl": current["elevation_ft_msl"],
            "time_ct": current.get("time_ct"),
            "time_label": current["time_label"],
            "percent_full": current["percent_full"],
            "storage_acft": current.get("storage_acft"),
            "below_full_ft": current.get("below_full_ft"),
            "site": "Mansfield Dam (LCRA site 3963)",
        },
        "changes": current.get("changes"),
        "lcra_note": lcra_note,
        "forecast": forecast,
        "thresholds": thresholds,
        "flood_stage_note": (
            "The 700 ft line is included because it was requested as a reference. "
            "It sits in LCRA's flood pool (681–714 ft) and is not a verified official "
            "LCRA “flood stage.” LCRA uses “flood stage” as an NWS / local term, not as "
            "a 700 ft gauge at Mansfield Dam. Official marked levels are conservation / "
            "full pool at 681 ft and the overflow spillway / top of flood pool at 714 ft."
        ),
        "climatology": {
            "start": clim["start"],
            "end": clim["end"],
            "note": clim["note"],
            "monthly": clim["monthly"],
            "year_2026": clim["year_2026"],
            "doy": clim["doy"],
            "highest_month": clim["highest_month"],
            "highest_mean": clim["highest_mean"],
            "lowest_month": clim["lowest_month"],
            "lowest_mean": clim["lowest_mean"],
        },
        "series": series,
        "overlay": overlay_years(readings, last.year, back=10),
        "same_date": same_date_table(readings, last, years=10),
        "same_date_note": (
            f"TWDB daily average elevation on {last.strftime('%B %-d')} of each year. "
            f"Today's live LCRA reading is {current['elevation_ft_msl']:.2f} ft; "
            "the TWDB figure for today is a daily average and may differ, especially "
            "while the lake is rising or falling quickly."
        ),
        "rises_2026": rises,
        "rises_note": (
            "A sharp rise is a gain of more than 1 foot over a few days. Elevations, "
            "rates, and peak 24-hour rises for 2026 come from LCRA Hydromet 5-minute "
            "readings (available back to mid-May 2026). A storm is named only when a "
            "cited NWS, LCRA, or news source ties that storm or its remnants to the rain "
            "or river flows that raised Lake Travis; otherwise the event is called a rain event."
        ),
        "historical_rises": hist,
        "historical_note": (
            "Historical comparisons use TWDB daily averages, which can differ from LCRA "
            "instantaneous or 8 a.m. readings. The September 1952 TWDB series shows an "
            "extremely large rise, including a one-day jump of about 56 ft on September 12, "
            "which may include a gap or catch-up in the daily record; it is not used as a "
            "headline comparison."
        ),
        "sources": [
            {"name": "LCRA Hydromet LakeLevel.csv (current official snapshot)",
             "url": "https://hydromet.lcra.org/media/LakeLevel.csv"},
            {"name": "LCRA Hydromet HistoricData API, site 3963 (5-minute lake level)",
             "url": "https://hydromet.lcra.org/HistoricalData"},
            {"name": "TWDB Water Data for Texas — Lake Travis daily history",
             "url": "https://www.waterdatafortexas.org/reservoirs/individual/travis.csv"},
            {"name": "LCRA dams and lakes (681, 714, official record high/low)",
             "url": "https://www.lcra.org/water/dams-and-lakes/"},
            {"name": "USACE Mansfield Dam (top of conservation 681, spillway / top of flood 714)",
             "url": "https://water.usace.army.mil/overview/swf/locations/msdt2"},
            {"name": "LCRA flood operations and Travis forecast",
             "url": "https://www.lcra.org/water/flood/"},
        ],
        "caveats": [
            "Every elevation on this page comes from published LCRA or TWDB data. Nothing is interpolated as a fake reading.",
            "Times are America/Chicago (Central Time), labeled CST or CDT.",
            "1-/7-/30-day changes use the LCRA 5-minute series at the same time of day, not the midnight values in LakeLevelsRR.csv.",
            "LCRA percent full and storage can lag the latest 5-minute elevation by a few minutes.",
            "TWDB daily averages and LCRA instantaneous or 8 a.m. readings can differ, especially on fast-changing days. Percent-full methods also differ.",
            "The Hydromet historic API returns about 179 days of 5-minute data. Longer charts use TWDB daily values (monthly means for the all-time view).",
        ],
    }
    return payload, clim, rises, hist


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>Lake Travis level — Point Venture</title>
<meta name="description" content="Current Lake Travis elevation at Mansfield Dam, with trends, typical seasonal levels, and this year's sharp rises. Built from published LCRA and TWDB data.">
<meta name="lake-travis-data-url" content="@@DATA_URL@@">
<style>
:root {
  --bg: #f3efe6;
  --card: #ffffff;
  --ink: #1a2332;
  --heading: var(--ink);
  --muted: #5b6573;
  --line: #e2ddd3;
  --lake: #0b5f8a;
  --lake-soft: rgba(11,95,138,.14);
  --up: #157a45;
  --down: #b42318;
  --warn: #8a5800;
  --band: rgba(11,95,138,.16);
  --radius: 16px;
  --shadow: 0 1px 2px rgba(26,35,50,.06), 0 8px 24px rgba(26,35,50,.06);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--ink); }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.45;
  padding: 16px 16px 48px;
  padding-left: max(16px, env(safe-area-inset-left));
  padding-right: max(16px, env(safe-area-inset-right));
}
.wrap { max-width: 760px; margin: 0 auto; }
header h1 { font-size: 1.35rem; margin: 0 0 2px; letter-spacing: -0.02em; color: var(--heading); }
header .sub { color: var(--muted); font-size: .92rem; margin: 0 0 16px; }
.card {
  background: var(--card);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 16px 18px;
  margin: 0 0 14px;
}
.level {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px;
}
.level .num {
  font-size: 3.1rem; font-weight: 700; letter-spacing: -0.04em; line-height: 1;
  color: var(--lake);
}
.level .unit { font-size: 1.05rem; color: var(--muted); font-weight: 600; }
.meta { color: var(--muted); font-size: .92rem; margin-top: 6px; }
.pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.pill {
  background: #f3f7fa; border-radius: 999px; padding: 6px 12px;
  font-size: .9rem; font-weight: 600;
}
.pill span { color: var(--muted); font-weight: 500; }
.changes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (min-width: 560px) { .changes { grid-template-columns: repeat(4, 1fr); } }
.chg { background: #f7f5f0; border-radius: 12px; padding: 10px 12px; }
.chg .k { font-size: .78rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.chg .v { font-size: 1.25rem; font-weight: 700; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--ink); }
.callout { border-left: 4px solid var(--lake); padding: 2px 0 2px 12px; }
.callout p { margin: 0 0 6px; }
.callout .asof { color: var(--muted); font-size: .85rem; }
.callout .note-level { font-weight: 700; margin: 0 0 8px; }
.callout .note-body { white-space: pre-wrap; }
#when { color: var(--muted); font-size: .92rem; margin-top: 6px; }
#when .site { display: block; margin-top: 2px; }
h2 { font-size: 1.15rem; margin: 0 0 10px; letter-spacing: -0.02em; }
h3 { font-size: 1.02rem; margin: 16px 0 8px; }
.toggles { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
.toggles button {
  appearance: none; border: 1px solid var(--line); background: #fff;
  border-radius: 999px; padding: 6px 12px; font: inherit; font-size: .88rem;
  font-weight: 600; color: var(--ink); cursor: pointer;
}
.toggles button[aria-pressed="true"] {
  background: var(--lake); color: #fff; border-color: var(--lake);
}
.chart-box { position: relative; height: 260px; }
.legend-note { color: var(--muted); font-size: .82rem; margin: 8px 0 0; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.this td { font-weight: 700; background: var(--lake-soft); }
.rise { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }
.rise:first-of-type { border-top: 0; margin-top: 0; padding-top: 0; }
.rise h3 { margin: 0 0 6px; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; margin: 8px 0; font-size: .92rem; }
@media (min-width: 560px) { .stats { grid-template-columns: 1fr 1fr 1fr; } }
.stats b { font-variant-numeric: tabular-nums; }
.sources, .caveats { font-size: .88rem; color: var(--ink); }
.sources a { color: var(--lake); }
.caveats li, .sources li { margin: 0 0 6px; }
footer { color: var(--muted); font-size: .82rem; margin-top: 8px; }
.credit {
  color: #fff;
  font-size: 1.1rem;
  font-weight: 600;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  text-align: center;
  margin: 8px 0 16px;
  padding: 8px 14px;
  background: var(--lake);
  border-radius: 14px;
}
</style>
</head>
<body>
<div class="wrap">
  <p class="credit">Made by Mike Muecke, using Grokbot</p>
  <header>
    <h1>Lake Travis level</h1>
    <p class="sub">Mansfield Dam · Point Venture, Texas</p>
  </header>

  <section class="card" id="current">
    <div class="level">
      <div class="num" id="elev">—</div>
      <div class="unit">ft msl</div>
    </div>
    <div class="meta" id="when"></div>
    <div class="pills">
      <div class="pill" id="pct"></div>
      <div class="pill" id="below"></div>
      <div class="pill" id="storage"></div>
    </div>
  </section>

  <section class="card">
    <h2>Change</h2>
    <div class="changes" id="changes"></div>
    <p class="legend-note" id="change-note"></p>
  </section>

  <section class="card callout" id="forecast"></section>

  <section class="card">
    <h2>Trend</h2>
    <div class="toggles" id="range-toggles" role="tablist" aria-label="Chart range">
      <button type="button" data-range="30d">30 days</button>
      <button type="button" data-range="90d">90 days</button>
      <button type="button" data-range="1y" aria-pressed="true">1 year</button>
      <button type="button" data-range="5y">5 years</button>
      <button type="button" data-range="all">All</button>
    </div>
    <div class="chart-box"><canvas id="trend"></canvas></div>
    <p class="legend-note" id="trend-note">Blue line is the lake. Dashed teal is the typical level for that date (1943–present monthly climatology as a day-of-year curve). Shaded band is the 10th–90th percentile. Horizontal lines mark full pool (681), a 700 ft reference in the flood pool, the official record high (710.44), and the spillway / top of flood (714) when they fall in view.</p>
  </section>

  <section class="card">
    <h2>This year vs. prior years</h2>
    <div class="chart-box" style="height:280px"><canvas id="overlay"></canvas></div>
    <p class="legend-note">Each faint line is a prior year (2016–2025) by day of year. The heavy blue line is 2026. The dashed teal line and shaded band are the long-term typical curve and 10th–90th percentile range, starting in 1943.</p>
  </section>

  <section class="card">
    <h2>Same date in prior years</h2>
    <p class="legend-note" id="same-note"></p>
    <div class="table-wrap"><table id="same-date"><thead></thead><tbody></tbody></table></div>
  </section>

  <section class="card">
    <h2>Typical level by month</h2>
    <p class="legend-note" id="clim-note"></p>
    <div class="table-wrap"><table id="monthly"><thead></thead><tbody></tbody></table></div>
  </section>

  <section class="card" id="rises">
    <h2>This year’s big rises</h2>
    <p class="legend-note" id="rises-note"></p>
    <div id="rise-list"></div>
    <h3>How this year compares</h3>
    <p class="legend-note" id="hist-note"></p>
    <div class="table-wrap"><table id="hist"><thead></thead><tbody></tbody></table></div>
  </section>

  <section class="card">
    <h2>Official reference levels</h2>
    <div class="table-wrap"><table id="thresholds"><tbody></tbody></table></div>
    <p class="legend-note" id="fs-note"></p>
  </section>

  <section class="card">
    <h2>Sources</h2>
    <ul class="sources" id="sources"></ul>
    <h3>Caveats</h3>
    <ul class="caveats" id="caveats"></ul>
  </section>

  <footer>
    Snapshot built from published LCRA and TWDB data. Opens in any browser; no sign-in required.
  </footer>
</div>

<script id="data" type="application/json"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script>
(function () {
  var LIVE_DATA_URL = "https://mmuecke69.github.io/lake-travis/data.json";

  function cacheBust(url) {
    try {
      var u = new URL(url, location.href);
      u.searchParams.set("t", String(Date.now()));
      return u.toString();
    } catch (e) {
      return url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    }
  }

  function relativeDataUrl() {
    var q = new URLSearchParams(location.search).get("data");
    if (q) return q;
    var meta = document.querySelector('meta[name="lake-travis-data-url"]');
    if (meta && meta.content) return meta.content;
    return "data.json";
  }

  function dataCandidates() {
    if (window.LAKE_TRAVIS_DATA_URL) return [window.LAKE_TRAVIS_DATA_URL];
    var list = [LIVE_DATA_URL];
    var rel = relativeDataUrl();
    if (rel && rel !== LIVE_DATA_URL) list.push(rel);
    return list;
  }

  function parseInlineData() {
    var inline = document.getElementById("data");
    if (!inline || !inline.textContent.trim()) return null;
    try { return JSON.parse(inline.textContent); }
    catch (e) { return null; }
  }

  function fetchJson(url) {
    return fetch(cacheBust(url), { cache: "no-store" }).then(function (res) {
      if (!res.ok) throw new Error("Could not load " + url + " (" + res.status + ")");
      return res.json();
    });
  }

  function loadData() {
    var urls = dataCandidates();
    var chain = Promise.reject(new Error("no data url"));
    urls.forEach(function (url) {
      chain = chain.catch(function () { return fetchJson(url); });
    });
    return chain.catch(function (err) {
      var inline = parseInlineData();
      if (inline) return inline;
      throw err;
    });
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatCtTime(d) {
    try {
      var parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Chicago",
        hour: "numeric",
        minute: "2-digit",
        hour12: true
      }).formatToParts(d);
      var map = {};
      parts.forEach(function (p) { map[p.type] = p.value; });
      return map.hour + ":" + map.minute + " " + map.dayPeriod + " CT";
    } catch (e) {
      return d.toLocaleTimeString();
    }
  }

  function readingTimeShort(cur) {
    if (cur && cur.time_ct) {
      var dt = new Date(cur.time_ct);
      if (!isNaN(dt.getTime())) return formatCtTime(dt);
    }
    var label = (cur && cur.time_label) || "";
    var m = label.match(/(\d{1,2}:\d{2}\s*[AP]M)/i);
    if (m) return m[1].replace(/\s+/g, " ") + " CT";
    return label;
  }

  function render(DATA) {
  const fmtFt = (n, digits=2) => (n == null ? "—" : Number(n).toFixed(digits) + " ft");
  const fmtChg = (n) => {
    if (n == null || Number.isNaN(n)) return { text: "—", cls: "flat" };
    const v = Number(n);
    const sign = v > 0 ? "+" : "";
    const cls = v > 0.005 ? "up" : (v < -0.005 ? "down" : "flat");
    return { text: sign + v.toFixed(2) + " ft", cls };
  };
  const fmtAcft = (n) => n == null ? "—" : Math.round(n).toLocaleString("en-US") + " ac-ft";

  const cur = DATA.current;
  const checkedAt = formatCtTime(new Date());
  const readingAt = readingTimeShort(cur);
  document.getElementById("elev").textContent = Number(cur.elevation_ft_msl).toFixed(2);
  document.getElementById("when").innerHTML =
    "Reading " + esc(readingAt) + " · checked " + esc(checkedAt) +
    (cur.site ? '<span class="site">' + esc(cur.site) + "</span>" : "");
  document.getElementById("pct").innerHTML = "<span>% full</span> " + cur.percent_full + "%";
  document.getElementById("below").innerHTML = "<span>vs full (681)</span> " +
    (cur.below_full_ft > 0 ? cur.below_full_ft.toFixed(2) + " ft below" : Math.abs(cur.below_full_ft).toFixed(2) + " ft above");
  document.getElementById("storage").innerHTML = "<span>storage</span> " + fmtAcft(cur.storage_acft);

  const chgMap = [
    ["vs yesterday", DATA.changes && DATA.changes.vs_1d],
    ["vs 7 days", DATA.changes && DATA.changes.vs_7d],
    ["vs 30 days", DATA.changes && DATA.changes.vs_30d],
    ["since midnight", DATA.changes && DATA.changes.since_midnight && {
      change_ft: DATA.changes.since_midnight.change_ft,
      then_time_label: "midnight CT (" + Number(DATA.changes.since_midnight.midnight_ft_msl).toFixed(2) + " ft)"
    }],
  ];
  const chgEl = document.getElementById("changes");
  chgMap.forEach(([label, c]) => {
    const d = document.createElement("div");
    d.className = "chg";
    const ch = fmtChg(c && c.change_ft);
    d.innerHTML = '<div class="k">' + label + '</div><div class="v ' + ch.cls + '">' + ch.text + '</div>' +
      (c && c.then_time_label ? '<div class="k">' + c.then_time_label + '</div>' : '') +
      (c && c.then_elevation_ft_msl != null ? '<div class="k">from ' + Number(c.then_elevation_ft_msl).toFixed(2) + ' ft</div>' : '');
    chgEl.appendChild(d);
  });
  document.getElementById("change-note").textContent = (DATA.changes && DATA.changes.method) || "";

  const note = DATA.lcra_note || DATA.forecast || {};
  const sourceUrl = note.source || (DATA.forecast && DATA.forecast.source) || "https://www.lcra.org/water/flood/";
  let noteHtml = "<h2>Latest from LCRA</h2>";
  if (note.ok === false && note.error && !note.situation_text && !note.travis_forecast && !note.mansfield_gates) {
    noteHtml += "<p>A current LCRA operations note could not be loaded from the flood operations page. Nothing is invented here.</p>";
    if (note.error) noteHtml += '<p class="asof">' + esc(note.error) + "</p>";
  } else {
    if (note.situation_level) noteHtml += '<p class="note-level">' + esc(note.situation_level) + "</p>";
    if (note.situation_text) noteHtml += '<p class="note-body">' + esc(note.situation_text) + "</p>";
    if (note.situation_as_of) noteHtml += '<p class="asof">' + esc(note.situation_as_of) + "</p>";
    if (note.travis_forecast) {
      noteHtml += "<p>" + esc(note.travis_forecast) + "</p>";
      if (note.travis_forecast_as_of) noteHtml += '<p class="asof">' + esc(note.travis_forecast_as_of) + "</p>";
    } else if (DATA.forecast && DATA.forecast.text) {
      noteHtml += "<p>" + esc(DATA.forecast.text) + "</p>";
    }
    if (note.mansfield_gates) {
      noteHtml += "<p>Mansfield Dam / Lake Travis: " + esc(note.mansfield_gates) + "</p>";
      if (note.mansfield_gates_as_of) noteHtml += '<p class="asof">' + esc(note.mansfield_gates_as_of) + "</p>";
    }
  }
  noteHtml += '<p class="asof"><a href="' + esc(sourceUrl) + '">Source: lcra.org/water/flood</a></p>';
  document.getElementById("forecast").innerHTML = noteHtml;

  document.getElementById("same-note").textContent = DATA.same_date_note || "";
  const sameT = document.querySelector("#same-date thead");
  const sameB = document.querySelector("#same-date tbody");
  sameT.innerHTML = "<tr><th>Year</th><th class='num'>Elevation</th><th class='num'>% full (TWDB)</th></tr>";
  (DATA.same_date || []).slice().reverse().forEach(r => {
    const tr = document.createElement("tr");
    if (r.is_this_year) tr.className = "this";
    tr.innerHTML = "<td>" + r.year + (r.is_this_year ? " (TWDB daily avg)" : "") + "</td>" +
      "<td class='num'>" + Number(r.elevation_ft_msl).toFixed(2) + " ft</td>" +
      "<td class='num'>" + (r.percent_full == null ? "—" : Number(r.percent_full).toFixed(1) + "%") + "</td>";
    sameB.appendChild(tr);
  });

  const clim = DATA.climatology;
  document.getElementById("clim-note").textContent =
    "Highest typical month: " + clim.highest_month + " (mean " + clim.highest_mean.toFixed(2) +
    " ft). Lowest: " + clim.lowest_month + " (mean " + clim.lowest_mean.toFixed(2) + " ft). " + clim.note;
  const mh = document.querySelector("#monthly thead");
  const mb = document.querySelector("#monthly tbody");
  mh.innerHTML = "<tr><th>Month</th><th class='num'>Mean</th><th class='num'>Median</th><th class='num'>10th</th><th class='num'>90th</th><th class='num'>2026</th></tr>";
  clim.monthly.forEach(m => {
    const y = clim.year_2026[m.month] || clim.year_2026[String(m.month)];
    const tr = document.createElement("tr");
    tr.innerHTML = "<td>" + m.name + "</td>" +
      "<td class='num'>" + m.mean.toFixed(2) + "</td>" +
      "<td class='num'>" + m.median.toFixed(2) + "</td>" +
      "<td class='num'>" + m.p10.toFixed(2) + "</td>" +
      "<td class='num'>" + m.p90.toFixed(2) + "</td>" +
      "<td class='num'>" + (y ? y.mean.toFixed(2) + (y.n < 28 ? "*" : "") : "—") + "</td>";
    mb.appendChild(tr);
  });

  document.getElementById("rises-note").textContent = DATA.rises_note || "";
  const list = document.getElementById("rise-list");
  (DATA.rises_2026 || []).forEach(ev => {
    const div = document.createElement("article");
    div.className = "rise";
    const p24 = ev.peak_24h;
    const src = (ev.sources || []).map(s => '<a href="'+s.url+'">'+s.name+'</a>').join("; ");
    div.innerHTML = "<h3>" + ev.title + "</h3><p>" + ev.lead + "</p>" +
      '<div class="stats">' +
      "<div>Start<br><b>" + ev.start_label + "</b><br>" + ev.start_ft.toFixed(2) + " ft</div>" +
      "<div>" + (ev.ongoing ? "Latest" : "End / crest") + "<br><b>" + ev.end_label + "</b><br>" + ev.end_ft.toFixed(2) + " ft</div>" +
      "<div>Rise<br><b>+" + ev.rise_ft.toFixed(2) + " ft</b><br>in " + ev.days.toFixed(2) + " days (" + ev.rate_ft_per_day.toFixed(2) + " ft/day)</div>" +
      (p24 ? "<div>Peak 24-hour rise<br><b>+" + p24.ft.toFixed(2) + " ft</b><br>" + p24.start_label + " (" + p24.start_ft.toFixed(2) + ") → " + p24.end_label + " (" + p24.end_ft.toFixed(2) + ")</div>" : "") +
      "</div><p>" + ev.attribution + "</p><p class='legend-note'>Source of levels: " + ev.series_source + ". " + src + "</p>";
    list.appendChild(div);
  });

  document.getElementById("hist-note").textContent = DATA.historical_note || "";
  const hh = document.querySelector("#hist thead");
  const hb = document.querySelector("#hist tbody");
  hh.innerHTML = "<tr><th>Event</th><th class='num'>Start</th><th class='num'>End</th><th class='num'>Rise</th><th class='num'>Peak 24h (daily)</th></tr>";
  const july = (DATA.rises_2026 || []).find(e => e.id === "july");
  const histRows = [];
  if (july) {
    histRows.push({
      title: "July 16–19, 2026 (this year)",
      start: july.start_ft.toFixed(2) + " ft",
      end: july.end_ft.toFixed(2) + " ft",
      rise: "+" + july.rise_ft.toFixed(2) + " ft in " + july.days.toFixed(2) + " days",
      peak: july.peak_24h ? "+" + july.peak_24h.ft.toFixed(2) + " ft (5-min)" : "—",
      note: "LCRA 5-minute series. Smaller than the July 2025, October 2018, and December 1991 rises, but it did enter the flood pool."
    });
  }
  (DATA.historical_rises || []).forEach(h => {
    histRows.push({
      title: h.title,
      start: h.start_ft.toFixed(2) + " ft (" + h.start + ")",
      end: h.end_ft.toFixed(2) + " ft (" + h.end + ")",
      rise: "+" + h.rise_ft.toFixed(2) + " ft in " + h.days + " days",
      peak: "+" + h.peak_24h_ft.toFixed(2) + " ft on " + h.peak_24h_date,
      note: h.note
    });
  });
  histRows.forEach((r, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "this";
    tr.innerHTML = "<td><strong>" + r.title + "</strong><div class='legend-note'>" + r.note + "</div></td>" +
      "<td class='num'>" + r.start + "</td><td class='num'>" + r.end + "</td>" +
      "<td class='num'>" + r.rise + "</td><td class='num'>" + r.peak + "</td>";
    hb.appendChild(tr);
  });

  const th = DATA.thresholds || {};
  const tb = document.querySelector("#thresholds tbody");
  const rows = [
    ["Conservation / full pool (water supply)", th.full_pool_ft_msl, "LCRA / USACE"],
    ["700 ft reference (in the flood pool, not official flood stage)", 700, "Requested reference line"],
    ["Official record high (daily 8 a.m.)", th.record_high_ft_msl, "Dec 25, 1991 · LCRA"],
    ["Overflow spillway / top of flood pool", th.spillway_crest_ft_msl, "LCRA / USACE"],
    ["Official record low (daily 8 a.m.)", th.record_low_ft_msl, "Aug 14, 1951 · LCRA"],
  ];
  rows.forEach(([n, v, s]) => {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td>" + n + "</td><td class='num'>" + (v != null ? Number(v).toFixed(2) + " ft" : "—") + "</td><td>" + s + "</td>";
    tb.appendChild(tr);
  });
  document.getElementById("fs-note").textContent = DATA.flood_stage_note || "";

  const src = document.getElementById("sources");
  (DATA.sources || []).forEach(s => {
    const li = document.createElement("li");
    li.innerHTML = '<a href="'+s.url+'">'+s.name+'</a>';
    src.appendChild(li);
  });
  const cav = document.getElementById("caveats");
  (DATA.caveats || []).forEach(t => {
    const li = document.createElement("li");
    li.textContent = t;
    cav.appendChild(li);
  });

  // ---- charts ----
  const doyMap = {};
  (clim.doy || []).forEach(p => { doyMap[p.md] = p; });
  function mdFromISO(iso) {
    const d = iso.slice(5, 10);
    return d === "02-29" ? "02-28" : d;
  }
  function climForSeries(pts) {
    const mean = [], p10 = [], p90 = [];
    pts.forEach(p => {
      const c = doyMap[mdFromISO(p.d)];
      mean.push(c && c.mean != null ? c.mean : null);
      p10.push(c && c.p10 != null ? c.p10 : null);
      p90.push(c && c.p90 != null ? c.p90 : null);
    });
    return { mean, p10, p90 };
  }

  const refs = [
    { y: 681, label: "Full pool 681", color: "#8a5800", dash: [6,4] },
    { y: 700, label: "700 ft reference", color: "#9a3412", dash: [2,4] },
    { y: 710.44, label: "Record high 710.44", color: "#7c3aed", dash: [8,4] },
    { y: 714, label: "Spillway 714", color: "#b42318", dash: [10,4] },
    { y: 614.18, label: "Record low 614.18", color: "#57534e", dash: [4,4] },
  ];

  let trendChart;
  function showRange(key) {
    const pts = DATA.series[key] || [];
    const labels = pts.map(p => p.d);
    const elev = pts.map(p => p.e);
    const useClim = key === "30d" || key === "90d" || key === "1y";
    const cl = useClim ? climForSeries(pts) : null;
    const ymin0 = Math.min(...elev);
    const ymax0 = Math.max(...elev);
    let pad = Math.max(1.5, (ymax0 - ymin0) * 0.12);
    let ymin = ymin0 - pad, ymax = ymax0 + pad;
    // If full pool is nearby, include it.
    if (681 >= ymin - 8 && 681 <= ymax + 8) {
      ymin = Math.min(ymin, 681 - 1);
      ymax = Math.max(ymax, 681 + 1);
    }
    const datasets = [];
    if (cl) {
      datasets.push({
        label: "90th percentile",
        data: cl.p90, borderWidth: 0, pointRadius: 0, fill: "+1",
        backgroundColor: "rgba(11,95,138,.16)", order: 3
      });
      datasets.push({
        label: "10th percentile",
        data: cl.p10, borderWidth: 0, pointRadius: 0, fill: false, order: 3
      });
      datasets.push({
        label: "Typical (mean)",
        data: cl.mean, borderColor: "#0e7490", borderWidth: 1.5,
        borderDash: [5,4], pointRadius: 0, fill: false, order: 2
      });
    }
    datasets.push({
      label: "Lake level",
      data: elev, borderColor: "#0b5f8a", backgroundColor: "#0b5f8a",
      borderWidth: 2.25, pointRadius: 0, tension: 0.15, fill: false, order: 1
    });
    refs.forEach(r => {
      if (r.y < ymin || r.y > ymax) return;
      datasets.push({
        label: r.label,
        data: labels.map(() => r.y),
        borderColor: r.color, borderWidth: 1, borderDash: r.dash,
        pointRadius: 0, fill: false, order: 4
      });
    });

    const cfg = {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => items[0] ? items[0].label : "",
              label: (ctx) => ctx.dataset.label + ": " + (ctx.parsed.y != null ? ctx.parsed.y.toFixed(2) + " ft" : "—")
            }
          }
        },
        scales: {
          x: {
            ticks: {
              maxRotation: 0, autoSkip: true, maxTicksLimit: 7,
              callback: function(v) {
                const s = this.getLabelForValue(v);
                return s ? s.slice(0, 10) : "";
              }
            },
            grid: { display: false }
          },
          y: {
            min: Math.floor(ymin * 2) / 2,
            max: Math.ceil(ymax * 2) / 2,
            ticks: { callback: (v) => v.toFixed(0) },
            title: { display: true, text: "ft msl" }
          }
        }
      }
    };
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(document.getElementById("trend"), cfg);
  }

  document.querySelectorAll("#range-toggles button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#range-toggles button").forEach(b => b.setAttribute("aria-pressed", "false"));
      btn.setAttribute("aria-pressed", "true");
      showRange(btn.getAttribute("data-range"));
    });
  });
  showRange("1y");

  // Overlay chart
  const ov = DATA.overlay;
  const oLabels = ov.labels;
  const oSets = [];
  oSets.push({
    label: "90th percentile",
    data: oLabels.map(md => doyMap[md] && doyMap[md].p90),
    borderWidth: 0, pointRadius: 0, fill: "+1",
    backgroundColor: "rgba(11,95,138,.16)", order: 4
  });
  oSets.push({
    label: "10th percentile",
    data: oLabels.map(md => doyMap[md] && doyMap[md].p10),
    borderWidth: 0, pointRadius: 0, fill: false, order: 4
  });
  oSets.push({
    label: "Typical (mean)",
    data: oLabels.map(md => doyMap[md] && doyMap[md].mean),
    borderColor: "#0e7490", borderWidth: 1.5, borderDash: [5,4],
    pointRadius: 0, fill: false, order: 3
  });
  Object.keys(ov.prior_years).sort().forEach(y => {
    oSets.push({
      label: y, data: ov.prior_years[y],
      borderColor: "rgba(26,35,50,.18)", borderWidth: 1,
      pointRadius: 0, fill: false, tension: 0.1, order: 2
    });
  });
  oSets.push({
    label: ov.this_year_label,
    data: ov.this_year,
    borderColor: "#0b5f8a", borderWidth: 2.4,
    pointRadius: 0, fill: false, tension: 0.1, order: 1
  });
  new Chart(document.getElementById("overlay"), {
    type: "line",
    data: { labels: oLabels, datasets: oSets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (c) => c.dataset.label === ov.this_year_label || c.dataset.label === "Typical (mean)" || /^\d{4}$/.test(c.dataset.label),
          callbacks: {
            title: (items) => items[0] ? items[0].label : "",
            label: (ctx) => ctx.dataset.label + ": " + (ctx.parsed.y != null ? ctx.parsed.y.toFixed(2) + " ft" : "—")
          }
        }
      },
      scales: {
        x: {
          ticks: {
            maxRotation: 0, autoSkip: true, maxTicksLimit: 12,
            callback: function(v) {
              const s = this.getLabelForValue(v) || "";
              return s.endsWith("-01") ? s.slice(0, 2) : "";
            }
          },
          grid: { display: false }
        },
        y: { title: { display: true, text: "ft msl" }, ticks: { callback: (v) => v.toFixed(0) } }
      }
    }
  });
  }

  loadData().then(render).catch(function (err) {
    const el = document.getElementById("when");
    if (el) el.textContent = "Could not load lake data. " + (err && err.message ? err.message : err);
  });
})();
</script>
</body>
</html>
"""


def main():
    payload, clim, rises, hist = build_payload()
    SITE.mkdir(parents=True, exist_ok=True)
    data_url = os.environ.get("LAKE_TRAVIS_DATA_URL", "data.json")
    html = HTML.replace("@@DATA_URL@@", data_url)
    (SITE / "index.html").write_text(html, encoding="utf-8")
    (SITE / "data.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    size = (SITE / "index.html").stat().st_size
    data_size = (SITE / "data.json").stat().st_size
    print(f"Wrote {SITE / 'index.html'} ({size} bytes, {size/1024:.1f} KB) [shell; data is not inlined]")
    print(f"Wrote {SITE / 'data.json'} ({data_size} bytes, {data_size/1024:.1f} KB)")
    note = payload.get("lcra_note") or {}
    if note.get("ok"):
        print("LCRA note:", note.get("situation_level") or "", "|",
              (note.get("travis_forecast") or "")[:120], "|",
              note.get("mansfield_gates") or "")
    else:
        print("LCRA note not available:", note.get("error"))
    print("Climatology start:", clim["start"], "highest:", clim["highest_month"], clim["highest_mean"],
          "lowest:", clim["lowest_month"], clim["lowest_mean"])
    for ev in rises:
        p24 = ev.get("peak_24h") or {}
        print(f"  RISE {ev['id']}: {ev['start_label']} {ev['start_ft']} -> {ev['end_label']} {ev['end_ft']}  +{ev['rise_ft']} ft in {ev['days']}d @ {ev['rate_ft_per_day']} ft/d  peak24={p24.get('ft')}")
    for h in hist:
        print(f"  HIST {h['id']}: {h['start']} {h['start_ft']} -> {h['end']} {h['end_ft']}  +{h['rise_ft']} in {h['days']}d  peak24={h['peak_24h_ft']} on {h['peak_24h_date']}")
    if size > 1_900_000:
        raise SystemExit(f"index.html is {size} bytes; aired.sh limit is 2 MB")


if __name__ == "__main__":
    main()
