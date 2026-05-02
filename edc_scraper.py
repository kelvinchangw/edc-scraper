#!/usr/bin/env python3
"""EDC Las Vegas set times scraper.

Pulls lineup data from festivaldust.com and emits JSON, CSV (for Google
Sheets), or a self-contained HTML viewer.

Usage:
    python edc_scraper.py                       # JSON to stdout
    python edc_scraper.py -o sets.json
    python edc_scraper.py -o sets.csv           # format inferred from extension
    python edc_scraper.py -o schedule.html
    python edc_scraper.py --year 2025 -o old.csv
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import requests
from bs4 import BeautifulSoup


FESTIVALS = {
    2026: {
        "url": "https://www.festivaldust.com/festivals/edc-las-vegas-2026-lasvegasnv/lineup",
        "dates": {"1": "2026-05-15", "2": "2026-05-16", "3": "2026-05-17"},
    },
    2025: {
        "url": "https://www.festivaldust.com/festivals/edc-las-vegas-2025-lasvegasnv/lineup",
        "dates": {"1": "2025-05-16", "2": "2025-05-17", "3": "2025-05-18"},
    },
}

# Matches "7pm - 8pm", "1:47am - 2:57am", "11:30pm - 1:30am" (en-dash or hyphen)
TIME_PATTERN = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?(am|pm)$",
    re.IGNORECASE,
)

# EDC runs ~7pm to ~5:30am. Anything before 3pm belongs to the next calendar day.
ROLLOVER_HOUR = 15


def to_24h(hour, minute, ampm):
    h = int(hour)
    m = int(minute) if minute else 0
    ampm = ampm.lower()
    if ampm == "pm" and h != 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    return h, m


USER_AGENT = (
    "edc-scraper/1.0 (+https://github.com/verthandiw/edc-scraper) "
    "daily lineup snapshot for personal use"
)


def fetch(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text


def parse_lineup(html, dates):
    """Parse the festivaldust lineup page into a list of set dicts.

    Page renders each artist as a 5-line sequence: artist, stage, "Day", N,
    "H:MMam/pm - H:MMam/pm". We anchor on the time-range line and walk back.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = [t.strip().replace("​", "") for t in soup.get_text("\n").split("\n")]
    lines = [l for l in lines if l]

    sets = []
    for i, line in enumerate(lines):
        m = TIME_PATTERN.match(line)
        if not m or i < 4:
            continue
        artist = lines[i - 4]
        stage = lines[i - 3]
        day_label = lines[i - 2]
        day_num = lines[i - 1]
        if day_label.lower() != "day" or day_num not in dates:
            continue

        s_h, s_m = to_24h(m.group(1), m.group(2), m.group(3))
        e_h, e_m = to_24h(m.group(4), m.group(5), m.group(6))
        base = datetime.strptime(dates[day_num], "%Y-%m-%d")
        s_dt = base + timedelta(days=(1 if s_h < ROLLOVER_HOUR else 0), hours=s_h, minutes=s_m)
        e_dt = base + timedelta(days=(1 if e_h < ROLLOVER_HOUR else 0), hours=e_h, minutes=e_m)
        if e_dt <= s_dt:
            e_dt += timedelta(days=1)

        sep = "–" if "–" in line else "-"
        start_label, end_label = [p.strip() for p in line.split(sep, 1)]

        sets.append({
            "artist": artist,
            "stage": stage,
            "day": f"Day {day_num}",
            "date": dates[day_num],
            "start": s_dt.isoformat(),
            "end": e_dt.isoformat(),
            "start_label": start_label,
            "end_label": end_label,
        })

    sets.sort(key=lambda s: (s["start"], s["stage"]))
    return sets


def write_json(sets, path):
    out = json.dumps(sets, indent=2)
    if path:
        Path(path).write_text(out)
    else:
        sys.stdout.write(out + "\n")


def write_csv(sets, path):
    cols = ["artist", "stage", "day", "date", "start", "end", "start_label", "end_label"]
    f = open(path, "w", newline="") if path else sys.stdout
    try:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(sets)
    finally:
        if path:
            f.close()


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDC Las Vegas {year} Set Times</title>
<style>
  :root {{
    --bg: #0a0612;
    --panel: #15102a;
    --panel-2: #1d1638;
    --grid: #1d1638;
    --grid-major: #2e2360;
    --text: #ece6ff;
    --muted: #8b82b8;
    --accent: #c084fc;
    --now: #fb7185;
    --col-w: 130px;
    --axis-w: 56px;
    --header-h: 38px;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased; overscroll-behavior: none; }}
  .app {{ display: flex; flex-direction: column; height: 100%; }}
  header {{ flex: 0 0 auto; background: var(--bg); padding: 12px 16px 10px;
    border-bottom: 1px solid #2a2050; z-index: 30; }}
  h1 {{ margin: 0 0 10px; font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }}
  h1 small {{ color: var(--muted); font-weight: 400; margin-left: 6px; font-size: 12px; }}
  .controls {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
  .tabs {{ display: flex; gap: 4px; }}
  .tab {{ background: var(--panel); color: var(--text); border: 1px solid transparent;
    padding: 6px 12px; border-radius: 999px; cursor: pointer; font: inherit; font-size: 13px; }}
  .tab.active {{ background: var(--accent); color: #1a0f2e; font-weight: 600; }}
  .search {{ flex: 1; min-width: 130px; background: var(--panel); color: var(--text);
    border: 1px solid #2a2050; border-radius: 999px; padding: 6px 12px; font: inherit;
    outline: none; font-size: 13px; }}
  .search:focus {{ border-color: var(--accent); }}
  .now-btn {{ background: var(--now); color: #fff; border: 0; border-radius: 999px;
    padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; font-weight: 600; }}
  .now-btn:disabled {{ opacity: 0.3; cursor: not-allowed; background: var(--panel); color: var(--muted); }}

  main {{ flex: 1 1 auto; overflow: auto; position: relative; }}
  .timeline {{ position: relative; display: flex; min-width: max-content; padding-bottom: 40px; }}

  .column {{ flex: 0 0 auto; position: relative; }}
  .axis-col {{ width: var(--axis-w); position: sticky; left: 0; z-index: 12;
    background: var(--bg); border-right: 1px solid var(--grid-major); }}
  .stage-col {{ width: var(--col-w); border-right: 1px solid var(--grid); }}

  .col-header {{ position: sticky; top: 0; height: var(--header-h);
    background: var(--panel); padding: 0 6px; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.04em; text-align: center;
    border-bottom: 2px solid var(--accent); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; z-index: 10; display: flex; align-items: center;
    justify-content: center; }}
  .axis-col .col-header {{ background: var(--bg); border-bottom-color: var(--grid-major);
    z-index: 13; }}

  .col-body {{ position: relative; }}

  .hour-mark {{ position: absolute; left: 0; right: 4px; text-align: right;
    font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums;
    transform: translateY(-50%); pointer-events: none; padding-right: 6px; }}
  .hour-mark.major {{ color: var(--accent); font-weight: 700; }}

  .hour-line {{ position: absolute; left: 0; right: 0; height: 1px;
    background: var(--grid); pointer-events: none; }}
  .hour-line.major {{ background: var(--grid-major); }}

  .set-block {{ position: absolute; left: 2px; right: 2px;
    background: var(--panel-2); border-left: 3px solid var(--accent);
    border-radius: 4px; padding: 4px 6px; overflow: hidden;
    cursor: default; transition: opacity 0.15s, transform 0.1s;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4); }}
  .set-block:hover {{ z-index: 8; transform: scale(1.03);
    box-shadow: 0 4px 12px rgba(0,0,0,0.6); }}
  .set-block.dim {{ opacity: 0.15; }}
  .set-block.match {{ outline: 2px solid var(--accent);
    box-shadow: 0 0 0 1px var(--bg), 0 0 12px rgba(192,132,252,0.5); }}
  .set-artist {{ font-weight: 600; font-size: 11px; line-height: 1.2;
    overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
    -webkit-line-clamp: 2; -webkit-box-orient: vertical; word-break: break-word; }}
  .set-time {{ color: var(--muted); font-size: 10px; margin-top: 2px;
    font-variant-numeric: tabular-nums; }}

  .now-line {{ position: absolute; left: var(--axis-w); right: 0; height: 2px;
    background: var(--now); z-index: 11; pointer-events: none;
    box-shadow: 0 0 8px var(--now); }}
  .now-line::before {{ content: "now"; position: absolute; left: -42px; top: -9px;
    background: var(--now); color: #fff; font-size: 10px; padding: 2px 6px;
    border-radius: 3px; font-weight: 700; letter-spacing: 0.05em; }}

  footer {{ color: var(--muted); font-size: 11px; text-align: center;
    padding: 8px 12px; border-top: 1px solid #2a2050; flex: 0 0 auto; }}
  footer a {{ color: var(--muted); }}
</style>
</head>
<body>
<div class="app">
<header>
  <h1>EDC Las Vegas {year} <small>{count} sets &middot; updated {generated}</small></h1>
  <div class="controls">
    <div class="tabs" id="tabs"></div>
    <input class="search" id="search" placeholder="Filter artists..." autocomplete="off">
    <button class="now-btn" id="now-btn">Jump to now</button>
  </div>
</header>
<main id="main"><div class="timeline" id="timeline"></div></main>
<footer>Source: <a href="{source}">festivaldust.com</a> &middot; scroll horizontally for stages, vertically through the night</footer>
</div>
<script>
const SETS = {data};
const STAGE_COLORS = {{
  "Kinetic Field": "#ec4899",
  "Circuit Grounds": "#3b82f6",
  "Neon Garden": "#22d3ee",
  "Cosmic Meadow": "#f59e0b",
  "Basspod": "#ef4444",
  "Wasteland": "#dc2626",
  "Quantum Valley": "#a855f7",
  "Stereobloom": "#f472b6",
  "Bionic Jungle": "#10b981",
  "Casa Bacardi": "#06b6d4",
  "Forest House": "#84cc16",
  "YeeDC": "#eab308",
  "Beatbox Art Car": "#fb923c",
  "Insomniac Fridays": "#8b5cf6",
}};
const STAGE_ORDER = Object.keys(STAGE_COLORS);
const DAY_NAMES = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const PX_PER_MIN = 1.5;
const HEADER_H = 38;
const TOP_PAD = 24;
const BOTTOM_PAD = 24;
const DAYS = [...new Set(SETS.map(s => s.day))].sort();
let currentDay = DAYS[0];
let query = "";

const tabsEl = document.getElementById("tabs");
const timelineEl = document.getElementById("timeline");
const searchEl = document.getElementById("search");
const mainEl = document.getElementById("main");
const nowBtnEl = document.getElementById("now-btn");

function dayBounds(day) {{
  const sets = SETS.filter(s => s.day === day);
  const startMs = Math.min.apply(null, sets.map(s => new Date(s.start).getTime()));
  const endMs = Math.max.apply(null, sets.map(s => new Date(s.end).getTime()));
  const min = new Date(startMs); min.setMinutes(0, 0, 0);
  const max = new Date(endMs);
  if (max.getMinutes() > 0 || max.getSeconds() > 0) {{
    max.setHours(max.getHours() + 1, 0, 0, 0);
  }}
  return {{ min, max }};
}}

function fmtHour(d) {{
  const h = d.getHours();
  const ampm = h >= 12 ? "pm" : "am";
  const h12 = h === 0 ? 12 : (h > 12 ? h - 12 : h);
  return h12 + ampm;
}}

function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, c => (
    {{ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }}[c]
  ));
}}

function findDayForNow() {{
  const now = new Date();
  for (const d of DAYS) {{
    const {{ min, max }} = dayBounds(d);
    if (now >= min && now <= max) return d;
  }}
  return null;
}}

function render() {{
  [...tabsEl.children].forEach(el =>
    el.classList.toggle("active", el.dataset.day === currentDay));

  const sets = SETS.filter(s => s.day === currentDay);
  const stages = [...new Set(sets.map(s => s.stage))]
    .sort((a, b) => {{
      const ai = STAGE_ORDER.indexOf(a), bi = STAGE_ORDER.indexOf(b);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    }});
  const {{ min, max }} = dayBounds(currentDay);
  const totalMin = (max - min) / 60000;
  const bodyH = totalMin * PX_PER_MIN;

  const hours = [];
  for (let t = min.getTime(); t <= max.getTime(); t += 60 * 60000) {{
    hours.push(new Date(t));
  }}

  let html = "";

  const fullH = bodyH + TOP_PAD + BOTTOM_PAD;

  // Time axis column
  html += '<div class="column axis-col">';
  html += '<div class="col-header"></div>';
  html += '<div class="col-body" style="height:' + fullH + 'px">';
  hours.forEach(h => {{
    const offset = (h - min) / 60000 * PX_PER_MIN + TOP_PAD;
    const isMidnight = h.getHours() === 0;
    html += '<div class="hour-mark ' + (isMidnight ? 'major' : '') +
            '" style="top:' + offset + 'px">' + fmtHour(h) + '</div>';
  }});
  html += '</div></div>';

  // Stage columns
  stages.forEach(stage => {{
    const color = STAGE_COLORS[stage] || "#888";
    html += '<div class="column stage-col">';
    html += '<div class="col-header" style="border-bottom-color:' + color +
            ';color:' + color + '">' + escapeHtml(stage) + '</div>';
    html += '<div class="col-body" style="height:' + fullH + 'px">';
    hours.forEach(h => {{
      const offset = (h - min) / 60000 * PX_PER_MIN + TOP_PAD;
      const isMidnight = h.getHours() === 0;
      html += '<div class="hour-line ' + (isMidnight ? 'major' : '') +
              '" style="top:' + offset + 'px"></div>';
    }});
    sets.filter(s => s.stage === stage).forEach(s => {{
      const startMs = new Date(s.start).getTime();
      const endMs = new Date(s.end).getTime();
      const top = (startMs - min) / 60000 * PX_PER_MIN + TOP_PAD;
      const height = Math.max(20, (endMs - startMs) / 60000 * PX_PER_MIN - 2);
      const matched = query && s.artist.toLowerCase().includes(query);
      const dimmed = query && !matched;
      html += '<div class="set-block ' + (dimmed ? 'dim ' : '') +
              (matched ? 'match' : '') +
              '" style="top:' + top + 'px;height:' + height +
              'px;border-left-color:' + color + '" title="' +
              escapeHtml(s.artist) + ' — ' + escapeHtml(s.start_label) +
              ' to ' + escapeHtml(s.end_label) + '">' +
              '<div class="set-artist">' + escapeHtml(s.artist) + '</div>' +
              (height >= 32 ? '<div class="set-time">' +
                escapeHtml(s.start_label) + ' - ' + escapeHtml(s.end_label) +
                '</div>' : '') +
              '</div>';
    }});
    html += '</div></div>';
  }});

  // Now line (overlaid across timeline)
  const now = new Date();
  if (now >= min && now <= max) {{
    const offset = (now - min) / 60000 * PX_PER_MIN + HEADER_H + TOP_PAD;
    html += '<div class="now-line" style="top:' + offset + 'px"></div>';
  }}

  timelineEl.innerHTML = html;

  const dayWithNow = findDayForNow();
  nowBtnEl.disabled = !dayWithNow;
  nowBtnEl.textContent = dayWithNow ? "Jump to now" : "Festival not live";
}}

function jumpToNow() {{
  const dayWithNow = findDayForNow();
  if (!dayWithNow) return;
  if (dayWithNow !== currentDay) {{
    currentDay = dayWithNow;
    render();
  }}
  const {{ min }} = dayBounds(currentDay);
  const offset = (new Date() - min) / 60000 * PX_PER_MIN + HEADER_H + TOP_PAD;
  mainEl.scrollTo({{ top: Math.max(0, offset - mainEl.clientHeight / 3), behavior: "smooth" }});
}}

DAYS.forEach(d => {{
  const b = document.createElement("button");
  b.className = "tab" + (d === currentDay ? " active" : "");
  b.dataset.day = d;
  const date = SETS.find(s => s.day === d).date;
  const dt = new Date(date + "T12:00:00");
  b.textContent = DAY_NAMES[dt.getDay()] + " " + date.slice(5);
  b.onclick = () => {{ currentDay = d; render(); }};
  tabsEl.appendChild(b);
}});

searchEl.addEventListener("input", e => {{
  query = e.target.value.toLowerCase().trim(); render();
}});
nowBtnEl.addEventListener("click", jumpToNow);

const liveDay = findDayForNow();
if (liveDay) currentDay = liveDay;

render();
if (liveDay) setTimeout(jumpToNow, 50);
setInterval(render, 60000);
</script>
</body>
</html>
"""


def write_html(sets, path, year, source):
    if not path:
        sys.stderr.write("HTML output requires -o <file>\n")
        sys.exit(2)
    html = HTML_TEMPLATE.format(
        year=year,
        count=len(sets),
        generated=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        source=escape(source),
        data=json.dumps(sets),
    )
    Path(path).write_text(html)


def main():
    p = argparse.ArgumentParser(description="Scrape EDC Las Vegas set times.")
    p.add_argument("-o", "--output", help="Output file path")
    p.add_argument("--format", choices=["json", "csv", "html"],
                   help="Override format (defaults to file extension or json)")
    p.add_argument("--year", type=int, default=2026, choices=sorted(FESTIVALS.keys()))
    p.add_argument("--from-file", help="Skip HTTP fetch, read cached HTML from this path")
    args = p.parse_args()

    fest = FESTIVALS[args.year]
    html = Path(args.from_file).read_text() if args.from_file else fetch(fest["url"])
    sets = parse_lineup(html, fest["dates"])

    fmt = args.format
    if not fmt and args.output:
        ext = Path(args.output).suffix.lower().lstrip(".")
        fmt = ext if ext in ("json", "csv", "html") else "json"
    fmt = fmt or "json"

    if fmt == "json":
        write_json(sets, args.output)
    elif fmt == "csv":
        write_csv(sets, args.output)
    elif fmt == "html":
        write_html(sets, args.output, args.year, fest["url"])

    if args.output:
        sys.stderr.write(f"wrote {len(sets)} sets to {args.output}\n")


if __name__ == "__main__":
    main()
