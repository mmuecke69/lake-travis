#!/usr/bin/env python3
"""Copy built site files to the repo root and say whether a commit is needed.

Used by the 15-minute GitHub Actions refresh. Exits 0 and prints
SHOULD_COMMIT=1 when index.html changed or when data.json changed in a
way that is not just a generated-at timestamp. Otherwise prints
SHOULD_COMMIT=0. Always copies the latest index.html so a later commit
can include it; data.json is copied only when the comparable payload
changed, so no-op refreshes do not bump timestamps in git.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"


def comparable(payload: object) -> object:
    if isinstance(payload, dict):
        skip = {"generated_at_ct", "fetched_at_ct", "fetched"}
        return {k: comparable(v) for k, v in payload.items() if k not in skip}
    if isinstance(payload, list):
        return [comparable(v) for v in payload]
    return payload


def load_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    html_src = SITE / "index.html"
    data_src = SITE / "data.json"
    if not html_src.exists() or not data_src.exists():
        print(f"Missing built site files in {SITE}", file=sys.stderr)
        return 1

    html_dst = ROOT / "index.html"
    data_dst = ROOT / "data.json"
    nojekyll = ROOT / ".nojekyll"
    if not nojekyll.exists():
        nojekyll.write_bytes(b"")

    new_data = load_json(data_src)
    old_data = load_json(data_dst)
    data_changed = comparable(new_data) != comparable(old_data)
    html_changed = (not html_dst.exists()) or html_dst.read_bytes() != html_src.read_bytes()

    shutil.copy2(html_src, html_dst)
    if data_changed or not data_dst.exists():
        shutil.copy2(data_src, data_dst)

    readings_src = ROOT / "readings.csv"
    readings_changed = False
    # update.py may have upserted a new daily row; commit that history too.
    try:
        import subprocess
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "readings.csv"],
            cwd=ROOT, check=False, text=True, capture_output=True,
        )
        readings_changed = bool((status.stdout or "").strip()) and readings_src.exists()
    except Exception:
        readings_changed = False

    should = data_changed or html_changed or readings_changed
    print(f"DATA_CHANGED={int(data_changed)}")
    print(f"HTML_CHANGED={int(html_changed)}")
    print(f"READINGS_CHANGED={int(readings_changed)}")
    print(f"SHOULD_COMMIT={int(should)}")
    if new_data and isinstance(new_data, dict):
        cur = new_data.get("current") or {}
        print(f"ELEVATION={cur.get('elevation_ft_msl')}")
        print(f"TIME_LABEL={cur.get('time_label')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
