# evidence/

`fixture.html` (20:44) and `fixture-v1-evidence.html` (20:48) are byte-identical leftovers found at the repo root before this project's real build started. They predate `fixtures/marker.html` and were not produced by the `detect.js`/`extract.py`/`run.py` pipeline in this repo.

Why they're evidence of a failed first attempt, not just clutter: both reference `style.css` and `script.js` that don't exist anywhere in the repo, and neither implements the marker fixture spec — missing the alt/aria-label/data-attribute markers, the off-screen/zero-size/camouflage markers, the dynamic-execution marker, and the zero-width-character marker, with no control over exact visible-word counts. Kept as-is (unmodified, original timestamps) rather than deleted, for provenance.
