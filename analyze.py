"""
Reads every out/*.t1.json produced by run.py and writes out/distribution.csv:
for each taxonomy reason, the total word count carried by findings with that
reason and its percentage of all hidden + attribute words.

A finding is counted once per distinct reason it carries, so a finding that
stacks three techniques contributes its word count to three rows. Percentages
therefore sum to more than 100% whenever techniques are stacked - that is
expected, not a bug.

Two taxonomy reasons - unicode/invisible-characters and unicode/bidi-override
- are measured in characters, not words (see detect.js), and only apply to
a finding's reasons when it is already hidden for another reason. They will
show 0 words unless some other hidden finding also happens to contain those
characters; the character-level counts live in each site's totals instead.
"""

import csv
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"
DISTRIBUTION_CSV = OUT_DIR / "distribution.csv"

TAXONOMY = [
    "visual-concealment/css-rendering-suppression",
    "visual-concealment/zero-sizing",
    "visual-concealment/off-screen-positioning",
    "visual-concealment/transparency",
    "visual-concealment/camouflage",
    "obfuscation/html-attribute-cloaking",
    "obfuscation/clip",
    "dynamic-execution",
    "markup/html-comment",
    "unicode/invisible-characters",
    "unicode/bidi-override",
]


def load_snapshots(out_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.t1.json"))]


def compute_distribution(snapshots: list[dict]) -> dict[str, int]:
    words_by_reason = {reason: 0 for reason in TAXONOMY}
    for snapshot in snapshots:
        for finding in snapshot["findings"]:
            for reason in finding["reasons"]:
                if reason in words_by_reason:
                    words_by_reason[reason] += finding["words"]
    return words_by_reason


def total_hidden_and_attr_words(snapshots: list[dict]) -> int:
    total = 0
    for snapshot in snapshots:
        totals = snapshot["totals"]
        total += totals["hidden_words"] + totals["attr_words"]
    return total


def main() -> None:
    snapshots = load_snapshots(OUT_DIR)
    words_by_reason = compute_distribution(snapshots)
    denominator = total_hidden_and_attr_words(snapshots)

    rows = []
    for reason in TAXONOMY:
        words = words_by_reason[reason]
        pct = (100 * words / denominator) if denominator > 0 else 0.0
        rows.append({"reason": reason, "words": words, "pct_of_hidden_and_attr_words": round(pct, 2)})

    rows.sort(key=lambda r: r["words"], reverse=True)

    with DISTRIBUTION_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["reason", "words", "pct_of_hidden_and_attr_words"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(snapshots)} snapshot(s), {denominator} hidden+attr words total")
    print(f"{'reason':<55} {'words':>10} {'% of hidden+attr':>18}")
    for row in rows:
        print(f"{row['reason']:<55} {row['words']:>10} {row['pct_of_hidden_and_attr_words']:>17.2f}%")


if __name__ == "__main__":
    main()
