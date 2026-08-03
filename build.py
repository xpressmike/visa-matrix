#!/usr/bin/env python3
"""Build the visa-matrix dataset: Wikipedia primary + passport-index cross-check.

Every cell records where its value came from and whether an independent source
agrees. The dataset never invents a number: when sources disagree the cell says
so out loud instead of silently picking one.

  confidence "high"      — both sources agree on the status type
  confidence "medium"    — only Wikipedia covers the cell (or the other source
                           has no comparable value)
  confidence "disputed"  — sources disagree; `dispute` shows both claims

Outputs (in data/):
  visa-matrix.json        canonical nested form with provenance
  visa-matrix-iso2.csv    matrix form  (passports x destinations)
  visa-matrix-tidy.csv    long form    (passport,destination,type,days,confidence)
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from sources import passportindex, wikipedia  # noqa: E402

DATA = pathlib.Path(__file__).parent / "data"

# Wikipedia country display names -> ISO2, for joining the two sources.
# Only rows that resolve here make it into the dataset.
COUNTRY_ISO2 = json.load(open(DATA / "countries-iso2.json"))

# Statuses comparable across sources. freedom-of-movement (Wikipedia-only
# nuance) is treated as agreeing with a bare "visa free" claim.
AGREE = {
    ("visa-free", "visa-free"),
    ("freedom-of-movement", "visa-free"),
    # An ETA (ESTA, eTA, K-ETA…) is a pre-authorisation for otherwise
    # visa-free travel; sources label the same regime either way.
    ("eta", "visa-free"),
    ("visa-free", "eta"),
    ("eta", "eta"),
}


def compatible(wiki_type: str, pi_type: str) -> bool:
    return wiki_type == pi_type or (wiki_type, pi_type) in AGREE


# `days` means "stay granted on entry", so it only exists for regimes that
# grant entry up front. Under visa-required / refused the length of stay comes
# from the visa itself, not the corridor.
STAY_REGIMES = {"visa-free", "freedom-of-movement", "eta", "visa-on-arrival", "e-visa"}
# Source prose mixes stay length with visa validity and age limits ("males
# aged 18-45 require a visa", "10-year multiple entry"), which parse into
# absurd day counts. The longest real visa-free stay we know of is Georgia's
# 365 days, so anything past a year is noise, not data.
MAX_PLAUSIBLE_STAY = 366


def sanitise_days(kind: str, days):
    if days is None or kind not in STAY_REGIMES:
        return None
    if days <= 0 or days > MAX_PLAUSIBLE_STAY:
        return None
    return days


def build():
    wiki = wikipedia.collect()
    pindex = passportindex.collect_all()
    # Full index: every passport either source knows about.
    passports = sorted(set(pindex) | set(wiki))
    today = dt.date.today().isoformat()

    matrix: dict = {}
    disputes = 0
    for nat in passports:
        cells = {}
        # Wikipedia rows (keyed by country display name) -> iso2.
        w_cells = {}
        for country_name, w in wiki.get(nat, {}).items():
            iso2 = COUNTRY_ISO2.get(country_name)
            if iso2 and iso2 != nat:
                w_cells[iso2] = w
        dests = set(w_cells) | set(pindex.get(nat, {}))
        for iso2 in dests:
            if iso2 == nat:
                continue
            w = w_cells.get(iso2)
            p = pindex.get(nat, {}).get(iso2)
            if p and p["type"] == "unknown":
                p = None
            if w:  # Wikipedia is primary where it covers the corridor
                cell = {
                    "type": w["type"],
                    "days": sanitise_days(w["type"], w["days"]),
                    "source": "wikipedia",
                    "checked": today,
                }
                if p:
                    if compatible(w["type"], p["type"]):
                        cell["confidence"] = "high"
                        # passport-index sometimes has the day count Wikipedia lacks
                        filled = sanitise_days(w["type"], p.get("days"))
                        if cell["days"] is None and filled:
                            cell["days"] = filled
                            cell["days_source"] = "passport-index"
                    else:
                        cell["confidence"] = "disputed"
                        cell["dispute"] = {
                            "wikipedia": w["type"],
                            "passport-index": p["type"],
                        }
                        disputes += 1
                else:
                    cell["confidence"] = "medium"
            elif p:  # passport-index only — full coverage, single-source
                cell = {
                    "type": p["type"],
                    "days": sanitise_days(p["type"], p.get("days")),
                    "source": "passport-index",
                    "checked": today,
                    "confidence": "medium",
                }
            else:
                continue
            cells[iso2] = cell
        if cells:
            matrix[nat] = dict(sorted(cells.items()))

    # Manual corrections — applied AFTER the scrape so a confirmed policy change
    # the upstream sources still lag (e.g. a reversion Wikipedia hasn't caught)
    # survives every weekly rebuild instead of being reverted. Each override
    # wins over both sources and is stamped source=manual-correction with a note.
    ov_path = DATA / "overrides.json"
    if ov_path.exists():
        overrides = json.load(open(ov_path)).get("overrides", [])
        applied = 0
        for o in overrides:
            nat, dest = o.get("nat"), o.get("dest")
            if not nat or not dest or nat not in matrix:
                continue
            matrix[nat][dest] = {
                "type": o["type"],
                "days": o.get("days"),
                "source": "manual-correction",
                "checked": today,
                "confidence": "high",
                "note": o.get("note", ""),
            }
            matrix[nat] = dict(sorted(matrix[nat].items()))
            applied += 1
        print(f"overrides applied: {applied}/{len(overrides)}")

    dataset = {
        "meta": {
            "name": "visa-matrix",
            "generated": today,
            "passports": passports,
            "passport_count": len(passports),
            "primary_source": (
                "English Wikipedia 'Visa requirements for X citizens' pages "
                "(per-corridor citations, day counts); corridors those pages "
                "don't cover fall back to passport-index"
            ),
            "cross_check": "imorte/passport-index-data (scraped from passportindex.org)",
            "license": "CC BY-SA 4.0 (inherited from Wikipedia)",
            "disclaimer": (
                "General information, not legal advice. Rules change; always "
                "verify with the destination's official government source "
                "before booking."
            ),
        },
        "matrix": matrix,
    }

    DATA.mkdir(exist_ok=True)
    with open(DATA / "visa-matrix.json", "w") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=1)

    # Matrix CSV: one row per passport, one column per destination.
    dests = sorted({d for cells in matrix.values() for d in cells})
    with open(DATA / "visa-matrix-iso2.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Passport"] + dests)
        for nat in passports:
            row = [nat]
            for d in dests:
                c = matrix.get(nat, {}).get(d)
                if not c:
                    row.append("")
                elif c["type"] == "visa-free" and c["days"]:
                    row.append(str(c["days"]))
                else:
                    row.append(c["type"])
            w.writerow(row)

    # Tidy CSV: one row per corridor.
    with open(DATA / "visa-matrix-tidy.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["passport", "destination", "type", "days", "confidence"])
        for nat in passports:
            for d, c in matrix.get(nat, {}).items():
                w.writerow([nat, d, c["type"], c["days"] or "", c["confidence"]])

    total = sum(len(c) for c in matrix.values())
    print(f"passports: {len(passports)}  corridors: {total}  disputed: {disputes}")
    return dataset


if __name__ == "__main__":
    build()
