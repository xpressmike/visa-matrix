"""Wikipedia source: parse "Visa requirements for X citizens" pages.

Primary source of the dataset. Wikipedia's visa tables are community-maintained,
usually cite Timatic or official government pages per row, and carry a
machine-readable day count in data-sort-value attributes. Licensed CC BY-SA 4.0,
which is why this dataset is CC BY-SA too.
"""

from __future__ import annotations

import json
import pathlib
import re
import urllib.error
import time
import urllib.parse
import urllib.request

UA = {
    "User-Agent": "visa-matrix/1.0 (open dataset; github.com/xpressmike/visa-matrix)"
}

DATA = pathlib.Path(__file__).parent.parent / "data"

# Titles that are about documents/groups, not a country's ordinary passport.
SKIP_TITLES = re.compile(
    r"crew members|non-citizens|refugees|stateless|diplomatic|official passport"
    r"|British Nationals? \(Overseas\)|British Overseas|travel document|holders of",
    re.I,
)


def discover_pages():
    """All 'Visa requirements for X citizens' pages -> {iso2: title}.

    The passport country is resolved from the title via two open maps:
    demonyms (mledoze/countries: 'German' -> DE) and plain country names
    ('United States' -> US). Unresolvable titles (unrecognised states,
    special travel documents) are skipped silently.
    """
    demonyms = json.load(open(DATA / "demonyms-iso2.json"))
    countries = json.load(open(DATA / "countries-iso2.json"))
    url = (
        "https://en.wikipedia.org/w/api.php?action=query&list=categorymembers"
        "&cmtitle=Category:Visa%20requirements%20by%20nationality"
        "&cmlimit=500&format=json&formatversion=2"
    )
    req = urllib.request.Request(url, headers=UA)
    r = json.load(urllib.request.urlopen(req, timeout=60))
    pages = {}
    for m in r["query"]["categorymembers"]:
        title = m["title"]
        if not title.startswith("Visa requirements for") or SKIP_TITLES.search(title):
            continue
        subject = title.removeprefix("Visa requirements for ").removesuffix(" citizens").strip()
        subject = subject.removeprefix("citizens of ").strip()
        iso2 = demonyms.get(subject) or countries.get(subject)
        if iso2 and iso2 not in pages:
            pages[iso2] = title
    return pages

STATUS_PATTERNS = [
    (r"freedom of movement", "freedom-of-movement"),
    (r"electronic travel authoris?z?ation|\besta\b|\bk?-?eta\b", "eta"),
    (r"visa\s*not\s*required|visa[- ]free", "visa-free"),
    (r"visa\s*on\s*arrival", "visa-on-arrival"),
    (r"\be[-\s]?visa\b", "e-visa"),
    (r"visa\s*required", "visa-required"),
    (r"admission refused|travel banned|entry banned", "refused"),
]


def _get(url: str):
    """One API call with backoff on throttling and transient network errors."""
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


# The API returns the content of up to 50 pages per call. Fetching one page
# per request instead means ~190 requests per build, which trips Wikipedia's
# throttling and turns a 5-minute crawl into hours of backoff.
BATCH = 25


def fetch_many(titles: list) -> dict:
    """{title: wikitext} for a list of page titles, batched."""
    out = {}
    for i in range(0, len(titles), BATCH):
        chunk = titles[i : i + BATCH]
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&prop=revisions"
            "&rvprop=content&rvslots=main&format=json&formatversion=2&titles="
            + urllib.parse.quote("|".join(chunk))
        )
        data = _get(url)
        for page in data.get("query", {}).get("pages", []):
            revs = page.get("revisions") or []
            if not revs:
                continue
            content = revs[0].get("slots", {}).get("main", {}).get("content")
            if content:
                out[page["title"]] = content
        time.sleep(0.5)
    return out


def strip_markup(s: str) -> str:
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"</?[a-z][^>]*>", "", s)
    return s.strip()


def classify(cell: str):
    txt = strip_markup(
        re.sub(r"\{\{(?:yes|no|partial|free|maybe|okay)2?\|?", "", cell)
    ).lower()
    for pattern, kind in STATUS_PATTERNS:
        if re.search(pattern, txt):
            return kind
    return None


def parse_page(wt: str) -> dict:
    """wikitext of one page -> {destination country name: {type, days}}"""
    out: dict = {}
    row_re = re.compile(
        r"\{\{flag(?:icon|country)?\|([^}|]+)[^}]*\}\}(.*?)(?=\n\|-|\n\|\})", re.S
    )
    for m in row_re.finditer(wt):
        country = m.group(1).strip()
        rest = m.group(2)
        status = None
        for cell in rest.split("\n|")[:3]:
            status = classify(cell)
            if status:
                break
        if not status:
            continue
        # Day counts live in the duration cell. Some pages (e.g. the Canadian
        # one) also put a data-sort-value on the STATUS cell purely for column
        # sorting (0 = visa-free, 1 = VOA…), so a page-wide "first
        # data-sort-value" grab reads that flag as a day count. Only trust a
        # sort value whose own cell actually talks about days/months.
        days = None
        for cell in rest.split("\n|"):
            plain = strip_markup(cell)
            if not re.search(r"\b(day|month|year)s?\b", plain, re.I):
                continue
            dm = re.search(r'data-sort-value="(\d+)"', cell)
            if dm:
                days = int(dm.group(1))
                break
            dm = re.search(r"(\d+)\s*days?", plain, re.I)
            if dm:
                days = int(dm.group(1))
                break
            mm = re.search(r"(\d+)\s*months?", plain, re.I)
            if mm:
                days = int(mm.group(1)) * 30
                break
            ym = re.search(r"(\d+)\s*years?", plain, re.I)
            if ym:
                days = int(ym.group(1)) * 365
                break
        out[country] = {"type": status, "days": days}
    return out


def collect() -> dict:
    """passport iso2 -> {destination name -> cell} for every discoverable page."""
    pages = discover_pages()
    texts = fetch_many(sorted(pages.values()))
    result = {}
    missing = []
    for iso2, title in sorted(pages.items()):
        wt = texts.get(title)
        if not wt:
            missing.append(iso2)
            continue
        rows = parse_page(wt)
        if rows:
            result[iso2] = rows
    print(f"  wikipedia: {len(result)}/{len(pages)} pages parsed"
          + (f", no content for {missing}" if missing else ""))
    return result


if __name__ == "__main__":
    pages = discover_pages()
    print("discovered passports:", len(pages))
    us = parse_page(fetch_many([pages["US"]])[pages["US"]])
    print("US destinations:", len(us), "| Japan:", us.get("Japan"))
