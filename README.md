# invisible-web

A ground-truth detector for text that is present in a web page's DOM but not
visible to a human reader. Built as a measurement instrument for a research
study into prompt-injection-style content hidden from sighted users but
reachable by agents that read the DOM/accessibility tree rather than a
rendered screen — so **correctness and reproducibility take priority over
speed or cleverness** throughout this codebase.

Findings are classified against Palo Alto Unit 42's published taxonomy of
prompt-delivery methods, so results here are directly comparable to their
telemetry.

## Taxonomy

| Reason | What it catches |
|---|---|
| `visual-concealment/css-rendering-suppression` | `display:none`, `visibility:hidden`/`collapse`, or a hidden `<textarea>` |
| `visual-concealment/zero-sizing` | computed `font-size:0`, `line-height:0`, or a zero-width/zero-height box |
| `visual-concealment/off-screen-positioning` | box rendered entirely outside the document canvas, or `text-indent` below -999 |
| `visual-concealment/transparency` | computed `opacity:0` on the element or any ancestor |
| `visual-concealment/camouflage` | text color within a small perceptual distance of its effective background |
| `obfuscation/html-attribute-cloaking` | text carried in `alt`/`aria-*`/`title`/`placeholder`/`data-*` instead of node text |
| `obfuscation/clip` | `clip: rect(0,0,0,0)` or a `clip-path` that collapses to zero area |
| `dynamic-execution` | present at T1 (post-scroll, post-settle) but absent at T0 (page load) |
| `markup/html-comment` | text inside an HTML comment node |
| `unicode/invisible-characters` | zero-width/formatting characters (stacked onto an existing finding, see [Design notes](#design-notes)) |
| `unicode/bidi-override` | bidirectional override/isolate characters (same stacking rule) |

A finding can carry more than one reason — attackers stack techniques, and
the detector records all of them, not just the first match.

## How it works

```
sites.txt ──► run.py ──► extract.py ──► detect.js (runs inside the page)
                │                          │
                ▼                          ▼
     out/summary.csv, run_meta.json   out/<slug>.t0.json, .t1.json, .png
                                              │
                                              ▼
                                        analyze.py ──► out/distribution.csv
```

| File | Role |
|---|---|
| `detect.js` | Runs inside the page via `page.evaluate`. Walks visible text, shadow DOM, and same-origin iframes; classifies every non-visible text/attribute finding; tallies unicode markers and HTML comments separately. No imports, no dependencies. |
| `extract.py` | Playwright driver for one URL: loads the page, snapshots `detect.js` at T0 (page load) and T1 (after a scroll pass + 10s settle), diffs the two to flag `dynamic-execution`, and saves a full-page screenshot. |
| `run.py` | Batch driver over `sites.txt`. Isolates failures per-site (logged to `out/failures.log`, run continues), writes `out/summary.csv` and `out/run_meta.json`. |
| `analyze.py` | Rolls every `out/*.t1.json` up into `out/distribution.csv` — word count and share per taxonomy reason, across all sites processed so far. |
| `fixtures/marker.html` | A minimal fixture with one deliberately hidden marker per taxonomy category. |
| `tests/test_marker.py` | Pins down the expected classification of every fixture marker. **Must pass before running against real sites.** |
| `evidence/` | Preserved leftovers from an earlier, broken attempt at this fixture — kept for provenance, not code. See `evidence/README.md`. |

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
playwright install chromium
```

Tested against Playwright 1.60.0 / Chromium 148.0.7778.96 (exact versions
used in any given run are recorded in `out/run_meta.json`).

## Running the tests

Run this first, always — the fixture test is the detector's own ground
truth and must be green before any real-site number is trusted:

```bash
python3 -m pytest tests/test_marker.py -v
```

It loads `fixtures/marker.html` over `file://`, runs the full T0/T1 pipeline
against it, and asserts, among other things:

- markers hidden via CSS suppression, off-screen positioning, transparency,
  camouflage, and zero-sizing each appear as a text finding with the
  correct `primary` reason
- markers carried in `alt`/`aria-label`/`data-*` appear as attribute
  findings with the correct attribute name
- the HTML comment marker shows up only in `comment_words`, never as a
  finding
- a marker injected by `setTimeout` after 3s is absent from T0, present in
  T1, and carries `dynamic-execution`
- `zero_width_chars` is exactly 1
- `visible_words` equals 40 (the fixture's plain product copy) plus the
  word count of the paragraph containing the zero-width character

On the current fixture this pipeline reports `hidden_share ≈ 0.365`
(31 hidden+attribute words out of 85 total) — a useful sanity number if
you're modifying `detect.js` and want to confirm you haven't silently
changed what counts as hidden.

## Running against real sites

```bash
# one URL per line in sites.txt (lines starting with # are ignored)
echo "https://example.com" >> sites.txt

python3 run.py       # writes out/summary.csv, out/run_meta.json, out/*.t0.json, out/*.t1.json, out/*.png
python3 analyze.py   # writes out/distribution.csv
```

`run.py` pauses 2s between sites, never lets one site's exception stop the
run (see `out/failures.log`), and prints median/mean `hidden_share` plus
counts of sites with any hidden content or any dynamically-injected
content.

## Output shape

Each `out/<slug>.t{0,1}.json` is `detect.js`'s return value:

```jsonc
{
  "meta": {
    "url": "...", "final_url": "...", "title": "...", "timestamp": "...",
    "viewport": { "width": 1440, "height": 900 },
    "data_attr_min_tokens": 3, "data_attr_min_chars": 20,
    "camouflage_threshold": 12,
    "shadow_roots_traversed": 0, "iframes_same_origin": 0, "iframes_cross_origin_skipped": 0,
    "background_image_limitation": true
  },
  "totals": {
    "visible_words": 0, "hidden_words": 0, "attr_words": 0, "comment_words": 0,
    "zero_width_chars": 0, "bidi_chars": 0,
    "zero_width_text_nodes": 0, "bidi_text_nodes": 0
  },
  "findings": [
    {
      "kind": "text",                 // or "attr"
      "text": "...",                  // trimmed, capped at 300 chars
      "words": 3,
      "reasons": ["visual-concealment/css-rendering-suppression"],
      "primary": "visual-concealment/css-rendering-suppression",
      "attr": "data-note",            // attribute findings only
      "tag": "DIV",
      "rect": { "x": 0, "y": 0, "w": 0, "h": 0 },  // document coords, or null with no layout box
      "dedup_key": "lowercased, whitespace-collapsed text"
    }
  ]
}
```

`out/summary.csv` columns: `url, visible_words, hidden_words, attr_words,
comment_words, dynamic_words, zero_width_chars, bidi_chars, hidden_share`,
where `hidden_share = (hidden_words + attr_words) / (visible_words +
hidden_words + attr_words)`.

`out/distribution.csv` columns: `reason, words, pct_of_hidden_and_attr_words`
— percentages can sum past 100% when a finding stacks multiple techniques,
since each reason it carries is counted independently.

## Design notes

- **Unicode markers don't create findings on their own.** A zero-width
  space or bidi-override character inside otherwise-visible text is
  counted in `totals.zero_width_chars`/`bidi_chars` but does not, by
  itself, make that text a finding — it still counts toward
  `visible_words`. If the same text is *already* hidden for a structural
  reason (CSS, clip, etc.), the unicode reason is appended to that
  finding's `reasons` array. This mirrors how an attacker would actually
  use these characters: alone, inside visible copy, to break up a phrase
  for a text-matching filter; stacked, on top of already-hidden text, to
  add a second layer of evasion.
- **`clip-path` detection is a heuristic**, not a full CSS geometry
  evaluator. It catches the two common cloaking shapes — `inset()`
  collapsing past 100% on an axis, and a zero-area `polygon()` — and
  nothing else (`circle()`, `url()`, pixel-based `inset()`).
- **`background-image` is ignored** for camouflage detection (documented
  in `meta.background_image_limitation`). Effective background is resolved
  from `background-color` only, walking up the ancestor chain to the first
  non-transparent value, defaulting to white.
- **Comments and unicode counts are excluded from `hidden_share`.** Opera
  documents its agent (Neon) as reading the DOM tree and layout data, so
  HTML comments likely never reach it — including them would inflate the
  headline number.
- **iframe coordinates are projected into top-level document space** by
  walking the offset of each same-origin iframe; cross-origin iframes are
  detected and counted but not traversed (can't read their DOM).

## Evidence

`evidence/` documents a first attempt at this fixture that predates the
current, spec-compliant `fixtures/marker.html` — kept deliberately
unmodified, with `SHA256SUMS` for integrity, rather than deleted, because
it's evidence of what a plausible-looking-but-wrong fixture attempt looks
like (dangling asset references, missing markers, no control over exact
word counts). See `evidence/README.md` for the full breakdown.
