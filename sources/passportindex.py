"""Cross-check source: the passport-index dataset (imorte/passport-index-data).

Scraped from passportindex.org by its maintainer. We never publish these values
directly — they exist to confirm or dispute what Wikipedia says. Agreement
raises a cell's confidence; disagreement flags it for review.
"""

from __future__ import annotations

import csv
import io
import urllib.request

UA = {
    "User-Agent": "visa-matrix/1.0 (open dataset; github.com/xpressmike/visa-matrix)"
}
CSV_URL = (
    "https://raw.githubusercontent.com/imorte/passport-index-data/"
    "main/passport-index-matrix-iso2.csv"
)


def normalise(raw: str):
    raw = raw.strip()
    low = raw.lower()
    if raw.isdigit():
        return {"type": "visa-free", "days": int(raw)}
    if low == "visa free":
        return {"type": "visa-free", "days": None}
    if low == "visa on arrival":
        return {"type": "visa-on-arrival", "days": None}
    if low == "e-visa":
        return {"type": "e-visa", "days": None}
    if low in ("eta", "e-ta"):  # electronic travel authorisation (ESTA, eTA…)
        return {"type": "eta", "days": None}
    if low in ("visa required", "covid ban", "no admission"):
        return {"type": "visa-required", "days": None}
    if low == "-1":  # self
        return None
    return {"type": "unknown", "days": None, "raw": raw}


def collect_all() -> dict:
    """Every passport in the matrix: iso2 -> {destination iso2 -> cell}"""
    req = urllib.request.Request(CSV_URL, headers=UA)
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    out: dict = {}
    for row in rows[1:]:
        cells = {}
        for i, dest in enumerate(header[1:], start=1):
            cell = normalise(row[i])
            if cell:
                cells[dest] = cell
        out[row[0]] = cells
    return out


def collect(passports: list) -> dict:
    """Subset view kept for callers that only need a few passports."""
    return {p: c for p, c in collect_all().items() if p in passports}


if __name__ == "__main__":
    data = collect(["US", "GB"])
    print("US destinations:", len(data["US"]))
    print("US->JP:", data["US"].get("JP"))
    print("US->TR:", data["US"].get("TR"))
