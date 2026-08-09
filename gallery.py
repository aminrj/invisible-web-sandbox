"""
Builds a single self-contained out/gallery.html from run.py's output:
out/summary.csv for the numbers, out/<slug>.t1.json for findings, and
out/<slug>.png for screenshots. No CDN, no external requests - screenshots
are embedded as base64 data URIs so the file opens straight from disk,
offline, in a browser.
"""

import base64
import csv
import html
import json
import statistics
from pathlib import Path
from urllib.parse import urlparse

import extract

OUT_DIR = Path(__file__).parent / "out"
SUMMARY_CSV = OUT_DIR / "summary.csv"
GALLERY_HTML = OUT_DIR / "gallery.html"

# From evidence/v2-control (see README.md "Current results"): the benign
# floor measured on a clean page with no planted concealment. Fixed
# reference value, not recomputed from this run's data.
CONTROL_HIDDEN_SHARE = 0.048

FINDING_TEXT_TRUNCATE = 200


def hostname_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname:
        return parsed.hostname
    if parsed.scheme == "file":
        return Path(parsed.path).name
    return url


def read_summary_rows() -> list[dict]:
    if not SUMMARY_CSV.exists():
        raise SystemExit(f"{SUMMARY_CSV} not found - run run.py first")
    with SUMMARY_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_site(row: dict) -> dict | None:
    url = row["url"]
    slug = extract.slugify(url)
    t1_path = OUT_DIR / f"{slug}.t1.json"
    png_path = OUT_DIR / f"{slug}.png"
    if not t1_path.exists() or not png_path.exists():
        print(f"[gallery] skipping {hostname_of(url)}: missing {t1_path.name} or {png_path.name}")
        return None

    t1 = json.loads(t1_path.read_text(encoding="utf-8"))
    image_b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")

    positioned = [f for f in t1["findings"] if f.get("rect") is not None]
    unpositioned = [f for f in t1["findings"] if f.get("rect") is None]

    return {
        "url": url,
        "hostname": hostname_of(url),
        "title": t1["meta"].get("title") or hostname_of(url),
        "hidden_share": float(row["hidden_share"]),
        "invalid": row["invalid"] == "True",
        "visible_words": int(row["visible_words"]),
        "positioned_findings": positioned,
        "unpositioned_findings": unpositioned,
        "image_data_uri": f"data:image/png;base64,{image_b64}",
    }


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_hero(valid_sites: list[dict]) -> str:
    shares = [s["hidden_share"] for s in valid_sites]
    median = statistics.median(shares) if shares else 0.0
    return f"""
<header class="hero">
  <div class="hero-value">{median * 100:.1f}%</div>
  <p class="hero-caption">
    Median <code>hidden_share</code> across <strong>{len(valid_sites)}</strong> valid site(s) &mdash;
    the share of agent-readable text a person never sees.
    <br>
    Control-page reference (no planted concealment): <strong>{CONTROL_HIDDEN_SHARE * 100:.1f}%</strong>
  </p>
</header>
"""


def render_bar_row(site: dict, max_valid_share: float) -> str:
    width_pct = (site["hidden_share"] / max_valid_share * 100) if max_valid_share > 0 else 0
    return f"""
    <div class="bar-row">
      <div class="bar-host" title="{esc(site['url'])}">{esc(site['hostname'])}</div>
      <div class="bar-track"><div class="bar-fill" style="width:{width_pct:.2f}%"></div></div>
      <div class="bar-pct">{site['hidden_share'] * 100:.1f}%</div>
    </div>"""


def render_invalid_row(site: dict) -> str:
    return f"""
    <div class="bar-row invalid">
      <div class="bar-host" title="{esc(site['url'])}">{esc(site['hostname'])}</div>
      <div class="bar-track"><div class="bar-fill bar-fill-invalid" style="width:100%"></div></div>
      <div class="bar-pct">invalid ({site['visible_words']}w)</div>
    </div>"""


def render_chart(valid_sites: list[dict], invalid_sites: list[dict]) -> str:
    max_valid_share = max((s["hidden_share"] for s in valid_sites), default=0.0)
    rows = "".join(render_bar_row(s, max_valid_share) for s in valid_sites)
    rows += "".join(render_invalid_row(s) for s in invalid_sites)
    return f"""
<section class="chart">
  <h2>hidden_share by site</h2>
  <div class="bars">{rows}
  </div>
</section>
"""


def render_overlay_box(finding: dict) -> str:
    rect = finding["rect"]
    reason = esc(finding.get("primary", ""))
    text = esc(truncate(finding.get("text", ""), FINDING_TEXT_TRUNCATE))
    return (
        f'<div class="overlay-box" '
        f'data-x="{rect["x"]}" data-y="{rect["y"]}" data-w="{rect["w"]}" data-h="{rect["h"]}" '
        f'title="{reason}: {text}"></div>'
    )


def render_finding_item(finding: dict) -> str:
    reason = esc(finding.get("primary", ""))
    text = esc(truncate(finding.get("text", ""), FINDING_TEXT_TRUNCATE))
    return f"""
        <div class="finding-item">
          <span class="reason-pill">{reason}</span>
          <span class="finding-text">{text}</span>
        </div>"""


def render_card(site: dict) -> str:
    invalid_badge = '<span class="badge">invalid</span>' if site["invalid"] else ""
    overlays = "".join(render_overlay_box(f) for f in site["positioned_findings"])
    findings = "".join(render_finding_item(f) for f in site["unpositioned_findings"])
    if not findings:
        findings = '<div class="finding-empty">No findings without a layout box.</div>'

    return f"""
  <article class="card">
    <div class="card-header">
      <div>
        <div class="card-host">{esc(site['hostname'])} {invalid_badge}</div>
        <div class="card-title">{esc(site['title'])}</div>
      </div>
      <div class="card-stat">{site['hidden_share'] * 100:.1f}%</div>
    </div>
    <div class="card-body">
      <div class="shot-wrap">
        <img class="shot-img" src="{site['image_data_uri']}" alt="{esc(site['hostname'])} screenshot">
        <div class="overlays">{overlays}</div>
      </div>
      <div class="findings-panel">
        <div class="findings-panel-header">
          <span>Findings with no layout box ({len(site['unpositioned_findings'])})</span>
          <label class="fade-toggle">
            <input type="checkbox" class="fade-checkbox">
            Fade overlays
          </label>
        </div>
        <div class="findings-list">{findings}
        </div>
      </div>
    </div>
  </article>
"""


CSS = """
:root {
  --bg: #0b0d12;
  --bg-card: #12151c;
  --bg-track: #1b1f28;
  --text: #e7e9f0;
  --text-dim: #8b93a3;
  --border: #232732;
  --accent: #ff9f43;
  --accent-rgb: 255, 159, 67;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
}
h2 { font-size: 1.05rem; letter-spacing: 0.02em; text-transform: uppercase; color: var(--text-dim); font-weight: 600; }
code { background: var(--bg-track); padding: 0.1em 0.4em; border-radius: 4px; font-size: 0.9em; }

.hero { text-align: center; padding: 5rem 1.5rem 3rem; }
.hero-value { font-size: clamp(5rem, 14vw, 10rem); font-weight: 800; color: var(--accent); line-height: 1; letter-spacing: -0.02em; }
.hero-caption { max-width: 40rem; margin: 1.5rem auto 0; color: var(--text-dim); font-size: 1.05rem; }
.hero-caption strong { color: var(--text); }

.chart { max-width: 56rem; margin: 0 auto; padding: 2rem 1.5rem; }
.bars { display: flex; flex-direction: column; gap: 0.55rem; margin-top: 1rem; }
.bar-row { display: grid; grid-template-columns: 11rem 1fr 5.5rem; align-items: center; gap: 0.75rem; }
.bar-host { color: var(--text); font-size: 0.9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { background: var(--bg-track); border-radius: 4px; height: 0.9rem; overflow: hidden; }
.bar-fill { background: var(--accent); height: 100%; border-radius: 4px; }
.bar-pct { color: var(--text-dim); font-size: 0.85rem; text-align: right; font-variant-numeric: tabular-nums; }
.bar-row.invalid { opacity: 0.4; }
.bar-fill-invalid { background: var(--text-dim); }

.cards { max-width: 72rem; margin: 0 auto; padding: 1rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; }
.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.card-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.25rem; border-bottom: 1px solid var(--border); }
.card-host { font-weight: 600; }
.card-title { color: var(--text-dim); font-size: 0.85rem; margin-top: 0.15rem; }
.card-stat { font-size: 1.5rem; font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }
.badge { background: rgba(var(--accent-rgb), 0.18); color: var(--accent); border: 1px solid rgba(var(--accent-rgb), 0.5); border-radius: 999px; padding: 0.05em 0.6em; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; vertical-align: middle; }

.card-body { display: flex; gap: 1px; background: var(--border); }
.shot-wrap { position: relative; flex: 1 1 60%; max-height: 34rem; overflow: auto; background: var(--bg); }
.shot-img { display: block; width: 100%; height: auto; }
.overlays { position: absolute; top: 0; left: 0; width: 100%; pointer-events: none; }
.overlay-box {
  position: absolute;
  border: 1.5px solid rgba(var(--accent-rgb), 0.9);
  background: rgba(var(--accent-rgb), 0.28);
  pointer-events: auto;
  transition: opacity 150ms ease;
}
.overlay-box.faded { opacity: 0.1; }

.findings-panel { flex: 1 1 40%; background: var(--bg-card); display: flex; flex-direction: column; min-width: 16rem; }
.findings-panel-header { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; font-size: 0.8rem; color: var(--text-dim); border-bottom: 1px solid var(--border); gap: 0.75rem; }
.fade-toggle { display: flex; align-items: center; gap: 0.35rem; cursor: pointer; white-space: nowrap; }
.findings-list { overflow-y: auto; max-height: 34rem; padding: 0.5rem 1rem; }
.finding-item { padding: 0.6rem 0; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.3rem; }
.finding-item:last-child { border-bottom: none; }
.reason-pill { align-self: flex-start; font-size: 0.7rem; font-family: "SF Mono", Menlo, Consolas, monospace; color: var(--accent); border: 1px solid rgba(var(--accent-rgb), 0.5); border-radius: 4px; padding: 0.1em 0.45em; }
.finding-text { font-size: 0.85rem; color: var(--text-dim); word-break: break-word; }
.finding-empty { color: var(--text-dim); font-size: 0.85rem; padding: 1rem 0; }

@media (max-width: 56rem) {
  .card-body { flex-direction: column; }
  .shot-wrap, .findings-panel { max-height: 26rem; }
}
"""

JS = """
function layoutOverlays(wrap) {
  var img = wrap.querySelector('.shot-img');
  if (!img.naturalWidth) return;
  var scale = img.clientWidth / img.naturalWidth;
  var boxes = wrap.querySelectorAll('.overlay-box');
  for (var i = 0; i < boxes.length; i++) {
    var box = boxes[i];
    var x = parseFloat(box.dataset.x);
    var y = parseFloat(box.dataset.y);
    var w = parseFloat(box.dataset.w);
    var h = parseFloat(box.dataset.h);
    box.style.left = (x * scale) + 'px';
    box.style.top = (y * scale) + 'px';
    box.style.width = Math.max(w * scale, 2) + 'px';
    box.style.height = Math.max(h * scale, 2) + 'px';
  }
}

function layoutAllOverlays() {
  document.querySelectorAll('.shot-wrap').forEach(layoutOverlays);
}

function debounce(fn, ms) {
  var t;
  return function () {
    clearTimeout(t);
    t = setTimeout(fn, ms);
  };
}

document.querySelectorAll('.shot-img').forEach(function (img) {
  var wrap = img.closest('.shot-wrap');
  if (img.complete) layoutOverlays(wrap);
  img.addEventListener('load', function () { layoutOverlays(wrap); });
});

window.addEventListener('resize', debounce(layoutAllOverlays, 150));

document.querySelectorAll('.fade-checkbox').forEach(function (checkbox) {
  checkbox.addEventListener('change', function () {
    var card = checkbox.closest('.card');
    card.querySelectorAll('.overlay-box').forEach(function (box) {
      box.classList.toggle('faded', checkbox.checked);
    });
  });
});
"""


def build_html(valid_sites: list[dict], invalid_sites: list[dict]) -> str:
    hero = render_hero(valid_sites)
    chart = render_chart(valid_sites, invalid_sites)
    cards = "".join(render_card(s) for s in valid_sites + invalid_sites)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>invisible-web gallery</title>
<style>{CSS}</style>
</head>
<body>
{hero}
{chart}
<section class="cards">
  <h2 style="padding: 0 0 0.5rem;">Per-site detail</h2>
  {cards}
</section>
<script>{JS}</script>
</body>
</html>
"""


def main() -> None:
    rows = read_summary_rows()
    sites = [s for s in (load_site(r) for r in rows) if s is not None]

    valid_sites = sorted((s for s in sites if not s["invalid"]), key=lambda s: -s["hidden_share"])
    invalid_sites = sorted((s for s in sites if s["invalid"]), key=lambda s: s["hostname"])

    GALLERY_HTML.write_text(build_html(valid_sites, invalid_sites), encoding="utf-8")

    size_mb = GALLERY_HTML.stat().st_size / (1024 * 1024)
    print(f"Wrote {GALLERY_HTML} ({size_mb:.1f} MB)")
    print(f"Valid sites: {len(valid_sites)}, invalid sites: {len(invalid_sites)}, skipped (missing files): {len(rows) - len(sites)}")


if __name__ == "__main__":
    main()
