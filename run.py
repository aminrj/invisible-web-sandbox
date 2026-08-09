"""
Batch driver: reads sites.txt, extracts each site with extract.py, and
writes out/summary.csv plus out/run_meta.json. Failures on one site do not
stop the run; they are logged to out/failures.log and the site is skipped.

Progress goes to stderr, one line per site, flushed immediately - a run
over sites.txt can take tens of minutes and this repo was silent for all of
it otherwise. The final summary (unchanged) still goes to stdout.
"""

import argparse
import csv
import json
import statistics
import sys
import time
import traceback
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import extract

SITES_FILE = Path(__file__).parent / "sites.txt"
OUT_DIR = Path(__file__).parent / "out"
FAILURES_LOG = OUT_DIR / "failures.log"
SUMMARY_CSV = OUT_DIR / "summary.csv"
RUN_META_JSON = OUT_DIR / "run_meta.json"

PAUSE_BETWEEN_SITES_S = 2
HOST_COLUMN_WIDTH = 28

# Below this, visible_words is too small to trust hidden_share (seen: a few
# sites return visible_words == 0, forcing hidden_share to a meaningless
# 1.000). This is a validity guard, not a fix - the row is kept and marked
# invalid, not dropped, and why visible_words came back low is not
# investigated here.
MIN_VALID_VISIBLE_WORDS = 50

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
    "invalid",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip URLs whose out/<slug>.t1.json already exists; their summary "
        "row is loaded from disk so the aggregate output still covers them",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="process only the first N URLs not already skipped (for smoke tests)",
    )
    return parser.parse_args()


def read_sites(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def hostname_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname:
        return parsed.hostname
    if parsed.scheme == "file":
        return Path(parsed.path).name
    return url


def format_elapsed(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def chromium_version() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        version = browser.version
        browser.close()
    return version


def summary_row(url: str, t1: dict, derived: dict) -> dict:
    totals = t1["totals"]
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
        "invalid": totals["visible_words"] < MIN_VALID_VISIBLE_WORDS,
    }


def load_existing_row(url: str, slug: str) -> dict:
    t1 = json.loads((OUT_DIR / f"{slug}.t1.json").read_text(encoding="utf-8"))
    derived = extract.compute_derived(t1)
    return summary_row(url, t1, derived)


def print_stats(rows: list[dict], attempted: int, elapsed_s: float) -> None:
    succeeded = len(rows)
    valid_rows = [r for r in rows if not r["invalid"]]
    invalid_rows = [r for r in rows if r["invalid"]]

    print(f"Total elapsed: {format_elapsed(elapsed_s)}")
    print(f"Sites attempted this run: {attempted}")
    print(f"Sites succeeded (in combined output): {succeeded}")
    print(f"  valid (visible_words >= {MIN_VALID_VISIBLE_WORDS}): {len(valid_rows)}")
    print(f"  invalid (visible_words < {MIN_VALID_VISIBLE_WORDS}, excluded below): {len(invalid_rows)}")
    if invalid_rows:
        excluded_hosts = ", ".join(hostname_of(r["url"]) for r in invalid_rows)
        print(f"  excluded: {excluded_hosts}")

    if not valid_rows:
        print("No valid sites to summarize.")
        return

    shares = [r["hidden_share"] for r in valid_rows]
    nonzero = sum(1 for s in shares if s > 0)
    dynamic = sum(1 for r in valid_rows if r["dynamic_words"] > 0)

    print("Median/mean/counts below are computed over VALID sites only, not all succeeded and not all attempted.")
    print(f"Median hidden_share: {statistics.median(shares):.4f}")
    print(f"Mean hidden_share:   {statistics.mean(shares):.4f}")
    print(f"Sites with hidden_share > 0: {nonzero} ({100 * nonzero / len(valid_rows):.1f}%)")
    print(f"Sites with dynamic_words > 0: {dynamic}")


def main() -> None:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sites = read_sites(SITES_FILE)
    wall_start = datetime.now(timezone.utc)

    rows: list[dict] = []
    to_process: list[tuple[str, str]] = []  # (url, slug)
    skipped = 0

    for url in sites:
        slug = extract.slugify(url)
        already_done = args.resume and (OUT_DIR / f"{slug}.t1.json").exists()
        if already_done:
            print(f"[skip] {hostname_of(url)}", file=sys.stderr, flush=True)
            rows.append(load_existing_row(url, slug))
            skipped += 1
        else:
            to_process.append((url, slug))

    if args.resume:
        print(f"Resume: {skipped} already-completed site(s) skipped, loaded from disk", file=sys.stderr)

    if args.limit is not None:
        to_process = to_process[: args.limit]

    total = len(to_process)
    index_width = len(str(total)) if total > 0 else 1
    run_start = time.monotonic()
    failures_so_far = 0

    log_mode = "a" if args.resume else "w"
    with FAILURES_LOG.open(log_mode, encoding="utf-8") as failures_log:
        for i, (url, slug) in enumerate(to_process, start=1):
            elapsed = format_elapsed(time.monotonic() - run_start)
            # ljust only pads short hosts; the explicit "  " guarantees a gap
            # even when a host overflows the column (e.g. very long names).
            host = hostname_of(url).ljust(HOST_COLUMN_WIDTH) + "  "
            prefix = f"[{i:>{index_width}}/{total}] {elapsed}  {host}"

            try:
                result = extract.extract(url, out_dir=OUT_DIR)
                row = summary_row(url, result["t1"], result["derived"])
                rows.append(row)
                print(
                    f"{prefix}hidden_share {row['hidden_share']:.3f}  ({failures_so_far} failed)",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as e:
                failures_so_far += 1
                failures_log.write(f"=== {url} ===\n")
                failures_log.write(traceback.format_exc())
                failures_log.write("\n")
                failures_log.flush()
                first_line = str(e).splitlines()[0] if str(e) else ""
                print(
                    f"{prefix}FAILED {type(e).__name__}: {first_line}  ({failures_so_far} failed)",
                    file=sys.stderr,
                    flush=True,
                )

            if i < total:
                time.sleep(PAUSE_BETWEEN_SITES_S)

    total_elapsed_s = time.monotonic() - run_start

    with SUMMARY_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    run_meta = {
        "playwright_version": pkg_version("playwright"),
        "chromium_version": chromium_version(),
        "start_time": wall_start.isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "viewport": extract.VIEWPORT,
        "config": {
            "goto_timeout_ms": extract.GOTO_TIMEOUT_MS,
            "networkidle_timeout_ms": extract.NETWORKIDLE_TIMEOUT_MS,
            "settle_sleep_s": extract.SETTLE_SLEEP_S,
            "scroll_step_px": extract.SCROLL_STEP_PX,
            "scroll_pause_s": extract.SCROLL_PAUSE_S,
            "pause_between_sites_s": PAUSE_BETWEEN_SITES_S,
            "min_valid_visible_words": MIN_VALID_VISIBLE_WORDS,
        },
        "resume": args.resume,
        "limit": args.limit,
        "sites_in_file": len(sites),
        "sites_skipped_resume": skipped,
        "sites_attempted_this_run": total,
        "sites_failed_this_run": failures_so_far,
        "sites_succeeded_combined": len(rows),
    }
    RUN_META_JSON.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    print_stats(rows, total, total_elapsed_s)


if __name__ == "__main__":
    main()
