"""
Batch driver: reads sites.txt, extracts each site with extract.py, and
writes out/summary.csv plus out/run_meta.json. Failures on one site do not
stop the run; they are logged to out/failures.log and the site is skipped.
"""

import csv
import json
import statistics
import time
import traceback
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from playwright.sync_api import sync_playwright

import extract

SITES_FILE = Path(__file__).parent / "sites.txt"
OUT_DIR = Path(__file__).parent / "out"
FAILURES_LOG = OUT_DIR / "failures.log"
SUMMARY_CSV = OUT_DIR / "summary.csv"
RUN_META_JSON = OUT_DIR / "run_meta.json"

PAUSE_BETWEEN_SITES_S = 2

SUMMARY_FIELDS = [
    "url",
    "visible_words",
    "hidden_words",
    "attr_words",
    "comment_words",
    "dynamic_words",
    "zero_width_chars",
    "bidi_chars",
    "hidden_share",
]


def read_sites(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def chromium_version() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        version = browser.version
        browser.close()
    return version


def summary_row(url: str, result: dict) -> dict:
    totals = result["t1"]["totals"]
    derived = result["derived"]
    return {
        "url": url,
        "visible_words": totals["visible_words"],
        "hidden_words": totals["hidden_words"],
        "attr_words": totals["attr_words"],
        "comment_words": totals["comment_words"],
        "dynamic_words": derived["dynamic_words"],
        "zero_width_chars": totals["zero_width_chars"],
        "bidi_chars": totals["bidi_chars"],
        "hidden_share": derived["hidden_share"],
    }


def print_stats(rows: list[dict]) -> None:
    shares = [r["hidden_share"] for r in rows]
    n = len(rows)
    if n == 0:
        print("No sites processed successfully.")
        return

    nonzero = sum(1 for s in shares if s > 0)
    dynamic = sum(1 for r in rows if r["dynamic_words"] > 0)

    print(f"Sites processed: {n}")
    print(f"Median hidden_share: {statistics.median(shares):.4f}")
    print(f"Mean hidden_share:   {statistics.mean(shares):.4f}")
    print(f"Sites with hidden_share > 0: {nonzero} ({100 * nonzero / n:.1f}%)")
    print(f"Sites with dynamic_words > 0: {dynamic}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sites = read_sites(SITES_FILE)

    start = datetime.now(timezone.utc)
    rows = []

    with FAILURES_LOG.open("w", encoding="utf-8") as failures_log:
        for i, url in enumerate(sites):
            try:
                result = extract.extract(url, out_dir=OUT_DIR)
                rows.append(summary_row(url, result))
            except Exception:
                failures_log.write(f"=== {url} ===\n")
                failures_log.write(traceback.format_exc())
                failures_log.write("\n")

            if i < len(sites) - 1:
                time.sleep(PAUSE_BETWEEN_SITES_S)

    end = datetime.now(timezone.utc)

    with SUMMARY_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    run_meta = {
        "playwright_version": pkg_version("playwright"),
        "chromium_version": chromium_version(),
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "viewport": extract.VIEWPORT,
        "config": {
            "goto_timeout_ms": extract.GOTO_TIMEOUT_MS,
            "networkidle_timeout_ms": extract.NETWORKIDLE_TIMEOUT_MS,
            "settle_sleep_s": extract.SETTLE_SLEEP_S,
            "scroll_step_px": extract.SCROLL_STEP_PX,
            "scroll_pause_s": extract.SCROLL_PAUSE_S,
            "pause_between_sites_s": PAUSE_BETWEEN_SITES_S,
        },
        "sites_total": len(sites),
        "sites_succeeded": len(rows),
        "sites_failed": len(sites) - len(rows),
    }
    RUN_META_JSON.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    print_stats(rows)


if __name__ == "__main__":
    main()
