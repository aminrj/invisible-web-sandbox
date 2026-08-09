"""
Playwright-driven extraction for a single page.

Loads a URL, runs detect.js at T0 (right after load) and T1 (after a
scroll pass and a settle period), diffs the two snapshots to flag
dynamic-execution findings, and writes both snapshots plus a full-page
screenshot to out/.
"""

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

DETECT_JS_PATH = Path(__file__).parent / "detect.js"
OUT_DIR = Path(__file__).parent / "out"

VIEWPORT = {"width": 1440, "height": 900}
GOTO_TIMEOUT_MS = 20_000
NETWORKIDLE_TIMEOUT_MS = 10_000
SETTLE_SLEEP_S = 10
SCROLL_STEP_PX = 500
SCROLL_PAUSE_S = 0.2

DYNAMIC_EXECUTION_REASON = "dynamic-execution"


def slugify(url: str) -> str:
    """hostname_pathhash8, so two pages on the same host never share a slug."""
    parsed = urlparse(url)
    base = Path(parsed.path).stem if parsed.scheme == "file" else (parsed.hostname or url)
    host_slug = re.sub(r"[^A-Za-z0-9_-]", "_", base)
    path_hash = hashlib.sha256((parsed.path or "/").encode("utf-8")).hexdigest()[:8]
    return f"{host_slug}_{path_hash}"


def load_detect_js() -> str:
    return DETECT_JS_PATH.read_text(encoding="utf-8")


def run_detect(page, detect_source: str) -> dict:
    return page.evaluate("() => {\n" + detect_source + "\nreturn detectInvisibleText();\n}")


def scroll_page(page) -> None:
    height = page.evaluate("document.documentElement.scrollHeight")
    y = 0
    while y < height:
        y += SCROLL_STEP_PX
        page.evaluate("window.scrollTo(0, %d)" % y)
        time.sleep(SCROLL_PAUSE_S)
    page.evaluate("window.scrollTo(0, 0)")


def diff_dynamic_execution(t0: dict, t1: dict) -> None:
    """Marks T1 findings absent from T0 (by dedup_key) as dynamic-execution."""
    t0_keys = {f["dedup_key"] for f in t0["findings"]}
    for finding in t1["findings"]:
        if finding["dedup_key"] not in t0_keys and DYNAMIC_EXECUTION_REASON not in finding["reasons"]:
            finding["reasons"].append(DYNAMIC_EXECUTION_REASON)


def _without_timestamp(snapshot: dict) -> dict:
    copy = json.loads(json.dumps(snapshot))
    copy.get("meta", {}).pop("timestamp", None)
    return copy


def assert_not_overwritten(slug: str, t0_path: Path, t1_path: Path, dynamic_words: int) -> None:
    """
    Sanity check against slug collisions: if we found dynamic-execution
    findings, the T1 file we just wrote must actually differ from T0 (beyond
    the timestamp). If it doesn't, the T0 (or T1) file on disk isn't really
    this run's snapshot - most likely another site's write landed on the
    same slug and clobbered it. A page with no delayed content legitimately
    produces T0 == T1 (minus timestamp); that's fine, since dynamic_words
    is 0 there and this check doesn't run.
    """
    if dynamic_words <= 0:
        return
    on_disk_t0 = _without_timestamp(json.loads(t0_path.read_text(encoding="utf-8")))
    on_disk_t1 = _without_timestamp(json.loads(t1_path.read_text(encoding="utf-8")))
    if on_disk_t0 == on_disk_t1:
        raise RuntimeError(
            f"{slug}: dynamic_words={dynamic_words} but {t0_path.name} and {t1_path.name} are "
            f"identical apart from meta.timestamp. This contradicts a real dynamic-execution "
            f"finding and almost always means a slug collision overwrote one snapshot with the "
            f"other's content."
        )


def compute_derived(t1: dict) -> dict:
    totals = t1["totals"]
    total = totals["visible_words"] + totals["hidden_words"] + totals["attr_words"]
    hidden_share = 0.0
    if total > 0:
        hidden_share = (totals["hidden_words"] + totals["attr_words"]) / total
    dynamic_words = sum(f["words"] for f in t1["findings"] if DYNAMIC_EXECUTION_REASON in f["reasons"])
    return {"total": total, "hidden_share": hidden_share, "dynamic_words": dynamic_words}


def extract(url: str, out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(url)
    detect_source = load_detect_js()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            pass

        t0_path = out_dir / f"{slug}.t0.json"
        t1_path = out_dir / f"{slug}.t1.json"

        t0 = run_detect(page, detect_source)
        t0_path.write_text(json.dumps(t0, indent=2), encoding="utf-8")

        scroll_page(page)
        time.sleep(SETTLE_SLEEP_S)

        t1 = run_detect(page, detect_source)
        diff_dynamic_execution(t0, t1)
        t1_path.write_text(json.dumps(t1, indent=2), encoding="utf-8")

        page.screenshot(path=str(out_dir / f"{slug}.png"), full_page=True)
        browser.close()

    derived = compute_derived(t1)
    assert_not_overwritten(slug, t0_path, t1_path, derived["dynamic_words"])

    return {"slug": slug, "t0": t0, "t1": t1, "derived": derived}


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python extract.py <url>")
        raise SystemExit(1)
    result = extract(sys.argv[1])
    print(json.dumps(result["derived"], indent=2))
