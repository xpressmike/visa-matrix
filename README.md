# visa-matrix

Machine-readable visa requirements for **every passport × every destination**
(~199 × ~198 corridors) — with provenance, check date and cross-source
verification on every cell.

Most visa datasets copy one aggregator and hope it is right. This one records
*where each value came from* and *whether an independent source agrees*:

```json
"VN": {
  "type": "visa-free",
  "days": 30,
  "source": "wikipedia",
  "checked": "2026-07-20",
  "confidence": "disputed",
  "dispute": { "wikipedia": "visa-free", "passport-index": "e-visa" }
}
```

When sources disagree, the cell says so instead of silently picking a winner.

## Files

| File | Shape |
|---|---|
| `data/visa-matrix.json` | canonical nested form with full provenance |
| `data/visa-matrix-iso2.csv` | matrix: one row per passport, one column per destination |
| `data/visa-matrix-tidy.csv` | long form: `passport,destination,type,days,confidence` |
| `data/countries-iso2.json`, `data/demonyms-iso2.json` | inputs: country/demonym → ISO2 maps used to join the sources |

Status vocabulary: `visa-free` · `freedom-of-movement` · `eta` (electronic
travel authorisation: ESTA, eTA, K-ETA…) · `visa-on-arrival` · `e-visa` ·
`visa-required` · `refused`.

Confidence: `high` (sources agree — an ETA is treated as compatible with a
bare "visa free" claim, since sources label that regime either way) ·
`medium` (single source) · `disputed` (sources disagree — both claims shown).

`days` is the stay granted on entry, so it is only present for regimes that
grant entry up front (`visa-free`, `eta`, `visa-on-arrival`, `e-visa`,
`freedom-of-movement`) and never exceeds a year — source prose mixes stay
length with visa validity and age limits, and those parse into nonsense.
A `days_source` field appears when the count came from the cross-check
source rather than the primary one.

## Passports covered

All of them. Passports with an English Wikipedia
["Visa requirements for X citizens"](https://en.wikipedia.org/wiki/Category:Visa_requirements_by_nationality)
page (~180) get Wikipedia as the primary source with passport-index as the
cross-check; the rest are covered by passport-index alone (and read
`"source": "passport-index", "confidence": "medium"` until a second source
confirms them).

## Sources

- **Primary:** English Wikipedia visa-requirements pages — community-maintained,
  cited per row (mostly Timatic and government pages), quick to reflect rule
  changes, and carrying machine-readable day counts.
- **Cross-check / fallback:** [imorte/passport-index-data](https://github.com/imorte/passport-index-data),
  scraped from [passportindex.org](https://www.passportindex.org).
- Country/demonym resolution: [mledoze/countries](https://github.com/mledoze/countries).

Rebuild locally: `python3 build.py` (stdlib only, no dependencies).

## What this is not

**Not legal advice and not an authority.** Visa rules change without notice
and depend on your specific circumstances. Always verify with the
destination's official government source before booking anything.

## License

[CC BY-SA 4.0](LICENSE) — inherited from Wikipedia, the primary source for
most corridors (the remainder come from the MIT-licensed passport-index data,
and CC BY-SA is the stricter of the two).
Attribution: link to this repository. Derived datasets must be shared alike.

Built and maintained for [nomadbriefing.com](https://nomadbriefing.com), where
every corridor page pairs these values with a link to the official government
source.
