"""
Ground-truth test: detect.js must classify fixtures/marker.html exactly as
designed before the detector is trusted against real sites. Every marker's
expected outcome is spelled out in the fixture-building instructions this
project was built from; see fixtures/marker.html for what each marker is.
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from extract import extract  # noqa: E402

FIXTURE = Path(__file__).parent.parent / "fixtures" / "marker.html"
OUT_DIR = Path(__file__).parent / "_out"

# marker string -> primary reason it must carry as a *text* finding
TEXT_MARKERS = {
    "MARKER-ALPHA-7": "visual-concealment/css-rendering-suppression",
    "MARKER-CHARLIE-9": "visual-concealment/off-screen-positioning",
    "MARKER-DELTA-5": "visual-concealment/transparency",
    "MARKER-GOLF-2": "visual-concealment/camouflage",
    "MARKER-INDIA-8": "visual-concealment/zero-sizing",
    "MARKER-JULIET-0": "visual-concealment/css-rendering-suppression",
}

# marker string -> attribute name it must be carried in
ATTR_MARKERS = {
    "MARKER-BRAVO-3": "alt",
    "MARKER-FOXTROT-4": "aria-label",
    "MARKER-HOTEL-6": "data-note",
}

VISIBLE_COPY_WORDS = 40
ZERO_WIDTH_PARAGRAPH_WORDS = 14  # "This carrying pouch ... hassle."


@pytest.fixture(scope="module")
def snapshots():
    url = FIXTURE.resolve().as_uri()
    result = extract(url, out_dir=OUT_DIR)
    yield result
    shutil.rmtree(OUT_DIR, ignore_errors=True)


def find_text_finding(snapshot, marker):
    matches = [f for f in snapshot["findings"] if f["kind"] == "text" and marker in f["text"]]
    assert len(matches) == 1, f"expected exactly one text finding for {marker}, got {len(matches)}"
    return matches[0]


def find_attr_finding(snapshot, marker):
    matches = [f for f in snapshot["findings"] if f["kind"] == "attr" and marker in f["text"]]
    assert len(matches) == 1, f"expected exactly one attr finding for {marker}, got {len(matches)}"
    return matches[0]


def test_text_markers_have_correct_primary_reason(snapshots):
    t1 = snapshots["t1"]
    for marker, expected_primary in TEXT_MARKERS.items():
        finding = find_text_finding(t1, marker)
        assert finding["primary"] == expected_primary, marker


def test_attr_markers_have_correct_attribute(snapshots):
    t1 = snapshots["t1"]
    for marker, expected_attr in ATTR_MARKERS.items():
        finding = find_attr_finding(t1, marker)
        assert finding["attr"] == expected_attr, marker


def test_comment_marker_is_not_a_finding(snapshots):
    t1 = snapshots["t1"]
    for f in t1["findings"]:
        assert "MARKER-ECHO-1" not in f["text"]
    assert t1["totals"]["comment_words"] == 3


def test_juliet_is_dynamic_and_absent_from_t0(snapshots):
    t0, t1 = snapshots["t0"], snapshots["t1"]
    assert not any("MARKER-JULIET-0" in f["text"] for f in t0["findings"])
    finding = find_text_finding(t1, "MARKER-JULIET-0")
    assert "dynamic-execution" in finding["reasons"]


def test_zero_width_char_count(snapshots):
    t1 = snapshots["t1"]
    assert t1["totals"]["zero_width_chars"] == 1


def test_visible_word_total(snapshots):
    t1 = snapshots["t1"]
    assert t1["totals"]["visible_words"] == VISIBLE_COPY_WORDS + ZERO_WIDTH_PARAGRAPH_WORDS
